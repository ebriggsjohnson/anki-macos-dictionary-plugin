"""
GUI dialogs for the Chinese Dictionary Anki add-on.

Core design:
- User enables one or both sources (macOS dict / MOE dict)
- Per source, user picks which parts to include (pos, defs, examples, etc.)
- Per source, user picks which Anki note field to write to
- Entries are formatted as clean HTML and dropped into the chosen fields
"""

import csv
import io
import os
from typing import Callable, Optional, List, Dict, Set

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QProgressBar, QComboBox, QFileDialog, QCheckBox, QGroupBox,
    QFormLayout, QGridLayout, QApplication, Qt, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox,
)
from aqt.utils import showInfo, showWarning, tooltip


# ------------------------------------------------------------------ #
#  Source config widget (one per dictionary source)                     #
# ------------------------------------------------------------------ #

class SourceConfig(QGroupBox):
    """
    Config panel for a single dictionary source.
    Has: enable checkbox, part toggles, target field selector.
    """

    PART_LABELS = {
        "pinyin":      "Pinyin",
        "bopomofo":    "Bopomofo (ㄅㄆㄇ)",
        "pos":         "Part of speech",
        "definitions": "Definitions",
        "examples":    "Example sentences",
        "usage_notes": "Usage notes (用法说明)",
    }

    def __init__(self, title: str, available_parts: List[str],
                 default_parts: Set[str], parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(True)

        self._part_checks: Dict[str, QCheckBox] = {}
        self._field_combo = QComboBox()

        layout = QVBoxLayout(self)

        # Part toggles
        parts_group = QGroupBox("Include:")
        parts_layout = QGridLayout(parts_group)
        row = 0
        col = 0
        for part in available_parts:
            cb = QCheckBox(self.PART_LABELS.get(part, part))
            cb.setChecked(part in default_parts)
            self._part_checks[part] = cb
            parts_layout.addWidget(cb, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1
        layout.addWidget(parts_group)

        # Target field
        field_row = QHBoxLayout()
        field_row.addWidget(QLabel("Write to Anki field:"))
        self._field_combo.setMinimumWidth(200)
        field_row.addWidget(self._field_combo)
        field_row.addStretch()
        layout.addLayout(field_row)

    def populate_fields(self, field_names: List[str]):
        """Fill the target field dropdown from an Anki note type."""
        self._field_combo.clear()
        for name in field_names:
            self._field_combo.addItem(name)

    def set_field_index(self, idx: int):
        if 0 <= idx < self._field_combo.count():
            self._field_combo.setCurrentIndex(idx)

    def get_enabled_parts(self) -> Set[str]:
        return {k for k, cb in self._part_checks.items() if cb.isChecked()}

    def get_target_field(self) -> str:
        return self._field_combo.currentText()

    def get_target_field_index(self) -> int:
        return self._field_combo.currentIndex()


# ------------------------------------------------------------------ #
#  Batch Lookup dialog                                                 #
# ------------------------------------------------------------------ #

class BatchLookupDialog(QDialog):
    """Main dialog: paste words → configure sources → preview → add to Anki / export."""

    def __init__(self, parent, get_sources_fn: Callable):
        super().__init__(parent)
        self._get_sources = get_sources_fn
        self._results: List[dict] = []  # [{word, macos_html, moe_html}, ...]
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Chinese Dict — Batch Lookup")
        self.setMinimumSize(800, 700)
        layout = QVBoxLayout(self)

        # --- Word input ---
        input_group = QGroupBox("Word List")
        input_layout = QVBoxLayout(input_group)
        input_layout.addWidget(QLabel("Chinese words — one per line, or comma separated:"))
        self._input_text = QTextEdit()
        self._input_text.setPlaceholderText("学习\n被\n规矩\n现代")
        self._input_text.setMaximumHeight(100)
        input_layout.addWidget(self._input_text)

        btn_row = QHBoxLayout()
        btn_load = QPushButton("Load from File…")
        btn_load.clicked.connect(self._load_file)
        btn_row.addWidget(btn_load)
        btn_row.addStretch()
        input_layout.addLayout(btn_row)
        layout.addWidget(input_group)

        # --- Source configs (side by side) ---
        sources_row = QHBoxLayout()

        self._macos_config = SourceConfig(
            "macOS 现代汉语规范词典",
            available_parts=["pinyin", "pos", "definitions", "examples", "usage_notes"],
            default_parts={"pos", "definitions", "examples"},
        )
        sources_row.addWidget(self._macos_config)

        self._moe_config = SourceConfig(
            "MOE 教育部重編國語辭典",
            available_parts=["pinyin", "bopomofo", "pos", "definitions", "examples"],
            default_parts={"pos", "definitions", "examples"},
        )
        sources_row.addWidget(self._moe_config)

        layout.addLayout(sources_row)

        # --- Deck + note type ---
        mapping_row = QHBoxLayout()
        mapping_row.addWidget(QLabel("Deck:"))
        self._deck_combo = QComboBox()
        self._populate_decks()
        mapping_row.addWidget(self._deck_combo)

        mapping_row.addWidget(QLabel("Note Type:"))
        self._model_combo = QComboBox()
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._populate_models()
        mapping_row.addWidget(self._model_combo)
        mapping_row.addStretch()
        layout.addLayout(mapping_row)

        # --- Word field mapping ---
        word_row = QHBoxLayout()
        word_row.addWidget(QLabel("Word field:"))
        self._word_field_combo = QComboBox()
        self._word_field_combo.setMinimumWidth(150)
        word_row.addWidget(self._word_field_combo)
        word_row.addStretch()
        layout.addLayout(word_row)

        # Trigger initial field population
        self._on_model_changed()

        # --- Lookup button ---
        self._btn_lookup = QPushButton("Look Up All")
        self._btn_lookup.clicked.connect(self._do_lookup)
        self._btn_lookup.setDefault(True)
        layout.addWidget(self._btn_lookup)

        # --- Progress ---
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # --- Results preview ---
        results_group = QGroupBox("Preview")
        results_layout = QVBoxLayout(results_group)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Word", "macOS Entry", "MOE Entry"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        results_layout.addWidget(self._table)
        layout.addWidget(results_group)

        # --- Action buttons ---
        action_row = QHBoxLayout()
        action_row.addStretch()
        self._btn_add = QPushButton("Add to Anki")
        self._btn_add.clicked.connect(self._add_notes)
        self._btn_add.setEnabled(False)
        action_row.addWidget(self._btn_add)

        self._btn_csv = QPushButton("Export CSV")
        self._btn_csv.clicked.connect(self._export_csv)
        self._btn_csv.setEnabled(False)
        action_row.addWidget(self._btn_csv)
        layout.addLayout(action_row)

    def _populate_decks(self):
        self._deck_combo.clear()
        for d in sorted(mw.col.decks.all_names_and_ids(), key=lambda d: d.name):
            self._deck_combo.addItem(d.name, d.id)

    def _populate_models(self):
        self._model_combo.clear()
        for m in sorted(mw.col.models.all_names_and_ids(), key=lambda m: m.name):
            self._model_combo.addItem(m.name, m.id)

    def _on_model_changed(self):
        """When note type changes, update all field dropdowns."""
        model_id = self._model_combo.currentData()
        if not model_id:
            return
        model = mw.col.models.get(model_id)
        if not model:
            return
        field_names = [f["name"] for f in model["flds"]]

        self._word_field_combo.clear()
        for name in field_names:
            self._word_field_combo.addItem(name)

        self._macos_config.populate_fields(field_names)
        self._moe_config.populate_fields(field_names)

        # Smart defaults: word → field 0, macos → field with "def" in name or field 1, moe → next
        self._word_field_combo.setCurrentIndex(0)

        # Try to guess good field assignments
        lower_names = [n.lower() for n in field_names]
        macos_idx = _find_field_index(lower_names, ["definition", "def", "meaning"], fallback=min(1, len(field_names) - 1))
        moe_idx = _find_field_index(lower_names, ["moe", "traditional", "trad", "國語"], fallback=min(2, len(field_names) - 1))
        if moe_idx == macos_idx and len(field_names) > macos_idx + 1:
            moe_idx = macos_idx + 1

        self._macos_config.set_field_index(macos_idx)
        self._moe_config.set_field_index(moe_idx)

    def _parse_words(self) -> List[str]:
        raw = self._input_text.toPlainText().strip()
        if not raw:
            return []
        words = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for part in line.replace("\t", ",").split(","):
                part = part.strip()
                if part:
                    words.append(part)
        return words

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Word List", "",
            "Text Files (*.txt *.csv);;All Files (*)"
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._input_text.setPlainText(f.read())
            except Exception as e:
                showWarning(f"Error: {e}")

    def _do_lookup(self):
        words = self._parse_words()
        if not words:
            showWarning("Enter some words first.")
            return

        use_macos = self._macos_config.isChecked()
        use_moe = self._moe_config.isChecked()

        if not use_macos and not use_moe:
            showWarning("Enable at least one dictionary source.")
            return

        # Get backends
        sources = self._get_sources()
        macos_dict = None
        moe_client = None

        if use_macos:
            for key, val in sources.items():
                if key.startswith("macOS: All"):
                    macos_dict = val
                    break

        if use_moe:
            for key, val in sources.items():
                if "MOE" in key:
                    moe_client = val
                    break

        macos_parts = self._macos_config.get_enabled_parts() if use_macos else set()
        moe_parts = self._moe_config.get_enabled_parts() if use_moe else set()

        # Import formatters and character converter
        from .formatter import format_macos_entry, format_moe_entry_from_db
        from .convert import to_simplified, to_traditional

        self._progress.setVisible(True)
        self._progress.setMaximum(len(words))
        self._results = []
        self._table.setRowCount(0)

        for i, word in enumerate(words):
            macos_html = ""
            moe_html = ""

            if macos_dict:
                # Auto-convert to simplified for macOS 现代汉语规范词典
                simp_word = to_simplified(word)
                raw = macos_dict.lookup(simp_word)
                # Fallback: try original form if conversion found nothing
                if not raw and simp_word != word:
                    raw = macos_dict.lookup(word)
                if raw:
                    macos_html = format_macos_entry(simp_word, raw, macos_parts)

            if moe_client and hasattr(moe_client, '_conn') and moe_client._conn:
                # Auto-convert to traditional for MOE 國語辭典
                trad_word = to_traditional(word)
                moe_html = format_moe_entry_from_db(trad_word, moe_client._conn, moe_parts)
                # Fallback: try original form
                if not moe_html and trad_word != word:
                    moe_html = format_moe_entry_from_db(word, moe_client._conn, moe_parts)
            elif moe_client:
                # Online fallback
                trad_word = to_traditional(word)
                entry = moe_client.lookup_parsed(trad_word)
                if entry and entry.raw_json:
                    from .formatter import format_moe_entry_online
                    moe_html = format_moe_entry_online(word, entry.raw_json, moe_parts)

            self._results.append({
                "word": word,
                "macos_html": macos_html,
                "moe_html": moe_html,
            })

            # Preview (strip HTML for table display)
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(word))
            self._table.setItem(row, 1, QTableWidgetItem(
                _preview_text(macos_html) if macos_html else "[not found]"
            ))
            self._table.setItem(row, 2, QTableWidgetItem(
                _preview_text(moe_html) if moe_html else "[not found]"
            ))

            self._progress.setValue(i + 1)
            QApplication.processEvents()

        self._progress.setVisible(False)
        self._btn_add.setEnabled(bool(self._results))
        self._btn_csv.setEnabled(bool(self._results))

        found_m = sum(1 for r in self._results if r["macos_html"])
        found_e = sum(1 for r in self._results if r["moe_html"])
        tooltip(f"{len(words)} words — macOS: {found_m} found, MOE: {found_e} found")

    def _add_notes(self):
        if not self._results:
            return

        model_id = self._model_combo.currentData()
        deck_id = self._deck_combo.currentData()
        model = mw.col.models.get(model_id)
        if not model:
            showWarning("Note type not found.")
            return

        field_names = [f["name"] for f in model["flds"]]
        word_field_idx = self._word_field_combo.currentIndex()
        macos_field_idx = self._macos_config.get_target_field_index()
        moe_field_idx = self._moe_config.get_target_field_index()

        use_macos = self._macos_config.isChecked()
        use_moe = self._moe_config.isChecked()

        # Show mapping summary
        mapping = [f"  Word → {field_names[word_field_idx]}"]
        if use_macos:
            mapping.append(f"  macOS entry → {field_names[macos_field_idx]}")
        if use_moe:
            mapping.append(f"  MOE entry → {field_names[moe_field_idx]}")

        reply = QMessageBox.question(
            self, "Add Notes",
            f"Add {len(self._results)} notes to '{self._deck_combo.currentText()}'?\n\n"
            f"Field mapping:\n" + "\n".join(mapping),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        added = 0
        skipped = 0
        for r in self._results:
            has_content = r["macos_html"] or r["moe_html"]
            if not has_content:
                skipped += 1
                continue

            note = mw.col.newNote(model)
            note.fields[word_field_idx] = r["word"]

            if use_macos and r["macos_html"]:
                note.fields[macos_field_idx] = r["macos_html"]

            if use_moe and r["moe_html"]:
                note.fields[moe_field_idx] = r["moe_html"]

            note.model()["did"] = deck_id

            try:
                mw.col.addNote(note)
                added += 1
            except Exception:
                skipped += 1

        mw.reset()
        showInfo(f"Added {added} notes, skipped {skipped}.")

    def _export_csv(self):
        if not self._results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "chinese_definitions.csv",
            "CSV (*.csv);;All Files (*)"
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Word", "macOS Definition", "MOE Definition"])
            for r in self._results:
                writer.writerow([r["word"], r["macos_html"], r["moe_html"]])
        tooltip(f"Exported {len(self._results)} entries.")


# ------------------------------------------------------------------ #
#  Batch Import dialog (file → Anki, no preview)                       #
# ------------------------------------------------------------------ #

class BatchImportDialog(QDialog):
    """Load a file of words → look up → import straight into Anki."""

    def __init__(self, parent, get_sources_fn: Callable):
        super().__init__(parent)
        self._get_sources = get_sources_fn
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Chinese Dict — Batch Import")
        self.setMinimumSize(650, 500)
        layout = QVBoxLayout(self)

        # File selector
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Word list file:"))
        self._file_label = QLabel("(none)")
        self._file_label.setStyleSheet("color: gray;")
        file_row.addWidget(self._file_label, stretch=1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        file_row.addWidget(btn)
        layout.addLayout(file_row)

        # Source configs
        sources_row = QHBoxLayout()
        self._macos_config = SourceConfig(
            "macOS 现代汉语规范词典",
            ["pinyin", "pos", "definitions", "examples", "usage_notes"],
            {"pos", "definitions", "examples"},
        )
        sources_row.addWidget(self._macos_config)
        self._moe_config = SourceConfig(
            "MOE 教育部重編國語辭典",
            ["pinyin", "bopomofo", "pos", "definitions", "examples"],
            {"pos", "definitions", "examples"},
        )
        sources_row.addWidget(self._moe_config)
        layout.addLayout(sources_row)

        # Deck / note type
        form = QFormLayout()
        self._deck_combo = QComboBox()
        for d in sorted(mw.col.decks.all_names_and_ids(), key=lambda d: d.name):
            self._deck_combo.addItem(d.name, d.id)
        form.addRow("Deck:", self._deck_combo)

        self._model_combo = QComboBox()
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        for m in sorted(mw.col.models.all_names_and_ids(), key=lambda m: m.name):
            self._model_combo.addItem(m.name, m.id)
        form.addRow("Note Type:", self._model_combo)

        self._word_field_combo = QComboBox()
        form.addRow("Word field:", self._word_field_combo)
        layout.addLayout(form)

        self._on_model_changed()

        # Options
        self._skip_empty = QCheckBox("Skip words not found in any dictionary")
        self._skip_empty.setChecked(True)
        layout.addWidget(self._skip_empty)

        # Progress
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._status = QLabel("")
        layout.addWidget(self._status)

        # Import button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_import = QPushButton("Import into Anki")
        self._btn_import.clicked.connect(self._do_import)
        self._btn_import.setEnabled(False)
        btn_row.addWidget(self._btn_import)
        layout.addLayout(btn_row)

        self._file_path = None

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Word List", "", "Text (*.txt *.csv);;All (*)"
        )
        if path:
            self._file_path = path
            self._file_label.setText(os.path.basename(path))
            self._file_label.setStyleSheet("")
            self._btn_import.setEnabled(True)

    def _on_model_changed(self):
        model_id = self._model_combo.currentData()
        if not model_id:
            return
        model = mw.col.models.get(model_id)
        if not model:
            return
        field_names = [f["name"] for f in model["flds"]]

        self._word_field_combo.clear()
        for n in field_names:
            self._word_field_combo.addItem(n)

        self._macos_config.populate_fields(field_names)
        self._moe_config.populate_fields(field_names)

        self._word_field_combo.setCurrentIndex(0)
        lower_names = [n.lower() for n in field_names]
        self._macos_config.set_field_index(
            _find_field_index(lower_names, ["definition", "def"], fallback=min(1, len(field_names)-1))
        )
        self._moe_config.set_field_index(
            _find_field_index(lower_names, ["moe", "traditional", "trad"], fallback=min(2, len(field_names)-1))
        )

    def _do_import(self):
        if not self._file_path:
            return

        words = []
        with open(self._file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    for p in line.replace("\t", ",").split(","):
                        p = p.strip()
                        if p:
                            words.append(p)

        if not words:
            showWarning("No words found in file.")
            return

        use_macos = self._macos_config.isChecked()
        use_moe = self._moe_config.isChecked()
        if not use_macos and not use_moe:
            showWarning("Enable at least one source.")
            return

        sources = self._get_sources()
        macos_dict = None
        moe_client = None
        for key, val in sources.items():
            if use_macos and key.startswith("macOS: All"):
                macos_dict = val
            if use_moe and "MOE" in key:
                moe_client = val

        from .formatter import format_macos_entry, format_moe_entry_from_db
        from .convert import to_simplified, to_traditional

        model_id = self._model_combo.currentData()
        deck_id = self._deck_combo.currentData()
        model = mw.col.models.get(model_id)
        if not model:
            showWarning("Note type not found.")
            return

        field_names = [f["name"] for f in model["flds"]]
        word_idx = self._word_field_combo.currentIndex()
        macos_idx = self._macos_config.get_target_field_index()
        moe_idx = self._moe_config.get_target_field_index()
        macos_parts = self._macos_config.get_enabled_parts()
        moe_parts = self._moe_config.get_enabled_parts()

        self._progress.setVisible(True)
        self._progress.setMaximum(len(words))

        added = skipped = not_found = 0

        for i, word in enumerate(words):
            macos_html = ""
            moe_html = ""

            if macos_dict:
                simp_word = to_simplified(word)
                raw = macos_dict.lookup(simp_word)
                if not raw and simp_word != word:
                    raw = macos_dict.lookup(word)
                if raw:
                    macos_html = format_macos_entry(simp_word, raw, macos_parts)

            if moe_client and hasattr(moe_client, '_conn') and moe_client._conn:
                trad_word = to_traditional(word)
                moe_html = format_moe_entry_from_db(trad_word, moe_client._conn, moe_parts)
                if not moe_html and trad_word != word:
                    moe_html = format_moe_entry_from_db(word, moe_client._conn, moe_parts)

            has_content = macos_html or moe_html
            if not has_content:
                not_found += 1
                if self._skip_empty.isChecked():
                    skipped += 1
                    self._progress.setValue(i + 1)
                    continue

            note = mw.col.newNote(model)
            note.fields[word_idx] = word
            if use_macos and macos_html:
                note.fields[macos_idx] = macos_html
            if use_moe and moe_html:
                note.fields[moe_idx] = moe_html
            note.model()["did"] = deck_id

            try:
                mw.col.addNote(note)
                added += 1
            except Exception:
                skipped += 1

            self._progress.setValue(i + 1)
            if i % 20 == 0:
                QApplication.processEvents()

        self._progress.setVisible(False)
        mw.reset()

        self._status.setText(f"Added: {added}  |  Skipped: {skipped}  |  Not found: {not_found}")
        showInfo(f"Import complete!\n\nAdded: {added}\nSkipped: {skipped}\nNot found: {not_found}")


# ------------------------------------------------------------------ #
#  Quick CSV Export                                                    #
# ------------------------------------------------------------------ #

class ExportCSVDialog(QDialog):
    """Paste words → get CSV with HTML entries from both sources."""

    def __init__(self, parent, get_sources_fn: Callable):
        super().__init__(parent)
        self._get_sources = get_sources_fn
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Chinese Dict — Quick CSV Export")
        self.setMinimumSize(650, 500)
        layout = QVBoxLayout(self)

        # Source configs
        sources_row = QHBoxLayout()
        self._macos_config = SourceConfig(
            "macOS 现代汉语规范词典",
            ["pinyin", "pos", "definitions", "examples", "usage_notes"],
            {"pos", "definitions", "examples"},
        )
        sources_row.addWidget(self._macos_config)
        self._moe_config = SourceConfig(
            "MOE 教育部重編國語辭典",
            ["pinyin", "bopomofo", "pos", "definitions", "examples"],
            {"pos", "definitions", "examples"},
        )
        sources_row.addWidget(self._moe_config)
        layout.addLayout(sources_row)

        layout.addWidget(QLabel("Chinese words (one per line):"))
        self._input = QTextEdit()
        self._input.setPlaceholderText("学习\n被\n规矩")
        layout.addWidget(self._input)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("CSV output here…")
        layout.addWidget(self._output)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        b1 = QPushButton("Generate")
        b1.clicked.connect(self._generate)
        b1.setDefault(True)
        btn_row.addWidget(b1)
        b2 = QPushButton("Copy")
        b2.clicked.connect(lambda: (QApplication.clipboard().setText(self._output.toPlainText()), tooltip("Copied.")))
        btn_row.addWidget(b2)
        b3 = QPushButton("Save…")
        b3.clicked.connect(self._save)
        btn_row.addWidget(b3)
        layout.addLayout(btn_row)

    def _generate(self):
        raw = self._input.toPlainText().strip()
        words = [w.strip() for w in raw.replace(",", "\n").split("\n") if w.strip()]
        if not words:
            showWarning("Enter some words.")
            return

        use_macos = self._macos_config.isChecked()
        use_moe = self._moe_config.isChecked()
        if not use_macos and not use_moe:
            showWarning("Enable at least one source.")
            return

        sources = self._get_sources()
        macos_dict = moe_client = None
        for key, val in sources.items():
            if use_macos and key.startswith("macOS: All"):
                macos_dict = val
            if use_moe and "MOE" in key:
                moe_client = val

        from .formatter import format_macos_entry, format_moe_entry_from_db
        from .convert import to_simplified, to_traditional

        macos_parts = self._macos_config.get_enabled_parts()
        moe_parts = self._moe_config.get_enabled_parts()

        self._progress.setVisible(True)
        self._progress.setMaximum(len(words))

        out = io.StringIO()
        writer = csv.writer(out)
        header = ["Word"]
        if use_macos:
            header.append("macOS Definition")
        if use_moe:
            header.append("MOE Definition")
        writer.writerow(header)

        for i, word in enumerate(words):
            row = [word]
            if use_macos:
                simp_word = to_simplified(word)
                raw = macos_dict.lookup(simp_word) if macos_dict else None
                if not raw and simp_word != word and macos_dict:
                    raw = macos_dict.lookup(word)
                row.append(format_macos_entry(simp_word, raw, macos_parts) if raw else "")
            if use_moe:
                moe_html = ""
                if moe_client and hasattr(moe_client, '_conn') and moe_client._conn:
                    trad_word = to_traditional(word)
                    moe_html = format_moe_entry_from_db(trad_word, moe_client._conn, moe_parts)
                    if not moe_html and trad_word != word:
                        moe_html = format_moe_entry_from_db(word, moe_client._conn, moe_parts)
                row.append(moe_html)
            writer.writerow(row)
            self._progress.setValue(i + 1)
            QApplication.processEvents()

        self._progress.setVisible(False)
        self._output.setPlainText(out.getvalue())

    def _save(self):
        text = self._output.toPlainText()
        if not text:
            showWarning("Generate first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save", "definitions.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(text)
            tooltip(f"Saved.")


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
#  Settings dialog — per-note-type field mapping for auto-fill         #
# ------------------------------------------------------------------ #

class SettingsDialog(QDialog):
    """
    Configure auto-fill behavior:
    - master toggle
    - overwrite existing fields?
    - which parts to include by default (macOS / MOE)
    - per-note-type field overrides
    """

    PART_LABELS = {
        "pinyin":      "Pinyin",
        "bopomofo":    "Bopomofo (ㄅㄆㄇ)",
        "pos":         "Part of speech",
        "definitions": "Definitions",
        "examples":    "Example sentences",
        "usage_notes": "Usage notes (用法说明)",
    }

    def __init__(self, parent):
        super().__init__(parent)
        self._addon_name = __name__.split(".")[0]
        self._cfg = mw.addonManager.getConfig(self._addon_name) or {}
        self._setup_ui()
        self._load_model_fields()

    def _setup_ui(self):
        self.setWindowTitle("Chinese Dict — Settings")
        self.setMinimumSize(600, 600)
        layout = QVBoxLayout(self)

        # --- Global toggles ---
        globals_group = QGroupBox("General")
        g_layout = QVBoxLayout(globals_group)

        self._cb_auto = QCheckBox("Auto-fill definition fields as I type")
        self._cb_auto.setChecked(bool(self._cfg.get("auto_generate", True)))
        g_layout.addWidget(self._cb_auto)

        self._cb_overwrite = QCheckBox("Overwrite existing field contents")
        self._cb_overwrite.setChecked(bool(self._cfg.get("overwrite_existing", False)))
        g_layout.addWidget(self._cb_overwrite)

        layout.addWidget(globals_group)

        # --- Default parts ---
        parts_group = QGroupBox("Default parts to include")
        parts_layout = QHBoxLayout(parts_group)

        self._macos_parts_group = QGroupBox("macOS entry includes:")
        mp_layout = QVBoxLayout(self._macos_parts_group)
        self._macos_part_checks: Dict[str, QCheckBox] = {}
        for part in ["pinyin", "pos", "definitions", "examples", "usage_notes"]:
            cb = QCheckBox(self.PART_LABELS[part])
            cb.setChecked(part in self._cfg.get("macos_parts", ["pos", "definitions", "examples"]))
            self._macos_part_checks[part] = cb
            mp_layout.addWidget(cb)
        parts_layout.addWidget(self._macos_parts_group)

        self._moe_parts_group = QGroupBox("MOE entry includes:")
        ep_layout = QVBoxLayout(self._moe_parts_group)
        self._moe_part_checks: Dict[str, QCheckBox] = {}
        for part in ["pinyin", "bopomofo", "pos", "definitions", "examples"]:
            cb = QCheckBox(self.PART_LABELS[part])
            cb.setChecked(part in self._cfg.get("moe_parts", ["pos", "definitions", "examples"]))
            self._moe_part_checks[part] = cb
            ep_layout.addWidget(cb)
        parts_layout.addWidget(self._moe_parts_group)

        layout.addWidget(parts_group)

        # --- Per-note-type field mapping ---
        mapping_group = QGroupBox("Field mapping (for this note type)")
        m_layout = QFormLayout(mapping_group)

        self._model_combo = QComboBox()
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        for m in sorted(mw.col.models.all_names_and_ids(), key=lambda m: m.name):
            self._model_combo.addItem(m.name, m.id)
        m_layout.addRow("Note Type:", self._model_combo)

        self._input_combo = QComboBox()
        self._macos_combo = QComboBox()
        self._moe_combo = QComboBox()
        for c in (self._input_combo, self._macos_combo, self._moe_combo):
            c.setMinimumWidth(200)

        m_layout.addRow("Input field (word):", self._input_combo)
        m_layout.addRow("macOS target field:", self._macos_combo)
        m_layout.addRow("MOE target field:", self._moe_combo)

        hint = QLabel(
            "Leave blank (select \"(auto-detect)\") to let the add-on guess based on field names."
        )
        hint.setStyleSheet("color: gray; font-size: 11px;")
        hint.setWordWrap(True)
        m_layout.addRow(hint)

        layout.addWidget(mapping_group)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self._save)
        btn_save.setDefault(True)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _load_model_fields(self):
        self._on_model_changed()

    def _on_model_changed(self):
        model_id = self._model_combo.currentData()
        if not model_id:
            return
        model = mw.col.models.get(model_id)
        if not model:
            return
        field_names = [f["name"] for f in model["flds"]]

        # Populate each combo with "(auto-detect)" + field names
        for combo in (self._input_combo, self._macos_combo, self._moe_combo):
            combo.clear()
            combo.addItem("(auto-detect)")
            for n in field_names:
                combo.addItem(n)

        # Load any existing overrides for this note type
        overrides = self._cfg.get("per_note_type", {}).get(model["name"], {})

        def _select(combo, name):
            if name and name in field_names:
                combo.setCurrentIndex(1 + field_names.index(name))
            else:
                combo.setCurrentIndex(0)

        _select(self._input_combo, overrides.get("input_field"))
        _select(self._macos_combo, overrides.get("macos_field"))
        _select(self._moe_combo, overrides.get("moe_field"))

    def _save(self):
        cfg = dict(self._cfg)
        cfg["auto_generate"] = self._cb_auto.isChecked()
        cfg["overwrite_existing"] = self._cb_overwrite.isChecked()
        cfg["macos_parts"] = [k for k, cb in self._macos_part_checks.items() if cb.isChecked()]
        cfg["moe_parts"] = [k for k, cb in self._moe_part_checks.items() if cb.isChecked()]

        # Save per-note-type override
        model_id = self._model_combo.currentData()
        model = mw.col.models.get(model_id) if model_id else None
        if model:
            per = dict(cfg.get("per_note_type", {}))
            entry = {}

            def _read(combo):
                idx = combo.currentIndex()
                if idx <= 0:
                    return None
                return combo.currentText()

            inp = _read(self._input_combo)
            mac = _read(self._macos_combo)
            moe = _read(self._moe_combo)

            if inp:
                entry["input_field"] = inp
            if mac:
                entry["macos_field"] = mac
            if moe:
                entry["moe_field"] = moe

            if entry:
                per[model["name"]] = entry
            else:
                per.pop(model["name"], None)
            cfg["per_note_type"] = per

        mw.addonManager.writeConfig(self._addon_name, cfg)
        tooltip("Settings saved.", period=1200)
        self.accept()


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _find_field_index(lower_names: List[str], keywords: List[str], fallback: int = 0) -> int:
    """Find the first field whose name contains any of the keywords."""
    for kw in keywords:
        for i, name in enumerate(lower_names):
            if kw in name:
                return i
    return fallback


def _preview_text(html: str, max_len: int = 80) -> str:
    """Strip HTML for table preview."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + "…" if len(text) > max_len else text
