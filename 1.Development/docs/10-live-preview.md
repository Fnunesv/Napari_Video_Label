[← Back to tutorial index](tutorial.md)

# 10. Live preview

A single annotated frame that updates automatically as you change any
setting elsewhere in the widget — no button needed. This is what you should
be watching while tuning timestamp/scale bar/labels/contrast.

| Field | Meaning |
|---|---|
| Active working stack | Which stack (merged timeline or a crop) the rest of the widget currently operates on |
| Preview frame | Which frame index is rendered live |
| Bake full annotated stack as a layer (slower) | Renders and adds *every* frame as a new napari image layer, useful for scrubbing through the whole result before exporting |

<p align="center">
  <img src="images/10-live-preview.png" width="700" alt="Live preview section">
</p>

<!--
SCREENSHOT NEEDED: images/10-live-preview.png
napari canvas showing the "live annotation preview" layer with several
annotations visible (timestamp, scale bar, a label), plus section 10's
controls.
-->

The live preview only renders one frame at a time, so it stays responsive
even on large stacks — use **Bake full annotated stack** when you want to
scrub through or play back the entire annotated result before exporting.
