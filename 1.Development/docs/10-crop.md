[← Back to tutorial index](tutorial.md)

# 10. Crop a region into its own working stack

Creates a new, independent working stack from a rectangular sub-region of
whichever stack is currently selected as **Active working stack** (section
10) — e.g. to zoom into one cell within a larger field of view.

## Steps

1. Click **Add crop-region shapes layer (draw a rectangle)**.
2. Draw a single rectangle over the region you want to keep.
3. Enter a **New working-stack name** (e.g. `crop 1`).
4. Click **Create cropped working stack from rectangle**.

<p align="center">
  <img src="images/09-crop.png" width="700" alt="Crop section">
</p>

<!--
SCREENSHOT NEEDED: images/09-crop.png
napari canvas with a crop rectangle drawn over part of the image, plus
the resulting new working-stack layer alongside it.
-->

The crop keeps all current phases, styling, and highlight regions —
their coordinates are shifted automatically to line up with the new,
smaller frame. The crop is added as a new entry in the **Active working
stack** dropdown (section 10), so you can keep switching between the
original and any number of crops, editing each independently.
