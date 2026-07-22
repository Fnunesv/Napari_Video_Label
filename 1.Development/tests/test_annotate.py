import numpy as np
import pytest

from bio_video_gui.annotate import (
    AnnotationConfig,
    HighlightConfig,
    HighlightRegion,
    PhaseLabelConfig,
    ScaleBarConfig,
    TextLabelConfig,
    TimestampConfig,
    annotate_frame,
    annotate_stack,
    normalize_frame,
)
from bio_video_gui.merge import Phase, concat_stacks, merge_phases, phase_label_at


def _synthetic_stack(t=10, h=64, w=64):
    rng = np.random.default_rng(0)
    return rng.integers(0, 4000, size=(t, h, w)).astype(np.uint16)


def test_normalize_frame_is_uint8_full_range():
    frame = np.array([[0, 100], [1000, 5000]], dtype=np.uint16)
    out = normalize_frame(frame, percentile_clip=(0, 100))
    assert out.dtype == np.uint8
    assert out.min() == 0
    assert out.max() >= 254  # rounding of the 255-scaled max may land at 254


def test_annotate_frame_shape_and_dtype():
    stack = _synthetic_stack()
    cfg = AnnotationConfig()
    out = annotate_frame(stack[0], 0, cfg)
    assert out.shape == (64, 64, 3)
    assert out.dtype == np.uint8


def test_annotate_stack_shape():
    stack = _synthetic_stack(t=5)
    cfg = AnnotationConfig()
    out = annotate_stack(stack, cfg)
    assert out.shape == (5, 64, 64, 3)


def test_timestamp_formats():
    from bio_video_gui.annotate import _format_timestamp
    assert _format_timestamp(3.4, "seconds") == "3.4 s"
    assert _format_timestamp(65, "mm:ss") == "01:05"
    assert _format_timestamp(3665, "hh:mm:ss") == "01:01:05"


def test_scale_bar_length_scales_with_pixel_size():
    stack = _synthetic_stack()
    cfg_small = AnnotationConfig(
        timestamp=TimestampConfig(enabled=False),
        scale_bar=ScaleBarConfig(enabled=True, pixel_size_um=0.1, length_um=5.0, show_label=False),
    )
    cfg_large = AnnotationConfig(
        timestamp=TimestampConfig(enabled=False),
        scale_bar=ScaleBarConfig(enabled=True, pixel_size_um=1.0, length_um=5.0, show_label=False),
    )
    out_small = annotate_frame(stack[0], 0, cfg_small)
    out_large = annotate_frame(stack[0], 0, cfg_large)
    # smaller pixel size -> more pixels needed for same physical length -> more white pixels
    assert (out_small == 255).sum() > (out_large == 255).sum()


def test_scale_bar_label_never_overflows_frame_even_when_bar_is_short():
    # A short bar (coarse pixel size) with a longer label used to overflow
    # the right/top/bottom edges silently, since the label was drawn without
    # accounting for its own text width.
    from bio_video_gui.annotate import draw_scale_bar

    H, W = 200, 200
    for corner in ["top-left", "top-right", "bottom-left", "bottom-right"]:
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        cfg = ScaleBarConfig(enabled=True, pixel_size_um=2.0, length_um=5.0, corner=corner, offset_px=(10, 10))
        draw_scale_bar(frame, cfg)
        ys, xs = np.where(frame.any(axis=2))
        assert xs.max() < W and ys.max() < H and xs.min() >= 0 and ys.min() >= 0, corner


def test_highlight_region_only_drawn_within_frame_range():
    stack = _synthetic_stack(t=5, h=100, w=100)
    cfg = AnnotationConfig(
        timestamp=TimestampConfig(enabled=False),
        scale_bar=ScaleBarConfig(enabled=False),
        highlight=HighlightConfig(
            enabled=True,
            color=(0, 0, 255),
            thickness=2,
            regions=[HighlightRegion(shape="rectangle", coords=(10, 10, 40, 40), frame_start=2, frame_end=3)],
        ),
    )
    out = annotate_stack(stack, cfg)
    has_red = lambda f: np.any((f[..., 2] == 255) & (f[..., 0] == 0) & (f[..., 1] == 0))
    assert not has_red(out[0])
    assert not has_red(out[1])
    assert has_red(out[2])
    assert has_red(out[3])
    assert not has_red(out[4])


def test_highlight_config_supports_multiple_independent_regions():
    stack = _synthetic_stack(t=4, h=100, w=100)
    cfg = AnnotationConfig(
        timestamp=TimestampConfig(enabled=False),
        scale_bar=ScaleBarConfig(enabled=False),
        highlight=HighlightConfig(
            enabled=True,
            color=(0, 0, 255),
            thickness=2,
            regions=[
                HighlightRegion(shape="rectangle", coords=(5, 5, 20, 20), frame_start=0, frame_end=0),
                HighlightRegion(shape="circle", coords=(60, 60, 15, 0), frame_start=1, frame_end=None),
            ],
        ),
    )
    out = annotate_stack(stack, cfg)
    has_red = lambda f: np.any((f[..., 2] == 255) & (f[..., 0] == 0) & (f[..., 1] == 0))
    assert has_red(out[0])  # only the rectangle region is active
    assert has_red(out[1])  # only the circle region is active
    assert has_red(out[3])  # circle region has no end -> still active


def test_manual_contrast_limits_override_percentile():
    frame = np.array([[0, 10], [500, 5000]], dtype=np.uint16)
    auto = normalize_frame(frame, percentile_clip=(0, 100))
    manual = normalize_frame(frame, limits=(0, 10000))
    assert not np.array_equal(auto, manual)
    assert manual.max() < auto.max()  # same data scaled against a wider fixed range -> dimmer


def test_concat_stacks_has_no_phase_bookkeeping():
    a = _synthetic_stack(t=3, h=8, w=8)
    b = _synthetic_stack(t=4, h=8, w=8)
    merged = concat_stacks([a, b])
    assert merged.shape == (7, 8, 8)


def test_merge_phases_concatenates_and_tracks_offsets():
    a = _synthetic_stack(t=3, h=8, w=8)
    b = _synthetic_stack(t=4, h=8, w=8)
    result = merge_phases([a, b], ["baseline", "activation"])
    assert result.stack.shape == (7, 8, 8)
    assert result.phases == [Phase("baseline", 0), Phase("activation", 3)]


def test_merge_phases_rejects_mismatched_shapes():
    a = _synthetic_stack(t=3, h=8, w=8)
    b = _synthetic_stack(t=3, h=16, w=16)
    with pytest.raises(ValueError):
        merge_phases([a, b], ["baseline", "activation"])


def test_phase_label_at_switches_at_boundary():
    phases = [Phase("baseline", 0), Phase("activation", 24)]
    assert phase_label_at(phases, 0) == "baseline"
    assert phase_label_at(phases, 23) == "baseline"
    assert phase_label_at(phases, 24) == "activation"
    assert phase_label_at(phases, 100) == "activation"


def test_phase_label_config_integrates_with_annotate():
    stack = _synthetic_stack(t=6, h=64, w=64)
    phases = [Phase("baseline", 0), Phase("activation", 3)]
    cfg = AnnotationConfig(
        timestamp=TimestampConfig(enabled=False),
        scale_bar=ScaleBarConfig(enabled=False),
        condition_label=TextLabelConfig(enabled=False),
        phase_label=PhaseLabelConfig(enabled=True, phases=phases),
    )
    out = annotate_stack(stack, cfg)
    # frames should differ between phases purely due to the label text drawn
    assert not np.array_equal(out[0], out[3])
