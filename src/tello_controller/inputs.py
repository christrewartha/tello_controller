"""Keyboard and gamepad input, merged into one `ControlInput` per tick.

Axes are floats in -1..1 *after* speed scaling (precision / normal / boost),
so the caller just multiplies by 100 to get Tello RC units.

Default layouts
---------------
Keyboard:
    W/S forward/back     A/D left/right     Up/Down climb/descend    Left/Right yaw
    E take off   Q land   F toggle face lock   Space hover (cancels lock)
    I/K/J/L flip fwd/back/left/right   Z snapshot   R toggle recording
    N enrol the current face   Shift boost   Ctrl precision
    Backspace EMERGENCY motor stop   Esc quit (lands first)

Xbox controller (Mode 2 layout):
    Left stick: climb/descend + yaw      Right stick: forward/back + left/right
    Menu take off   View land   Y toggle face lock   B hover (cancels lock)
    X snapshot   RB toggle recording   Hold A + D-pad flip
    LB hold precision   RT analog boost
    Click BOTH sticks: EMERGENCY motor stop
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

import pygame

from .config import InputConfig

log = logging.getLogger(__name__)


class Action(enum.Enum):
    TAKEOFF = "takeoff"
    LAND = "land"
    EMERGENCY = "emergency"
    HOVER = "hover"
    TOGGLE_LOCK = "toggle_lock"
    FLIP_FORWARD = "flip_f"
    FLIP_BACK = "flip_b"
    FLIP_LEFT = "flip_l"
    FLIP_RIGHT = "flip_r"
    SNAPSHOT = "snapshot"
    TOGGLE_RECORD = "toggle_record"
    ENROLL = "enroll"
    QUIT = "quit"


FLIP_ACTIONS = {
    Action.FLIP_FORWARD: "f",
    Action.FLIP_BACK: "b",
    Action.FLIP_LEFT: "l",
    Action.FLIP_RIGHT: "r",
}

AXES = ("lr", "fb", "ud", "yaw")


@dataclass
class ControlInput:
    lr: float = 0.0
    fb: float = 0.0
    ud: float = 0.0
    yaw: float = 0.0
    actions: set[Action] = field(default_factory=set)

    def axis(self, name: str) -> float:
        return getattr(self, name)

    def as_rc(self) -> tuple[int, int, int, int]:
        return tuple(int(round(self.axis(a) * 100)) for a in AXES)  # type: ignore[return-value]

    @staticmethod
    def merge(*inputs: "ControlInput") -> "ControlInput":
        """Per axis, the input with the largest magnitude wins; actions are unioned."""
        out = ControlInput()
        for a in AXES:
            setattr(out, a, max((i.axis(a) for i in inputs), key=abs, default=0.0))
        for i in inputs:
            out.actions |= i.actions
        return out


# --------------------------------------------------------------------------
# Shaping helpers (pure functions, unit tested)
# --------------------------------------------------------------------------

def apply_deadzone(v: float, deadzone: float) -> float:
    """Remove the deadzone and rescale so output still reaches +-1."""
    if abs(v) <= deadzone:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * min(1.0, (abs(v) - deadzone) / (1.0 - deadzone))


def apply_expo(v: float, expo: float) -> float:
    return (1.0 - expo) * v + expo * v**3


def approach(current: float, target: float, max_step: float) -> float:
    if current < target:
        return min(target, current + max_step)
    return max(target, current - max_step)


# --------------------------------------------------------------------------
# Keyboard
# --------------------------------------------------------------------------

class KeyboardInput:
    AXIS_KEYS = {
        "fb": (pygame.K_w, pygame.K_s),
        "lr": (pygame.K_d, pygame.K_a),
        "ud": (pygame.K_UP, pygame.K_DOWN),
        "yaw": (pygame.K_RIGHT, pygame.K_LEFT),
    }
    ACTION_KEYS = {
        pygame.K_e: Action.TAKEOFF,
        pygame.K_q: Action.LAND,
        pygame.K_f: Action.TOGGLE_LOCK,
        pygame.K_SPACE: Action.HOVER,
        pygame.K_i: Action.FLIP_FORWARD,
        pygame.K_k: Action.FLIP_BACK,
        pygame.K_j: Action.FLIP_LEFT,
        pygame.K_l: Action.FLIP_RIGHT,
        pygame.K_z: Action.SNAPSHOT,
        pygame.K_r: Action.TOGGLE_RECORD,
        pygame.K_n: Action.ENROLL,
        pygame.K_BACKSPACE: Action.EMERGENCY,
        pygame.K_ESCAPE: Action.QUIT,
    }

    def __init__(self, config: InputConfig):
        self.config = config
        self._axes = {a: 0.0 for a in AXES}
        self._pending: set[Action] = set()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key in self.ACTION_KEYS:
            self._pending.add(self.ACTION_KEYS[event.key])

    def read(self, dt: float, pressed=None) -> ControlInput:
        pressed = pressed if pressed is not None else pygame.key.get_pressed()
        mods = pygame.key.get_mods()
        if mods & pygame.KMOD_SHIFT:
            scale = self.config.boost_scale
        elif mods & pygame.KMOD_CTRL:
            scale = self.config.precision_scale
        else:
            scale = self.config.normal_scale

        out = ControlInput(actions=self._pending)
        self._pending = set()
        for axis, (pos, neg) in self.AXIS_KEYS.items():
            target = float(pressed[pos]) - float(pressed[neg])
            rate = self.config.keyboard_ramp_per_s if target else self.config.keyboard_release_per_s
            # Reversing direction should be quick, so treat it like a release.
            if target and self._axes[axis] * target < 0:
                rate = self.config.keyboard_release_per_s
            self._axes[axis] = approach(self._axes[axis], target, rate * dt)
            setattr(out, axis, self._axes[axis] * scale)
        return out


# --------------------------------------------------------------------------
# Gamepad
# --------------------------------------------------------------------------

@dataclass
class GamepadState:
    """Device-independent snapshot. Sticks -1..1 (up is -1), triggers 0..1."""

    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    lt: float = 0.0
    rt: float = 0.0
    buttons: frozenset[str] = frozenset()
    """Names: a b x y lb rb back start ls rs up down left right."""


def gamepad_to_input(state: GamepadState, prev: GamepadState, config: InputConfig) -> ControlInput:
    """Map an Xbox-style pad to drone controls (Mode 2). Pure function."""

    def shape(v: float) -> float:
        return apply_expo(apply_deadzone(v, config.deadzone), config.expo)

    pressed = state.buttons - prev.buttons  # rising edges only
    held = state.buttons

    if "lb" in held:
        scale = config.precision_scale
    else:
        rt = apply_deadzone(state.rt, 0.05)
        scale = config.normal_scale + (config.boost_scale - config.normal_scale) * rt

    out = ControlInput(
        yaw=shape(state.lx) * scale,
        ud=-shape(state.ly) * scale,
        lr=shape(state.rx) * scale,
        fb=-shape(state.ry) * scale,
    )

    if {"ls", "rs"} <= held and pressed & {"ls", "rs"}:
        out.actions.add(Action.EMERGENCY)
    if "a" in held:
        for btn, action in (("up", Action.FLIP_FORWARD), ("down", Action.FLIP_BACK),
                            ("left", Action.FLIP_LEFT), ("right", Action.FLIP_RIGHT)):
            if btn in pressed:
                out.actions.add(action)
    simple = {
        "start": Action.TAKEOFF,
        "back": Action.LAND,
        "y": Action.TOGGLE_LOCK,
        "b": Action.HOVER,
        "x": Action.SNAPSHOT,
        "rb": Action.TOGGLE_RECORD,
    }
    for btn, action in simple.items():
        if btn in pressed:
            out.actions.add(action)
    return out


class GamepadInput:
    """Reads the first connected controller, with hot-plug support.

    Uses SDL's GameController API (standardised Xbox layout regardless of driver)
    when available, falling back to the raw joystick API with the XInput mapping.
    """

    _RAW_BUTTONS = {0: "a", 1: "b", 2: "x", 3: "y", 4: "lb", 5: "rb", 6: "back", 7: "start", 8: "ls", 9: "rs"}

    def __init__(self, config: InputConfig):
        self.config = config
        self._prev = GamepadState()
        self._device = None
        self._kind = ""
        self._retry_in = 0.0
        try:
            from pygame._sdl2 import controller as sdl_controller

            sdl_controller.init()
            self._sdl = sdl_controller
        except Exception:  # noqa: BLE001 - experimental API may be missing
            self._sdl = None
        pygame.joystick.init()

    @property
    def connected(self) -> bool:
        return self._device is not None

    @property
    def device_name(self) -> str:
        if self._device is None:
            return ""
        return getattr(self._device, "name", None) or self._device.get_name()

    def rumble(self, low: float, high: float, duration_ms: int) -> None:
        """Haptic feedback (e.g. when a face lock is acquired). Silently ignored if unsupported."""
        if self._device is not None and hasattr(self._device, "rumble"):
            try:
                self._device.rumble(low, high, duration_ms)
            except Exception:  # noqa: BLE001
                pass

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
            self._device = None
            self._retry_in = 0.0

    def _connect(self) -> None:
        count = pygame.joystick.get_count()
        for i in range(count):
            try:
                if self._sdl is not None and self._sdl.is_controller(i):
                    self._device, self._kind = self._sdl.Controller(i), "controller"
                else:
                    js = pygame.joystick.Joystick(i)
                    js.init()
                    self._device, self._kind = js, "joystick"
                log.info("Gamepad connected: %s (%s API)", self.device_name, self._kind)
                return
            except Exception:  # noqa: BLE001
                log.debug("Failed to open joystick %d", i, exc_info=True)

    def _read_state(self) -> GamepadState:
        d = self._device
        if self._kind == "controller":
            c = pygame

            def ax(a):
                return max(-1.0, d.get_axis(a) / 32767.0)

            names = {
                c.CONTROLLER_BUTTON_A: "a", c.CONTROLLER_BUTTON_B: "b",
                c.CONTROLLER_BUTTON_X: "x", c.CONTROLLER_BUTTON_Y: "y",
                c.CONTROLLER_BUTTON_LEFTSHOULDER: "lb", c.CONTROLLER_BUTTON_RIGHTSHOULDER: "rb",
                c.CONTROLLER_BUTTON_BACK: "back", c.CONTROLLER_BUTTON_START: "start",
                c.CONTROLLER_BUTTON_LEFTSTICK: "ls", c.CONTROLLER_BUTTON_RIGHTSTICK: "rs",
                c.CONTROLLER_BUTTON_DPAD_UP: "up", c.CONTROLLER_BUTTON_DPAD_DOWN: "down",
                c.CONTROLLER_BUTTON_DPAD_LEFT: "left", c.CONTROLLER_BUTTON_DPAD_RIGHT: "right",
            }
            return GamepadState(
                lx=ax(c.CONTROLLER_AXIS_LEFTX), ly=ax(c.CONTROLLER_AXIS_LEFTY),
                rx=ax(c.CONTROLLER_AXIS_RIGHTX), ry=ax(c.CONTROLLER_AXIS_RIGHTY),
                lt=ax(c.CONTROLLER_AXIS_TRIGGERLEFT), rt=ax(c.CONTROLLER_AXIS_TRIGGERRIGHT),
                buttons=frozenset(n for b, n in names.items() if d.get_button(b)),
            )

        # Raw joystick, XInput ordering on Windows: axes LX LY RX RY LT RT.
        n_axes = d.get_numaxes()

        def ax(i, default=0.0):
            return d.get_axis(i) if i < n_axes else default

        buttons = {n for i, n in self._RAW_BUTTONS.items() if i < d.get_numbuttons() and d.get_button(i)}
        if d.get_numhats():
            hx, hy = d.get_hat(0)
            buttons |= {n for cond, n in ((hy > 0, "up"), (hy < 0, "down"), (hx < 0, "left"), (hx > 0, "right")) if cond}
        return GamepadState(
            lx=ax(0), ly=ax(1), rx=ax(2), ry=ax(3),
            lt=(ax(4, -1.0) + 1) / 2, rt=(ax(5, -1.0) + 1) / 2,
            buttons=frozenset(buttons),
        )

    def read(self, dt: float) -> ControlInput:
        if self._device is None:
            self._retry_in -= dt
            if self._retry_in <= 0:
                self._retry_in = 1.0
                self._connect()
            if self._device is None:
                return ControlInput()
        try:
            state = self._read_state()
        except Exception:  # noqa: BLE001 - device unplugged mid-read
            log.warning("Gamepad read failed; will reconnect", exc_info=True)
            self._device = None
            self._prev = GamepadState()
            return ControlInput()
        out = gamepad_to_input(state, self._prev, self.config)
        self._prev = state
        return out
