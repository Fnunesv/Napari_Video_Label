"""Frame-level annotation primitives: timestamp, scale bar, text labels, highlight regions.

This generalizes the "merge and annotate videos" logic from the
actin-polarization pipeline (stack_to_video) into reusable, stack-agnostic
building blocks driven by a single AnnotationConfig, so it works for any
pixel size / frame rate / phase layout rather than one hardcoded experiment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np

from .merge import Phase, phase_label_at

Corner = Literal["top-left", "top-right", "bottom-left", "bottom-right"]

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _format_timestamp(t_s: float, fmt: str) -> str:
    if fmt == "seconds":
        return f"{t_s:.1f} s"
    if fmt == "mm:ss":
        m, s = divmod(int(round(t_s)), 60)
        return f"{m:02d}:{s:02d}"
    if fmt == "hh:mm:ss":
        h, rem = divmod(int(round(t_s)), 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    raise ValueError(f"Unknown timestamp format: {fmt}")


def _anchor(shape_hw: tuple[int, int], corner: Corner, offset_px: tuple[int, int],
            text_size: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Pixel anchor for the given corner, accounting for text/element size."""
    H, W = shape_hw
    tw, th = text_size
    x_off, y_off = offset_px
    if corner == "top-left":
        return x_off, y_off + th
    if corner == "top-right":
        return W - x_off - tw, y_off + th
    if corner == "bottom-left":
        return x_off, H - y_off
    if corner == "bottom-right":
        return W - x_off - tw, H - y_off
    raise ValueError(f"Unknown corner: {corner}")


@dataclass
class TimestampConfig:
    enabled: bool = True
    frame_interval_s: float = 1.0
    start_offset_s: float = 0.0
    fmt: str = "seconds"  # "seconds" | "mm:ss" | "hh:mm:ss"
    corner: Corner = "bottom-left"
    offset_px: tuple[int, int] = (10, 10)
    font_scale: float = 0.6
    thickness: int = 2
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class ScaleBarConfig:
    enabled: bool = True
    pixel_size_um: float = 1.0
    length_um: float = 5.0
    corner: Corner = "bottom-right"
    offset_px: tuple[int, int] = (20, 20)
    thickness_px: int | None = None  # auto if None
    color: tuple[int, int, int] = (255, 255, 255)
    show_label: bool = True
    font_scale: float = 0.6
    thickness: int = 2


@dataclass
class TextLabelConfig:
    """A static free-text label, e.g. condition name ('CRY2-mCherry')."""
    enabled: bool = False
    text: str = ""
    corner: Corner = "top-left"
    offset_px: tuple[int, int] = (10, 10)
    font_scale: float = 0.7
    thickness: int = 2
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass
class PhaseLabelConfig:
    """Time-controlled label that switches text at given frame boundaries.

    Phases are typically defined *after* merging (see the widget's phase
    table), so a phase name/boundary can be added, renamed, or removed
    independently of how the underlying stacks were concatenated.
    """
    enabled: bool = False
    phases: list[Phase] = field(default_factory=list)  # e.g. [Phase("baseline",0), Phase("activation",24)]
    corner: Corner = "top-right"
    offset_px: tuple[int, int] = (10, 10)
    font_scale: float = 0.7
    thickness: int = 2
    color: tuple[int, int, int] = (0, 255, 255)


@dataclass
class HighlightRegion:
    """A single highlighted ROI (box or circle), visible during a frame range.

    Coordinates are in the pixel space of the stack this config is rendered
    against (i.e. already shifted for crop origin if applicable — see
    `_widget.py`'s `_build_config`).
    """
    shape: str  # "rectangle" | "circle"
    # rectangle: (x0, y0, x1, y1); circle: (cx, cy, radius, unused)
    coords: tuple[float, float, float, float]
    frame_start: int = 0
    frame_end: int | None = None  # inclusive; None = until the end


@dataclass
class HighlightConfig:
    """Zero or more highlight regions, sharing one color/thickness style."""
    enabled: bool = False
    regions: list[HighlightRegion] = field(default_factory=list)
    color: tuple[int, int, int] = (0, 0, 255)
    thickness: int = 2


@dataclass
class AnnotationConfig:
    timestamp: TimestampConfig = field(default_factory=TimestampConfig)
    scale_bar: ScaleBarConfig = field(default_factory=ScaleBarConfig)
    condition_label: TextLabelConfig = field(default_factory=TextLabelConfig)
    phase_label: PhaseLabelConfig = field(default_factory=PhaseLabelConfig)
    highlight: HighlightConfig = field(default_factory=HighlightConfig)
    colormap: int | None = cv2.COLORMAP_INFERNO  # None = grayscale (BGR passthrough)
    percentile_clip: tuple[float, float] = (1, 99)
    contrast_limits: tuple[float, float] | None = None  # if set, overrides percentile_clip with fixed min/max


def normalize_frame(
    frame: np.ndarray,
    percentile_clip: tuple[float, float] = (1, 99),
    limits: tuple[float, float] | None = None,
) -> np.ndarray:
    """Contrast-stretch a single 2-D frame to uint8.

    Uses fixed `limits` (min, max) if given (consistent contrast across a
    whole stack); otherwise falls back to per-frame percentile clipping.
    """
    if limits is not None:
        lo, hi = limits
    else:
        lo, hi = np.percentile(frame, percentile_clip)
    if hi <= lo:
        lo, hi = float(frame.min()), float(frame.max() or 1)
    clipped = np.clip(frame, lo, hi)
    scaled = (clipped - lo) / (hi - lo + 1e-9) * 255.0
    return scaled.astype(np.uint8)


def to_bgr(img8: np.ndarray, colormap: int | None) -> np.ndarray:
    if colormap is None:
        return cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)
    return cv2.applyColorMap(img8, colormap)


def draw_timestamp(frame_bgr: np.ndarray, frame_idx: int, cfg: TimestampConfig) -> None:
    if not cfg.enabled:
        return
    t_s = cfg.start_offset_s + frame_idx * cfg.frame_interval_s
    text = _format_timestamp(t_s, cfg.fmt)
    (tw, th), _ = cv2.getTextSize(text, _FONT, cfg.font_scale, cfg.thickness)
    x, y = _anchor(frame_bgr.shape[:2], cfg.corner, cfg.offset_px, (tw, th))
    cv2.putText(frame_bgr, text, (x, y), _FONT, cfg.font_scale, cfg.color, cfg.thickness, cv2.LINE_AA)


def draw_scale_bar(frame_bgr: np.ndarray, cfg: ScaleBarConfig) -> None:
    """Draw the bar and (optionally) its length label as one block anchored
    at `cfg.corner` + `cfg.offset_px`, sized to fit both bar and label —
    unlike a naive bar-only layout, this keeps a wide label from silently
    overflowing past the frame edge when the bar itself is short.
    """
    if not cfg.enabled:
        return
    H, W = frame_bgr.shape[:2]
    bar_px = max(1, int(round(cfg.length_um / cfg.pixel_size_um)))
    bar_thickness = cfg.thickness_px or max(2, H // 200)
    x_off, y_off = cfg.offset_px

    label = f"{cfg.length_um:g} um" if cfg.show_label else ""
    if label:
        (label_w, label_h), baseline = cv2.getTextSize(label, _FONT, cfg.font_scale, cfg.thickness)
    else:
        label_w = label_h = baseline = 0

    block_w = max(bar_px, label_w)
    gap = 6 if label else 0
    block_h = bar_thickness + gap + label_h + baseline

    if cfg.corner in ("bottom-right", "top-right"):
        x0 = W - x_off - block_w
    else:
        x0 = x_off
    bar_x0 = x0 + (block_w - bar_px) // 2
    bar_x1 = bar_x0 + bar_px
    text_x = x0 + (block_w - label_w) // 2

    if cfg.corner in ("bottom-left", "bottom-right"):
        bar_y1 = H - y_off
        bar_y0 = bar_y1 - bar_thickness
        text_baseline_y = bar_y0 - gap
    else:
        text_baseline_y = y_off + label_h
        bar_y0 = text_baseline_y + baseline + gap
        bar_y1 = bar_y0 + bar_thickness

    cv2.rectangle(frame_bgr, (bar_x0, bar_y0), (bar_x1, bar_y1), cfg.color, cv2.FILLED)
    if label:
        cv2.putText(frame_bgr, label, (text_x, text_baseline_y), _FONT, cfg.font_scale, cfg.color, cfg.thickness, cv2.LINE_AA)


def draw_text_label(frame_bgr: np.ndarray, text: str, corner: Corner, offset_px: tuple[int, int],
                     font_scale: float, thickness: int, color: tuple[int, int, int]) -> None:
    if not text:
        return
    (tw, th), _ = cv2.getTextSize(text, _FONT, font_scale, thickness)
    x, y = _anchor(frame_bgr.shape[:2], corner, offset_px, (tw, th))
    cv2.putText(frame_bgr, text, (x, y), _FONT, font_scale, color, thickness, cv2.LINE_AA)


def draw_phase_label(frame_bgr: np.ndarray, frame_idx: int, cfg: PhaseLabelConfig) -> None:
    if not cfg.enabled or not cfg.phases:
        return
    text = phase_label_at(cfg.phases, frame_idx)
    draw_text_label(frame_bgr, text, cfg.corner, cfg.offset_px, cfg.font_scale, cfg.thickness, cfg.color)


def draw_highlight_regions(frame_bgr: np.ndarray, frame_idx: int, cfg: HighlightConfig) -> None:
    if not cfg.enabled:
        return
    for region in cfg.regions:
        end = region.frame_end if region.frame_end is not None else float("inf")
        if not (region.frame_start <= frame_idx <= end):
            continue
        if region.shape == "rectangle":
            x0, y0, x1, y1 = (int(round(v)) for v in region.coords)
            cv2.rectangle(frame_bgr, (x0, y0), (x1, y1), cfg.color, cfg.thickness)
        elif region.shape == "circle":
            cx, cy, r = region.coords[0], region.coords[1], region.coords[2]
            cv2.circle(frame_bgr, (int(round(cx)), int(round(cy))), int(round(r)), cfg.color, cfg.thickness)
        else:
            raise ValueError(f"Unknown highlight region shape: {region.shape}")


def annotate_frame(frame: np.ndarray, frame_idx: int, cfg: AnnotationConfig) -> np.ndarray:
    """Annotate a single 2-D frame (grayscale) -> (H, W, 3) uint8 BGR."""
    img8 = normalize_frame(frame, cfg.percentile_clip, cfg.contrast_limits)
    out = to_bgr(img8, cfg.colormap)
    draw_timestamp(out, frame_idx, cfg.timestamp)
    draw_scale_bar(out, cfg.scale_bar)
    if cfg.condition_label.enabled:
        draw_text_label(out, cfg.condition_label.text, cfg.condition_label.corner,
                         cfg.condition_label.offset_px, cfg.condition_label.font_scale,
                         cfg.condition_label.thickness, cfg.condition_label.color)
    draw_phase_label(out, frame_idx, cfg.phase_label)
    draw_highlight_regions(out, frame_idx, cfg.highlight)
    return out


def annotate_stack(stack: np.ndarray, cfg: AnnotationConfig) -> np.ndarray:
    """Annotate a (T, H, W) grayscale stack -> (T, H, W, 3) uint8 BGR."""
    if stack.ndim != 3:
        raise ValueError(f"Expected a (T, H, W) stack, got shape {stack.shape}")
    T = stack.shape[0]
    first = annotate_frame(stack[0], 0, cfg)
    out = np.empty((T, *first.shape), dtype=np.uint8)
    out[0] = first
    for t in range(1, T):
        out[t] = annotate_frame(stack[t], t, cfg)
    return out
