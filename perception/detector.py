from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# COCO class names we map to our two categories of interest.
VEHICLE_CLASSES = {"car", "motorcycle", "bus", "truck", "bicycle"}
PEDESTRIAN_CLASSES = {"person"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class FrameDetections:
    """Detections in a single frame."""

    frame_idx: int
    timestamp_s: float
    vehicles: int
    pedestrians: int
    by_class: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DetectionSummary:
    """Aggregate detection statistics over a clip/image."""

    source: str
    frames: int
    duration_s: float
    unique_vehicles: int
    unique_pedestrians: int
    peak_vehicles_in_frame: int
    peak_pedestrians_in_frame: int
    avg_vehicles_per_frame: float
    avg_pedestrians_per_frame: float
    by_class_total: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Detector:
    """Thin wrapper over ultralytics YOLO for vehicle/pedestrian detection."""

    def __init__(self, model_name: str = "yolov8n.pt", conf: float = 0.3,
                 device: Optional[str] = None) -> None:
        from ultralytics import YOLO

        log.info("Loading YOLO model '%s'...", model_name)
        self.model = YOLO(model_name)
        self.conf = conf
        self.device = device
        self.names: dict[int, str] = self.model.names

    # --- helpers ---
    def _category(self, cls_name: str) -> Optional[str]:
        if cls_name in VEHICLE_CLASSES:
            return "vehicle"
        if cls_name in PEDESTRIAN_CLASSES:
            return "pedestrian"
        return None

    @staticmethod
    def _fps(source: str) -> float:
        import cv2

        cap = cv2.VideoCapture(source)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        cap.release()
        return fps if fps and fps > 1e-3 else 25.0

    # --- main entry points ---
    def analyze(self, source: str, *, track: bool = True,
                max_frames: Optional[int] = None) -> tuple[list[FrameDetections], DetectionSummary]:
        """Detect on an image or video file; return per-frame detections + summary."""
        if Path(source).suffix.lower() in IMAGE_SUFFIXES:
            return self._analyze_image(source)
        return self._analyze_video(source, track=track, max_frames=max_frames)

    def _analyze_image(self, source: str) -> tuple[list[FrameDetections], DetectionSummary]:
        results = self.model.predict(source, conf=self.conf, verbose=False,
                                     device=self.device)
        by_class: dict[str, int] = {}
        for r in results:
            for c in r.boxes.cls.tolist():
                name = self.names[int(c)]
                if self._category(name):
                    by_class[name] = by_class.get(name, 0) + 1
        veh = sum(n for k, n in by_class.items() if k in VEHICLE_CLASSES)
        ped = sum(n for k, n in by_class.items() if k in PEDESTRIAN_CLASSES)
        frame = FrameDetections(0, 0.0, veh, ped, by_class)
        summary = DetectionSummary(
            source=source, frames=1, duration_s=0.0,
            unique_vehicles=veh, unique_pedestrians=ped,
            peak_vehicles_in_frame=veh, peak_pedestrians_in_frame=ped,
            avg_vehicles_per_frame=float(veh), avg_pedestrians_per_frame=float(ped),
            by_class_total=by_class,
        )
        return [frame], summary

    def _analyze_video(self, source: str, *, track: bool,
                       max_frames: Optional[int]) -> tuple[list[FrameDetections], DetectionSummary]:
        fps = self._fps(source)
        veh_track_ids: set[int] = set()
        ped_track_ids: set[int] = set()
        by_class_total: dict[str, int] = {}
        frames: list[FrameDetections] = []
        veh_counts: list[int] = []
        ped_counts: list[int] = []

        # stream=True yields one Results per frame without buffering the video.
        stream = (self.model.track(source, stream=True, persist=True, conf=self.conf,
                                   verbose=False, device=self.device)
                  if track else
                  self.model.predict(source, stream=True, conf=self.conf,
                                     verbose=False, device=self.device))

        for idx, r in enumerate(stream):
            if max_frames is not None and idx >= max_frames:
                break
            by_class: dict[str, int] = {}
            ids = r.boxes.id.tolist() if (track and r.boxes.id is not None) else None
            classes = r.boxes.cls.tolist()
            for j, c in enumerate(classes):
                name = self.names[int(c)]
                cat = self._category(name)
                if not cat:
                    continue
                by_class[name] = by_class.get(name, 0) + 1
                by_class_total[name] = by_class_total.get(name, 0) + 1
                if ids is not None:
                    tid = int(ids[j])
                    (veh_track_ids if cat == "vehicle" else ped_track_ids).add(tid)
            veh = sum(n for k, n in by_class.items() if k in VEHICLE_CLASSES)
            ped = sum(n for k, n in by_class.items() if k in PEDESTRIAN_CLASSES)
            veh_counts.append(veh)
            ped_counts.append(ped)
            frames.append(FrameDetections(idx, round(idx / fps, 3), veh, ped, by_class))

        n = max(len(frames), 1)
        summary = DetectionSummary(
            source=source,
            frames=len(frames),
            duration_s=round(len(frames) / fps, 2),
            # With tracking, unique counts come from track ids; else fall back to peak.
            unique_vehicles=len(veh_track_ids) if track else (max(veh_counts) if veh_counts else 0),
            unique_pedestrians=len(ped_track_ids) if track else (max(ped_counts) if ped_counts else 0),
            peak_vehicles_in_frame=max(veh_counts) if veh_counts else 0,
            peak_pedestrians_in_frame=max(ped_counts) if ped_counts else 0,
            avg_vehicles_per_frame=round(sum(veh_counts) / n, 2),
            avg_pedestrians_per_frame=round(sum(ped_counts) / n, 2),
            by_class_total=by_class_total,
        )
        log.info("Detected over %d frames: ~%d unique vehicles, %d unique pedestrians",
                 summary.frames, summary.unique_vehicles, summary.unique_pedestrians)
        return frames, summary
