"""Face detection (YuNet) and recognition (SFace), both built into OpenCV."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .config import FaceConfig
from .models import ensure_model

log = logging.getLogger(__name__)


@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float
    score: float
    frame_w: int
    frame_h: int
    row: np.ndarray
    """Raw YuNet row (box, 5 landmarks, score) in full-frame pixels; needed by SFace."""
    name: str | None = None
    similarity: float = 0.0

    # Normalised geometry (0..1 of frame) used by the controller.
    @property
    def cx(self) -> float:
        return (self.x + self.w / 2) / self.frame_w

    @property
    def cy(self) -> float:
        return (self.y + self.h / 2) / self.frame_h

    @property
    def size(self) -> float:
        """Face width as a fraction of frame width (proxy for distance)."""
        return self.w / self.frame_w

    @property
    def box(self) -> tuple[int, int, int, int]:
        return int(self.x), int(self.y), int(self.w), int(self.h)

    @property
    def landmarks(self) -> np.ndarray:
        return self.row[4:14].reshape(5, 2)


class FaceDetector:
    def __init__(self, config: FaceConfig):
        self.config = config
        model = ensure_model("yunet", config.models_dir)
        self._net = cv2.FaceDetectorYN.create(str(model), "", (320, 320), config.score_threshold, 0.3, 5000)
        self._input_size: tuple[int, int] | None = None

    def detect(self, frame: np.ndarray) -> list[Face]:
        h, w = frame.shape[:2]
        scale = min(1.0, self.config.detect_width / w)
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame
        size = (small.shape[1], small.shape[0])
        if size != self._input_size:
            self._net.setInputSize(size)
            self._input_size = size
        _, rows = self._net.detect(small)
        faces: list[Face] = []
        if rows is None:
            return faces
        for r in rows:
            full = r.copy()
            full[:14] /= scale
            faces.append(Face(*map(float, full[:4]), score=float(full[14]), frame_w=w, frame_h=h, row=full))
        faces.sort(key=lambda f: f.w * f.h, reverse=True)
        return faces


class FaceRecognizer:
    def __init__(self, config: FaceConfig):
        model = ensure_model("sface", config.models_dir)
        self._net = cv2.FaceRecognizerSF.create(str(model), "")

    def embed(self, frame: np.ndarray, face: Face) -> np.ndarray:
        aligned = self._net.alignCrop(frame, face.row)
        feat = self._net.feature(aligned).flatten()
        return feat / (np.linalg.norm(feat) + 1e-9)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    if not cleaned:
        raise ValueError("Name must contain letters or digits")
    return cleaned


class FaceGallery:
    """Enrolled people: one `<name>.npy` file of unit embeddings per person."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.people: dict[str, np.ndarray] = {}
        if directory.exists():
            for f in sorted(directory.glob("*.npy")):
                self.people[f.stem] = np.load(f)
        if self.people:
            log.info("Face gallery: %s", ", ".join(f"{n} ({len(e)})" for n, e in self.people.items()))

    def __bool__(self) -> bool:
        return bool(self.people)

    def add(self, name: str, embedding: np.ndarray) -> int:
        name = _safe_name(name)
        existing = self.people.get(name)
        stacked = embedding[None] if existing is None else np.vstack([existing, embedding])
        self.people[name] = stacked
        self.directory.mkdir(parents=True, exist_ok=True)
        np.save(self.directory / f"{name}.npy", stacked)
        return len(stacked)

    def identify(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Best matching person and cosine similarity (embeddings are unit length)."""
        best_name, best = None, -1.0
        for name, embs in self.people.items():
            sim = float(np.max(embs @ embedding))
            if sim > best:
                best_name, best = name, sim
        return best_name, best
