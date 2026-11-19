import pytest

from tello_controller.config import InputConfig
from tello_controller.inputs import (
    Action, ControlInput, GamepadState, apply_deadzone, apply_expo, approach, gamepad_to_input,
)


def test_deadzone_rescales_to_full_range():
    assert apply_deadzone(0.1, 0.12) == 0.0
    assert apply_deadzone(1.0, 0.12) == pytest.approx(1.0)
    assert apply_deadzone(-1.0, 0.12) == pytest.approx(-1.0)
    assert 0 < apply_deadzone(0.2, 0.12) < 0.2


def test_expo_keeps_endpoints_and_softens_centre():
    assert apply_expo(1.0, 0.35) == pytest.approx(1.0)
    assert apply_expo(-1.0, 0.35) == pytest.approx(-1.0)
    assert abs(apply_expo(0.3, 0.35)) < 0.3


def test_approach():
    assert approach(0.0, 1.0, 0.25) == 0.25
    assert approach(0.9, 1.0, 0.25) == 1.0
    assert approach(0.0, -1.0, 0.25) == -0.25


def test_merge_largest_magnitude_wins_per_axis():
    a = ControlInput(lr=0.2, fb=-0.9, actions={Action.TAKEOFF})
    b = ControlInput(lr=-0.5, fb=0.1, actions={Action.SNAPSHOT})
    m = ControlInput.merge(a, b)
    assert (m.lr, m.fb) == (-0.5, -0.9)
    assert m.actions == {Action.TAKEOFF, Action.SNAPSHOT}


CFG = InputConfig()


def test_gamepad_mode2_mapping_and_inversion():
    # Left stick pushed up = climb, right stick pushed up = forward.
    s = GamepadState(lx=1.0, ly=-1.0, rx=-1.0, ry=-1.0)
    out = gamepad_to_input(s, GamepadState(), CFG)
    assert out.ud == pytest.approx(CFG.normal_scale)
    assert out.fb == pytest.approx(CFG.normal_scale)
    assert out.yaw == pytest.approx(CFG.normal_scale)
    assert out.lr == pytest.approx(-CFG.normal_scale)


def test_gamepad_speed_modes():
    s = GamepadState(ry=-1.0, buttons=frozenset({"lb"}))
    assert gamepad_to_input(s, GamepadState(), CFG).fb == pytest.approx(CFG.precision_scale)
    s = GamepadState(ry=-1.0, rt=1.0)
    assert gamepad_to_input(s, GamepadState(), CFG).fb == pytest.approx(CFG.boost_scale)


def test_gamepad_buttons_are_edge_triggered():
    held = GamepadState(buttons=frozenset({"start", "y"}))
    assert gamepad_to_input(held, GamepadState(), CFG).actions == {Action.TAKEOFF, Action.TOGGLE_LOCK}
    assert gamepad_to_input(held, held, CFG).actions == set()


def test_gamepad_flip_requires_a_held():
    dpad = GamepadState(buttons=frozenset({"left"}))
    assert gamepad_to_input(dpad, GamepadState(), CFG).actions == set()
    prev = GamepadState(buttons=frozenset({"a"}))
    combo = GamepadState(buttons=frozenset({"a", "left"}))
    assert gamepad_to_input(combo, prev, CFG).actions == {Action.FLIP_LEFT}


def test_gamepad_emergency_needs_both_sticks():
    one = GamepadState(buttons=frozenset({"ls"}))
    assert Action.EMERGENCY not in gamepad_to_input(one, GamepadState(), CFG).actions
    both = GamepadState(buttons=frozenset({"ls", "rs"}))
    assert Action.EMERGENCY in gamepad_to_input(both, one, CFG).actions
    assert Action.EMERGENCY not in gamepad_to_input(both, both, CFG).actions
