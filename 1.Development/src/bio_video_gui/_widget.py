"""Napari dock widget: merge, annotate (post-merge, editable), crop, preview, export, batch."""
from __future__ import annotations

from pathlib import Path

import napari
import numpy as np
from qtpy.QtCore import Qt, QTimer
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .annotate import (
    AnnotationConfig,
    HighlightConfig,
    HighlightRegion,
    PhaseLabelConfig,
    ScaleBarConfig,
    TextLabelConfig,
    TimestampConfig,
    annotate_frame,
    annotate_stack,
)
from .io_utils import load_stack
from .merge import Phase, concat_stacks, merge_phases
from .video_export import write_image_sequence, write_tiff_stack, write_video

CORNERS = ["bottom-left", "bottom-right", "top-left", "top-right"]
TIMESTAMP_FORMATS = ["seconds", "mm:ss", "hh:mm:ss"]
EXPORT_FORMATS = {
    "MP4 video (.mp4)": ("video", ".mp4"),
    "AVI video (.avi)": ("video", ".avi"),
    "MOV video (.mov)": ("video", ".mov"),
    "TIFF stack (.tif, one file)": ("tiff", ".tif"),
    "PNG image sequence (one folder)": ("sequence", None),
}
MERGED_LAYER_NAME = "merged timeline"
LIVE_PREVIEW_LAYER_NAME = "live annotation preview"
FULL_PREVIEW_LAYER_NAME = "annotated preview (full stack)"


class ColorButton(QPushButton):
    """A small button that shows a color swatch and opens a picker on click."""

    def __init__(self, initial_rgb: tuple[int, int, int] = (255, 255, 255), on_change=None):
        super().__init__()
        self._rgb = initial_rgb
        self._on_change = on_change
        self.setFixedWidth(36)
        self.setToolTip("Click to choose a color")
        self.clicked.connect(self._pick)
        self._update_swatch()

    def _pick(self) -> None:
        from qtpy.QtWidgets import QColorDialog

        color = QColorDialog.getColor(QColor(*self._rgb), self)
        if color.isValid():
            self._rgb = (color.red(), color.green(), color.blue())
            self._update_swatch()
            if self._on_change:
                self._on_change()

    def _update_swatch(self) -> None:
        r, g, b = self._rgb
        self.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #888;")

    def bgr(self) -> tuple[int, int, int]:
        r, g, b = self._rgb
        return (b, g, r)


def _offset_spinboxes(default_x: int, default_y: int) -> tuple[QHBoxLayout, QSpinBox, QSpinBox]:
    """A labeled X/Y pixel-offset row (from the chosen corner) for custom positioning."""
    row = QHBoxLayout()
    x_spin = QSpinBox()
    x_spin.setRange(0, 5000)
    x_spin.setValue(default_x)
    y_spin = QSpinBox()
    y_spin.setRange(0, 5000)
    y_spin.setValue(default_y)
    row.addWidget(QLabel("X:"))
    row.addWidget(x_spin)
    row.addWidget(QLabel("Y:"))
    row.addWidget(y_spin)
    return row, x_spin, y_spin


class BioVideoWidget(QWidget):
    """Main widget for the bio-video-gui napari plugin."""

    def __init__(self, viewer: napari.viewer.Viewer):
        super().__init__()
        self.viewer = viewer
        self._phases: list[Phase] = []
        self._working_stacks: dict[str, dict] = {}  # name -> {"stack": ndarray, "origin": (oy, ox)}
        self._connected_shapes_layer = None
        self._batch_phase_files: dict[str, list[str]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        scroll.setWidget(content)

        content_layout.addWidget(self._build_merge_box())
        content_layout.addWidget(self._build_calibration_box())
        content_layout.addWidget(self._build_contrast_box())
        content_layout.addWidget(self._build_timestamp_box())
        content_layout.addWidget(self._build_scalebar_box())
        content_layout.addWidget(self._build_condition_box())
        content_layout.addWidget(self._build_phase_box())
        content_layout.addWidget(self._build_highlight_box())
        content_layout.addWidget(self._build_crop_box())
        content_layout.addWidget(self._build_preview_box())
        content_layout.addWidget(self._build_export_box())
        content_layout.addWidget(self._build_batch_box())
        content_layout.addStretch()

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._refresh_live_preview)
        self._connect_live_updates()

        self.viewer.layers.events.inserted.connect(self._refresh_layer_list)
        self.viewer.layers.events.removed.connect(self._refresh_layer_list)
        self._refresh_layer_list()

    # ---- UI sections -----------------------------------------------------

    def _build_merge_box(self) -> QGroupBox:
        box = QGroupBox("1. Merge layers into a timeline")
        v = QVBoxLayout()
        box.setLayout(v)

        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layer_list.itemSelectionChanged.connect(self._on_selection_changed)
        v.addWidget(self.layer_list)

        self.load_tif_btn = QPushButton("Load .tif as layer(s)...")
        self.load_tif_btn.clicked.connect(self._on_load_tif)
        v.addWidget(self.load_tif_btn)

        self.merge_btn = QPushButton("Merge selected layers -> timeline")
        self.merge_btn.clicked.connect(self._on_merge)
        v.addWidget(self.merge_btn)

        self.merge_status = QLabel(
            "No merged stack yet. Phase labels are defined afterwards, in section 7."
        )
        self.merge_status.setWordWrap(True)
        v.addWidget(self.merge_status)
        return box

    def _build_calibration_box(self) -> QGroupBox:
        box = QGroupBox("2. Calibration")
        form = QFormLayout()
        box.setLayout(form)

        self.pixel_size_spin = QDoubleSpinBox()
        self.pixel_size_spin.setDecimals(5)
        self.pixel_size_spin.setRange(0.00001, 1000)
        self.pixel_size_spin.setValue(1.0)
        self.pixel_size_spin.setSuffix(" um/px")
        form.addRow("Pixel size:", self.pixel_size_spin)

        self.frame_interval_spin = QDoubleSpinBox()
        self.frame_interval_spin.setDecimals(3)
        self.frame_interval_spin.setRange(0.001, 100000)
        self.frame_interval_spin.setValue(1.0)
        self.frame_interval_spin.setSuffix(" s/frame")
        form.addRow("Frame interval:", self.frame_interval_spin)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setValue(10)
        form.addRow("Output FPS:", self.fps_spin)
        return box

    def _build_contrast_box(self) -> QGroupBox:
        box = QGroupBox("3. Contrast")
        form = QFormLayout()
        box.setLayout(form)

        self.contrast_mode = QComboBox()
        self.contrast_mode.addItems(["Auto (percentile, per frame)", "Manual min/max"])
        form.addRow("Mode:", self.contrast_mode)

        pct_row = QHBoxLayout()
        self.contrast_pct_low = QDoubleSpinBox()
        self.contrast_pct_low.setRange(0, 100)
        self.contrast_pct_low.setValue(1)
        self.contrast_pct_high = QDoubleSpinBox()
        self.contrast_pct_high.setRange(0, 100)
        self.contrast_pct_high.setValue(99)
        pct_row.addWidget(self.contrast_pct_low)
        pct_row.addWidget(self.contrast_pct_high)
        form.addRow("Percentile low/high:", pct_row)

        minmax_row = QHBoxLayout()
        self.contrast_min = QDoubleSpinBox()
        self.contrast_min.setRange(0, 1_000_000)
        self.contrast_min.setValue(0)
        self.contrast_max = QDoubleSpinBox()
        self.contrast_max.setRange(0, 1_000_000)
        self.contrast_max.setValue(65535)
        minmax_row.addWidget(self.contrast_min)
        minmax_row.addWidget(self.contrast_max)
        form.addRow("Manual min/max:", minmax_row)

        self.contrast_autofill_btn = QPushButton("Auto-fill min/max from current stack")
        self.contrast_autofill_btn.clicked.connect(self._on_contrast_autofill)
        form.addRow(self.contrast_autofill_btn)
        return box

    def _build_timestamp_box(self) -> QGroupBox:
        box = QGroupBox("4. Timestamp")
        form = QFormLayout()
        box.setLayout(form)

        self.ts_enabled = QCheckBox("Show timestamp")
        self.ts_enabled.setChecked(True)
        form.addRow(self.ts_enabled)

        self.ts_format = QComboBox()
        self.ts_format.addItems(TIMESTAMP_FORMATS)
        form.addRow("Format:", self.ts_format)

        self.ts_corner = QComboBox()
        self.ts_corner.addItems(CORNERS)
        self.ts_corner.setCurrentText("bottom-left")
        form.addRow("Anchor corner:", self.ts_corner)

        ts_offset_row, self.ts_offset_x, self.ts_offset_y = _offset_spinboxes(10, 10)
        form.addRow("Offset from corner (px):", ts_offset_row)

        self.ts_font_scale = QDoubleSpinBox()
        self.ts_font_scale.setRange(0.1, 3.0)
        self.ts_font_scale.setSingleStep(0.1)
        self.ts_font_scale.setValue(0.6)
        form.addRow("Font size:", self.ts_font_scale)

        self.ts_color = ColorButton((255, 255, 255), on_change=self._schedule_preview)
        form.addRow("Font color:", self.ts_color)

        hint = QLabel(
            "Offset is measured inward from the anchor corner. For fully free\n"
            "placement, set the anchor to 'top-left' and use X/Y as an absolute\n"
            "pixel position from the top-left of the frame."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return box

    def _build_scalebar_box(self) -> QGroupBox:
        box = QGroupBox("5. Scale bar")
        form = QFormLayout()
        box.setLayout(form)

        self.sb_enabled = QCheckBox("Show scale bar")
        self.sb_enabled.setChecked(True)
        form.addRow(self.sb_enabled)

        self.sb_length = QDoubleSpinBox()
        self.sb_length.setRange(0.01, 10000)
        self.sb_length.setValue(5.0)
        self.sb_length.setSuffix(" um")
        form.addRow("Length:", self.sb_length)

        self.sb_corner = QComboBox()
        self.sb_corner.addItems(CORNERS)
        self.sb_corner.setCurrentText("bottom-right")
        form.addRow("Anchor corner:", self.sb_corner)

        sb_offset_row, self.sb_offset_x, self.sb_offset_y = _offset_spinboxes(20, 20)
        form.addRow("Offset from corner (px):", sb_offset_row)

        self.sb_font_scale = QDoubleSpinBox()
        self.sb_font_scale.setRange(0.1, 3.0)
        self.sb_font_scale.setSingleStep(0.1)
        self.sb_font_scale.setValue(0.6)
        form.addRow("Label font size:", self.sb_font_scale)

        self.sb_color = ColorButton((255, 255, 255), on_change=self._schedule_preview)
        form.addRow("Color (bar + label):", self.sb_color)
        return box

    def _build_condition_box(self) -> QGroupBox:
        box = QGroupBox("6. Condition label")
        form = QFormLayout()
        box.setLayout(form)

        self.cond_enabled = QCheckBox("Show condition label")
        form.addRow(self.cond_enabled)
        self.cond_text = QLineEdit("CRY2-mCherry")
        form.addRow("Text:", self.cond_text)
        self.cond_corner = QComboBox()
        self.cond_corner.addItems(CORNERS)
        self.cond_corner.setCurrentText("top-left")
        form.addRow("Anchor corner:", self.cond_corner)
        cond_offset_row, self.cond_offset_x, self.cond_offset_y = _offset_spinboxes(10, 10)
        form.addRow("Offset from corner (px):", cond_offset_row)
        self.cond_font_scale = QDoubleSpinBox()
        self.cond_font_scale.setRange(0.1, 3.0)
        self.cond_font_scale.setSingleStep(0.1)
        self.cond_font_scale.setValue(0.7)
        form.addRow("Font size:", self.cond_font_scale)
        self.cond_color = ColorButton((255, 255, 255), on_change=self._schedule_preview)
        form.addRow("Font color:", self.cond_color)
        return box

    def _build_phase_box(self) -> QGroupBox:
        box = QGroupBox("7. Phase annotations (defined after merging)")
        v = QVBoxLayout()
        box.setLayout(v)

        self.phase_enabled = QCheckBox("Show phase label")
        v.addWidget(self.phase_enabled)

        self.phase_table = QTableWidget(0, 2)
        self.phase_table.setHorizontalHeaderLabels(["Label", "Start frame"])
        self.phase_table.itemChanged.connect(self._on_phase_table_changed)
        v.addWidget(self.phase_table)

        row = QHBoxLayout()
        self.add_phase_btn = QPushButton("Add phase at preview frame")
        self.add_phase_btn.clicked.connect(self._on_add_phase_row)
        row.addWidget(self.add_phase_btn)
        self.delete_phase_btn = QPushButton("Delete selected")
        self.delete_phase_btn.clicked.connect(self._on_delete_phase_rows)
        row.addWidget(self.delete_phase_btn)
        v.addLayout(row)

        hint = QLabel(
            "Edit a cell to rename a phase or move its start frame; e.g. fix a\n"
            "wrongly-labeled range by just retyping its name. Overlapping starts\n"
            "are sorted automatically; the label switches at each start frame."
        )
        hint.setWordWrap(True)
        v.addWidget(hint)

        form = QFormLayout()
        self.phase_corner = QComboBox()
        self.phase_corner.addItems(CORNERS)
        self.phase_corner.setCurrentText("top-right")
        form.addRow("Anchor corner:", self.phase_corner)
        phase_offset_row, self.phase_offset_x, self.phase_offset_y = _offset_spinboxes(10, 10)
        form.addRow("Offset from corner (px):", phase_offset_row)
        self.phase_font_scale = QDoubleSpinBox()
        self.phase_font_scale.setRange(0.1, 3.0)
        self.phase_font_scale.setSingleStep(0.1)
        self.phase_font_scale.setValue(0.7)
        form.addRow("Font size:", self.phase_font_scale)
        self.phase_color = ColorButton((0, 255, 255), on_change=self._schedule_preview)
        form.addRow("Font color:", self.phase_color)
        v.addLayout(form)
        return box

    def _build_highlight_box(self) -> QGroupBox:
        box = QGroupBox("8. Highlight regions (box or circle on the image)")
        v = QVBoxLayout()
        box.setLayout(v)

        self.marker_enabled = QCheckBox("Show highlight regions")
        v.addWidget(self.marker_enabled)

        self.add_roi_btn = QPushButton("Add highlight shapes layer (draw rectangle/ellipse)")
        self.add_roi_btn.clicked.connect(self._on_add_roi_layer)
        v.addWidget(self.add_roi_btn)

        form = QFormLayout()
        self.marker_layer_combo = QComboBox()
        self.marker_layer_combo.currentIndexChanged.connect(self._on_marker_layer_changed)
        form.addRow("Shapes layer:", self.marker_layer_combo)
        v.addLayout(form)

        self.highlight_table = QTableWidget(0, 4)
        self.highlight_table.setHorizontalHeaderLabels(["#", "Shape", "Start frame", "End frame (-1=end)"])
        self.highlight_table.itemChanged.connect(self._on_highlight_table_changed)
        v.addWidget(self.highlight_table)

        self.delete_highlight_btn = QPushButton("Delete selected shape(s)")
        self.delete_highlight_btn.clicked.connect(self._on_delete_selected_highlight)
        v.addWidget(self.delete_highlight_btn)

        style_form = QFormLayout()
        self.marker_thickness = QSpinBox()
        self.marker_thickness.setRange(1, 20)
        self.marker_thickness.setValue(2)
        style_form.addRow("Line thickness:", self.marker_thickness)
        self.marker_color = ColorButton((255, 0, 0), on_change=self._schedule_preview)
        style_form.addRow("Color:", self.marker_color)
        v.addLayout(style_form)

        hint = QLabel(
            "Click 'Add highlight shapes layer', then draw as many rectangles/\n"
            "ellipses as you like directly on the canvas — each becomes its own\n"
            "row here with its own visible frame range. Delete a shape (here or\n"
            "in napari) to remove it; drag its handles in napari to edit it."
        )
        hint.setWordWrap(True)
        v.addWidget(hint)
        return box

    def _build_crop_box(self) -> QGroupBox:
        box = QGroupBox("9. Crop a region into its own working stack")
        v = QVBoxLayout()
        box.setLayout(v)

        self.add_crop_roi_btn = QPushButton("Add crop-region shapes layer (draw a rectangle)")
        self.add_crop_roi_btn.clicked.connect(self._on_add_crop_roi_layer)
        v.addWidget(self.add_crop_roi_btn)

        form = QFormLayout()
        self.crop_layer_combo = QComboBox()
        form.addRow("Crop rectangle layer:", self.crop_layer_combo)
        self.crop_name_edit = QLineEdit("crop 1")
        form.addRow("New working-stack name:", self.crop_name_edit)
        v.addLayout(form)

        self.create_crop_btn = QPushButton("Create cropped working stack from rectangle")
        self.create_crop_btn.clicked.connect(self._on_create_crop)
        v.addWidget(self.create_crop_btn)

        hint = QLabel(
            "Crops the stack currently selected as 'Active working stack' below.\n"
            "The crop keeps all current phases/styling/highlight regions\n"
            "(shifted to line up) and can still be edited or deleted\n"
            "independently — just select it as the active working stack."
        )
        hint.setWordWrap(True)
        v.addWidget(hint)
        return box

    def _build_preview_box(self) -> QGroupBox:
        box = QGroupBox("10. Live preview")
        form = QFormLayout()
        box.setLayout(form)

        self.working_stack_combo = QComboBox()
        self.working_stack_combo.currentIndexChanged.connect(self._on_working_stack_changed)
        form.addRow("Active working stack:", self.working_stack_combo)

        self.preview_frame_spin = QSpinBox()
        self.preview_frame_spin.setRange(0, 0)
        self.preview_frame_spin.valueChanged.connect(self._schedule_preview)
        form.addRow("Preview frame:", self.preview_frame_spin)

        self.bake_full_btn = QPushButton("Bake full annotated stack as a layer (slower)")
        self.bake_full_btn.clicked.connect(self._on_bake_full_preview)
        form.addRow(self.bake_full_btn)

        hint = QLabel(
            "A single-frame preview updates automatically as you change any\n"
            "setting above or move the frame spinner — no button needed."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return box

    def _build_export_box(self) -> QGroupBox:
        box = QGroupBox("11. Export")
        form = QFormLayout()
        box.setLayout(form)

        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(EXPORT_FORMATS.keys())
        form.addRow("Format:", self.export_format_combo)

        self.export_btn = QPushButton("Export...")
        self.export_btn.clicked.connect(self._on_export)
        form.addRow(self.export_btn)
        return box

    def _build_batch_box(self) -> QGroupBox:
        box = QGroupBox("12. Batch processing (apply current settings to many files)")
        v = QVBoxLayout()
        box.setLayout(v)

        hint = QLabel(
            "Define one file list per phase. Files are paired by position —\n"
            "the i-th file in each phase's list belongs to the same item.\n"
            "Current timestamp/scale bar/labels/contrast/highlight-region\n"
            "settings are applied to every item; pixel size and frame interval\n"
            "are re-read from each item's own TIFF metadata when available."
        )
        hint.setWordWrap(True)
        v.addWidget(hint)

        v.addWidget(QLabel("Batch phase names (comma-separated):"))
        self.batch_phase_names_edit = QLineEdit("baseline, activation")
        v.addWidget(self.batch_phase_names_edit)

        self.batch_select_btn = QPushButton("Select files for each phase...")
        self.batch_select_btn.clicked.connect(self._on_select_batch_files)
        v.addWidget(self.batch_select_btn)

        self.batch_files_status = QLabel("No files selected yet.")
        self.batch_files_status.setWordWrap(True)
        v.addWidget(self.batch_files_status)

        self.batch_apply_crop = QCheckBox("Also apply the current crop rectangle (if any) to each item")
        v.addWidget(self.batch_apply_crop)

        self.batch_run_btn = QPushButton("Run batch export...")
        self.batch_run_btn.clicked.connect(self._on_run_batch)
        v.addWidget(self.batch_run_btn)

        self.batch_progress = QLabel("")
        self.batch_progress.setWordWrap(True)
        v.addWidget(self.batch_progress)
        return box

    # ---- live-update wiring ------------------------------------------------

    def _connect_live_updates(self) -> None:
        checkboxes = [self.ts_enabled, self.sb_enabled, self.cond_enabled, self.phase_enabled, self.marker_enabled]
        for cb in checkboxes:
            cb.toggled.connect(self._schedule_preview)

        combos = [
            self.ts_format, self.ts_corner, self.sb_corner, self.cond_corner,
            self.phase_corner, self.contrast_mode,
        ]
        for combo in combos:
            combo.currentIndexChanged.connect(self._schedule_preview)

        spins = [
            self.pixel_size_spin, self.frame_interval_spin, self.sb_length,
            self.ts_font_scale, self.sb_font_scale, self.cond_font_scale, self.phase_font_scale,
            self.marker_thickness, self.contrast_pct_low, self.contrast_pct_high,
            self.contrast_min, self.contrast_max,
            self.ts_offset_x, self.ts_offset_y, self.sb_offset_x, self.sb_offset_y,
            self.cond_offset_x, self.cond_offset_y, self.phase_offset_x, self.phase_offset_y,
        ]
        for spin in spins:
            spin.valueChanged.connect(self._schedule_preview)

        self.cond_text.textChanged.connect(self._schedule_preview)

    def _schedule_preview(self, *_args) -> None:
        self._preview_timer.start(150)

    # ---- layer bookkeeping --------------------------------------------------

    def _refresh_layer_list(self, event=None) -> None:
        self.layer_list.clear()
        prev_marker = self.marker_layer_combo.currentText()
        prev_crop = self.crop_layer_combo.currentText()
        self.marker_layer_combo.blockSignals(True)
        self.marker_layer_combo.clear()
        self.crop_layer_combo.clear()
        for layer in self.viewer.layers:
            if isinstance(layer, napari.layers.Image):
                self.layer_list.addItem(QListWidgetItem(layer.name))
            elif isinstance(layer, napari.layers.Shapes):
                self.marker_layer_combo.addItem(layer.name)
                self.crop_layer_combo.addItem(layer.name)
        if prev_marker:
            self.marker_layer_combo.setCurrentText(prev_marker)
        if prev_crop:
            self.crop_layer_combo.setCurrentText(prev_crop)
        self.marker_layer_combo.blockSignals(False)

        for name in list(self._working_stacks.keys()):
            if name not in self.viewer.layers:
                del self._working_stacks[name]
        self._refresh_working_stack_combo()
        self._sync_highlight_table()

    def _refresh_working_stack_combo(self) -> None:
        current = self.working_stack_combo.currentText()
        self.working_stack_combo.blockSignals(True)
        self.working_stack_combo.clear()
        self.working_stack_combo.addItems(list(self._working_stacks.keys()))
        if current in self._working_stacks:
            self.working_stack_combo.setCurrentText(current)
        self.working_stack_combo.blockSignals(False)

    def _on_working_stack_changed(self, *_args) -> None:
        self._update_preview_range()
        self._schedule_preview()

    def _on_selection_changed(self) -> None:
        self._update_preview_range()
        self._schedule_preview()

    def _on_load_tif(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Load TIF stack(s)", "", "TIFF (*.tif *.tiff)")
        for p in paths:
            stack, meta = load_stack(p)
            self.viewer.add_image(stack, name=Path(p).stem)
            if meta.pixel_size_um:
                self.pixel_size_spin.setValue(meta.pixel_size_um)
            if meta.frame_interval_s:
                self.frame_interval_spin.setValue(meta.frame_interval_s)

    def _register_working_stack(self, name: str, stack: np.ndarray, origin: tuple[float, float]) -> None:
        self._working_stacks[name] = {"stack": stack, "origin": origin}
        if name in self.viewer.layers:
            self.viewer.layers[name].data = stack
            self.viewer.layers[name].translate = origin
        else:
            self.viewer.add_image(stack, name=name, translate=origin)
        self._refresh_working_stack_combo()
        self.working_stack_combo.setCurrentText(name)
        self._update_preview_range()

    def _active_stack(self) -> np.ndarray | None:
        entry = self._working_stacks.get(self.working_stack_combo.currentText())
        if entry is not None:
            return entry["stack"]
        selected = self.layer_list.selectedItems()
        if len(selected) == 1:
            return self.viewer.layers[selected[0].text()].data
        return None

    def _active_origin(self) -> tuple[float, float]:
        entry = self._working_stacks.get(self.working_stack_combo.currentText())
        return entry["origin"] if entry else (0.0, 0.0)

    def _update_preview_range(self) -> None:
        stack = self._active_stack()
        n_frames = stack.shape[0] if stack is not None else 1
        self.preview_frame_spin.setMaximum(max(0, n_frames - 1))

    # ---- merge ---------------------------------------------------------------

    def _on_merge(self) -> None:
        selected_names = [item.text() for item in self.layer_list.selectedItems()]
        if not selected_names:
            QMessageBox.warning(self, "No layers selected", "Select one or more image layers to merge, in order.")
            return
        stacks = [self.viewer.layers[name].data for name in selected_names]
        try:
            merged = concat_stacks(stacks)
        except ValueError as e:
            QMessageBox.warning(self, "Cannot merge", str(e))
            return

        self._register_working_stack(MERGED_LAYER_NAME, merged, origin=(0.0, 0.0))
        self.merge_status.setText(
            f"Merged {len(stacks)} layer(s) -> {merged.shape[0]} frames. "
            f"Define phase labels in section 7."
        )

        if self.phase_table.rowCount() == 0:
            self.phase_table.blockSignals(True)
            self.phase_table.setRowCount(1)
            self.phase_table.setItem(0, 0, QTableWidgetItem("phase 1"))
            self.phase_table.setItem(0, 1, QTableWidgetItem("0"))
            self.phase_table.blockSignals(False)
            self._rebuild_phases_from_table()

        self._schedule_preview()

    # ---- phase table (post-merge, editable/deletable) -------------------------

    def _on_add_phase_row(self) -> None:
        row = self.phase_table.rowCount()
        self.phase_table.blockSignals(True)
        self.phase_table.insertRow(row)
        self.phase_table.setItem(row, 0, QTableWidgetItem(f"phase {row + 1}"))
        self.phase_table.setItem(row, 1, QTableWidgetItem(str(self.preview_frame_spin.value())))
        self.phase_table.blockSignals(False)
        self._rebuild_phases_from_table()

    def _on_delete_phase_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.phase_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.phase_table.removeRow(row)
        self._rebuild_phases_from_table()

    def _on_phase_table_changed(self, _item) -> None:
        self._rebuild_phases_from_table()

    def _rebuild_phases_from_table(self) -> None:
        phases = []
        for row in range(self.phase_table.rowCount()):
            name_item = self.phase_table.item(row, 0)
            start_item = self.phase_table.item(row, 1)
            if name_item is None or start_item is None:
                continue
            name = name_item.text().strip()
            try:
                start = int(start_item.text())
            except ValueError:
                continue
            if name:
                phases.append(Phase(name=name, start_frame=start))
        phases.sort(key=lambda p: p.start_frame)
        self._phases = phases
        self._schedule_preview()

    # ---- highlight regions (multi-shape, editable/deletable) ------------------

    def _on_add_roi_layer(self) -> None:
        name = "highlight_roi"
        suffix = 1
        while name in self.viewer.layers:
            suffix += 1
            name = f"highlight_roi_{suffix}"
        shapes_layer = self.viewer.add_shapes(
            name=name, shape_type="rectangle", edge_color="red", face_color="transparent", edge_width=3,
        )
        shapes_layer.mode = "add_rectangle"
        self._refresh_layer_list()
        self.marker_layer_combo.setCurrentText(name)
        self.marker_enabled.setChecked(True)
        self._on_marker_layer_changed()

    def _on_marker_layer_changed(self, *_args) -> None:
        if self._connected_shapes_layer is not None:
            try:
                self._connected_shapes_layer.events.data.disconnect(self._sync_highlight_table)
            except Exception:
                pass
            self._connected_shapes_layer = None
        layer_name = self.marker_layer_combo.currentText()
        if layer_name and layer_name in self.viewer.layers:
            layer = self.viewer.layers[layer_name]
            layer.events.data.connect(self._sync_highlight_table)
            self._connected_shapes_layer = layer
        self._sync_highlight_table()

    def _sync_highlight_table(self, *_args) -> None:
        layer_name = self.marker_layer_combo.currentText()
        if not layer_name or layer_name not in self.viewer.layers:
            self.highlight_table.setRowCount(0)
            self._schedule_preview()
            return
        shapes_layer = self.viewer.layers[layer_name]
        n_shapes = len(shapes_layer.data)
        if self.highlight_table.rowCount() != n_shapes:
            self.highlight_table.blockSignals(True)
            self.highlight_table.setRowCount(n_shapes)
            for i in range(n_shapes):
                shape_kind = shapes_layer.shape_type[i] if i < len(shapes_layer.shape_type) else "rectangle"
                idx_item = QTableWidgetItem(str(i))
                idx_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.highlight_table.setItem(i, 0, idx_item)
                shape_item = QTableWidgetItem(shape_kind)
                shape_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.highlight_table.setItem(i, 1, shape_item)
                self.highlight_table.setItem(i, 2, QTableWidgetItem("0"))
                self.highlight_table.setItem(i, 3, QTableWidgetItem("-1"))
            self.highlight_table.blockSignals(False)
        self._schedule_preview()

    def _on_highlight_table_changed(self, _item) -> None:
        self._schedule_preview()

    def _on_delete_selected_highlight(self) -> None:
        layer_name = self.marker_layer_combo.currentText()
        if not layer_name or layer_name not in self.viewer.layers:
            return
        rows = {idx.row() for idx in self.highlight_table.selectedIndexes()}
        if not rows:
            return
        shapes_layer = self.viewer.layers[layer_name]
        shapes_layer.selected_data = rows
        shapes_layer.remove_selected()
        # shapes_layer.events.data fires -> _sync_highlight_table runs automatically

    def _highlight_regions_from_ui(self, origin: tuple[float, float]) -> list[HighlightRegion]:
        regions: list[HighlightRegion] = []
        layer_name = self.marker_layer_combo.currentText()
        if not (self.marker_enabled.isChecked() and layer_name and layer_name in self.viewer.layers):
            return regions
        shapes_layer = self.viewer.layers[layer_name]
        oy, ox = origin
        for i, coords_yx in enumerate(shapes_layer.data):
            if len(coords_yx) == 0:
                continue
            y0, x0 = coords_yx.min(axis=0)
            y1, x1 = coords_yx.max(axis=0)
            shape_kind = "circle" if (
                i < len(shapes_layer.shape_type) and shapes_layer.shape_type[i] == "ellipse"
            ) else "rectangle"
            if shape_kind == "circle":
                cx, cy = (x0 + x1) / 2 - ox, (y0 + y1) / 2 - oy
                r = max(x1 - x0, y1 - y0) / 2
                coords = (cx, cy, r, 0)
            else:
                coords = (x0 - ox, y0 - oy, x1 - ox, y1 - oy)

            start_item = self.highlight_table.item(i, 2) if i < self.highlight_table.rowCount() else None
            end_item = self.highlight_table.item(i, 3) if i < self.highlight_table.rowCount() else None
            try:
                start = int(start_item.text()) if start_item and start_item.text().strip() else 0
                end_raw = int(end_item.text()) if end_item and end_item.text().strip() else -1
            except ValueError:
                raise ValueError(f"Highlight row {i}: start/end frame must be integers.")
            end = None if end_raw < 0 else end_raw
            regions.append(HighlightRegion(shape=shape_kind, coords=coords, frame_start=start, frame_end=end))
        return regions

    # ---- crop ------------------------------------------------------------------

    def _on_add_crop_roi_layer(self) -> None:
        name = "crop_region"
        suffix = 1
        while name in self.viewer.layers:
            suffix += 1
            name = f"crop_region_{suffix}"
        shapes_layer = self.viewer.add_shapes(
            name=name, shape_type="rectangle", edge_color="cyan", face_color="transparent", edge_width=3,
        )
        shapes_layer.mode = "add_rectangle"
        self._refresh_layer_list()
        self.crop_layer_combo.setCurrentText(name)

    def _on_create_crop(self) -> None:
        base_stack = self._active_stack()
        if base_stack is None:
            QMessageBox.warning(self, "No stack", "Select or merge a working stack to crop from first.")
            return
        layer_name = self.crop_layer_combo.currentText()
        if not layer_name or layer_name not in self.viewer.layers:
            QMessageBox.warning(self, "No crop rectangle", "Add a crop-region shapes layer and draw a rectangle first.")
            return
        shapes_layer = self.viewer.layers[layer_name]
        if len(shapes_layer.data) == 0:
            QMessageBox.warning(self, "No crop rectangle", "Draw a rectangle in the crop layer first.")
            return

        coords_yx = shapes_layer.data[0]
        y0, x0 = coords_yx.min(axis=0)
        y1, x1 = coords_yx.max(axis=0)
        base_oy, base_ox = self._active_origin()
        y0i, x0i = max(0, int(round(y0))), max(0, int(round(x0)))
        y1i, x1i = int(round(y1)), int(round(x1))
        cropped = np.ascontiguousarray(base_stack[:, y0i:y1i, x0i:x1i])
        if cropped.shape[1] == 0 or cropped.shape[2] == 0:
            QMessageBox.warning(self, "Empty crop", "The crop rectangle doesn't overlap the image.")
            return

        name = self.crop_name_edit.text().strip() or f"crop {len(self._working_stacks) + 1}"
        new_origin = (base_oy + y0i, base_ox + x0i)
        self._register_working_stack(name, cropped, origin=new_origin)
        self._schedule_preview()

    # ---- contrast ---------------------------------------------------------------

    def _on_contrast_autofill(self) -> None:
        stack = self._active_stack()
        if stack is None:
            return
        lo, hi = np.percentile(stack, (0.5, 99.5))
        self.contrast_min.setValue(float(lo))
        self.contrast_max.setValue(float(hi))
        self._schedule_preview()

    # ---- config assembly --------------------------------------------------------

    def _build_config(
        self,
        phases_override: list[Phase] | None = None,
        pixel_size_override: float | None = None,
        frame_interval_override: float | None = None,
        origin: tuple[float, float] = (0.0, 0.0),
    ) -> AnnotationConfig:
        phases = phases_override if phases_override is not None else self._phases
        pixel_size = pixel_size_override if pixel_size_override is not None else self.pixel_size_spin.value()
        frame_interval = (
            frame_interval_override if frame_interval_override is not None else self.frame_interval_spin.value()
        )

        if self.contrast_mode.currentIndex() == 1:
            contrast_limits = (self.contrast_min.value(), self.contrast_max.value())
            percentile_clip = (0.0, 100.0)
        else:
            contrast_limits = None
            percentile_clip = (self.contrast_pct_low.value(), self.contrast_pct_high.value())

        regions = self._highlight_regions_from_ui(origin)

        return AnnotationConfig(
            timestamp=TimestampConfig(
                enabled=self.ts_enabled.isChecked(),
                frame_interval_s=frame_interval,
                fmt=self.ts_format.currentText(),
                corner=self.ts_corner.currentText(),
                offset_px=(self.ts_offset_x.value(), self.ts_offset_y.value()),
                font_scale=self.ts_font_scale.value(),
                color=self.ts_color.bgr(),
            ),
            scale_bar=ScaleBarConfig(
                enabled=self.sb_enabled.isChecked(),
                pixel_size_um=pixel_size,
                length_um=self.sb_length.value(),
                corner=self.sb_corner.currentText(),
                offset_px=(self.sb_offset_x.value(), self.sb_offset_y.value()),
                font_scale=self.sb_font_scale.value(),
                color=self.sb_color.bgr(),
            ),
            condition_label=TextLabelConfig(
                enabled=self.cond_enabled.isChecked(),
                text=self.cond_text.text(),
                corner=self.cond_corner.currentText(),
                offset_px=(self.cond_offset_x.value(), self.cond_offset_y.value()),
                font_scale=self.cond_font_scale.value(),
                color=self.cond_color.bgr(),
            ),
            phase_label=PhaseLabelConfig(
                enabled=self.phase_enabled.isChecked(),
                phases=phases,
                corner=self.phase_corner.currentText(),
                offset_px=(self.phase_offset_x.value(), self.phase_offset_y.value()),
                font_scale=self.phase_font_scale.value(),
                color=self.phase_color.bgr(),
            ),
            highlight=HighlightConfig(
                enabled=self.marker_enabled.isChecked(),
                regions=regions,
                thickness=self.marker_thickness.value(),
                color=self.marker_color.bgr(),
            ),
            percentile_clip=percentile_clip,
            contrast_limits=contrast_limits,
        )

    def _annotated_full_stack(self) -> np.ndarray | None:
        stack = self._active_stack()
        if stack is None:
            QMessageBox.warning(self, "No stack", "Merge phases or select a single image layer first.")
            return None
        try:
            cfg = self._build_config(origin=self._active_origin())
        except ValueError as e:
            QMessageBox.warning(self, "Configuration error", str(e))
            return None
        return annotate_stack(stack, cfg)

    def _refresh_live_preview(self) -> None:
        stack = self._active_stack()
        if stack is None:
            return
        frame_idx = min(self.preview_frame_spin.value(), stack.shape[0] - 1)
        try:
            cfg = self._build_config(origin=self._active_origin())
        except ValueError:
            return  # e.g. bad frame-range text mid-edit; just skip silently
        frame_bgr = annotate_frame(stack[frame_idx], frame_idx, cfg)
        frame_rgb = frame_bgr[..., ::-1]
        if LIVE_PREVIEW_LAYER_NAME in self.viewer.layers:
            self.viewer.layers[LIVE_PREVIEW_LAYER_NAME].data = frame_rgb
        else:
            self.viewer.add_image(frame_rgb, name=LIVE_PREVIEW_LAYER_NAME, rgb=True)

    def _on_bake_full_preview(self) -> None:
        annotated = self._annotated_full_stack()
        if annotated is None:
            return
        rgb = annotated[..., ::-1]  # BGR -> RGB for napari display
        if FULL_PREVIEW_LAYER_NAME in self.viewer.layers:
            self.viewer.layers[FULL_PREVIEW_LAYER_NAME].data = rgb
        else:
            self.viewer.add_image(rgb, name=FULL_PREVIEW_LAYER_NAME, rgb=True)

    def _on_export(self) -> None:
        annotated = self._annotated_full_stack()
        if annotated is None:
            return

        kind, ext = EXPORT_FORMATS[self.export_format_combo.currentText()]
        if kind == "video":
            path, _ = QFileDialog.getSaveFileName(self, "Export video", f"annotated{ext}", f"Video (*{ext})")
            if not path:
                return
            if not path.lower().endswith(ext):
                path += ext
            out = write_video(annotated, path, fps=self.fps_spin.value())
        elif kind == "tiff":
            path, _ = QFileDialog.getSaveFileName(self, "Export TIFF stack", "annotated.tif", "TIFF (*.tif *.tiff)")
            if not path:
                return
            out = write_tiff_stack(annotated, path)
        else:  # image sequence
            directory = QFileDialog.getExistingDirectory(self, "Choose output folder for image sequence")
            if not directory:
                return
            out = write_image_sequence(annotated, directory)

        QMessageBox.information(self, "Export complete", f"Saved to:\n{out}")

    # ---- batch processing ---------------------------------------------------------

    def _on_select_batch_files(self) -> None:
        names = [n.strip() for n in self.batch_phase_names_edit.text().split(",") if n.strip()]
        if not names:
            QMessageBox.warning(self, "No phase names", "Enter at least one phase name first.")
            return
        batch_files: dict[str, list[str]] = {}
        for name in names:
            paths, _ = QFileDialog.getOpenFileNames(
                self, f"Select files for phase '{name}' (in item order)", "", "TIFF (*.tif *.tiff)"
            )
            if not paths:
                self.batch_files_status.setText(f"Cancelled — no files chosen for phase '{name}'.")
                return
            batch_files[name] = paths
        self._batch_phase_files = batch_files
        counts = {n: len(f) for n, f in batch_files.items()}
        if len(set(counts.values())) > 1:
            self.batch_files_status.setText(f"Mismatched file counts per phase: {counts}. Fix before running.")
        else:
            n_items = next(iter(counts.values()))
            self.batch_files_status.setText(f"{n_items} item(s) ready across {len(names)} phase(s): {counts}")

    def _on_run_batch(self) -> None:
        if not self._batch_phase_files:
            QMessageBox.warning(self, "No batch files", "Click 'Select files for each phase...' first.")
            return
        names = list(self._batch_phase_files.keys())
        counts = {n: len(f) for n, f in self._batch_phase_files.items()}
        if len(set(counts.values())) != 1:
            QMessageBox.warning(self, "Mismatched files", f"Phase file counts don't match: {counts}")
            return
        n_items = next(iter(counts.values()))

        kind, ext = EXPORT_FORMATS[self.export_format_combo.currentText()]
        out_root = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not out_root:
            return
        out_root_path = Path(out_root)

        crop_bbox = None
        if self.batch_apply_crop.isChecked():
            layer_name = self.crop_layer_combo.currentText()
            if layer_name and layer_name in self.viewer.layers and len(self.viewer.layers[layer_name].data) > 0:
                coords_yx = self.viewer.layers[layer_name].data[0]
                y0, x0 = coords_yx.min(axis=0)
                y1, x1 = coords_yx.max(axis=0)
                crop_bbox = (max(0, int(round(y0))), max(0, int(round(x0))), int(round(y1)), int(round(x1)))

        errors = []
        for i in range(n_items):
            stem = None
            self.batch_progress.setText(f"Processing item {i + 1}/{n_items}...")
            QApplication.processEvents()
            try:
                item_stacks = []
                item_pixel_size = None
                item_frame_interval = None
                for name in names:
                    path = self._batch_phase_files[name][i]
                    stack, meta = load_stack(path)
                    item_stacks.append(stack)
                    if item_pixel_size is None and meta.pixel_size_um:
                        item_pixel_size = meta.pixel_size_um
                    if item_frame_interval is None and meta.frame_interval_s:
                        item_frame_interval = meta.frame_interval_s
                    if stem is None:
                        stem = Path(path).stem

                result = merge_phases(item_stacks, names)
                item_stack = result.stack
                origin = (0.0, 0.0)
                if crop_bbox is not None:
                    y0, x0, y1, x1 = crop_bbox
                    item_stack = item_stack[:, y0:y1, x0:x1]
                    origin = (float(y0), float(x0))
                    if item_stack.shape[1] == 0 or item_stack.shape[2] == 0:
                        raise ValueError("crop rectangle is out of bounds for this item's image size")

                cfg = self._build_config(
                    phases_override=result.phases,
                    pixel_size_override=item_pixel_size,
                    frame_interval_override=item_frame_interval,
                    origin=origin,
                )
                annotated = annotate_stack(item_stack, cfg)

                out_name = f"{stem}_annotated"
                if kind == "video":
                    write_video(annotated, out_root_path / (out_name + ext), fps=self.fps_spin.value())
                elif kind == "tiff":
                    write_tiff_stack(annotated, out_root_path / (out_name + ".tif"))
                else:
                    write_image_sequence(annotated, out_root_path / out_name)
            except Exception as e:
                errors.append(f"item {i + 1} ({stem or '?'}): {e}")

        summary = f"Batch done: {n_items - len(errors)}/{n_items} succeeded."
        if errors:
            summary += "\nErrors:\n" + "\n".join(errors)
        self.batch_progress.setText(summary)
        QMessageBox.information(self, "Batch export complete", summary)
