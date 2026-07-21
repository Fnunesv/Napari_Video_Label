"""Loading .tif stacks and recovering acquisition metadata (pixel size, frame interval)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile


@dataclass
class StackMetadata:
    pixel_size_um: float | None = None
    frame_interval_s: float | None = None
    n_frames: int | None = None
    source_path: str | None = None


def _pixel_size_from_resolution(tf: tifffile.TiffFile) -> float | None:
    """Recover pixel size (um/px) from the TIFF XResolution tag + ImageJ unit."""
    try:
        page = tf.pages[0]
        res = page.tags.get("XResolution")
        if res is None:
            return None
        num, den = res.value
        if num == 0:
            return None
        px_per_unit = num / den
        unit = (tf.imagej_metadata or {}).get("unit", "").lower()
        if unit in ("micron", "um", "µm"):
            return 1.0 / px_per_unit
        if unit == "nm":
            return 1000.0 / px_per_unit
        # unknown unit: still return the reciprocal, caller can sanity-check
        return 1.0 / px_per_unit
    except Exception:
        return None


def load_stack(path: str | Path) -> tuple[np.ndarray, StackMetadata]:
    """Load a (T, H, W) tif stack and best-effort metadata.

    Falls back to None fields when metadata is absent, so callers must let the
    user fill in pixel size / frame interval manually in that case.
    """
    path = Path(path)
    with tifffile.TiffFile(str(path)) as tf:
        stack = tf.asarray()
        ij_meta = tf.imagej_metadata or {}
        pixel_size_um = _pixel_size_from_resolution(tf)
        frame_interval_s = ij_meta.get("finterval")

    if stack.ndim == 2:
        stack = stack[np.newaxis, ...]

    meta = StackMetadata(
        pixel_size_um=pixel_size_um,
        frame_interval_s=float(frame_interval_s) if frame_interval_s else None,
        n_frames=stack.shape[0],
        source_path=str(path),
    )
    return stack, meta
