"""Enrol a face from a webcam so lock-on can recognise that person.

    uv run tello-enroll --name chris

Look at the camera and move your head slightly (left/right/up/down) while
samples are captured. Press Esc to stop early.
"""

from __future__ import annotations

import argparse
import logging
import time

import cv2

from .config import FaceConfig
from .faces import FaceDetector, FaceGallery, FaceRecognizer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--webcam", type=int, default=0)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--interval", type=float, default=0.4, help="seconds between samples")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = FaceConfig()
    detector, recognizer, gallery = FaceDetector(cfg), FaceRecognizer(cfg), FaceGallery(cfg.gallery_dir)
    cap = cv2.VideoCapture(args.webcam)
    if not cap.isOpened():
        raise SystemExit(f"Could not open webcam {args.webcam}")

    taken, last = 0, 0.0
    try:
        while taken < args.samples:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            faces = detector.detect(frame)
            now = time.monotonic()
            if len(faces) == 1 and now - last >= args.interval:
                gallery.add(args.name, recognizer.embed(frame, faces[0]))
                taken, last = taken + 1, now
            for f in faces:
                x, y, w, h = f.box
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 220, 0) if len(faces) == 1 else (0, 0, 255), 2)
            msg = f"{args.name}: {taken}/{args.samples}" if len(faces) <= 1 else "Only one face in view please"
            cv2.putText(frame, msg, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
            cv2.imshow("Enrol face (Esc to stop)", frame)
            if cv2.waitKey(1) == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print(f"Saved {taken} samples for '{args.name}' in {cfg.gallery_dir}")


if __name__ == "__main__":
    main()
