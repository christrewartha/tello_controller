"""All tunable settings in one place.

Everything is a plain dataclass so values can be overridden in code or (later)
loaded from a file. Speeds are in Tello RC units (-100..100).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class FlightConfig:
    min_battery_to_takeoff: int = 15
    """Refuse to take off below this battery %."""
    auto_land_battery: int = 8
    """Land automatically when battery drops to this %."""
    control_rate_hz: float = 20.0
    """How often RC commands are sent to the drone."""
    telemetry_timeout_s: float = 2.0
    """If no state packet arrives for this long while flying, hover then land."""


@dataclass
class InputConfig:
    # Speed scaling applied to manual input (fraction of full RC range).
    normal_scale: float = 0.6
    precision_scale: float = 0.25
    boost_scale: float = 1.0

    # Keyboard: digital keys are ramped so movement isn't jerky.
    keyboard_ramp_per_s: float = 3.0
    """Axis units (0..1) per second when a key is held."""
    keyboard_release_per_s: float = 6.0
    """Axis units per second when returning to zero after release."""

    # Gamepad stick shaping.
    deadzone: float = 0.12
    expo: float = 0.35
    """0 = linear, 1 = fully cubic. Softens small stick movements."""
    manual_override_threshold: float = 0.05
    """Manual axis magnitude above which it overrides autonomous control."""


@dataclass
class FaceConfig:
    models_dir: Path = PROJECT_ROOT / "models"
    gallery_dir: Path = PROJECT_ROOT / "data" / "faces"
    detect_width: int = 480
    """Frames are downscaled to this width for detection (speed)."""
    score_threshold: float = 0.75
    match_threshold: float = 0.40
    """SFace cosine similarity above which a face is considered a known person."""
    recognise_every_n_frames: int = 10
    """Re-run (relatively expensive) recognition on the locked face this often."""


@dataclass
class LockOnConfig:
    # PID gains act on normalised errors (fractions of frame size).
    yaw_pid: tuple[float, float, float] = (110.0, 0.0, 12.0)
    ud_pid: tuple[float, float, float] = (90.0, 0.0, 10.0)
    fb_pid: tuple[float, float, float] = (60.0, 0.0, 8.0)
    """Acts on *relative* size error: +0.5 means the face looks half as big as the setpoint."""
    yaw_limit: int = 50
    ud_limit: int = 40
    fb_limit: int = 30

    # Deadbands (normalised) so the drone doesn't twitch when you're nearly still.
    x_deadband: float = 0.03
    y_deadband: float = 0.04
    size_deadband: float = 0.08

    # The face size / vertical position captured when lock engages is used as the
    # setpoint ("stay where you are relative to me"), clamped to sane ranges.
    # Face width / frame width. With the Tello's ~83 deg FOV and a ~15cm face:
    # 0.05 ~= 1.7m away, 0.08 ~= 1.1m, 0.14 ~= 0.6m. Max is a safety minimum distance.
    min_target_size: float = 0.05
    max_target_size: float = 0.14
    min_target_y: float = 0.30
    max_target_y: float = 0.60

    lost_hold_s: float = 1.0
    """After losing the face, keep coasting on the last command for this long."""
    lost_give_up_s: float = 8.0
    """After this long without the face, drop back to manual mode."""
    max_jump: float = 0.25
    """Max normalised centre movement between frames to count as the same face."""

    acknowledge_nod: bool = True
    """Do a small up/down 'nod' when a face is first locked, so the person knows."""
    nod_speed: int = 35
    nod_duration_s: float = 0.25


@dataclass
class RecordingConfig:
    output_dir: Path = PROJECT_ROOT / "recordings"
    snapshot_dir: Path = PROJECT_ROOT / "snapshots"
    fps: float = 30.0


@dataclass
class DisplayConfig:
    window_size: tuple[int, int] = (960, 720)
    """Tello's native stream resolution."""
    fps: int = 30


@dataclass
class AppConfig:
    flight: FlightConfig = field(default_factory=FlightConfig)
    input: InputConfig = field(default_factory=InputConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    lock_on: LockOnConfig = field(default_factory=LockOnConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
