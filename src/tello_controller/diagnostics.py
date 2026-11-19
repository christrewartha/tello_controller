"""Drone health: what the status LED means, plus battery drain analysis.

The Tello does not report its LED state or any error codes over Wi-Fi, so the
info screen shows the official LED table next to the telemetry that explains
the usual causes of a red light (battery level / health, temperature).

LED table from the Ryze Tello User Manual, "Aircraft Status Indicator".
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# (colour, pattern, meaning, severity) - severity: ok / warn / bad / info
LED_TABLE: list[tuple[str, str, str, str]] = [
    ("red/green/yellow", "alternating", "Powering on, self-test", "info"),
    ("green", "blinks twice, repeating", "Normal: vision positioning active", "ok"),
    ("yellow", "blinking slowly", "Vision positioning unavailable (attitude mode: drifts)", "warn"),
    ("yellow", "blinking quickly", "Control signal lost", "warn"),
    ("red", "blinking slowly", "Low battery", "warn"),
    ("red", "blinking quickly", "Critically low battery", "bad"),
    ("red", "solid", "Critical error", "bad"),
    ("blue", "blinking slowly", "Charging", "info"),
    ("blue", "solid", "Charging complete", "info"),
    ("blue", "blinking quickly", "Charging error", "bad"),
]

# Heuristics, not official specs. A Tello flies ~13 minutes on a full, healthy
# battery, so hover drain is roughly 7-8 %/min.
HEALTHY_DRAIN_PCT_PER_MIN = 8.0
HIGH_DRAIN_PCT_PER_MIN = 12.0
SUDDEN_DROP_PCT = 5
SUDDEN_DROP_WINDOW_S = 10.0
HOT_TEMP_C = 80.0


@dataclass
class BatteryReport:
    battery: int
    drain_pct_per_min: float | None
    """Linear-fit drain over the recent flying window, None until enough data."""
    est_minutes_left: float | None
    sudden_drops: int
    """Times the % fell by SUDDEN_DROP_PCT or more within SUDDEN_DROP_WINDOW_S."""
    start_battery: int | None

    @property
    def verdict(self) -> tuple[str, str]:
        """(text, severity) - severity is ok / warn / bad / info."""
        if self.drain_pct_per_min is None:
            return "Measuring drain: fly for a minute or so", "info"
        if self.sudden_drops:
            return f"Battery % dropped suddenly {self.sudden_drops}x: likely a worn battery", "bad"
        if self.drain_pct_per_min >= HIGH_DRAIN_PCT_PER_MIN:
            return f"Draining fast ({self.drain_pct_per_min:.1f} %/min): battery may be worn", "bad"
        if self.drain_pct_per_min > HEALTHY_DRAIN_PCT_PER_MIN * 1.15:
            return f"Drain a bit high ({self.drain_pct_per_min:.1f} %/min)", "warn"
        return f"Drain looks healthy ({self.drain_pct_per_min:.1f} %/min)", "ok"


class BatteryMonitor:
    """Tracks battery % while flying to estimate drain rate and spot sudden drops."""

    def __init__(self, window_s: float = 90.0, min_span_s: float = 45.0):
        self.window_s = window_s
        self.min_span_s = min_span_s
        self._samples: deque[tuple[float, int]] = deque()
        self._recent: deque[tuple[float, int]] = deque()
        self._last_battery: int | None = None
        self.sudden_drops = 0
        self.start_battery: int | None = None

    def update(self, t: float, battery: int, flying: bool) -> None:
        if not flying or battery <= 0:
            # Drain on the ground is meaningless; start fresh next flight.
            self._samples.clear()
            self._recent.clear()
            self._last_battery = None
            return
        if self.start_battery is None:
            self.start_battery = battery
        if battery == self._last_battery:
            return  # only store changes; % is coarse and updates slowly
        self._last_battery = battery
        self._samples.append((t, battery))
        while self._samples and t - self._samples[0][0] > self.window_s:
            self._samples.popleft()

        self._recent.append((t, battery))
        while self._recent and t - self._recent[0][0] > SUDDEN_DROP_WINDOW_S:
            self._recent.popleft()
        if self._recent[0][1] - battery >= SUDDEN_DROP_PCT:
            self.sudden_drops += 1
            self._recent.clear()
            self._recent.append((t, battery))

    def drain_pct_per_min(self) -> float | None:
        s = self._samples
        if len(s) < 3 or s[-1][0] - s[0][0] < self.min_span_s:
            return None
        n = len(s)
        mt = sum(t for t, _ in s) / n
        mb = sum(b for _, b in s) / n
        var = sum((t - mt) ** 2 for t, _ in s)
        if var == 0:
            return None
        slope = sum((t - mt) * (b - mb) for t, b in s) / var  # % per second
        return max(0.0, -slope * 60)

    def report(self, battery: int) -> BatteryReport:
        drain = self.drain_pct_per_min()
        left = battery / drain if drain else None
        return BatteryReport(battery, drain, left, self.sudden_drops, self.start_battery)
