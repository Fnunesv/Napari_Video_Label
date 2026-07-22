# bio-video-gui

Napari plugin to merge, annotate, crop, and export microscopy timelapses
(.tif stacks) as presentation-ready videos. Generalizes the "merge and
annotate videos" logic from
`actin-polarization/2.Processing/Actin_Polarization_FullProcessing copy.py`
into reusable, pixel-size/frame-rate-agnostic building blocks.

Highlights:
- Merge phase stacks first, **define/edit/delete phase labels afterwards**
  in an editable table.
- Timestamp, scale bar, condition label, phase label — each with its own
  position, font size, and color.
- Any number of highlight regions (box/circle), each drawn as a napari
  Shapes-layer shape with its own visible frame range; delete a shape (in
  napari or in the widget's table) to remove its highlight.
- Contrast: per-frame auto percentile, or fixed manual min/max.
- Crop any working stack into a new one — annotations carry over
  automatically (coordinates shift to match) and stay independently editable.
- Live single-frame preview that updates as you change any setting.
- Export to MP4/AVI/MOV, a multi-page TIFF stack, or a PNG sequence.
- Batch processing: apply the current settings to many file-sets at once;
  phase names can be copied in from the section 7 phase table with one
  click instead of retyping (opt-in — won't overwrite anything you've
  already typed unless you click it).

See `handoff.md` for full session-by-session history and known gaps.

See [`docs/tutorial.md`](docs/tutorial.md) for a walkthrough of every
section of the widget, with screenshots.

## Install

Requires Python >=3.10 and napari (`pip install napari[all]` if you don't
have it yet).

**If you don't have napari, follow these steps**

1. Create a virtual environment to run napari visualization (always recommended)
```bash
conda create -n napari_env
```

2. Install napari and then bio-video-gui
```bash
pip install napari[all]
```

**Quick install (no manual clone):**
On the virtual environment (napari_env)


```bash
conda activate napari_env
pip install "git+https://github.com/Fnunesv/Napari_Video_Label.git#subdirectory=1.Development"
```

**Clone + editable install** (if you also want to run the tests or edit code):

```bash
conda activate napari_env
git clone https://github.com/Fnunesv/Napari_Video_Label.git
cd Napari_Video_Label/1.Development
pip install -e .
```

Then launch napari (`napari` on the command line, or from Anaconda
Navigator/your usual launcher). The widget appears under
`Plugins > Bio Video GUI > Video Annotation & Export`.

## Architecture

- `io_utils.py` — loads a `.tif` stack and best-effort recovers pixel size
  (from the TIFF XResolution tag) and frame interval (from ImageJ metadata),
  so users don't have to re-enter calibration for every acquisition.
- `merge.py` — `concat_stacks` merges phase stacks with no labeling required
  (labels are defined afterwards); `merge_phases` merges *and* auto-labels
  in one step, used internally by batch processing where phase names are
  already known per file-group.
- `annotate.py` — pure numpy/OpenCV drawing functions (timestamp, scale bar,
  condition label, phase label, `HighlightConfig` with a list of
  independent `HighlightRegion`s), each configurable via dataclasses in
  `AnnotationConfig` (position, font size, color, thickness). Contrast is
  either per-frame percentile clipping or a fixed `contrast_limits`
  min/max. No GUI or hardcoded experiment assumptions.
- `video_export.py` — writes an annotated `(T, H, W, 3)` uint8 stack to a
  video (`write_video`, codec by suffix: .mp4/.mov/.avi), a multi-page TIFF
  (`write_tiff_stack`), or a folder of per-frame images (`write_image_sequence`).
- `_widget.py` — the napari dock widget (scrollable), 12 sections: merge,
  calibration, contrast, timestamp, scale bar, condition label, phase table
  (post-merge, editable/deletable), highlight regions (multi-shape table,
  editable/deletable), crop (creates a new "working stack" with shifted
  annotations), live preview (with a working-stack selector), export, and
  batch processing.

## Tests

```bash
python -m pytest tests/
```

`pyproject.toml` disables napari's own pytest plugin (`-p no:napari`) because
its `make_napari_viewer` fixture creates a real Qt/vispy canvas, which segfaults
in headless/sandboxed environments without a display or GPU. If you add GUI
integration tests on a machine with a real display, remove that line.

## Known limitation

Creating a real `napari.Viewer` requires a display/GPU-backed Qt platform.
It was verified programmatically here using `napari.components.ViewerModel`
(the same layer/event API, without the Qt canvas) plus a `QApplication` for
the widget itself — full interactive GUI use should be confirmed by launching
`napari` on a normal desktop session.
