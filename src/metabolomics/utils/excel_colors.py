"""Helpers for reading Excel font colors across openpyxl variants."""

from __future__ import annotations

from typing import Any


def normalize_rgb_code(rgb: Any) -> str | None:
    """Normalize openpyxl RGB strings to a 6-digit uppercase RGB code."""
    if rgb is None:
        return None

    rgb_str = str(rgb).strip().upper()
    if rgb_str.startswith("0X"):
        rgb_str = rgb_str[2:]

    if len(rgb_str) < 6:
        return None

    return rgb_str[-6:]


def cell_has_red_font(cell: Any) -> bool:
    """Return True when a cell uses an explicit red RGB font color."""
    color = getattr(getattr(cell, "font", None), "color", None)
    if color is None or getattr(color, "type", None) != "rgb":
        return False

    return normalize_rgb_code(getattr(color, "rgb", None)) == "FF0000"
