"""Heads-up display drawn with pygame over the video frame."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pygame

from .diagnostics import HOT_TEMP_C, LED_TABLE, BatteryReport
from .drone import Telemetry
from .faces import Face
from .lock_on import LockState, LockStatus

WHITE = (240, 240, 240)
GREY = (150, 150, 150)
GREEN = (60, 220, 90)
YELLOW = (250, 210, 60)
ORANGE = (255, 150, 40)
RED = (240, 60, 60)
CYAN = (80, 200, 255)
PANEL = (0, 0, 0, 150)

HELP_LINES = [
    "KEYBOARD                              XBOX",
    "W/S A/D    move fwd/back/left/right   right stick",
    "Up/Down    climb / descend            left stick up/down",
    "Left/Right yaw                        left stick left/right",
    "E / Q      take off / land            Menu / View",
    "F          toggle face lock           Y",
    "Space      hover (cancel lock)        B",
    "I K J L    flip f/b/l/r               hold A + D-pad",
    "Z          snapshot                   X",
    "R          record video+telemetry     RB",
    "N          enrol current face",
    "Shift/Ctrl boost / precision          RT / LB",
    "Backspace  EMERGENCY motor stop       click both sticks",
    "H          toggle this help           Esc quit (lands first)",
    "Tab        drone info + LED guide",
]


@dataclass
class HudState:
    drone_name: str
    telemetry: Telemetry
    flying: bool
    busy: str | None
    mode: str
    lock: LockStatus | None
    faces: list[Face]
    rc: tuple[int, int, int, int]
    manual_axes: set[str]
    recording: bool
    gamepad: str
    fps: float
    detect_ms: float
    known_only: bool
    show_help: bool
    show_info: bool = False
    battery: BatteryReport | None = None
    toasts: list[tuple[str, tuple[int, int, int]]] = field(default_factory=list)


class Hud:
    def __init__(self) -> None:
        pygame.font.init()
        self.font = pygame.font.SysFont("consolas,dejavusansmono,monospace", 18)
        self.small = pygame.font.SysFont("consolas,dejavusansmono,monospace", 15)
        self.big = pygame.font.SysFont("consolas,dejavusansmono,monospace", 28, bold=True)

    def _text(self, surf, text, pos, color=WHITE, font=None, center=False):
        font = font or self.font
        img = font.render(text, True, color)
        rect = img.get_rect()
        if center:
            rect.center = pos
        else:
            rect.topleft = pos
        surf.blit(img, rect)
        return rect

    def _panel(self, surf, rect):
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        panel.fill(PANEL)
        surf.blit(panel, rect.topleft)

    def draw(self, surf: pygame.Surface, s: HudState) -> None:
        w, h = surf.get_size()
        self._draw_faces(surf, s)
        self._draw_top_bar(surf, s, w)
        self._draw_sticks(surf, s, w, h)
        if s.busy:
            self._text(surf, s.busy.upper() + "...", (w // 2, h // 2), YELLOW, self.big, center=True)
        for i, (msg, color) in enumerate(s.toasts[-4:]):
            r = self.font.size(msg)
            rect = pygame.Rect(0, 0, r[0] + 20, r[1] + 8)
            rect.center = (w // 2, 70 + i * 32)
            self._panel(surf, rect)
            self._text(surf, msg, rect.center, color, center=True)
        if s.show_help:
            self._draw_help(surf, w, h)
        elif s.show_info:
            self._draw_info(surf, s, w, h)

    def _draw_top_bar(self, surf, s: HudState, w: int) -> None:
        t = s.telemetry
        self._panel(surf, pygame.Rect(0, 0, w, 30))
        bat_color = GREEN if t.battery > 40 else YELLOW if t.battery > 20 else RED
        x = 8
        for text, color in [
            (s.drone_name, CYAN),
            (f"BAT {t.battery:3d}%", bat_color),
            (f"H {t.height_cm:3d}cm", WHITE),
            (f"T {t.flight_time_s:3d}s", WHITE),
            ("FLYING" if s.flying else "LANDED", GREEN if s.flying else GREY),
        ]:
            x = self._text(surf, text, (x, 5), color).right + 18
        if t.age_s > 1.0:
            x = self._text(surf, f"NO TELEMETRY {t.age_s:.0f}s", (x, 5), RED).right + 18

        right = []
        if s.recording and int(time.monotonic() * 2) % 2 == 0:
            right.append(("● REC", RED))
        right.append((s.gamepad or "keyboard", GREY))
        right.append((f"{s.fps:4.1f}fps det {s.detect_ms:4.1f}ms", GREY))
        rx = w - 8
        for text, color in reversed(right):
            size = self.small.size(text)
            rx -= size[0]
            self._text(surf, text, (rx, 7), color, self.small)
            rx -= 16

        # Mode banner.
        mode_color = WHITE
        label = s.mode
        if s.lock is not None:
            st = s.lock.state
            mode_color = {LockState.LOCKED: GREEN, LockState.SEARCHING: YELLOW, LockState.LOST: ORANGE, LockState.GAVE_UP: RED}[st]
            who = f" {s.lock.name} ({s.lock.similarity:.2f})" if s.lock.name else ""
            label = f"LOCK-ON: {st.value.upper()}{who}"
            if st == LockState.LOST:
                label += f" {s.lock.lost_for_s:.1f}s"
            if st == LockState.SEARCHING and s.known_only:
                label += " (known faces only)"
        size = self.font.size(label)
        rect = pygame.Rect(0, 34, size[0] + 20, size[1] + 8)
        rect.centerx = w // 2
        self._panel(surf, rect)
        self._text(surf, label, rect.center, mode_color, center=True)

    def _draw_faces(self, surf, s: HudState) -> None:
        target = s.lock.target if (s.lock and s.lock.state == LockState.LOCKED) else None
        for face in s.faces:
            x, y, fw, fh = face.box
            is_target = target is not None and face is target
            color = GREEN if is_target else (YELLOW if s.lock else GREY)
            pygame.draw.rect(surf, color, (x, y, fw, fh), 3 if is_target else 1)
            if face.name:
                self._text(surf, f"{face.name} {face.similarity:.2f}", (x, y - 20), color, self.small)
        if target is not None and s.lock:
            w, h = surf.get_size()
            # Setpoint: where (and how big) the face should be.
            ty = int(s.lock.target_y * h)
            tw = int(s.lock.target_size * w)
            pygame.draw.line(surf, CYAN, (w // 2 - 15, ty), (w // 2 + 15, ty), 2)
            pygame.draw.line(surf, CYAN, (w // 2, ty - 15), (w // 2, ty + 15), 2)
            pygame.draw.rect(surf, CYAN, (w // 2 - tw // 2, ty - tw // 2, tw, tw), 1)

    def _draw_sticks(self, surf, s: HudState, w: int, h: int) -> None:
        lr, fb, ud, yaw = s.rc
        size = 90
        for i, (sx, sy, ax_x, ax_y, label) in enumerate([
            (yaw, ud, "yaw", "ud", "YAW / ALT"),
            (lr, fb, "lr", "fb", "ROLL / PITCH"),
        ]):
            cx = 20 + size // 2 if i == 0 else w - 20 - size // 2
            cy = h - 20 - size // 2
            rect = pygame.Rect(0, 0, size, size)
            rect.center = (cx, cy)
            self._panel(surf, rect)
            pygame.draw.rect(surf, GREY, rect, 1)
            pygame.draw.line(surf, GREY, (cx, rect.top), (cx, rect.bottom))
            pygame.draw.line(surf, GREY, (rect.left, cy), (rect.right, cy))
            manual = bool({ax_x, ax_y} & s.manual_axes)
            dot = (cx + int(sx / 100 * size / 2), cy - int(sy / 100 * size / 2))
            pygame.draw.circle(surf, WHITE if manual else GREEN, dot, 7)
            self._text(surf, label, (rect.centerx, rect.top - 12), GREY, self.small, center=True)

    def _draw_help(self, surf, w, h) -> None:
        line_h = 22
        rect = pygame.Rect(0, 0, 700, line_h * len(HELP_LINES) + 20)
        rect.center = (w // 2, h // 2)
        self._panel(surf, rect)
        for i, line in enumerate(HELP_LINES):
            self._text(surf, line, (rect.left + 14, rect.top + 10 + i * line_h), YELLOW if i == 0 else WHITE, self.small)

    # -- info screen -----------------------------------------------------
    _SEVERITY = {"ok": GREEN, "warn": YELLOW, "bad": RED, "info": GREY}
    _LED_RGB = {"red": RED, "green": GREEN, "yellow": YELLOW, "blue": CYAN}

    def _draw_info(self, surf, s: HudState, w, h) -> None:
        rect = pygame.Rect(0, 0, 820, 510)
        rect.midtop = (w // 2, 75)  # below the mode banner, above the stick indicators
        self._panel(surf, rect)
        x, y = rect.left + 16, rect.top + 12
        self._text(surf, "STATUS LED  (the drone can't report it over Wi-Fi, so match it by eye)", (x, y), YELLOW, self.small)
        y += 26
        meaning_x = x + 26 + self.small.size(" " * 41)[0]
        for colour, pattern, meaning, severity in LED_TABLE:
            self._led_swatch(surf, colour, pattern, (x + 8, y + 8))
            self._text(surf, f"{colour:<17}{pattern:<24}", (x + 26, y), WHITE, self.small)
            self._text(surf, meaning, (meaning_x, y), self._SEVERITY[severity], self.small)
            y += 21
        self._text(surf, "Solid red: often fixed by IMU calibration in the official Tello app,", (x, y + 4), GREY, self.small)
        self._text(surf, "letting it cool down, or checking the props/motors spin freely.", (x, y + 23), GREY, self.small)

        y += 58
        self._text(surf, "LIVE DIAGNOSTICS", (x, y), YELLOW, self.small)
        y += 24
        t = s.telemetry
        b = s.battery
        lines = []
        bat_col = GREEN if t.battery > 40 else YELLOW if t.battery > 20 else RED
        start = f" (started flight at {b.start_battery}%)" if b and b.start_battery is not None else ""
        lines.append((f"Battery        {t.battery}%{start}", bat_col))
        if b is not None:
            if b.drain_pct_per_min is not None:
                left = f", ~{b.est_minutes_left:.1f} min left" if b.est_minutes_left else ""
                lines.append((f"Drain          {b.drain_pct_per_min:.1f} %/min{left}  (healthy is ~7-8)", WHITE))
            text, sev = b.verdict
            lines.append((f"Battery health {text}", self._SEVERITY[sev]))
        lo = float(t.raw.get("templ", t.temp_c))
        hi = float(t.raw.get("temph", t.temp_c))
        lines.append((f"Temperature    {lo:.0f}-{hi:.0f} C", RED if hi >= HOT_TEMP_C else WHITE))
        if hi >= HOT_TEMP_C:
            lines.append(("               Running hot. It heats up sitting idle; let it cool between flights", YELLOW))
        lines.append((f"Height         {t.height_cm} cm (ToF sensor {t.tof_cm} cm)", WHITE))
        lines.append((f"Attitude       pitch {t.pitch}  roll {t.roll}  yaw {t.yaw}", WHITE))
        age = "fresh" if t.age_s < 1 else f"{t.age_s:.1f}s old"
        lines.append((f"Telemetry      {age}", GREEN if t.age_s < 1 else RED))
        for text, color in lines:
            self._text(surf, text, (x, y), color, self.small)
            y += 21
        self._text(surf, "Tab to close", (rect.right - 110, rect.bottom - 24), GREY, self.small)

    def _led_swatch(self, surf, colour: str, pattern: str, center) -> None:
        """Animated dot that blinks the way the real LED does."""
        t = time.monotonic()
        if "/" in colour:  # alternating colours
            cols = [self._LED_RGB[c] for c in colour.split("/")]
            pygame.draw.circle(surf, cols[int(t * 3) % len(cols)], center, 6)
            return
        if pattern == "solid":
            on = True
        elif "quickly" in pattern:
            on = int(t * 8) % 2 == 0
        elif "twice" in pattern:
            phase = t % 1.5
            on = phase < 0.15 or 0.3 < phase < 0.45
        else:  # slowly
            on = int(t * 2) % 2 == 0
        pygame.draw.circle(surf, self._LED_RGB[colour] if on else (50, 50, 50), center, 6)
