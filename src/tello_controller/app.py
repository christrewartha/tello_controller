"""Main application: input -> mode arbitration -> RC commands, plus video/HUD."""

from __future__ import annotations

import argparse
import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
import pygame

from .config import AppConfig
from .diagnostics import BatteryMonitor
from .drone import Drone, SimDrone, TelloDrone
from .hud import GREEN, ORANGE, RED, WHITE, YELLOW, Hud, HudState
from .inputs import AXES, FLIP_ACTIONS, Action, ControlInput, GamepadInput, KeyboardInput
from .lock_on import LockOnController, LockState, LockStatus
from .recorder import Recorder, save_snapshot

log = logging.getLogger(__name__)


class CommandRunner:
    """Runs blocking drone commands (takeoff, land, flip) on a worker thread so the
    UI and video keep running. RC commands are suppressed while one is in flight."""

    def __init__(self, on_error: Callable[[str], None]):
        self._q: queue.Queue[tuple[str, Callable[[], None]] | None] = queue.Queue()
        self._on_error = on_error
        self.busy: str | None = None
        self._thread = threading.Thread(target=self._worker, name="drone-commands", daemon=True)
        self._thread.start()

    def submit(self, name: str, fn: Callable[[], None]) -> bool:
        if self.busy:
            return False
        self.busy = name
        self._q.put((name, fn))
        return True

    def _worker(self) -> None:
        while (item := self._q.get()) is not None:
            name, fn = item
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log.warning("%s failed: %s", name, e)
                self._on_error(f"{name} failed: {e}")
            finally:
                self.busy = None

    def stop(self) -> None:
        self._q.put(None)


@dataclass
class Toast:
    text: str
    color: tuple[int, int, int]
    expires: float


def arbitrate(manual: ControlInput, auto_rc: tuple[int, int, int, int] | None, threshold: float) -> tuple[tuple[int, int, int, int], set[str]]:
    """Per axis: manual input above threshold always wins over autonomy."""
    manual_rc = manual.as_rc()
    if auto_rc is None:
        return manual_rc, {a for a in AXES if abs(manual.axis(a)) > threshold}
    out, overridden = [], set()
    for i, a in enumerate(AXES):
        if abs(manual.axis(a)) > threshold:
            out.append(manual_rc[i])
            overridden.add(a)
        else:
            out.append(auto_rc[i])
    return tuple(out), overridden  # type: ignore[return-value]


class App:
    def __init__(self, config: AppConfig, drone: Drone, enable_faces: bool = True, enroll_name: str = "me"):
        self.config = config
        self.drone = drone
        self.enable_faces = enable_faces
        self.enroll_name = enroll_name
        self.toasts: deque[Toast] = deque(maxlen=8)
        self.running = True
        self.show_help = False
        self.show_info = False
        self.battery_monitor = BatteryMonitor()
        self._battery_warned = False
        self.rc = (0, 0, 0, 0)
        self.manual_axes: set[str] = set()
        self.lock_status: LockStatus | None = None
        self.faces: list = []
        self.detect_ms = 0.0
        self._last_rc_send = 0.0
        self._telemetry_warned = False
        self._low_battery_landing = False

    # -- helpers ---------------------------------------------------------
    def toast(self, text: str, color=WHITE, seconds: float = 3.0) -> None:
        log.info(text)
        self.toasts.append(Toast(text, color, time.monotonic() + seconds))

    def _init_faces(self) -> None:
        self.detector = self.recognizer = self.gallery = None
        if self.enable_faces:
            try:
                from .faces import FaceDetector, FaceGallery, FaceRecognizer

                self.detector = FaceDetector(self.config.face)
                self.recognizer = FaceRecognizer(self.config.face)
                self.gallery = FaceGallery(self.config.face.gallery_dir)
            except Exception as e:  # noqa: BLE001
                log.exception("Face pipeline unavailable")
                self.toast(f"Face detection disabled: {e}", RED, 8)
                self.detector = None
        self.lock = LockOnController(self.config.lock_on, self.config.face, self.recognizer, self.gallery)

    # -- actions ---------------------------------------------------------
    def _handle_actions(self, actions: set[Action], frame: np.ndarray | None) -> None:
        d = self.drone
        tel = d.telemetry()
        if Action.EMERGENCY in actions:
            d.emergency()  # non-blocking, bypasses the queue on purpose
            self.lock.disengage()
            self.toast("EMERGENCY STOP", RED, 6)
            return
        if Action.QUIT in actions:
            self.running = False
        if Action.HOVER in actions:
            if self.lock.active:
                self.lock.disengage()
            self.toast("Hover", WHITE, 1.5)
        if Action.TAKEOFF in actions and not d.is_flying:
            if tel.battery and tel.battery < self.config.flight.min_battery_to_takeoff:
                self.toast(f"Battery too low to take off ({tel.battery}%)", RED)
            else:
                self.runner.submit("take off", d.takeoff)
        if Action.LAND in actions and d.is_flying:
            self.lock.disengage()
            self.runner.submit("land", d.land)
        for action, direction in FLIP_ACTIONS.items():
            if action in actions and d.is_flying:
                self.runner.submit(f"flip {direction}", lambda direction=direction: d.flip(direction))
        if Action.TOGGLE_LOCK in actions:
            if self.detector is None:
                self.toast("Face detection unavailable", RED)
            elif self.lock.active:
                self.lock.disengage()
                self.toast("Lock-on off")
            else:
                self.lock.engage()
                self.toast("Lock-on: looking for a face" + (" I know" if self.lock.known_only else ""), YELLOW, 1.5)
        if Action.SNAPSHOT in actions and frame is not None:
            path = save_snapshot(frame, self.config.recording.snapshot_dir)
            self.toast(f"Snapshot {path.name}", GREEN, 2)
        if Action.TOGGLE_RECORD in actions:
            if self.recorder.recording:
                self.recorder.stop()
                self.toast("Recording stopped", GREEN)
            else:
                path = self.recorder.start()
                self.toast(f"Recording to {path.name}", RED)
        if Action.ENROLL in actions:
            self._enroll(frame)

    def _enroll(self, frame: np.ndarray | None) -> None:
        if self.recognizer is None or self.gallery is None or frame is None:
            self.toast("Face recognition unavailable", RED)
            return
        face = self.lock_status.target if (self.lock_status and self.lock_status.target) else (self.faces[0] if self.faces else None)
        if face is None:
            self.toast("No face to enrol", ORANGE)
            return
        n = self.gallery.add(self.enroll_name, self.recognizer.embed(frame, face))
        self.toast(f"Enrolled '{self.enroll_name}' ({n} samples)", GREEN)

    def _battery_health(self) -> None:
        tel = self.drone.telemetry()
        self.battery_monitor.update(time.monotonic(), tel.battery, self.drone.is_flying)
        text, severity = self.battery_monitor.report(tel.battery).verdict
        if severity == "bad" and not self._battery_warned:
            self._battery_warned = True  # once per session; details stay on the Tab screen
            self.toast(f"{text} (Tab for details)", ORANGE, 8)

    # -- safety ----------------------------------------------------------
    def _safety(self) -> None:
        d, tel, cfg = self.drone, self.drone.telemetry(), self.config.flight
        if not d.is_flying:
            self._low_battery_landing = False
            return
        if tel.battery and tel.battery <= cfg.auto_land_battery and not self._low_battery_landing:
            self.lock.disengage()
            # Retried every tick until the runner is free (e.g. mid-flip).
            if self.runner.submit("land", d.land):
                self._low_battery_landing = True
                self.toast(f"Battery {tel.battery}% - landing", RED, 6)
        stale = tel.age_s > cfg.telemetry_timeout_s
        if stale and not self._telemetry_warned:
            self.toast("Lost telemetry - hovering", RED, 5)
            self.lock.disengage()
        self._telemetry_warned = stale

    # -- main loop -------------------------------------------------------
    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption(f"Tello Controller - {self.drone.name}")
        screen = pygame.display.set_mode(self.config.display.window_size)
        clock = pygame.time.Clock()
        hud = Hud()
        keyboard = KeyboardInput(self.config.input)
        self.gamepad = GamepadInput(self.config.input)
        self.recorder = Recorder(self.config.recording.output_dir, self.config.recording.fps)
        self.runner = CommandRunner(lambda msg: self.toast(msg, RED, 5))
        self._init_faces()

        self.drone.connect()
        self.drone.start_video()
        self.toast("Press H for controls", WHITE, 5)

        try:
            while self.running:
                dt = clock.tick(self.config.display.fps) / 1000.0
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    elif event.type == pygame.KEYDOWN and event.key in (pygame.K_h, pygame.K_F1):
                        self.show_help = not self.show_help
                        self.show_info = False
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                        self.show_info = not self.show_info
                        self.show_help = False
                    keyboard.handle_event(event)
                    self.gamepad.handle_event(event)

                manual = ControlInput.merge(keyboard.read(dt), self.gamepad.read(dt))
                frame = self.drone.get_frame()
                if frame is not None and (frame.shape[1], frame.shape[0]) != self.config.display.window_size:
                    frame = cv2.resize(frame, self.config.display.window_size)
                self._handle_actions(manual.actions, frame)
                self._safety()
                self._battery_health()

                # Face pipeline.
                self.faces = []
                auto_rc = None
                if self.detector is not None and frame is not None:
                    t0 = time.perf_counter()
                    self.faces = self.detector.detect(frame)
                    if self.lock.active:
                        prev_state = self.lock_status.state if self.lock_status else None
                        auto_rc, self.lock_status = self.lock.update(self.faces, frame)
                        if self.lock_status.state == LockState.LOCKED and prev_state != LockState.LOCKED:
                            self.gamepad.rumble(0.4, 0.8, 250)
                        if self.lock_status.state == LockState.GAVE_UP:
                            self.lock.disengage()
                            self.toast("Lost the face - back to manual", YELLOW)
                            auto_rc = None
                    self.detect_ms = 0.9 * self.detect_ms + 0.1 * (time.perf_counter() - t0) * 1000
                if not self.lock.active:
                    self.lock_status = None

                if self._telemetry_warned:
                    auto_rc = None
                self.rc, self.manual_axes = arbitrate(manual, auto_rc, self.config.input.manual_override_threshold)

                # Send RC at a fixed rate, never while a blocking command is running.
                now = time.monotonic()
                if self.runner.busy is None and now - self._last_rc_send >= 1.0 / self.config.flight.control_rate_hz:
                    self._last_rc_send = now
                    if self.drone.is_flying:
                        self.drone.send_rc(*self.rc)

                if frame is not None and self.recorder.recording:
                    self.recorder.write(frame, self.drone.telemetry(), self.rc)

                self._render(screen, hud, frame, clock)
        finally:
            self._shutdown()

    def _render(self, screen: pygame.Surface, hud: Hud, frame: np.ndarray | None, clock: pygame.time.Clock) -> None:
        w, h = screen.get_size()
        if frame is not None:  # already resized to the window in run()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            screen.blit(pygame.image.frombuffer(rgb.tobytes(), (w, h), "RGB"), (0, 0))
        else:
            screen.fill((20, 20, 20))
            hud._text(screen, "Waiting for video...", (w // 2, h // 2 + 40), WHITE, center=True)

        now = time.monotonic()
        while self.toasts and self.toasts[0].expires < now:
            self.toasts.popleft()
        hud.draw(screen, HudState(
            drone_name=self.drone.name,
            telemetry=self.drone.telemetry(),
            flying=self.drone.is_flying,
            busy=self.runner.busy,
            mode="MANUAL",
            lock=self.lock_status if self.lock.active else None,
            faces=self.faces,
            rc=self.rc,
            manual_axes=self.manual_axes,
            recording=self.recorder.recording,
            gamepad=self.gamepad.device_name,
            fps=clock.get_fps(),
            detect_ms=self.detect_ms,
            known_only=self.lock.known_only,
            show_help=self.show_help,
            show_info=self.show_info,
            battery=self.battery_monitor.report(self.drone.telemetry().battery),
            toasts=[(t.text, t.color) for t in self.toasts],
        ))
        pygame.display.flip()

    def _shutdown(self) -> None:
        log.info("Shutting down")
        try:
            self.recorder.stop()
            self.lock.disengage()
            # Wait for any in-progress command, then land if still airborne.
            deadline = time.monotonic() + 10
            while self.runner.busy and time.monotonic() < deadline:
                time.sleep(0.1)
            if self.drone.is_flying:
                log.info("Landing before exit")
                self.drone.send_rc(0, 0, 0, 0)
                self.drone.land()
        except Exception:  # noqa: BLE001
            log.exception("Error during shutdown")
        finally:
            self.runner.stop()
            self.drone.close()
            pygame.quit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fly a DJI/Ryze Tello with keyboard or Xbox controller, with face lock-on.")
    parser.add_argument("--sim", action="store_true", help="use the simulator instead of a real drone")
    parser.add_argument("--webcam", type=int, nargs="?", const=0, default=None, metavar="INDEX",
                        help="(with --sim) use a webcam as the simulated drone camera")
    parser.add_argument("--wifi", nargs="?", const="", default=None, metavar="SSID",
                        help="switch to the Tello's Wi-Fi first (auto-detects TELLO-*), restore on exit")
    parser.add_argument("--no-faces", action="store_true", help="disable face detection / lock-on")
    parser.add_argument("--name", default="me", help="name used when enrolling a face with N (default: me)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")

    config = AppConfig()
    drone: Drone = SimDrone(webcam_index=args.webcam) if args.sim else TelloDrone()

    def go() -> None:
        App(config, drone, enable_faces=not args.no_faces, enroll_name=args.name).run()

    if args.wifi is not None and not args.sim:
        from .network import tello_wifi

        try:
            with tello_wifi(args.wifi or None):
                go()
        except KeyboardInterrupt:
            print("Cancelled.")
        except (RuntimeError, TimeoutError) as e:
            raise SystemExit(f"Wi-Fi: {e}") from None
    else:
        go()


if __name__ == "__main__":
    main()
