"""Drone backends.

`TelloDrone` wraps djitellopy for the real aircraft. `SimDrone` is a stand-in
that integrates RC commands into a simulated pose and can use a webcam as its
"camera", so the UI, controls and face lock-on can be developed without flying.

All frames returned by `get_frame()` are BGR uint8 (OpenCV convention).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)

FLIP_DIRECTIONS = ("l", "r", "f", "b")


@dataclass
class Telemetry:
    battery: int = 0
    height_cm: int = 0
    tof_cm: int = 0
    pitch: int = 0
    roll: int = 0
    yaw: int = 0
    vgx: int = 0
    vgy: int = 0
    vgz: int = 0
    temp_c: float = 0.0
    flight_time_s: int = 0
    updated_at: float = 0.0
    """time.monotonic() when the last state packet arrived."""
    raw: dict = field(default_factory=dict)

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.updated_at if self.updated_at else math.inf


class Drone(Protocol):
    name: str

    def connect(self) -> None: ...
    def start_video(self) -> None: ...
    def get_frame(self) -> np.ndarray | None: ...
    def telemetry(self) -> Telemetry: ...
    @property
    def is_flying(self) -> bool: ...
    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> None: ...
    # The following block until the drone acknowledges; call them off the UI thread.
    def takeoff(self) -> None: ...
    def land(self) -> None: ...
    def flip(self, direction: str) -> None: ...
    def emergency(self) -> None: ...
    def close(self) -> None: ...


def _clamp_rc(v: float) -> int:
    return int(max(-100, min(100, round(v))))


class TelloDrone:
    """Real Tello via djitellopy."""

    name = "Tello"

    def __init__(self) -> None:
        from djitellopy import Tello

        Tello.LOGGER.setLevel(logging.WARNING)
        self._tello = Tello()
        self._frame_reader = None
        self._last_state_obj: object | None = None
        self._telemetry = Telemetry()

    def connect(self) -> None:
        self._tello.connect()
        log.info("Connected to Tello, battery %s%%", self._tello.get_battery())

    def start_video(self) -> None:
        self._tello.streamon()
        self._frame_reader = self._tello.get_frame_read()

    def get_frame(self) -> np.ndarray | None:
        if self._frame_reader is None:
            return None
        frame = self._frame_reader.frame
        # djitellopy starts with a 300x400 black placeholder until the stream decodes.
        if frame is None or frame.shape[:2] == (300, 400):
            return None
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def telemetry(self) -> Telemetry:
        state = self._tello.get_current_state()
        # djitellopy replaces the state dict on every packet, so identity tells us
        # whether a fresh packet has arrived since we last looked.
        if state and state is not self._last_state_obj:
            self._last_state_obj = state
            g = state.get
            self._telemetry = Telemetry(
                battery=int(g("bat", 0)),
                height_cm=int(g("h", 0)),
                tof_cm=int(g("tof", 0)),
                pitch=int(g("pitch", 0)),
                roll=int(g("roll", 0)),
                yaw=int(g("yaw", 0)),
                vgx=int(g("vgx", 0)),
                vgy=int(g("vgy", 0)),
                vgz=int(g("vgz", 0)),
                temp_c=(float(g("templ", 0)) + float(g("temph", 0))) / 2,
                flight_time_s=int(g("time", 0)),
                updated_at=time.monotonic(),
                raw=dict(state),
            )
        return self._telemetry

    @property
    def is_flying(self) -> bool:
        return bool(self._tello.is_flying)

    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> None:
        self._tello.send_rc_control(_clamp_rc(lr), _clamp_rc(fb), _clamp_rc(ud), _clamp_rc(yaw))

    def takeoff(self) -> None:
        self._tello.takeoff()

    def land(self) -> None:
        self._tello.land()

    def flip(self, direction: str) -> None:
        if direction not in FLIP_DIRECTIONS:
            raise ValueError(direction)
        self._tello.flip(direction)

    def emergency(self) -> None:
        self._tello.emergency()

    def close(self) -> None:
        try:
            if self._frame_reader is not None:
                self._tello.streamoff()
        except Exception:  # noqa: BLE001 - best effort during shutdown
            log.debug("streamoff failed", exc_info=True)
        self._tello.end()


class SimDrone:
    """Simulated drone. Integrates RC input into a pose; optional webcam camera."""

    name = "Simulator"

    MAX_SPEED_CM_S = 100.0
    MAX_YAW_DEG_S = 100.0
    TAKEOFF_HEIGHT_CM = 80

    def __init__(self, webcam_index: int | None = None, frame_size: tuple[int, int] = (960, 720)):
        self._webcam_index = webcam_index
        self._cap: cv2.VideoCapture | None = None
        self._frame_size = frame_size
        self._lock = threading.Lock()
        self._rc = (0, 0, 0, 0)
        self._flying = False
        self._x = self._y = self._z = 0.0  # cm, world frame
        self._yaw = 0.0  # degrees
        self._battery = 100.0
        self._last_step = time.monotonic()
        self._takeoff_at = 0.0

    # -- lifecycle -------------------------------------------------------
    def connect(self) -> None:
        log.info("Simulator connected")

    def start_video(self) -> None:
        if self._webcam_index is not None:
            self._cap = cv2.VideoCapture(self._webcam_index, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(self._webcam_index)
            if not self._cap.isOpened():
                log.warning("Could not open webcam %s; using synthetic video", self._webcam_index)
                self._cap = None

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()

    # -- physics ---------------------------------------------------------
    def _step(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last_step, 0.2)
        self._last_step = now
        with self._lock:
            lr, fb, ud, yaw = self._rc
            flying = self._flying
        if flying:
            yaw_rad = math.radians(self._yaw)
            vx = (fb * math.cos(yaw_rad) - lr * math.sin(yaw_rad)) / 100 * self.MAX_SPEED_CM_S
            vy = (fb * math.sin(yaw_rad) + lr * math.cos(yaw_rad)) / 100 * self.MAX_SPEED_CM_S
            self._x += vx * dt
            self._y += vy * dt
            self._z = max(20.0, self._z + ud / 100 * self.MAX_SPEED_CM_S * dt)
            self._yaw = (self._yaw + yaw / 100 * self.MAX_YAW_DEG_S * dt + 180) % 360 - 180
            self._battery = max(0.0, self._battery - dt * 0.15)

    @property
    def pose(self) -> tuple[float, float, float, float]:
        self._step()
        return self._x, self._y, self._z, self._yaw

    # -- Drone API -------------------------------------------------------
    def get_frame(self) -> np.ndarray | None:
        self._step()
        w, h = self._frame_size
        if self._cap is not None:
            ok, frame = self._cap.read()
            if ok:
                frame = cv2.flip(frame, 1)  # mirror so it feels like a camera facing you
                return cv2.resize(frame, (w, h))
        frame = np.full((h, w, 3), 40, np.uint8)
        # Scrolling grid that responds to yaw so movement is visible.
        offset = int(self._yaw / 90 * w) % 80
        for gx in range(-offset, w, 80):
            cv2.line(frame, (gx, 0), (gx, h), (70, 70, 70), 1)
        horizon = int(h / 2 + (self._z - self.TAKEOFF_HEIGHT_CM) * 0.5)
        cv2.line(frame, (0, horizon), (w, horizon), (120, 160, 120), 2)
        cv2.putText(frame, "SIMULATOR", (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 150, 150), 2)
        return frame

    def telemetry(self) -> Telemetry:
        x, y, z, yaw = self.pose
        lr, fb, ud, yw = self._rc
        return Telemetry(
            battery=int(self._battery),
            height_cm=int(z) if self._flying else 0,
            tof_cm=int(z) if self._flying else 10,
            yaw=int(yaw),
            vgx=fb,
            vgy=lr,
            vgz=ud,
            temp_c=40.0,
            flight_time_s=int(time.monotonic() - self._takeoff_at) if self._flying else 0,
            updated_at=time.monotonic(),
        )

    @property
    def is_flying(self) -> bool:
        return self._flying

    def send_rc(self, lr: int, fb: int, ud: int, yaw: int) -> None:
        self._step()
        with self._lock:
            self._rc = (_clamp_rc(lr), _clamp_rc(fb), _clamp_rc(ud), _clamp_rc(yaw))

    def takeoff(self) -> None:
        time.sleep(1.5)  # real takeoff blocks for several seconds
        self._z = self.TAKEOFF_HEIGHT_CM
        self._takeoff_at = time.monotonic()
        self._flying = True

    def land(self) -> None:
        self.send_rc(0, 0, 0, 0)
        time.sleep(1.0)
        self._flying = False
        self._z = 0.0

    def flip(self, direction: str) -> None:
        if direction not in FLIP_DIRECTIONS:
            raise ValueError(direction)
        time.sleep(0.8)

    def emergency(self) -> None:
        self._flying = False
        self._z = 0.0
        self._rc = (0, 0, 0, 0)
