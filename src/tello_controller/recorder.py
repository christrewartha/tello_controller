"""Flight recording: raw video + per-frame telemetry.

Each recording is a folder containing `video.mp4` (clean frames, no HUD) and
`frames.csv` (one row per video frame: timestamp, telemetry, RC command). This
is the input format for offline 3D reconstruction / SLAM experiments.
"""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .drone import Telemetry

log = logging.getLogger(__name__)

CSV_FIELDS = [
    "frame", "t", "battery", "height_cm", "tof_cm", "pitch", "roll", "yaw",
    "vgx", "vgy", "vgz", "rc_lr", "rc_fb", "rc_ud", "rc_yaw",
]


class Recorder:
    def __init__(self, output_dir: Path, fps: float):
        self.output_dir = output_dir
        self.fps = fps
        self._writer: cv2.VideoWriter | None = None
        self._csv_file = None
        self._csv: csv.writer | None = None
        self._frame_idx = 0
        self._t0 = 0.0
        self.path: Path | None = None

    @property
    def recording(self) -> bool:
        return self._csv is not None

    def start(self) -> Path:
        self.path = self.output_dir / time.strftime("%Y%m%d_%H%M%S")
        self.path.mkdir(parents=True, exist_ok=True)
        self._frame_idx = 0
        self._t0 = time.monotonic()
        self._csv_file = open(self.path / "frames.csv", "w", newline="")
        self._csv = csv.writer(self._csv_file)
        self._csv.writerow(CSV_FIELDS)
        log.info("Recording to %s", self.path)
        return self.path

    def write(self, frame: np.ndarray, tel: Telemetry, rc: tuple[int, int, int, int]) -> None:
        if self._csv is None:
            return
        if self._writer is None:
            h, w = frame.shape[:2]
            self._writer = cv2.VideoWriter(str(self.path / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
        self._writer.write(frame)
        self._csv.writerow([
            self._frame_idx, f"{time.monotonic() - self._t0:.4f}", tel.battery, tel.height_cm, tel.tof_cm,
            tel.pitch, tel.roll, tel.yaw, tel.vgx, tel.vgy, tel.vgz, *rc,
        ])
        self._frame_idx += 1

    def stop(self) -> None:
        if self._writer is not None:
            self._writer.release()
        if self._csv_file is not None:
            self._csv_file.close()
        if self._csv is not None:
            log.info("Recording stopped: %d frames in %s", self._frame_idx, self.path)
        self._writer = None
        self._csv_file = None
        self._csv = None


def save_snapshot(frame: np.ndarray, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.jpg"
    cv2.imwrite(str(path), frame)
    log.info("Snapshot saved: %s", path)
    return path
