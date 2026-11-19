"""Run the whole app headless against the simulator with scripted input."""

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from tello_controller.app import App  # noqa: E402
from tello_controller.config import AppConfig  # noqa: E402
from tello_controller.drone import SimDrone  # noqa: E402
from tello_controller.inputs import Action, KeyboardInput  # noqa: E402


def test_sim_session_takeoff_record_land(tmp_path, monkeypatch):
    drone = SimDrone()
    # Ticks are counted from the moment the drone is airborne (takeoff blocks ~1.5s).
    airborne_script = {
        1: {Action.TOGGLE_RECORD},
        10: {Action.SNAPSHOT},
        40: {Action.TOGGLE_RECORD},
        45: {Action.LAND},
    }
    state = {"n": 0, "airborne": 0, "landed_ticks": 0}
    real_read = KeyboardInput.read

    def scripted_read(self, dt, pressed=None):
        out = real_read(self, dt, pressed)
        state["n"] += 1
        if state["n"] == 2:
            out.actions.add(Action.TAKEOFF)
        if drone.is_flying:
            state["airborne"] += 1
            out.actions |= airborne_script.get(state["airborne"], set())
            if state["airborne"] < 35:
                out.fb = 0.5  # push forward
        elif state["airborne"]:
            state["landed_ticks"] += 1
            if state["landed_ticks"] == 5:
                out.actions.add(Action.QUIT)
        if state["n"] > 2000:  # safety net so a bug can't hang the test
            out.actions.add(Action.QUIT)
        return out

    monkeypatch.setattr(KeyboardInput, "read", scripted_read)

    cfg = AppConfig()
    cfg.recording.output_dir = tmp_path / "rec"
    cfg.recording.snapshot_dir = tmp_path / "snap"
    cfg.display.fps = 60
    flew = {"max_x": 0.0}
    real_send = drone.send_rc

    def tracking_send(*rc):
        real_send(*rc)
        flew["max_x"] = max(flew["max_x"], drone.pose[0])

    drone.send_rc = tracking_send
    App(cfg, drone, enable_faces=False).run()

    assert not drone.is_flying
    assert flew["max_x"] > 10, "drone should have moved forward"
    recs = list((tmp_path / "rec").iterdir())
    assert len(recs) == 1
    assert (recs[0] / "video.mp4").stat().st_size > 0
    lines = (recs[0] / "frames.csv").read_text().splitlines()
    assert lines[0].startswith("frame,t,battery") and len(lines) > 5
    assert len(list((tmp_path / "snap").glob("*.jpg"))) == 1


def test_quit_while_flying_lands_first(monkeypatch):
    tick = {"n": 0}
    real_read = KeyboardInput.read

    def scripted_read(self, dt, pressed=None):
        out = real_read(self, dt, pressed)
        tick["n"] += 1
        if tick["n"] == 2:
            out.actions.add(Action.TAKEOFF)
        if tick["n"] == 120:
            out.actions.add(Action.QUIT)
        return out

    monkeypatch.setattr(KeyboardInput, "read", scripted_read)
    cfg = AppConfig()
    cfg.display.fps = 60
    drone = SimDrone()
    landed = []
    real_land = drone.land
    drone.land = lambda: (landed.append(True), real_land())
    App(cfg, drone, enable_faces=False).run()
    assert landed and not drone.is_flying
