"""Tests for the ANPR plate-filter logic (pure; no torch/easyocr/cv2 needed)."""
from __future__ import annotations

from perception.anpr import INDIAN_PLATE_RE, _clean, looks_like_plate


def test_clean_strips_to_alnum_uppercase():
    assert _clean("mh 12 ab-1234") == "MH12AB1234"
    assert _clean("DL.8C.AF.1234") == "DL8CAF1234"


def test_looks_like_plate_accepts_plausible():
    assert looks_like_plate("MH12AB1234")
    assert looks_like_plate("DL8CAF1234")


def test_looks_like_plate_rejects_non_plates():
    assert not looks_like_plate("STOP")        # no digits
    assert not looks_like_plate("12")          # too short
    assert not looks_like_plate("HELLOWORLD")  # no digits
    assert not looks_like_plate("9999999999")  # no letters


def test_indian_format_regex():
    assert INDIAN_PLATE_RE.match("MH12AB1234")
    assert INDIAN_PLATE_RE.match("DL8CAF1234")
    assert not INDIAN_PLATE_RE.match("1234567890")
    assert not INDIAN_PLATE_RE.match("ABCDEFGH")
