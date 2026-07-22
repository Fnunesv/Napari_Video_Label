[← Back to tutorial index](tutorial.md)

# 11. Export

Renders the full annotated stack (all settings from sections 2–8 applied to
every frame of the **Active working stack**) and saves it to disk.

## Formats

| Format | Output |
|---|---|
| MP4 video (.mp4) | Single video file, playback speed set by **Output FPS** (section 2) |
| AVI video (.avi) | Single video file |
| MOV video (.mov) | Single video file |
| TIFF stack (.tif, one file) | Single multi-page TIFF, one page per frame |
| PNG image sequence (one folder) | One PNG per frame in a chosen folder |

## Steps

1. Pick a **Format**.
2. Click **Export...** and choose a save location (or output folder, for
   the image sequence option).

<p align="center">
  <img src="images/11-export.png" width="500" alt="Export section">
</p>

<!--
SCREENSHOT NEEDED: images/11-export.png
Section 11 group box with a format selected, plus the "Export complete"
confirmation dialog.
-->

Export always uses the currently selected **Active working stack** (section
10) — double-check that dropdown before exporting if you have more than one
crop defined.
