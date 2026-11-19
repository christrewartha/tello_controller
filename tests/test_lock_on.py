import numpy as np
import pytest

from tello_controller.app import arbitrate
from tello_controller.config import FaceConfig, LockOnConfig
from tello_controller.faces import Face
from tello_controller.inputs import ControlInput
from tello_controller.lock_on import PID, LockOnController, LockState, deadband

W, H = 960, 720


def face(cx, cy, size):
    w = size * W
    return Face(cx * W - w / 2, cy * H - w / 2, w, w, 0.9, W, H, np.zeros(15, np.float32))


def make(**overrides):
    cfg = LockOnConfig(acknowledge_nod=False, **overrides)
    lock = LockOnController(cfg, FaceConfig())
    lock.engage()
    return lock


def test_deadband():
    assert deadband(0.02, 0.03) == 0
    assert deadband(0.05, 0.03) == pytest.approx(0.02)
    assert deadband(-0.05, 0.03) == pytest.approx(-0.02)


def test_pid_clamps_and_antiwindup():
    pid = PID(10, 5, 0, limit=20)
    for _ in range(100):
        out = pid.update(10, 0.1)
    assert out == 20
    assert pid.update(-0.1, 0.1) <= 20


def test_searching_until_face_appears():
    lock = make()
    rc, st = lock.update([], None, now=0.0)
    assert st.state == LockState.SEARCHING and rc == (0, 0, 0, 0)


def test_setpoint_is_captured_at_lock_then_holds_still():
    lock = make()
    rc, st = lock.update([face(0.5, 0.45, 0.10)], None, now=0.0)
    assert st.state == LockState.LOCKED
    assert st.target_size == pytest.approx(0.10)
    assert st.target_y == pytest.approx(0.45)
    rc, _ = lock.update([face(0.5, 0.45, 0.10)], None, now=0.05)
    assert rc == (0, 0, 0, 0)


def test_controller_directions():
    lock = make()
    lock.update([face(0.5, 0.45, 0.10)], None, now=0.0)
    # Face moves right, up, and further away (smaller).
    lr, fb, ud, yaw = lock.update([face(0.6, 0.38, 0.08)], None, now=0.05)[0]
    assert yaw > 0, "should yaw right towards the face"
    assert ud > 0, "should climb when the face rises in frame"
    assert fb > 0, "should move forward when the face gets smaller"
    assert lr == 0


def test_moves_back_when_face_gets_closer():
    lock = make()
    lock.update([face(0.5, 0.45, 0.10)], None, now=0.0)
    _, fb, _, _ = lock.update([face(0.5, 0.45, 0.13)], None, now=0.05)[0]
    assert fb < 0


def test_ignores_far_away_jump_and_reports_lost_then_gives_up():
    lock = make(lost_hold_s=0.5, lost_give_up_s=2.0)
    lock.update([face(0.3, 0.45, 0.10)], None, now=0.0)
    # Only a much bigger face on the other side of the frame: not our target.
    _, st = lock.update([face(0.9, 0.5, 0.35)], None, now=0.1)
    assert st.state == LockState.LOST
    _, st = lock.update([], None, now=1.0)
    assert st.state == LockState.LOST
    rc, st = lock.update([], None, now=2.2)
    assert st.state == LockState.GAVE_UP and rc == (0, 0, 0, 0)


def test_coasts_then_hovers_while_lost():
    lock = make(lost_hold_s=0.5, lost_give_up_s=5.0)
    lock.update([face(0.5, 0.45, 0.10)], None, now=0.0)
    rc, _ = lock.update([face(0.6, 0.45, 0.10)], None, now=0.05)
    assert rc[3] > 0
    coast, _ = lock.update([], None, now=0.1)
    assert 0 < coast[3] <= rc[3]
    still, _ = lock.update([], None, now=0.8)
    assert still == (0, 0, 0, 0)


def test_reacquires_similar_face_after_gap():
    lock = make()
    lock.update([face(0.3, 0.45, 0.10)], None, now=0.0)
    lock.update([], None, now=0.1)
    _, st = lock.update([face(0.8, 0.45, 0.105)], None, now=0.6)
    assert st.state == LockState.LOCKED
    assert st.target_size == pytest.approx(0.10), "setpoint kept from original lock"


def test_nod_on_first_lock():
    cfg = LockOnConfig(acknowledge_nod=True, nod_duration_s=0.25, nod_speed=30)
    lock = LockOnController(cfg, FaceConfig())
    lock.engage()
    assert lock.update([face(0.5, 0.45, 0.10)], None, now=0.0)[0][2] == 30
    assert lock.update([face(0.5, 0.45, 0.10)], None, now=0.3)[0][2] == -30
    assert lock.update([face(0.5, 0.45, 0.10)], None, now=0.6)[0][2] == 0


def test_manual_overrides_autonomy_per_axis():
    manual = ControlInput(lr=0.5, yaw=0.01)
    rc, overridden = arbitrate(manual, (0, 10, 20, 30), threshold=0.05)
    assert rc == (50, 10, 20, 30)
    assert overridden == {"lr"}
    rc, _ = arbitrate(ControlInput(), None, threshold=0.05)
    assert rc == (0, 0, 0, 0)
