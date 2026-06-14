from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from perception.detector import VEHICLE_CLASSES

log = logging.getLogger(__name__)


@dataclass
class ParkingReport:
    stationary_count: int
    moving_count: int
    stationary_ids: list[int] = field(default_factory=list)
    encroachment: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def classify_tracks(
    tracks: dict[int, list[tuple[int, float, float]]],
    *,
    move_threshold_px: float = 15.0,
    min_frames: int = 50,
) -> ParkingReport:
    
    stationary: list[int] = []
    moving: list[int] = []
    for tid, pts in tracks.items():
        if len(pts) < min_frames:
            continue
        xs = [p[1] for p in pts]
        ys = [p[2] for p in pts]
        displacement = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
        (stationary if displacement < move_threshold_px else moving).append(tid)

    encroachment = len(stationary) > 0
    note = (f"{len(stationary)} stationary vehicle(s) detected — likely illegal "
            f"parking narrowing the carriageway." if encroachment
            else "No stationary vehicles detected.")
    return ParkingReport(len(stationary), len(moving), stationary, encroachment, note)


class ParkingDetector:

    def __init__(self, model_name: str = "yolov8n.pt", conf: float = 0.3) -> None:
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.conf = conf
        self.names = self.model.names

    def analyze(self, source: str, *, move_threshold_px: float = 15.0,
                min_seconds: float = 3.0) -> ParkingReport:
        import cv2

        cap = cv2.VideoCapture(source)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        cap.release()

        tracks: dict[int, list[tuple[int, float, float]]] = {}
        stream = self.model.track(source, stream=True, persist=True, conf=self.conf,
                                  verbose=False)
        for idx, r in enumerate(stream):
            if r.boxes.id is None:
                continue
            for box, cls, tid in zip(r.boxes.xywh.tolist(), r.boxes.cls.tolist(),
                                     r.boxes.id.tolist()):
                if self.names[int(cls)] not in VEHICLE_CLASSES:
                    continue
                tracks.setdefault(int(tid), []).append((idx, float(box[0]), float(box[1])))

        return classify_tracks(tracks, move_threshold_px=move_threshold_px,
                               min_frames=int(min_seconds * fps))
