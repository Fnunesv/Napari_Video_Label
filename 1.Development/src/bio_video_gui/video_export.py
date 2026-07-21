"""Write an annotated (T, H, W, 3) BGR uint8 stack to a video, TIFF stack, or image sequence."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import tifffile

VIDEO_FOURCC = {
    ".mp4": "mp4v",
    ".mov": "mp4v",
    ".avi": "XVID",
}


def _check_shape(annotated_stack_bgr: np.ndarray) -> None:
    if annotated_stack_bgr.ndim != 4 or annotated_stack_bgr.shape[-1] != 3:
        raise ValueError(f"Expected a (T, H, W, 3) BGR stack, got shape {annotated_stack_bgr.shape}")


def write_video(annotated_stack_bgr: np.ndarray, output_path: str | Path, fps: float = 10.0) -> Path:
    """Write a (T, H, W, 3) uint8 BGR stack to a video file.

    Codec is chosen from the output suffix: .mp4/.mov -> mp4v, .avi -> XVID.
    """
    _check_shape(annotated_stack_bgr)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    T, H, W, _ = annotated_stack_bgr.shape
    fourcc_str = VIDEO_FOURCC.get(output_path.suffix.lower(), "mp4v")
    fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (W, H), isColor=True)
    if not writer.isOpened():
        raise IOError(f"Could not open video writer for {output_path}")
    try:
        for t in range(T):
            writer.write(annotated_stack_bgr[t])
    finally:
        writer.release()
    return output_path


def write_tiff_stack(annotated_stack_bgr: np.ndarray, output_path: str | Path) -> Path:
    """Write a (T, H, W, 3) uint8 BGR stack to a single multi-page RGB TIFF."""
    _check_shape(annotated_stack_bgr)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb = annotated_stack_bgr[..., ::-1]
    tifffile.imwrite(str(output_path), rgb, photometric="rgb")
    return output_path


def write_image_sequence(
    annotated_stack_bgr: np.ndarray,
    output_dir: str | Path,
    prefix: str = "frame",
    ext: str = ".png",
) -> Path:
    """Write each frame of a (T, H, W, 3) uint8 BGR stack as a separate image file."""
    _check_shape(annotated_stack_bgr)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    T = annotated_stack_bgr.shape[0]
    ndigits = max(4, len(str(T)))
    for t in range(T):
        fname = output_dir / f"{prefix}_{t:0{ndigits}d}{ext}"
        cv2.imwrite(str(fname), annotated_stack_bgr[t])
    return output_dir
