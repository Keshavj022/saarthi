#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from perception.anpr import ANPR  # noqa: E402
from perception.detector import IMAGE_SUFFIXES, Detector  # noqa: E402

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _find_footage() -> Path | None:
    if not settings.videos_dir.exists():
        return None
    for p in sorted(settings.videos_dir.iterdir()):
        if p.suffix.lower() in (VIDEO_SUFFIXES | IMAGE_SUFFIXES):
            return p
    return None


def _sampled_frames(source: str, every_n_sec: float = 1.0):
    """Yield (frame_idx, timestamp_s, frame_bgr) sampled ~every_n_sec for ANPR."""
    import cv2

    if Path(source).suffix.lower() in IMAGE_SUFFIXES:
        img = cv2.imread(source)
        if img is not None:
            yield 0, 0.0, img
        return

    cap = cv2.VideoCapture(source)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * every_n_sec))
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            yield idx, round(idx / fps, 3), frame
        idx += 1
    cap.release()


def _downsample_timeline(frames, every_sec: int = 1) -> list[dict]:
    """Keep ~one detection record per `every_sec` to keep the JSON readable."""
    out, last = [], None
    for f in frames:
        bucket = int(f.timestamp_s // every_sec)
        if bucket != last:
            out.append(f.to_dict())
            last = bucket
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    source = sys.argv[1] if len(sys.argv) > 1 else None
    if source is None:
        found = _find_footage()
        if found is None:
            print("\n⚠️  USER ACTION NEEDED — no footage found.")
            print(f"Place a video (or image) in {settings.videos_dir}/ and re-run,")
            print("or pass a path: python scripts/run_perception.py path/to/clip.mp4")
            print("Best clip: a junction with clearly visible vehicles, pedestrians,")
            print("and a few legible, roughly frontal number plates.")
            return 2
        source = str(found)

    if not Path(source).exists():
        print(f"⚠️  File not found: {source}")
        return 2

    print(f"Perception on: {source}")

    # --- detection ---
    detector = Detector()
    frames, summary = detector.analyze(source)

    # --- ANPR on sampled frames ---
    anpr = ANPR()
    plates: dict[str, dict] = {}
    for fidx, ts, frame in _sampled_frames(source):
        for pr in anpr.read_plates(frame, frame_idx=fidx, timestamp_s=ts):
            best = plates.get(pr.text)
            if best is None or pr.confidence > best["confidence"]:
                plates[pr.text] = pr.to_dict()

    events = {
        "source": source,
        "detection_summary": summary.to_dict(),
        "timeline": _downsample_timeline(frames),
        "plates": sorted(plates.values(), key=lambda p: -p["confidence"]),
    }
    out = settings.outputs_dir / "perception.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(events, indent=2))

    s = summary
    print("\n=== Perception summary ===")
    print(f"Frames analysed     : {s.frames}  ({s.duration_s}s)")
    print(f"Unique vehicles     : {s.unique_vehicles}")
    print(f"Unique pedestrians  : {s.unique_pedestrians}")
    print(f"Peak in one frame   : {s.peak_vehicles_in_frame} vehicles, "
          f"{s.peak_pedestrians_in_frame} pedestrians")
    print(f"By class            : {s.by_class_total}")
    if events["plates"]:
        print(f"\nPlates read ({len(events['plates'])}):")
        for p in events["plates"]:
            tag = "✓format" if p["format_match"] else "~loose"
            print(f"  {p['text']:12s} conf={p['confidence']:.2f} [{tag}] @ t={p['timestamp_s']}s")
    else:
        print("\nPlates read         : none "
              "(need footage with legible, roughly frontal plates)")
    print(f"\nSaved events -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
