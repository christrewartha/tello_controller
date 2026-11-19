"""Face lock-on: hold the drone's position *relative to a face*.

When lock engages, the face's current vertical position and apparent size become
the setpoints. Then:

* yaw     keeps the face horizontally centred
* up/down keeps the face at the same height in frame
* fwd/back keeps the face the same size (i.e. the same distance away)

So if the person walks around, the drone turns, rises/falls and moves in or
out to stay put relative to them - a clear "I see you" response. It does not
plan paths or avoid obstacles; that's the person's job (and later, SLAM's).

If people are enrolled in the face gallery, only known people are locked onto
and identity is re-checked periodically; otherwise the largest face is used.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass

import numpy as np

from .config import FaceConfig, LockOnConfig
from .faces import Face, FaceGallery, FaceRecognizer

log = logging.getLogger(__name__)


class PID:
    def __init__(self, kp: float, ki: float, kd: float, limit: float, d_filter: float = 0.5):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.limit = limit
        self.d_filter = d_filter
        self.reset()

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error: float | None = None
        self._d = 0.0

    def update(self, error: float, dt: float) -> float:
        dt = max(dt, 1e-3)
        if self._prev_error is not None:
            raw_d = (error - self._prev_error) / dt
            self._d = self.d_filter * self._d + (1 - self.d_filter) * raw_d
        self._prev_error = error
        if self.ki:
            self._integral += error * dt
            # Anti-windup: integral alone may not exceed the output limit.
            max_i = self.limit / self.ki
            self._integral = float(np.clip(self._integral, -max_i, max_i))
        out = self.kp * error + self.ki * self._integral + self.kd * self._d
        return float(np.clip(out, -self.limit, self.limit))


def deadband(error: float, band: float) -> float:
    if abs(error) <= band:
        return 0.0
    return error - band if error > 0 else error + band


class LockState(enum.Enum):
    SEARCHING = "searching"
    LOCKED = "locked"
    LOST = "lost"
    GAVE_UP = "gave up"


@dataclass
class LockStatus:
    state: LockState
    target: Face | None = None
    name: str | None = None
    similarity: float = 0.0
    lost_for_s: float = 0.0
    target_y: float = 0.0
    target_size: float = 0.0


class LockOnController:
    def __init__(
        self,
        config: LockOnConfig,
        face_config: FaceConfig,
        recognizer: FaceRecognizer | None = None,
        gallery: FaceGallery | None = None,
    ):
        self.config = config
        self.face_config = face_config
        self.recognizer = recognizer
        self.gallery = gallery
        self.yaw_pid = PID(*config.yaw_pid, limit=config.yaw_limit)
        self.ud_pid = PID(*config.ud_pid, limit=config.ud_limit)
        self.fb_pid = PID(*config.fb_pid, limit=config.fb_limit)
        self.active = False
        self._reset_tracking()

    # -- public API ------------------------------------------------------
    @property
    def known_only(self) -> bool:
        return bool(self.gallery) and self.recognizer is not None

    def engage(self) -> None:
        self.active = True
        self._reset_tracking()
        log.info("Lock-on engaged (%s)", "known faces only" if self.known_only else "largest face")

    def disengage(self) -> None:
        if self.active:
            log.info("Lock-on disengaged")
        self.active = False
        self._reset_tracking()

    def update(self, faces: list[Face], frame: np.ndarray | None, now: float | None = None) -> tuple[tuple[int, int, int, int], LockStatus]:
        """Returns RC (lr, fb, ud, yaw) and status. Call once per processed frame."""
        now = time.monotonic() if now is None else now
        dt = now - self._last_update if self._last_update else 0.05
        self._last_update = now
        self._now = now
        self._frame_count += 1

        if self._target is None:
            face = self._acquire(faces, frame)
            if face is None:
                return (0, 0, 0, 0), self._status(LockState.SEARCHING)
            self._set_target(face, now, first=True)
        else:
            face = self._follow(faces, frame)
            if face is None:
                return self._lost(now)
            self._set_target(face, now, first=False)

        f = self._target
        c = self.config
        yaw = self.yaw_pid.update(deadband(f.cx - 0.5, c.x_deadband), dt)
        ud = self.ud_pid.update(deadband(self._target_y - f.cy, c.y_deadband), dt)
        size_err = (self._target_size - f.size) / self._target_size  # relative: +0.5 = half as big
        fb = self.fb_pid.update(deadband(size_err, c.size_deadband), dt)

        if self._nod_until > now:
            phase_up = (self._nod_until - now) > c.nod_duration_s
            ud = c.nod_speed if phase_up else -c.nod_speed

        self._last_rc = (0, int(fb), int(ud), int(yaw))
        return self._last_rc, self._status(LockState.LOCKED)

    # -- internals -------------------------------------------------------
    def _reset_tracking(self) -> None:
        self._target: Face | None = None
        self._name: str | None = None
        self._similarity = 0.0
        self._target_y = 0.0
        self._target_size = 0.0
        self._lost_since: float | None = None
        self._last_seen = 0.0
        self._last_update = 0.0
        self._now = 0.0
        self._last_rc = (0, 0, 0, 0)
        self._frame_count = 0
        self._mismatches = 0
        self._nod_until = 0.0
        self._ever_locked = False
        for pid in (self.yaw_pid, self.ud_pid, self.fb_pid):
            pid.reset()

    def _status(self, state: LockState) -> LockStatus:
        lost = (self._now - self._lost_since) if self._lost_since is not None else 0.0
        return LockStatus(state, self._target, self._name, self._similarity, lost, self._target_y, self._target_size)

    def _identify(self, frame: np.ndarray, face: Face) -> tuple[str | None, float]:
        emb = self.recognizer.embed(frame, face)  # type: ignore[union-attr]
        return self.gallery.identify(emb)  # type: ignore[union-attr]

    def _acquire(self, faces: list[Face], frame: np.ndarray | None) -> Face | None:
        if not faces:
            return None
        if not self.known_only or frame is None:
            return faces[0]  # largest
        best, best_sim = None, self.face_config.match_threshold
        for face in faces[:4]:
            name, sim = self._identify(frame, face)
            if sim >= best_sim:
                best, best_sim, self._name = face, sim, name
        if best is not None:
            best.name, best.similarity = self._name, best_sim
            self._similarity = best_sim
        return best

    def _follow(self, faces: list[Face], frame: np.ndarray | None) -> Face | None:
        prev = self._target
        assert prev is not None
        candidates = []
        for face in faces:
            jump = np.hypot(face.cx - prev.cx, face.cy - prev.cy)
            ratio = face.size / max(prev.size, 1e-6)
            if jump <= self.config.max_jump and 0.6 <= ratio <= 1.6:
                candidates.append((jump, face))
        face = min(candidates, key=lambda c: c[0])[1] if candidates else None

        if face is None:
            if self._lost_since is not None and self.known_only:
                # Re-identify anywhere in frame while lost.
                face = self._acquire(faces, frame)
            elif self._lost_since is not None and not self.known_only and faces:
                # Without identities, accept a similar-sized face after a short gap.
                lost_for = self._now - self._lost_since
                similar = [f for f in faces if 0.5 <= f.size / max(prev.size, 1e-6) <= 2.0]
                if similar and lost_for > 0.3:
                    face = similar[0]
            return face

        # Periodically confirm it's still the same person.
        if self.known_only and frame is not None and self._frame_count % self.face_config.recognise_every_n_frames == 0:
            name, sim = self._identify(frame, face)
            if name == self._name and sim >= self.face_config.match_threshold * 0.8:
                self._mismatches = 0
                self._similarity = sim
            else:
                self._mismatches += 1
                if self._mismatches >= 2:
                    log.info("Locked face no longer matches %s (sim %.2f)", self._name, sim)
                    self._mismatches = 0
                    return None
        face.name, face.similarity = self._name, self._similarity
        return face

    def _set_target(self, face: Face, now: float, first: bool) -> None:
        c = self.config
        if first and not self._ever_locked:
            self._target_size = float(np.clip(face.size, c.min_target_size, c.max_target_size))
            self._target_y = float(np.clip(face.cy, c.min_target_y, c.max_target_y))
            self._ever_locked = True
            if c.acknowledge_nod:
                self._nod_until = now + 2 * c.nod_duration_s
            log.info("Locked onto %s (size %.2f, y %.2f)", self._name or "face", self._target_size, self._target_y)
        if self._lost_since is not None:
            log.info("Re-acquired target")
        self._target = face
        self._lost_since = None
        self._last_seen = now

    def _lost(self, now: float) -> tuple[tuple[int, int, int, int], LockStatus]:
        if self._lost_since is None:
            self._lost_since = now
            for pid in (self.yaw_pid, self.ud_pid, self.fb_pid):
                pid.reset()
        lost_for = now - self._lost_since
        if lost_for >= self.config.lost_give_up_s:
            return (0, 0, 0, 0), self._status(LockState.GAVE_UP)
        if lost_for < self.config.lost_hold_s:
            # Coast: fade the last command out (helps when the face briefly leaves frame
            # because the drone was turning towards it).
            k = 1.0 - lost_for / self.config.lost_hold_s
            rc = tuple(int(v * k) for v in self._last_rc)
            return rc, self._status(LockState.LOST)  # type: ignore[return-value]
        return (0, 0, 0, 0), self._status(LockState.LOST)
