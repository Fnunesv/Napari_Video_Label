[← Back to tutorial index](tutorial.md)

# 11. Batch processing (apply current settings to many files)

Applies your current timestamp/scale bar/labels/contrast/highlight-region
settings to many file-sets at once — e.g. exporting the same annotated
video style across every acquisition from an experiment.

## How files are paired

You define **one file list per phase**. Files are paired **by position**:
the *i*-th file in each phase's list belongs to the same output item. So if
you have phases `baseline, activation` and select 5 files for each, you get
5 output items, each merging its own baseline+activation pair.

## Steps

1. Enter **Batch phase names (comma-separated)**, e.g. `baseline,
   activation` — or, if you've already defined phases in section 7's table
   for an interactive merge, click **Use names from section 7 phase table**
   to copy them in instead of retyping. This only fills the field once,
   on click; it won't overwrite anything you type afterward, and editing
   the section 7 table later won't change it again unless you click the
   button a second time.
2. Click **Select files for each phase...** — you'll be prompted once per
   phase name to choose files, in item order.
3. Optionally check **Also apply the current crop rectangle (if any) to
   each item** (section 9) to crop every item the same way.
4. Click **Run batch export...** and choose an output folder.

> Reusing section 7's names is safe when every item in the batch has the
> **same phase structure** (same number of phases, same order). Each
> item's actual phase *start frames* are still recomputed from its own
> stack lengths — they aren't copied — so this only saves you from
> retyping names, not from checking that your stacks are structured
> consistently.

<p align="center">
  <img src="images/12-batch-processing.png" width="700" alt="Batch processing section">
</p>

<!--
SCREENSHOT NEEDED: images/12-batch-processing.png
Section 12 group box after files are selected, showing the
"N item(s) ready across N phase(s)" status and a completed batch summary.
-->

## Notes

- Pixel size and frame interval are **re-read from each item's own TIFF
  metadata** when available, so calibration doesn't have to be identical
  across items — only the annotation *style* (fonts, colors, positions,
  contrast mode) is shared.
- Output files are named `<original filename>_annotated` in the chosen
  output folder.
- If an item fails (e.g. mismatched image sizes when merging its phases),
  it's skipped and reported in the final summary — the rest of the batch
  still completes.
