"""The Narration section of the Audio page (ADR 0060): pick a voice, generate speech, keep it in step.

The voice (provider, language, voice, speed) is the project's, or one subtitle's own with "Selected
subtitle only". **Generate voice** speaks the subtitles that have no current sound (or the selected one, or
all) in the voice helper process and places each result as a sound at its subtitle's start, as one undo
step; whatever finished is placed even when the rest was cancelled or failed. **Follow speech** moves the
subtitles (and their sounds) so each lasts as long as its speech; **Fit speech to cues** goes the other
way and sets the speeds so the speech fits the subtitles. A subtitle whose text, voice or speed changed
since its sound was made is *stale*: it keeps playing the old sound until it is generated again.

Nothing here runs a provider's code: the editor asks ``VoiceClient``. A provider that sends text over the
internet asks once (remembered) before it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import plugins
from ...core.editing import edits, tables
from ...core.model.schema import AudioClip, Cue, Project, VoiceChoice
from ...core.sound import audio
from ...core.voice import narration, pronunciation, retime, voice_cache
from ..services.voice_client import VoiceClient
from ..style import icons, theme
from ..style.card import Chip
from ..style.fields import caption

SAMPLE = "This is how this voice sounds."
ALL_LANGUAGES = "All languages"
SPACE = theme.SPACE


def section_label(text: str) -> QLabel:
    """An uppercase group label (Lumen's section label: 11 px, tracked, muted)."""
    label = QLabel(text.upper())
    font = theme.font("section")
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    label.setFont(font)
    label.setProperty("role", "muted")
    label.setAccessibleName(text)
    return label


def _rules(c: theme.Colours) -> str:
    top = theme.mix(c.accent, c.on_accent, 0.10)
    grad = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {top}, stop:1 {c.accent})"
    return f"""
QGroupBox#narrationPanel {{
    background: {c.panel}; border: 1px solid {theme.css(c.line)}; border-radius: {theme.RADIUS_CARD}px;
    margin-top: 0; padding-top: 0;
}}
QGroupBox#narrationPanel::title {{
    subcontrol-origin: padding; subcontrol-position: top left; left: 14px; top: 10px; color: {c.text};
    font-weight: 650;
}}
QToolButton#generateVoice {{
    background: {grad}; color: {c.on_accent}; border: 0; border-radius: {theme.RADIUS}px;
    padding: 6px 14px; font-weight: 600;
}}
QToolButton#generateVoice:hover {{ background: {theme.mix(c.accent, c.on_accent, 0.14)}; }}
QToolButton#generateVoice:disabled {{ background: {c.surface_3}; color: {c.disabled}; }}
QToolButton#generateVoice::menu-button {{ border: 0; width: 18px; }}
"""


theme.register_rules(_rules)

VOICE_COLUMN = tables.Column("voice", "Voice", "The voice this subtitle is spoken with", editable=False)
SPEECH_COLUMN = tables.Column(
    "speech", "Speech", "Whether the sound made for this subtitle is current", editable=False
)
NARRATION_COLUMNS = (VOICE_COLUMN, SPEECH_COLUMN, tables.PAUSE_COLUMN)


def cue_cell(project: Project, cue: Cue, key: str) -> str:
    """The text of a Voice or Speech cell of the subtitles table."""
    if key == "voice":
        choice = narration.effective_voice(project, cue)
        if choice is None:
            return ""
        return f"{choice.voice}{' *' if cue.voice is not None else ''}"
    state = narration.state(project, cue)
    if state == narration.READY:
        clip = next((c for c in project.audio if c.id == cue.audio_id), None)
        return f"ready, {clip.duration:.1f} s" if clip is not None else "ready"
    return "" if state in (narration.EMPTY, narration.NO_VOICE) else state


@dataclass
class _Generation:
    jobs: list[narration.Job]  # to speak
    cached: list[narration.Job]  # already spoken: only placed
    batches: list[tuple[str, list[narration.Job]]] = field(default_factory=list)  # one request per provider
    failed: dict[str, str] = field(default_factory=dict)  # cue id -> why
    finished: set[str] = field(default_factory=set)  # cue ids spoken now
    total: int = 0
    cancelled: bool = False
    preview: bool = False


class NarrationPanel(QGroupBox):
    def __init__(self, window, client: VoiceClient | None = None) -> None:
        super().__init__("Narration")
        self.window = window
        self.client = client if client is not None else VoiceClient(parent=self)
        self.voices: dict[str, list[dict]] = {}  # provider -> its voices, once listed
        self.problems: dict[str, str] = {}  # provider -> why it cannot be used now
        self.loading: set[str] = set()
        self.confirm_online = self._ask_online  # (provider label, number of texts) -> bool; tests replace it
        self._syncing = False
        self._all_languages = False  # the user chose "All languages"
        self._apply_when_listed = False  # the user changed provider or language: choose its first voice
        self._wanted: tuple[str, str] | None = None  # the (provider, voice) the project has, to show
        self._run: _Generation | None = None
        self._by_out: dict[str, list[narration.Job]] = {}
        self._build()
        self.client.voicesListed.connect(self._on_voices)
        self.client.spoken.connect(self._on_spoken)
        self.client.speakFinished.connect(self._on_batch_finished)

    # -- building ---------------------------------------------------------------------------

    def _build(self) -> None:
        self.provider_combo = QComboBox()
        self.language_combo = QComboBox()
        self.voice_combo = QComboBox()
        self.load_button = QPushButton("Load voices")
        self.load_button.setToolTip("Ask the online service for its voices (no subtitle text is sent)")
        self.load_button.hide()
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.5, 2.0)
        self.rate_spin.setSingleStep(0.05)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSuffix(" x")
        self.rate_spin.setValue(1.0)
        self.rate_spin.setToolTip("Speaking speed; 1.00 is normal. Not every voice can change it.")
        self.provider_combo.setToolTip("The speech engine. Add one by putting a plugin in the plugin folder.")
        self.language_combo.setToolTip("Only the voices of this language")
        self.voice_combo.setToolTip("The voice")
        self.scope_check = QCheckBox("Selected subtitle only")
        self.scope_check.setToolTip("Give the selected subtitle a voice of its own; unchecked removes it")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setProperty("role", "muted")
        self.preview_button = QPushButton(icons.icon("play"), "Preview")
        self.preview_button.setToolTip("Hear this voice say the selected subtitle (or a sample)")

        self.generate_button = QToolButton()
        self.generate_button.setText("Generate voice")
        self.generate_button.setIcon(icons.icon("sound"))
        self.generate_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.generate_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.generate_button)
        self.generate_stale = menu.addAction("New and changed subtitles")
        self.generate_selected = menu.addAction("Selected subtitle")
        self.generate_all = menu.addAction("All subtitles (again)")
        self.generate_button.setMenu(menu)
        self.generate_button.clicked.connect(lambda: self.generate("stale"))
        self.generate_stale.triggered.connect(lambda: self.generate("stale"))
        self.generate_selected.triggered.connect(lambda: self.generate("selected"))
        self.generate_all.triggered.connect(lambda: self.generate("all"))
        self.cancel_button = QPushButton(icons.icon("close"), "Cancel")
        self.cancel_button.hide()
        self.progress = QProgressBar()
        self.progress.hide()

        self.follow_check = QCheckBox("Follow speech")
        self.follow_check.setToolTip(
            "After generating, move the subtitles so each lasts as long as its speech, with a pause between"
        )
        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 5.0)
        self.pause_spin.setSingleStep(0.1)
        self.pause_spin.setDecimals(2)
        self.pause_spin.setValue(retime.PAUSE)
        self.pause_spin.setSuffix(" s pause")
        self.follow_button = QPushButton("Follow speech now")
        self.follow_button.setToolTip("Move the subtitles and their sounds to the length of the speech")
        self.fit_button = QPushButton("Fit speech to subtitles")
        self.fit_button.setToolTip(
            "Set each subtitle's speed so its speech fits it (between 0.85x and 1.25x), then generate again"
        )
        self.pronunciation_button = QPushButton("Pronunciation...")
        self.pronunciation_button.setToolTip("How written words are spoken (the subtitle keeps its text)")
        self.script_button = QPushButton(icons.icon("export"), "Export script...")
        self.script_button.setToolTip("Write the narration as plain text")
        self.status = QLabel()
        self.status.setWordWrap(True)

        # Lumen: the controls in labelled groups on a card, the states as chips, one primary action.
        self.setObjectName("narrationPanel")
        self.generate_button.setObjectName("generateVoice")
        self.cancel_button.setProperty("role", "danger")
        for button in (self.pronunciation_button, self.script_button):
            button.setProperty("role", "ghost")
        self.status.setProperty("role", "muted")
        self.chips = {
            narration.READY: Chip("", "ok"),
            narration.STALE: Chip("", "warn"),
            narration.NEW: Chip("", "neutral"),
        }
        self.chips[narration.READY].setToolTip("Subtitles whose sound is current")
        self.chips[narration.STALE].setToolTip("Subtitles changed since their sound was made: generate again")
        self.chips[narration.NEW].setToolTip("Subtitles with no sound yet")
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        for chip in self.chips.values():
            chip.hide()
            chips_row.addWidget(chip)
        chips_row.addStretch(1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(2 * SPACE)
        grid.setVerticalSpacing(5)
        for column, (text, widget) in enumerate(
            (("Provider", self.provider_combo), ("Language", self.language_combo))
        ):
            grid.addWidget(caption(text), 0, column)
            grid.addWidget(widget, 1, column)
        voice_row = QHBoxLayout()
        voice_row.setSpacing(SPACE)
        voice_row.addWidget(self.voice_combo, 1)
        voice_row.addWidget(self.load_button)
        grid.addWidget(caption("Voice"), 2, 0)
        grid.addLayout(voice_row, 3, 0)
        grid.addWidget(caption("Speed"), 2, 1)
        grid.addWidget(self.rate_spin, 3, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        generate_row = QHBoxLayout()
        generate_row.setSpacing(2 * SPACE)
        for widget in (self.generate_button, self.cancel_button, self.preview_button):
            generate_row.addWidget(widget)
        generate_row.addWidget(self.progress, 1)
        follow_row = QHBoxLayout()
        follow_row.setSpacing(2 * SPACE)
        for widget in (self.follow_check, self.pause_spin, self.follow_button, self.fit_button):
            follow_row.addWidget(widget)
        follow_row.addStretch(1)
        extras = QHBoxLayout()
        extras.setSpacing(SPACE)
        extras.addWidget(self.pronunciation_button)
        extras.addWidget(self.script_button)
        extras.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 30, 14, 14)
        layout.setSpacing(2 * SPACE)
        layout.addLayout(chips_row)
        layout.addWidget(section_label("Voice"))
        layout.addLayout(grid)
        layout.addWidget(self.scope_check)
        layout.addWidget(self.info)
        layout.addWidget(section_label("Speech"))
        for row in (generate_row, follow_row):
            layout.addLayout(row)
        layout.addWidget(section_label("More"))
        layout.addLayout(extras)
        layout.addWidget(self.status)

        self.provider_combo.activated.connect(self._provider_chosen)
        self.language_combo.activated.connect(self._language_chosen)
        self.voice_combo.activated.connect(lambda _i: self._apply_choice())
        self.rate_spin.editingFinished.connect(self._apply_choice)
        self.scope_check.toggled.connect(self._scope_toggled)
        self.load_button.clicked.connect(self._load_voices)
        self.cancel_button.clicked.connect(self.cancel)
        self.preview_button.clicked.connect(self.preview)
        self.follow_button.clicked.connect(self.follow_speech)
        self.fit_button.clicked.connect(self.fit_speech)
        self.pronunciation_button.clicked.connect(self.edit_pronunciations)
        self.script_button.clicked.connect(self.export_script)
        self._fill_providers()

    def _fill_providers(self) -> None:
        providers = plugins.voice_providers()
        order = sorted(providers, key=lambda name: (name not in ("sapi", "edge"), name != "sapi", name))
        self._syncing = True
        try:
            self.provider_combo.clear()
            for name in order:
                provider = providers[name]
                self.provider_combo.addItem(provider.label, name)
        finally:
            self._syncing = False

    # -- the project's voice, shown ---------------------------------------------------------

    @property
    def project(self) -> Project | None:
        return self.window.project

    def selected_cue(self) -> Cue | None:
        project, cue_id = self.project, self.window.selection.subtitle_id
        return next((c for c in project.subtitles if c.id == cue_id), None) if project is not None else None

    def refresh(self) -> None:
        """Show the voice of the project (or the selected subtitle) and what can be done now."""
        project = self.project
        cue = self.selected_cue()
        self._syncing = True
        try:
            self.scope_check.setEnabled(cue is not None)
            self.scope_check.setChecked(cue is not None and cue.voice is not None)
            choice = None
            if project is not None:
                choice = (cue.voice if cue is not None else None) or project.voice
            if choice is not None:
                self._wanted = (choice.provider, choice.voice)
                self.rate_spin.setValue(choice.rate)
                at = self.provider_combo.findData(choice.provider)
                if at >= 0:
                    self.provider_combo.setCurrentIndex(at)
            elif self._wanted is None and self.provider_combo.count():
                first = self._default_provider()
                self.provider_combo.setCurrentIndex(max(self.provider_combo.findData(first), 0))
                self._wanted = (self.provider_combo.currentData(), "")
        finally:
            self._syncing = False
        self._show_provider()
        self._update_buttons()

    def _default_provider(self) -> str | None:
        """The provider shown when the project has no voice: the first that can list its voices right
        now (installed, and no service to ask first), else the first."""
        providers = plugins.voice_providers()
        names = [self.provider_combo.itemData(i) for i in range(self.provider_combo.count())]
        for name in names:
            provider = providers[name]
            if (provider.check is None or provider.check() is None) and (
                not provider.online or self.consented(name)
            ):
                return name
        return names[0] if names else None

    def _provider(self) -> str | None:
        return self.provider_combo.currentData()

    def _show_provider(self, asked: bool = False) -> None:
        """List the current provider's voices (once) and show the ones for the chosen language."""
        name = self._provider()
        if name is None:
            return
        provider = plugins.voice_providers().get(name)
        reason = provider.check() if provider is not None and provider.check is not None else None
        if reason:
            self.problems[name] = reason
        elif name not in self.voices and name not in self.loading and name not in self.problems:
            online_unasked = provider is not None and provider.online and not self.consented(name)
            if asked or not online_unasked:  # an online service is contacted only when the user chose it
                self.loading.add(name)
                self.client.list_voices(name)
        self._fill_voices(name)
        self._show_info(name)

    def _fill_voices(self, name: str, language: str | None = None) -> None:
        """Show ``name``'s voices; ``language`` ("" for all) is the user's choice, else the voice's own."""
        voices = self.voices.get(name, [])
        wanted = self._wanted[1] if self._wanted and self._wanted[0] == name else ""
        if wanted and not any(
            v["id"] == wanted for v in voices
        ):  # not listed (yet): still show the project's
            voices = [*voices, {"id": wanted, "name": wanted, "language": "", "gender": ""}]
        languages = sorted({v["language"] for v in voices if v["language"]})
        current_language = self.language_combo.currentData() if self.language_combo.count() else None
        if language is not None:
            current_language = language
        elif self._all_languages:
            current_language = ""  # the user chose to see every voice, whatever the project's voice speaks
        elif wanted:
            known = next((v["language"] for v in voices if v["id"] == wanted), None)
            if known:
                current_language = known
        elif current_language not in languages:
            current_language = self._default_language(languages)
        self._syncing = True
        try:
            self.language_combo.clear()
            self.language_combo.addItem(ALL_LANGUAGES, "")
            for language in languages:
                self.language_combo.addItem(language, language)
            at = self.language_combo.findData(current_language or "")
            self.language_combo.setCurrentIndex(max(at, 0))
            shown = [v for v in voices if not current_language or v["language"] == current_language]
            self.voice_combo.clear()
            for voice in shown:
                label = voice["name"] + (f"  ({voice['gender']})" if voice["gender"] else "")
                self.voice_combo.addItem(label, voice["id"])
            at = self.voice_combo.findData(wanted) if wanted else -1
            self.voice_combo.setCurrentIndex(at if at >= 0 else (0 if self.voice_combo.count() else -1))
            if name in self.loading:
                self.voice_combo.setPlaceholderText("loading voices...")
            else:
                self.voice_combo.setPlaceholderText("no voices")
        finally:
            self._syncing = False
        if self._apply_when_listed and voices and self.voice_combo.count():
            self._apply_when_listed = False
            self._apply_choice()

    @staticmethod
    def _default_language(languages: list[str]) -> str | None:
        system = QLocale().name().replace("_", "-")
        for candidate in (system, "en-US"):
            if candidate in languages:
                return candidate
        return languages[0] if languages else None

    def _show_info(self, name: str) -> None:
        provider = plugins.voice_providers().get(name)
        if provider is None:
            self.info.setText("")
            return
        self.load_button.setVisible(
            name not in self.voices and name not in self.loading and name not in self.problems
        )
        parts = []
        if name in self.problems:
            parts.append(f"Not available: {self.problems[name]}")
        elif name in self.loading:
            parts.append("Loading the voices...")
        if provider.online:
            parts.append("Online: the subtitle text is sent to a service over the internet.")
        if not provider.supports_rate:
            parts.append("This voice ignores the speed.")
        if provider.license_note:
            parts.append(provider.license_note)
        self.info.setText(" ".join(parts))

    def _on_voices(self, name: str, answer: dict) -> None:
        self.loading.discard(name)
        if answer.get("ok"):
            self.voices[name] = answer["voices"]
            self.problems.pop(name, None)
        else:
            self.problems[name] = str(answer.get("error", "the voices could not be listed"))
        if name == self._provider():
            self._fill_voices(name)
            self._show_info(name)
        self._update_buttons()

    # -- choosing ---------------------------------------------------------------------------

    def current_choice(self) -> VoiceChoice | None:
        provider, voice = self._provider(), self.voice_combo.currentData()
        if not provider or not voice:
            return None
        return VoiceChoice(provider=provider, voice=voice, rate=round(self.rate_spin.value(), 3))

    def _load_voices(self) -> None:
        """The user asked for the current provider's voices (this changes nothing in the project)."""
        name = self._provider()
        if name is not None:
            self.problems.pop(name, None)
            self._show_provider(asked=True)

    def _provider_chosen(self, _index: int) -> None:
        name = self._provider() or ""
        self._all_languages = False
        self._wanted = (name, "")
        self._apply_when_listed = True
        if name not in self.voices:
            self.problems.pop(name, None)  # choosing it again tries again
        self._show_provider(asked=True)

    def _language_chosen(self, _index: int) -> None:
        name = self._provider()
        if name is None:
            return
        language = self.language_combo.currentData()
        self._all_languages = not language
        voices = [v for v in self.voices.get(name, []) if not language or v["language"] == language]
        self._wanted = (name, voices[0]["id"] if voices else "")
        self._apply_when_listed = True
        self._fill_voices(name, language or "")

    def _apply_choice(self) -> None:
        """The user chose a voice or a speed: the project's (or the selected subtitle's) voice becomes it."""
        project, choice = self.project, self.current_choice()
        if self._syncing or project is None or choice is None:
            return
        self._wanted = (choice.provider, choice.voice)
        cue = self.selected_cue()
        if cue is not None and self.scope_check.isChecked():
            edit = edits.set_cue_voice(project, [cue.id], choice)
            text = "Voice of subtitle"
        else:
            edit = edits.set_voice(project, choice)
            text = "Choose voice"
        self.window.document.apply(edit, text)

    def _scope_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        project, cue = self.project, self.selected_cue()
        if project is None or cue is None:
            return
        if checked:
            choice = self.current_choice() or project.voice
            if choice is not None:
                self.window.document.apply(
                    edits.set_cue_voice(project, [cue.id], choice), "Voice of subtitle"
                )
        elif cue.voice is not None:
            self.window.document.apply(edits.set_cue_voice(project, [cue.id], None), "Use the project voice")
        self.refresh()

    # -- generating -------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._run is not None

    def folder(self) -> Path:
        return voice_cache.folder_for(self.window.path)

    def generate(self, scope: str = "stale") -> None:
        """Speak the subtitles that need it: ``"stale"`` (new and changed), ``"selected"`` or ``"all"``."""
        project = self.project
        if project is None or self.running:
            return
        cue = self.selected_cue()
        if scope == "selected" and cue is None:
            self._say("Select a subtitle first.")
            return
        if project.voice is None and not all(
            c.voice is not None for c in project.subtitles if c.text.strip()
        ):
            choice = self.current_choice()
            if choice is None:
                self._say("Choose a voice first.")
                return
            self.window.document.apply(edits.set_voice(project, choice), "Choose voice")
            project = self.project
        wanted = [cue.id] if scope == "selected" and cue is not None else None
        plan = narration.plan(project, wanted, self.folder(), only_missing=scope == "stale")
        if not plan.jobs and not plan.cached:
            self._say(self._nothing_to_do(plan, project))
            return
        run = _Generation(plan.jobs, plan.cached, total=len(plan.jobs))
        for provider in dict.fromkeys(job.provider for job in plan.jobs):
            if not self._allowed_online(provider, sum(1 for j in plan.jobs if j.provider == provider)):
                self._say("Cancelled: nothing was sent.")
                return
            run.batches.append((provider, [j for j in plan.jobs if j.provider == provider]))
        self._begin(run)

    def _nothing_to_do(self, plan: narration.Plan, project: Project) -> str:
        reasons = sorted(set(plan.skipped.values()) - {narration.EMPTY})
        if reasons:
            return "Nothing to generate: " + "; ".join(reasons) + "."
        if not any(c.text.strip() for c in project.subtitles):
            return "There are no subtitles to speak. Add some on the timeline or import an .srt file."
        return "Every subtitle's sound is current."

    def _allowed_online(self, name: str, count: int) -> bool:
        provider = plugins.voice_providers().get(name)
        if provider is None or not provider.online:
            return True
        if self.consented(name):
            return True
        if self.confirm_online(provider.label, count):
            self.window.prefs.set_option(f"voice_online_{name}", True)
            return True
        return False

    def consented(self, name: str) -> bool:
        """Whether the user agreed that text goes to the online service ``name``."""
        return bool(self.window.prefs.option(f"voice_online_{name}", False))

    def _ask_online(self, label: str, count: int) -> bool:
        answer = QMessageBox.question(
            self,
            "Send text over the internet?",
            f"{label} speaks over the internet: the text of {count} subtitle{'s' if count != 1 else ''} "
            "will be sent to its service. Continue? (You are asked once for each service.)",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _begin(self, run: _Generation) -> None:
        self._run = run
        self._by_out = {}
        for job in run.jobs:
            self._by_out.setdefault(str(job.out), []).append(job)
        self.progress.setRange(0, max(run.total, 1))
        self.progress.setValue(0)
        self.progress.setVisible(run.total > 0)
        self.cancel_button.setVisible(run.total > 0)
        self._say(f"Speaking {run.total} subtitle{'s' if run.total != 1 else ''}...")
        self._update_buttons()
        if not self._next_batch():
            self._finish()

    def _next_batch(self) -> bool:
        run = self._run
        if run is None or not run.batches:
            return False
        provider, jobs = run.batches.pop(0)
        items = []
        for out, same in self._by_out.items():  # one text per file: cues that say the same share it
            first = same[0]
            if first.provider == provider and first in jobs:
                items.append(
                    {
                        "id": first.cue_id,
                        "text": first.text,
                        "voice": first.voice,
                        "rate": first.rate,
                        "out": out,
                    }
                )
        if not self.client.speak(provider, items):
            for job in jobs:
                run.failed[job.cue_id] = "the voice helper is busy"
            return self._next_batch()
        return True

    def _on_spoken(self, item_id: str, ok: bool, why: str) -> None:
        run = self._run
        if run is None:
            return
        first = next((j for j in run.jobs if j.cue_id == item_id), None)
        same = self._by_out.get(str(first.out), []) if first is not None else []
        for job in same:
            if ok:
                run.finished.add(job.cue_id)
            else:
                run.failed[job.cue_id] = why
        self.progress.setValue(min(self.progress.value() + len(same), self.progress.maximum()))

    def _on_batch_finished(self, completed: bool, why: str) -> None:
        run = self._run
        if run is None:
            return
        if why == "cancelled" or run.cancelled:
            run.cancelled = True
            run.batches.clear()
        elif self._next_batch():
            return
        self._finish()

    def cancel(self) -> None:
        run = self._run
        if run is not None:
            run.cancelled = True
            run.batches.clear()
        self.client.cancel()
        if self._run is not None:  # the client had nothing running (between batches)
            self._finish()

    def _finish(self) -> None:
        run, self._run = self._run, None
        self.progress.hide()
        self.cancel_button.hide()
        if run is None:
            return
        if run.preview:
            self._play_preview(run)
            self._update_buttons()
            return
        project = self.project
        placed: list[narration.Spoken] = []
        late = 0
        if project is not None:
            by_cue = {c.id: c for c in project.subtitles}
            for job in [*run.cached, *run.jobs]:
                if job.cue_id in run.failed or (job.cue_id not in run.finished and job in run.jobs):
                    continue
                cue = by_cue.get(job.cue_id)
                if cue is None or narration.key_for(project, cue) != job.key:
                    late += 1  # the subtitle changed while it was being spoken: it stays stale
                    continue
                seconds = audio.probe(str(job.out))
                if seconds is None or seconds <= 0:
                    run.failed.setdefault(job.cue_id, "the sound could not be read")
                    continue
                placed.append(narration.Spoken(job.cue_id, job.key, job.out, seconds))
            if placed:
                edit = narration.place(
                    project, placed, follow=self.follow_check.isChecked(), pause=self.pause_spin.value()
                )
                self.window.document.apply(edit, "Generate voice")
        self._say(self._summary(run, len(placed), late))
        self._update_buttons()
        self.refresh()

    @staticmethod
    def _summary(run: _Generation, placed: int, late: int) -> str:
        text = f"Placed {placed} sound{'s' if placed != 1 else ''}."
        if run.cancelled:
            text = f"Cancelled. {text}"
        if late:
            text += f" {late} subtitle{'s' if late != 1 else ''} changed meanwhile and stay stale."
        if run.failed:
            first = next(iter(run.failed.values()))
            text += f" {len(run.failed)} failed: {first}"
        return text

    # -- preview ----------------------------------------------------------------------------

    def preview(self) -> None:
        choice = self.current_choice()
        if choice is None or self.running:
            self._say("Choose a voice first." if choice is None else "Wait for the speech in progress.")
            return
        cue = self.selected_cue()
        project = self.project
        text = " ".join((cue.text if cue is not None else "").split()) or SAMPLE
        if project is not None:
            text = pronunciation.spoken(text, project.pronunciations)
        provider = plugins.voice_providers().get(choice.provider)
        if provider is None:
            return
        if not self._allowed_online(choice.provider, 1):
            self._say("Cancelled: nothing was sent.")
            return
        key = narration.make_key(choice, text)
        out = voice_cache.default_folder() / "preview" / f"{key}{provider.extension}"
        job = narration.Job("preview", choice.provider, choice.voice, choice.rate, text, key, out)
        if out.exists() and out.stat().st_size > 0:
            self._play(out)
            return
        run = _Generation([job], [], batches=[(choice.provider, [job])], total=1, preview=True)
        self._begin(run)

    def _play_preview(self, run: _Generation) -> None:
        job = run.jobs[0]
        if job.cue_id in run.failed:
            self._say(f"Could not speak the sample: {run.failed[job.cue_id]}")
        elif job.cue_id in run.finished:
            self._play(job.out)

    def _play(self, path: Path) -> None:
        player = getattr(self.window, "audio_player", None)
        seconds = audio.probe(str(path))
        if player is None or not seconds:
            self._say(f"Spoken to {path.name}, but this computer has no sound output to play it.")
            return
        clip = AudioClip(id="preview", path=str(path), duration=seconds)
        player.play(audio.source(Project(audio=[clip])), 0.0)
        self._say("Playing the preview.")

    # -- follow, fit, pronunciation, script --------------------------------------------------

    def follow_speech(self) -> None:
        project = self.project
        if project is None:
            return
        edit = narration.follow_speech(project, self.pause_spin.value())
        if edit.project == project:
            self._say("The subtitles already follow their speech.")
            return
        self.window.document.apply(edit, "Follow speech")
        self._say("The subtitles now last as long as their speech.")

    def fit_speech(self) -> None:
        project = self.project
        if project is None:
            return
        edit, fits = narration.fit_speech(project)
        if not fits:
            self._say("Every speech already fits its subtitle (or none has been generated).")
            return
        self.window.document.apply(edit, "Fit speech to subtitles")
        loose = [f for f in fits if not f.fits]
        text = (
            f"Set the speed of {len(fits)} subtitle{'s' if len(fits) != 1 else ''}: generate the voice again."
        )
        if loose:
            limit = retime.FIT_LIMITS[1]
            text += f" {len(loose)} cannot fit even at {limit:g}x: lengthen them or shorten the text."
        self._say(text)

    def edit_pronunciations(self) -> None:
        project = self.project
        if project is None:
            return
        dialog = PronunciationDialog(project.pronunciations, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.window.document.apply(edits.set_pronunciations(project, dialog.entries()), "Pronunciation")
            self.refresh()

    def export_script(self) -> None:
        project = self.project
        if project is None:
            return
        start = str(self.window.path.with_suffix(".script.txt")) if self.window.path else "narration.txt"
        name, _ = QFileDialog.getSaveFileName(self, "Export narration script", start, "Text (*.txt *.md)")
        if name:
            Path(name).write_text(narration.script(project), encoding="utf-8")
            self._say(f"Wrote {name}")

    # -- state ------------------------------------------------------------------------------

    def _update_buttons(self) -> None:
        project = self.project
        busy = self.running
        has_cues = project is not None and any(c.text.strip() for c in project.subtitles)
        for widget in (self.generate_button, self.preview_button, self.follow_button, self.fit_button):
            widget.setEnabled(not busy and project is not None)
        self.generate_button.setEnabled(not busy and has_cues)
        for widget in (self.provider_combo, self.language_combo, self.voice_combo, self.rate_spin):
            widget.setEnabled(not busy)
        self.generate_selected.setEnabled(self.selected_cue() is not None)
        counts = narration.counts(project) if project is not None else {}
        if project is not None:
            todo = counts.get(narration.NEW, 0) + counts.get(narration.STALE, 0)
            self.generate_stale.setText(f"New and changed subtitles ({todo})")
        words = {narration.READY: "ready", narration.STALE: "stale", narration.NEW: "no sound"}
        for state, chip in self.chips.items():
            count = counts.get(state, 0)
            chip.setText(f"{count} {words[state]}")
            chip.setVisible(count > 0)

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.window.statusBar().showMessage(text, 10000)


class PronunciationDialog(QDialog):
    """Pairs of written -> spoken, one per row (ADR 0060)."""

    def __init__(self, entries: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pronunciation")
        self.resize(460, 340)
        note = QLabel(
            "How words are spoken. The subtitle keeps what is written; the voice says the right column. "
            "Whole words only, longest first."
        )
        note.setWordWrap(True)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Written", "Spoken as"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for written, spoken in entries.items():
            self._add(written, spoken)
        add = QPushButton(icons.icon("add"), "Add")
        remove = QPushButton(icons.icon("delete"), "Remove")
        add.clicked.connect(lambda: self._add("", ""))
        remove.clicked.connect(self._remove)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        layout.addWidget(buttons)

    def _add(self, written: str, spoken: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(written))
        self.table.setItem(row, 1, QTableWidgetItem(spoken))
        self.table.setCurrentCell(row, 0)

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def entries(self) -> dict[str, str]:
        found = {}
        for row in range(self.table.rowCount()):
            written = self.table.item(row, 0)
            spoken = self.table.item(row, 1)
            if written is not None and spoken is not None:
                found[written.text()] = spoken.text()
        return found
