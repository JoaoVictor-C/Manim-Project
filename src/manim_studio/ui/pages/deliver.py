"""The Deliver page (P6b.5, ADR 0041, ADR 0042; Lumen, ADR 0063): destinations, render settings, a queue.

Three cards. At the left, **where is it going?**: large selectable destinations (a video for the web, a quick
draft, Full HD, an archive master - each starts the form from a size and a quality - and the Python scene).
In the middle, the shared viewer beside (in a narrow window, over) the chosen destination's **settings**
(file, size, frame rate, range, quality, subtitles, with estimate tiles) and *Render video* / *Add to queue*;
for the Python destination, the readable/exact scene with *Save as...*. At the right, the **queue** of
exports, run one after another through ``ExportJob`` (each from the project as it was when it was added): the
running job has a progress ring and the time left, the finished ones a check. The settings are the page's own
state, not the project's; they start from the project's canvas.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.engine import adapter
from ...core.engine.python_export import PythonExport, class_name, to_python
from ...core.model.schema import Project
from ...logging_config import get_logger
from ...render.options import (
    DEFAULT_CRF,
    HEIGHT_PRESETS,
    QUALITIES,
    OptionsError,
    RenderOptions,
    apply_options,
    frame_window,
    size_for_height,
)
from ..deliver.export_job import ExportJob
from ..deliver.queue_view import (
    ROW_HEIGHT,
    BlankTextDelegate,
    DestinationCard,
    EstimateTile,
    JobRow,
    ProgressRing,
    SlimBar,
)
from ..deliver.render_queue import QueueJob, RenderQueue, Status
from ..style import icons, theme
from ..style.card import Card, Chip, gutter_splitter, page_margins
from . import Page, Shared

log = get_logger(__name__)

PYTHON_DELAY_MS = 400  # the preview follows edits this long after the last one
SUBTITLE_LABELS = (
    ("burn", "Burned into the video (and an .srt beside it)"),
    ("srt", "An .srt beside the video only"),
    ("none", "None"),
)
ENCODER_LABELS = (
    ("auto", "Automatic"),
    ("gpu", "Graphics card (NVENC)"),
    ("cpu", "Processor (x264)"),
)
PROCESS_LABELS = (
    (None, "Automatic"),
    (1, "1 (this process alone)"),
    (2, "2"),
    (3, "3"),
    (4, "4"),
    (6, "6"),
    (8, "8"),
)
STATUS_TEXT = {
    Status.QUEUED: "Queued",
    Status.DONE: "Done",
    Status.CANCELLED: "Cancelled",
}


def open_folder(path: Path) -> None:
    """Show the folder holding ``path`` in the system's file manager."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def default_output(path: Path | None, folder: Path | None = None) -> Path:
    """Next to the project in ``out/``; a never-saved one in ``folder`` (GP)."""
    name = path.stem if path else "untitled"
    return (path.parent if path else folder or Path.cwd()) / "out" / f"{name}.mp4"


class Destination:
    """A card of the left column: what to make, and the settings it starts the form from."""

    def __init__(
        self,
        key: str,
        title: str,
        summary: str,
        icon: str,
        gradient: tuple[str, str] | None,
        size: str | None = None,
        crf: int | None = None,
    ) -> None:
        self.key, self.title, self.summary, self.icon, self.gradient = key, title, summary, icon, gradient
        self.size, self.crf = size, crf  # None: leave the form as it is


DESTINATIONS = (
    Destination(
        "web",
        "Video for the web",
        "Project size, MP4 (H.264)",
        "film",
        ("danger", "warning"),
        "project",
        DEFAULT_CRF,
    ),
    Destination(
        "draft",
        "Quick draft",
        "480p, small and fast",
        "effects",
        ("accent_2", "accent"),
        "480p",
        QUALITIES["Draft"],
    ),
    Destination("hd", "Full HD", "1080p, high quality", "play", ("key", "warning"), "1080p", DEFAULT_CRF),
    Destination(
        "master",
        "Archive master",
        "2160p, the highest quality",
        "export",
        ("morph", "accent"),
        "2160p",
        QUALITIES["Archive"],
    ),
    Destination("python", "Manim Python", "A scene you can run with manim", "python", None),
)
BITS_PER_PIXEL = 0.05  # at crf 23: a rough figure for the size estimate (simple animation compresses well)


def clock(seconds: float) -> str:
    """0:07 or 1:05:09 - a duration for people."""
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def megabytes(size: float) -> str:
    if size < 1e6:
        return f"{max(1, round(size / 1e3))} KB"
    return f"{size / 1e6:.1f} MB" if size < 1e8 else f"{round(size / 1e6)} MB"


class _Reflow(QObject):
    """Puts a splitter's two parts side by side when there is room (the mock-up: the viewer at the left, the
    settings at the right) and one over the other when there is not."""

    WIDE = 880

    def __init__(self, splitter) -> None:
        super().__init__(splitter)
        self.splitter = splitter
        splitter.installEventFilter(self)

    def reflow(self, force: bool = False) -> None:
        splitter = self.splitter
        wide = splitter.width() >= self.WIDE
        horizontal = splitter.orientation() == Qt.Orientation.Horizontal
        if wide == horizontal and not force:
            return
        splitter.setOrientation(Qt.Orientation.Horizontal if wide else Qt.Orientation.Vertical)
        extent = max(splitter.width() if wide else splitter.height(), 700)
        first = 0.38 if wide else 0.42
        splitter.setSizes([int(extent * first), int(extent * (1 - first))])

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.splitter and event.type() == QEvent.Type.Resize:
            self.reflow()
        return False


class DeliverPage(Page):
    name = "deliver"
    title = "Deliver"
    icon = "deliver"
    tooltip = "Export the video (size, range, quality, a queue of renders) and the Python scene (Ctrl+5)"

    # -- building ---------------------------------------------------------------------

    def build(self) -> QWidget:
        self.queue = RenderQueue()
        self._export: ExportJob | None = None  # the running export, for queue.current
        self._rows: dict[int, QTreeWidgetItem] = {}
        self._row_widgets: dict[int, JobRow] = {}
        self._first_progress: tuple[float, int] | None = None
        self._pixel_rate: float | None = (
            None  # pixels x frames rendered per second, from the last finished job
        )
        self._default_output: str = ""
        self._fps_touched = False
        self._markers_chosen = False  # until the user picks, the range is first marker to last
        self._seen = None
        self._duration: float | None = None
        self._python_stale = True
        self._destination = DESTINATIONS[0]
        self._last: QueueJob | None = None  # what the queue panel shows once nothing is running
        self._python_timer = QTimer(singleShot=True, interval=PYTHON_DELAY_MS)
        self._python_timer.timeout.connect(self.refresh_python)

        self.destinations: dict[str, DestinationCard] = {}
        self.destination_group = QButtonGroup(self.window)
        self.destination_card = self._build_destinations()
        self.settings_card = self._build_settings()
        self.queue_card = self._build_queue()

        self.outer = gutter_splitter(Qt.Orientation.Horizontal)  # destinations | viewer, settings | queue
        self.centre = gutter_splitter(Qt.Orientation.Horizontal)
        self.centre.addWidget(self.settings_card)
        self._centre_watch = _Reflow(self.centre)
        self.outer.addWidget(self.destination_card)
        self.outer.addWidget(self.centre)
        self.outer.addWidget(self.queue_card)
        self.outer.setStretchFactor(0, 0)
        self.outer.setStretchFactor(1, 1)
        self.outer.setStretchFactor(2, 0)
        self.centre.setStretchFactor(0, 1)
        self.centre.setStretchFactor(1, 1)
        self.right = self.queue_card  # what the old three-part column was called
        root = QWidget()
        layout = QHBoxLayout(root)
        page_margins(layout)
        layout.addWidget(self.outer)

        document = self.window.document
        document.reset.connect(self._on_reset)
        document.changed.connect(self._on_changed)
        self._on_reset(document.project)
        self.choose_destination("web", apply=False)
        return root

    def _build_destinations(self) -> Card:
        card = Card("Where is it going?")
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(theme.GUTTER)
        for destination in DESTINATIONS:
            button = DestinationCard(
                destination.key,
                destination.title,
                destination.summary,
                destination.icon,
                destination.gradient,
            )
            button.clicked.connect(lambda _=False, key=destination.key: self.choose_destination(key))
            self.destination_group.addButton(button)
            self.destinations[destination.key] = button
            column.addWidget(button)
        column.addStretch(1)
        card.set_body(self._scrolling(body))
        card.setMinimumWidth(240)
        return card

    @staticmethod
    def _scrolling(content: QWidget) -> QScrollArea:
        """``content`` in a frameless, transparent scroll area: a small window scrolls, nothing squeezes."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        return scroll

    def _build_settings(self) -> Card:
        card = Card("Video for the web")
        self.preset_chip = Chip("Preset")
        self.preset_chip.setFixedHeight(22)
        card.add_title_widget(self.preset_chip)
        self.settings_stack = QStackedWidget()
        self.settings_stack.addWidget(self._build_video_settings())
        self.settings_stack.addWidget(self._build_python())
        card.set_body(self.settings_stack)
        return card

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "muted")
        return label

    def _build_video_settings(self) -> QWidget:
        self.tile_length = EstimateTile("Length")
        self.tile_time = EstimateTile("Render time")
        self.tile_size = EstimateTile("File size")
        self.tile_sound = EstimateTile("Sound")
        tiles = QGridLayout()
        tiles.setSpacing(10)
        for index, tile in enumerate((self.tile_length, self.tile_time, self.tile_size, self.tile_sound)):
            tiles.addWidget(tile, index // 2, index % 2)
        tiles.setColumnStretch(0, 1)
        tiles.setColumnStretch(1, 1)

        self.path = QLineEdit()
        self.path.setPlaceholderText("Where to save the video")
        browse = QPushButton("Browse...")
        browse.setIcon(icons.icon("folder"))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.setSpacing(theme.GUTTER)
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)

        self.size = QComboBox()
        self.size.addItem("", "project")
        for label in HEIGHT_PRESETS:
            self.size.addItem("", label)
        self.size.addItem("Custom", "custom")
        self.width = QSpinBox(minimum=2, maximum=16384, singleStep=2)
        self.height = QSpinBox(minimum=2, maximum=16384, singleStep=2)
        size_row = QHBoxLayout()
        size_row.setSpacing(theme.GUTTER)
        size_row.addWidget(self.size, 1)
        size_row.addWidget(self.width)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.height)
        self.size.currentIndexChanged.connect(self._on_size_choice)
        self.width.valueChanged.connect(self._refresh_summary)
        self.height.valueChanged.connect(self._refresh_summary)

        self.fps = QSpinBox(minimum=1, maximum=240, suffix=" fps")
        self.fps.valueChanged.connect(self._on_fps_edited)

        self.range = QComboBox()
        for label, key in (
            ("Whole scene", "whole"),
            ("From - to", "times"),
            ("Between two markers", "markers"),
        ):
            self.range.addItem(label, key)
        self.range.currentIndexChanged.connect(self._on_range_choice)
        self.start = QDoubleSpinBox(decimals=3, singleStep=0.1, suffix=" s")
        self.end = QDoubleSpinBox(decimals=3, singleStep=0.1, suffix=" s")
        times_row = QHBoxLayout()
        times_row.setSpacing(theme.GUTTER)
        times_row.addWidget(self.start, 1)
        times_row.addWidget(QLabel("to"))
        times_row.addWidget(self.end, 1)
        self.marker_from, self.marker_to = QComboBox(), QComboBox()
        markers_row = QHBoxLayout()
        markers_row.setSpacing(theme.GUTTER)
        markers_row.addWidget(self.marker_from, 1)
        markers_row.addWidget(QLabel("to"))
        markers_row.addWidget(self.marker_to, 1)
        for widget in (self.start, self.end):
            widget.valueChanged.connect(self._refresh_summary)
        for combo in (self.marker_from, self.marker_to):
            combo.currentIndexChanged.connect(self._refresh_summary)
            combo.activated.connect(self._on_marker_chosen)

        self.quality = QComboBox()
        for label, crf in QUALITIES.items():
            self.quality.addItem(f"{label} (crf {crf})", crf)
        self.quality.setCurrentIndex(self.quality.findData(DEFAULT_CRF))
        self.quality.currentIndexChanged.connect(self._refresh_summary)

        self.subtitles = QComboBox()
        for key, label in SUBTITLE_LABELS:
            self.subtitles.addItem(label, key)

        self.encoder = QComboBox()
        for key, label in ENCODER_LABELS:
            self.encoder.addItem(label, key)
        self.encoder.setToolTip(
            "What turns the pictures into H.264. Automatic uses the graphics card's encoder (NVIDIA NVENC) "
            "for longer exports when there is one, else the processor (x264). The pictures are drawn on the "
            "processor either way, so the video looks the same; the card is faster and leaves the cores free."
        )
        self.processes = QComboBox()
        for count, label in PROCESS_LABELS:
            self.processes.addItem(label, count)
        self.processes.setToolTip(
            "How many processes draw frames (and render code layers) side by side. Automatic picks from "
            "your cores and free memory, and keeps short or light exports in one. Each takes about 400 MB."
        )

        form = QGridLayout()
        form.setHorizontalSpacing(theme.GUTTER * 2)
        form.setVerticalSpacing(4)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        form.addWidget(self._label("Quality"), 0, 0)
        form.addWidget(self.quality, 1, 0)
        form.addWidget(self._label("Frame rate"), 0, 1)
        form.addWidget(self.fps, 1, 1)
        form.addWidget(self._label("Size"), 2, 0, 1, 2)
        form.addLayout(size_row, 3, 0, 1, 2)
        form.addWidget(self._label("Range"), 4, 0, 1, 2)
        form.addWidget(self.range, 5, 0, 1, 2)
        form.addLayout(times_row, 6, 0, 1, 2)
        form.addLayout(markers_row, 7, 0, 1, 2)
        form.addWidget(self._label("Subtitles"), 8, 0, 1, 2)
        form.addWidget(self.subtitles, 9, 0, 1, 2)
        form.addWidget(self._label("Encoder"), 10, 0)
        form.addWidget(self.encoder, 11, 0)
        form.addWidget(self._label("Render processes"), 10, 1)
        form.addWidget(self.processes, 11, 1)
        form.addWidget(self._label("Save to"), 12, 0, 1, 2)
        form.addLayout(path_row, 13, 0, 1, 2)

        self.summary = QLabel()
        self.summary.setProperty("role", "readout")
        self.summary.setWordWrap(True)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("role", "error")
        self.add_button = QPushButton("Add to queue")
        self.add_button.clicked.connect(self.add_to_queue)
        self.render_button = QPushButton(icons.icon("export"), "Render video")
        self.render_button.setProperty("role", "primary")
        self.render_button.setDefault(True)
        self.render_button.setToolTip("Add this export to the queue and start the queue")
        self.render_button.clicked.connect(self.render_now)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.render_button, 1)
        actions.addWidget(self.add_button)
        note = QLabel("Rendering never changes your project and keeps the editor usable.")
        note.setProperty("role", "hint")
        note.setWordWrap(True)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(20, 16, 20, 16)
        column.setSpacing(14)
        column.addLayout(tiles)
        column.addLayout(form)
        column.addWidget(self.summary)
        column.addWidget(self.error)
        column.addLayout(actions)
        column.addWidget(note)
        column.addStretch(1)
        return self._scrolling(content)

    def _build_queue(self) -> Card:
        card = Card("Queue")
        self.queue_chip = Chip("", "accent")
        self.queue_chip.setFixedHeight(22)
        self.queue_chip.setVisible(False)
        card.add_title_widget(self.queue_chip)
        self.clear_button = QPushButton("Clear finished")
        self.clear_button.setProperty("role", "ghost")
        self.clear_button.clicked.connect(self.clear_finished)
        card.add_action(self.clear_button)

        self.now = QFrame()
        self.now.setObjectName("queueNow")
        self.now.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.now_ring = ProgressRing(44)
        self.now_title = QLabel("Nothing is rendering")
        self.now_title.setProperty("role", "rowName")
        self.queue_status = QLabel("Add an export, then start the queue.")
        self.queue_status.setWordWrap(True)
        self.queue_status.setProperty("role", "rowDetail")
        self.bar = SlimBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addWidget(self.now_title)
        words.addWidget(self.queue_status)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(self.now_ring)
        head.addLayout(words, 1)
        inner = QVBoxLayout(self.now)
        inner.setContentsMargins(14, 14, 14, 14)
        inner.setSpacing(12)
        inner.addLayout(head)
        inner.addWidget(self.bar)

        self.tree = QTreeWidget()
        self.tree.setObjectName("queueTree")
        self.tree.setHeaderLabels(["Video", "Render", "Status"])
        self.tree.setHeaderHidden(True)
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegate(BlankTextDelegate(self.tree))
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setMinimumHeight(90)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self.open_folder())

        self.start_button = QPushButton("Start queue")
        self.start_button.setProperty("role", "primary")
        self.cancel_button = QPushButton("Cancel")
        self.remove_button = QPushButton("Remove")
        self.open_button = QPushButton(icons.icon("folder"), "")
        self.open_button.setToolTip("Open the folder of the selected video")
        self.open_button.setAccessibleName("Open folder")
        self.start_button.clicked.connect(self.start_queue)
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.remove_button.clicked.connect(self.remove_selected)
        self.open_button.clicked.connect(self.open_folder)
        buttons = QHBoxLayout()
        buttons.setSpacing(theme.GUTTER)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)

        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(10)
        column.addWidget(self.now)
        column.addWidget(self.tree, 1)
        column.addLayout(buttons)
        card.set_body(body)
        card.setMinimumWidth(300)
        self._update_buttons()
        return card

    def _build_python(self) -> QWidget:
        self.python_kind = QLabel()
        self.python_kind.setProperty("role", "section")
        self.python_kind.setWordWrap(True)
        self.python_reasons = QLabel()
        self.python_reasons.setWordWrap(True)
        self.python_reasons.setProperty("role", "muted")
        self.python_code = QPlainTextEdit()
        self.python_code.setReadOnly(True)
        self.python_code.setFont(theme.mono_font())
        self.python_code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.python_code.setMinimumHeight(90)
        self.python_save = QPushButton("Save as...")
        self.python_save.setIcon(icons.icon("save"))
        self.python_save.clicked.connect(self.save_python)
        row = QHBoxLayout()
        row.addWidget(self.python_kind, 1)
        row.addWidget(self.python_save)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addLayout(row)
        layout.addWidget(self.python_reasons)
        layout.addWidget(self.python_code, 1)
        return body

    # -- destinations ------------------------------------------------------------------------

    def choose_destination(self, key: str, *, apply: bool = True) -> None:
        """Pick a card: it starts the form from its size and quality (the Python card shows the scene)."""
        destination = next(d for d in DESTINATIONS if d.key == key)
        self._destination = destination
        self.destinations[key].setChecked(True)
        self.settings_card.set_title(destination.title)
        python = key == "python"
        self.settings_stack.setCurrentIndex(1 if python else 0)
        self.preset_chip.setVisible(not python)
        if python:
            if self._python_stale:
                self.refresh_python()
            return
        if apply and destination.size is not None:
            index = self.size.findData(destination.size)
            if index >= 0:
                self.size.setCurrentIndex(index)
            if destination.crf is not None:
                self.quality.setCurrentIndex(self.quality.findData(destination.crf))
        self._refresh_summary()

    def _matches_destination(self) -> bool:
        destination = self._destination
        if destination.size is None:
            return True
        return self.size.currentData() == destination.size and self.quality.currentData() == destination.crf

    # -- page lifecycle -----------------------------------------------------------------

    def place(self, shared: Shared) -> None:
        self.centre.insertWidget(0, shared.viewer)
        self._centre_watch.reflow()

    def on_show(self) -> None:
        if not getattr(self, "_sized", False):  # first show: the side cards at their natural widths
            self._sized = True
            total = max(self.outer.width(), 1200)
            self.outer.setSizes([280, total - 280 - 360, 360])
            self._centre_watch.reflow(force=True)
        self._follow_default_output()
        if self._python_stale:
            self.refresh_python()

    def on_hide(self) -> None:
        self._python_timer.stop()

    @property
    def busy(self) -> bool:
        """An export of the queue is rendering (the window asks before closing)."""
        return self.queue.busy

    def cancel_all(self) -> None:
        """Stop the running export and the rest of the queue (the window is closing)."""
        if self.queue.cancel_all() and self._export is not None:
            self._export.cancel()
            self._export = None
        for job in self.queue.jobs:
            self._update_row(job)
        self._update_buttons()

    # -- the project ----------------------------------------------------------------------

    def _canvas(self):
        return self.window.document.project.canvas

    def _on_reset(self, project: Project) -> None:
        """A project was opened: the settings start from its canvas again."""
        self._fps_touched = False
        self._markers_chosen = False
        self._seen = None
        self.size.blockSignals(True)
        self.size.setCurrentIndex(0)
        self.size.blockSignals(False)
        self._refresh_sizes()
        self._set_fps(project.canvas.fps)
        self.range.setCurrentIndex(0)
        self.quality.setCurrentIndex(self.quality.findData(DEFAULT_CRF))
        self.subtitles.setCurrentIndex(
            self.subtitles.findData("burn" if project.subtitle_style.burn_in else "srt")
        )
        self._follow_default_output(force=True)
        self.start.setValue(0.0)
        self._duration = None
        self._refresh_project_fields(project)
        self.error.clear()
        self._python_changed()

    def _on_changed(self, project: Project, *_rest) -> None:
        self._refresh_sizes()
        if not self._fps_touched:
            self._set_fps(project.canvas.fps)
        self._refresh_project_fields(project)
        self._python_changed()

    def _refresh_project_fields(self, project: Project) -> None:
        """The range, markers and subtitle choice follow the project's duration, markers and cues."""
        duration, markers = project.canvas.duration, tuple(project.markers)
        seen = (duration, markers, bool(project.subtitles), project.canvas.width_px, project.canvas.height_px)
        if seen == self._seen:  # a drag changes the document often; most changes touch none of this
            return
        self._seen = seen
        for spin in (self.start, self.end):
            spin.blockSignals(True)
            spin.setRange(0.0, duration)
            spin.blockSignals(False)
        if self._duration is None or abs(self.end.value() - self._duration) < 1e-9:
            self.end.setValue(duration)  # the end follows the scene's end until it is set
        self._duration = duration
        for combo, last in ((self.marker_from, False), (self.marker_to, True)):
            before = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for marker in markers:
                combo.addItem(f"{marker.name or marker.id} ({marker.t:.2f} s)", marker.t)
            index = combo.findData(before) if before is not None and self._markers_chosen else -1
            combo.setCurrentIndex(index if index >= 0 else (combo.count() - 1 if last else 0))
            combo.blockSignals(False)
        self.subtitles.setEnabled(bool(project.subtitles))
        self.add_button.setEnabled(self.window.project is not None)
        self._on_range_choice()
        self._on_size_choice()

    def _refresh_sizes(self) -> None:
        canvas = self._canvas()
        self.size.setItemText(0, f"Project canvas ({canvas.width_px}x{canvas.height_px})")
        for index in range(1, self.size.count() - 1):
            width, height = size_for_height(canvas, HEIGHT_PRESETS[self.size.itemData(index)])
            self.size.setItemText(index, f"{self.size.itemData(index)} ({width}x{height})")

    def _set_fps(self, value: int) -> None:
        self.fps.blockSignals(True)
        self.fps.setValue(value)
        self.fps.blockSignals(False)
        self._refresh_summary()

    def _on_fps_edited(self, _value: int) -> None:
        self._fps_touched = True
        self._refresh_summary()

    def _follow_default_output(self, force: bool = False) -> None:
        """The path field offers ``out/<project>.mp4`` until the user types another."""
        new = str(default_output(self.window.path, self.window.default_folder()))
        if force or not self.path.text() or self.path.text() == self._default_output:
            self.path.setText(new)
        self._default_output = new

    # -- the settings -----------------------------------------------------------------------

    def _on_size_choice(self, *_args) -> None:
        key = self.size.currentData()
        canvas = self._canvas()
        if key == "project":
            width, height = canvas.width_px, canvas.height_px
        elif key == "custom":
            width, height = self.width.value(), self.height.value()
        else:
            width, height = size_for_height(canvas, HEIGHT_PRESETS[key])
        for spin, value in ((self.width, width), (self.height, height)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.width.setEnabled(key == "custom")
        self.height.setEnabled(key == "custom")
        self._refresh_summary()

    def _on_range_choice(self, *_args) -> None:
        mode = self.range.currentData()
        self.start.setEnabled(mode == "times")
        self.end.setEnabled(mode == "times")
        self.marker_from.setEnabled(mode == "markers")
        self.marker_to.setEnabled(mode == "markers")
        self._refresh_summary()

    def _on_marker_chosen(self, _index: int) -> None:
        self._markers_chosen = True

    def options(self) -> RenderOptions:
        """The options the form describes (OptionsError when they cannot be rendered)."""
        canvas = self._canvas()
        key = self.size.currentData()
        if key == "project":
            width = height = None
        else:
            width, height = self.width.value(), self.height.value()
        fps = self.fps.value() if self.fps.value() != canvas.fps else None
        start, end = 0.0, None
        mode = self.range.currentData()
        if mode == "times":
            start, end = self.start.value(), self.end.value()
        elif mode == "markers":
            a, b = self.marker_from.currentData(), self.marker_to.currentData()
            if a is None or b is None or self.marker_from.count() < 2:
                raise OptionsError("Add two markers to the timeline (M) to export between them.")
            if abs(a - b) < 1e-9:
                raise OptionsError("Choose two different markers.")
            start, end = min(a, b), max(a, b)
        return RenderOptions(
            width=width,
            height=height,
            fps=fps,
            start=start,
            end=end,
            crf=self.quality.currentData(),
            subtitles=self.subtitles.currentData() if self.subtitles.isEnabled() else None,
            encoder=self.encoder.currentData(),
            jobs=self.processes.currentData(),
        )

    def _refresh_summary(self, *_args) -> None:
        """What the current settings would render, or why they cannot."""
        if not hasattr(self, "summary"):
            return
        project = self.window.document.project
        try:
            options = self.options()
            canvas = apply_options(project, options).canvas
            first, last = frame_window(canvas, options)
        except OptionsError as error:
            self.summary.setText(str(error))
            for tile in (self.tile_length, self.tile_time, self.tile_size):
                tile.set_value("-")
            return
        seconds = (last - first) / canvas.fps
        size = f"{canvas.width_px}x{canvas.height_px} at {canvas.fps} fps"
        self.summary.setText(f"{last - first} frames, {seconds:.2f} s - {size}")
        self._show_estimates(project, options, canvas, last - first)
        edited = not self._matches_destination()
        self.preset_chip.setText("Edited" if edited else "Preset")
        self.preset_chip.set_tone("accent" if edited else "neutral")

    def _show_estimates(self, project: Project, options: RenderOptions, canvas, frames: int) -> None:
        """The tiles over the form: how long the video is, a guess at the render time (from the last export of
        this session; none before) and the file size (a rough figure from the quality), and its sound."""
        seconds = frames / canvas.fps
        pixels = canvas.width_px * canvas.height_px
        self.tile_length.set_value(f"{clock(seconds)} - {frames} frames", f"{seconds:.2f} s")
        if self._pixel_rate:
            self.tile_time.set_value(
                f"about {clock(frames * pixels / self._pixel_rate)}", "From your last render"
            )
        else:
            self.tile_time.set_value("-", "Known after the first render")
        bits = BITS_PER_PIXEL * 2 ** ((23 - options.crf) / 6)
        self.tile_size.set_value(
            f"about {megabytes(frames * pixels * bits / 8)}", "A rough guess from the quality"
        )
        sounds = len(project.audio)
        self.tile_sound.set_value(f"{sounds} sound{'s' if sounds != 1 else ''}" if sounds else "None")

    def _browse(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self.widget, "Export video", self.path.text(), "MP4 video (*.mp4)"
        )
        if name:
            self.path.setText(name)

    # -- the queue ----------------------------------------------------------------------------

    def add_to_queue(self) -> QueueJob | None:
        """Queue an export of the project as it is now with the settings shown."""
        project = self.window.project
        if project is None:
            self.error.setText("Create or open a project first.")
            return None
        text = self.path.text().strip()
        if not text:
            self.error.setText("Choose where to save the video.")
            return None
        try:
            options = self.options()
            frame_window(apply_options(project, options).canvas, options)
        except OptionsError as error:
            self.error.setText(str(error))
            return None
        self.error.clear()
        trust = not self.window.trust.untrusted(project)  # fixed now, like the snapshot (ADR 0019)
        job = self.queue.add(project, options, Path(text), trust)
        self._add_row(job)
        self.queue_status.setText(f"Added {job.output.name}.")
        self._update_buttons()  # a running queue picks it up when the others are done
        return job

    def render_now(self) -> None:
        """Render video: queue this export and start the queue."""
        if self.add_to_queue() is not None:
            self.start_queue()

    def start_queue(self) -> None:
        if self.queue.start() is not None:
            self._launch(self.queue.current)

    def _launch_next(self) -> None:
        job = self.queue.advance()
        if job is not None:
            self._launch(job)
        elif not self.queue.busy:
            self._queue_idle()

    def _launch(self, job: QueueJob) -> None:
        self._first_progress = None
        export = ExportJob(
            job.project,
            job.output,
            adapter.cache_dir(),
            trust_code=job.trust,
            options=job.options,
            parent=self.widget,
        )
        export.progress.connect(lambda frame, total: self._on_progress(job, frame, total))
        export.stage.connect(lambda text: self._on_stage(job, text))
        export.finished.connect(lambda path, warning: self._on_finished(job, path, warning))
        export.failed.connect(lambda message: self._on_failed(job, message))
        self._export = export
        self.bar.setRange(0, 0)  # busy until the first frame
        self.queue_status.setText(f"Starting the renderer for {job.output.name}...")
        self._last = None
        self._update_row(job)
        self._update_buttons()
        log.info("deliver: rendering %s (%s)", job.output, job.summary)
        export.start()

    def _on_stage(self, job: QueueJob, text: str) -> None:
        """Before the first frame: what the renderer is busy with (the code layers it plays first)."""
        if job.status is Status.RENDERING and self._first_progress is None:
            self.queue_status.setText(f"{job.output.name}: {text}")
            self._status_message(f"{job.output.name}: {text}")

    def _on_progress(self, job: QueueJob, frame: int, total: int) -> None:
        if job.status is not Status.RENDERING:
            return
        now = time.monotonic()
        if self._first_progress is None:
            self._first_progress = (now, frame)
        self.queue.progress(job, frame, total)
        self.bar.setRange(0, total)
        self.bar.setValue(frame)
        text = f"Rendering {job.output.name}: frame {frame} of {total}"
        started, first = self._first_progress
        if frame > first and now > started:
            rate = (frame - first) / (now - started)
            text += f" - about {max(0.0, (total - frame) / rate):.0f} s left"
        self.queue_status.setText(text)
        self._update_row(job)
        self._show_now()
        self._status_message(text)

    def _on_finished(self, job: QueueJob, path: str, warning: str) -> None:
        if job.status is not Status.RENDERING:  # a late signal from a cancelled job
            return
        self._measure(job)
        how = f" - {self._export.how}" if self._export is not None and self._export.how else ""
        self.queue.finish(job, Path(path), warning)
        self._after_job(job, f"Exported to {path}{how}" + (f"\n{warning}" if warning else ""))

    def _measure(self, job: QueueJob) -> None:
        """Remember how fast this export went (pixels x frames per second) for the render-time estimate."""
        if self._first_progress is None:
            return
        started, first = self._first_progress
        elapsed, frames = time.monotonic() - started, job.frame - first
        if elapsed > 0.2 and frames > 0:
            canvas = apply_options(job.project, job.options).canvas
            self._pixel_rate = frames * canvas.width_px * canvas.height_px / elapsed
            self._refresh_summary()

    def _on_failed(self, job: QueueJob, message: str) -> None:
        if job.status is not Status.RENDERING:
            return
        self.queue.fail(job, message)
        self._after_job(job, f"Export failed: {message}")

    def _after_job(self, job: QueueJob, text: str) -> None:
        if self._export is not None:
            self._export.deleteLater()
            self._export = None
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if job.status is Status.DONE else 0)
        self.queue_status.setText(text)
        self._last = job
        self._update_row(job)
        self._launch_next()
        self._update_buttons()

    def _queue_idle(self) -> None:
        self._status_message("")
        self._update_buttons()

    def cancel_selected(self) -> None:
        """Cancel the selected job, or the one rendering when none is selected."""
        job = self.selected() or self.queue.current
        if job is None:
            return
        if self.queue.cancel(job) and self._export is not None:
            self._export.cancel()
            self._export = None
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            self.queue_status.setText("Cancelled. A video already at that path was left as it was.")
        self._last = job
        self._update_row(job)
        self._launch_next()
        self._update_buttons()

    def remove_selected(self) -> None:
        job = self.selected()
        if job is not None and self.queue.remove(job):
            self._drop_row(job)
            self._update_buttons()

    def clear_finished(self) -> None:
        for job in [j for j in self.queue.jobs if j.finished]:
            self.queue.remove(job)
            self._drop_row(job)
        self._update_buttons()

    def open_folder(self) -> None:
        job = self.selected()
        if job is not None and job.result is not None:
            open_folder(job.result)

    def selected(self) -> QueueJob | None:
        items = self.tree.selectedItems()
        return self.queue.get(items[0].data(0, Qt.ItemDataRole.UserRole)) if items else None

    def select(self, job: QueueJob) -> None:
        self.tree.setCurrentItem(self._rows[job.id])

    # -- the queue's rows ---------------------------------------------------------------------

    def _add_row(self, job: QueueJob) -> None:
        item = QTreeWidgetItem(self.tree)
        item.setData(0, Qt.ItemDataRole.UserRole, job.id)
        self._rows[job.id] = item
        row = JobRow()
        self._row_widgets[job.id] = row
        self.tree.setItemWidget(item, 0, row)
        item.setSizeHint(0, QSize(120, ROW_HEIGHT))
        self._update_row(job)

    def _drop_row(self, job: QueueJob) -> None:
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(self._rows.pop(job.id)))
        self._row_widgets.pop(job.id, None)
        if self._last is job:
            self._last = None

    def status_text(self, job: QueueJob) -> str:
        if job.status is Status.RENDERING:
            return f"Rendering {job.percent} %" if job.total else "Starting..."
        if job.status is Status.FAILED:
            return "Failed: " + (job.message.splitlines()[0] if job.message else "unknown error")
        if job.status is Status.DONE and job.message:
            return f"Done - {job.message}"
        return STATUS_TEXT[job.status]

    def _update_row(self, job: QueueJob) -> None:
        item = self._rows.get(job.id)
        if item is None:
            return
        item.setText(0, job.output.name)
        item.setToolTip(0, str(job.output))
        item.setText(1, job.summary)
        item.setText(2, self.status_text(job))
        item.setToolTip(2, job.message or item.text(2))
        row = self._row_widgets.get(job.id)
        if row is not None:
            state = {
                Status.QUEUED: "queued",
                Status.DONE: "done",
                Status.FAILED: "failed",
                Status.CANCELLED: "cancelled",
            }.get(job.status, "running" if job.total else "starting")
            fraction = job.frame / job.total if job.total else 0.0
            row.show_job(
                job.output.name, f"{self.status_text(job)} - {job.summary}", state, fraction, str(job.output)
            )

    def _update_buttons(self) -> None:
        job = self.selected()
        target = job or self.queue.current
        self.start_button.setEnabled(bool(self.queue.queued) and not self.queue.active)
        self.cancel_button.setEnabled(target is not None and not target.finished)
        self.remove_button.setEnabled(job is not None and job.status is not Status.RENDERING)
        self.clear_button.setEnabled(any(j.finished for j in self.queue.jobs))
        self.open_button.setEnabled(job is not None and job.result is not None)
        running, waiting = self.queue.current is not None, len(self.queue.queued)
        self.queue_chip.setVisible(running or bool(waiting))
        self.queue_chip.setText("1 running" if running else f"{waiting} queued")
        self.queue_chip.set_tone("accent" if running else "neutral")
        self._show_now()

    def _show_now(self) -> None:
        """The panel above the list: the running job with its ring and the time left, else the last one."""
        job = self.queue.current or self._last
        running = job is not None and job.status is Status.RENDERING
        if job is None:
            self.now_ring.set_state("idle")
            self.now_title.setText("Nothing is rendering")
        else:
            self.now_title.setText(job.output.name)
            if running:
                fraction = job.frame / job.total if job.total else 0.0
                self.now_ring.set_state("running" if job.total else "starting", fraction)
            else:
                self.now_ring.set_state(
                    {Status.DONE: "done", Status.FAILED: "failed"}.get(job.status, "cancelled")
                )
        if self.now.property("running") != running:
            self.now.setProperty("running", running)
            self.now.style().unpolish(self.now)
            self.now.style().polish(self.now)

    def _status_message(self, text: str) -> None:
        bar = self.window.statusBar()
        if text:
            bar.showMessage(f"Deliver: {text}")
        elif bar.currentMessage().startswith("Deliver: "):
            bar.clearMessage()

    # -- the Python scene -----------------------------------------------------------------------

    def _python_changed(self) -> None:
        self._python_stale = True
        if self.window.page == self.name:
            self._python_timer.start()

    def refresh_python(self) -> None:
        """Show ``to_python`` of the project as it is: readable code, or the exact scene and why."""
        self._python_timer.stop()
        self._python_stale = False
        project = self.window.project
        if project is None:
            self._show_python(None, "Open a project to see its Python scene.")
            return
        stem = self.window.path.stem if self.window.path else "scene"
        try:
            export = to_python(project, class_name(stem), str(adapter.cache_dir() / "code"))
        except Exception as error:  # a preview must never take the editor down
            log.exception("python preview failed")
            self._show_python(None, f"The scene cannot be written yet: {error}")
            return
        self._show_python(export, "")

    def _show_python(self, export: PythonExport | None, message: str) -> None:
        self.python_save.setEnabled(export is not None)
        if export is None:
            self.python_kind.setText(message)
            self.python_reasons.clear()
            self.python_code.clear()
            return
        if export.readable:
            self.python_kind.setText("Readable Manim code - runs with plain Manim")
            self.python_reasons.setText("Nothing in the project needs Manim Studio to play it.")
        else:
            self.python_kind.setText("Exact scene - plays the project through Manim Studio")
            shown = "; ".join(export.problems[:4]) + (
                f"; and {len(export.problems) - 4} more" if len(export.problems) > 4 else ""
            )
            self.python_reasons.setText(f"Exact because: {shown}")
        self.python_code.setPlainText(export.code)

    def save_python(self) -> None:
        """Save the scene as a .py file (the same as File > Export Python...)."""
        self.window.export_python()
