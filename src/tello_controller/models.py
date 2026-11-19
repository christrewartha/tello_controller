"""Model file management. Models are downloaded on first use (not committed)."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"

MODELS = {
    "yunet": ("face_detection_yunet_2023mar.onnx", f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    "sface": ("face_recognition_sface_2021dec.onnx", f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx"),
}


def ensure_model(key: str, models_dir: Path) -> Path:
    filename, url = MODELS[key]
    path = models_dir / filename
    if path.exists() and path.stat().st_size > 10_000:
        return path
    models_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %s model from %s ...", key, url)
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(path)
    return path
