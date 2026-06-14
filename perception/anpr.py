from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Indian plate canonical format, e.g. MH12AB1234 / DL8CAF1234:
#   2 letters (state) + 1-2 digits (RTO) + 1-3 letters (series) + 4 digits.
INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")


@dataclass
class PlateRead:
    """A single plate-like OCR read."""

    text: str
    confidence: float
    frame_idx: int
    timestamp_s: float
    format_match: bool  # matches the canonical Indian plate format

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(text: str) -> str:
    """Uppercase and strip to alphanumerics (drops spaces, hyphens, dots)."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def looks_like_plate(s: str) -> bool:
    """Permissive heuristic: plausible plate even if OCR mangled the format."""
    if not (6 <= len(s) <= 11) or not s.isalnum():
        return False
    letters = sum(c.isalpha() for c in s)
    digits = sum(c.isdigit() for c in s)
    return letters >= 2 and digits >= 3


class ANPR:
    """EasyOCR-based plate reader with a plate-pattern filter."""

    def __init__(self, langs: tuple[str, ...] = ("en",), gpu: bool = False,
                 min_confidence: float = 0.3) -> None:
        import easyocr

        log.info("Initialising EasyOCR (langs=%s, gpu=%s)...", langs, gpu)
        self.reader = easyocr.Reader(list(langs), gpu=gpu)
        self.min_confidence = min_confidence

    def read_plates(self, image, *, frame_idx: int = 0,
                    timestamp_s: float = 0.0) -> list[PlateRead]:
        """Read plate-like strings from a full image/frame (numpy BGR array or path)."""
        reads: list[PlateRead] = []
        for _bbox, text, conf in self.reader.readtext(image):
            if conf < self.min_confidence:
                continue
            cleaned = _clean(text)
            if looks_like_plate(cleaned):
                reads.append(PlateRead(
                    text=cleaned,
                    confidence=round(float(conf), 3),
                    frame_idx=frame_idx,
                    timestamp_s=timestamp_s,
                    format_match=bool(INDIAN_PLATE_RE.match(cleaned)),
                ))
        return reads

    def read_plates_in_boxes(self, frame, boxes, *, frame_idx: int = 0,
                             timestamp_s: float = 0.0) -> list[PlateRead]:
        """OCR within vehicle bounding boxes (x1,y1,x2,y2) for better accuracy."""
        reads: list[PlateRead] = []
        h, w = frame.shape[:2]
        for (x1, y1, x2, y2) in boxes:
            x1, y1 = max(0, int(x1)), max(0, int(y1))
            x2, y2 = min(w, int(x2)), min(h, int(y2))
            if x2 - x1 < 20 or y2 - y1 < 20:
                continue
            crop = frame[y1:y2, x1:x2]
            reads.extend(self.read_plates(crop, frame_idx=frame_idx,
                                          timestamp_s=timestamp_s))
        return reads
