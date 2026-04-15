"""
Chinese Dictionary Lookup — Anki Add-on

Looks up Chinese words using:
  1. macOS built-in dictionaries (现代汉语规范词典, Oxford, etc.)
  2. Taiwan MOE dictionary (教育部重編國語辭典修訂本) — offline via SQLite

SETUP:
1. For macOS dicts: Open Dictionary.app → Preferences → enable your dictionaries
2. For MOE dict: run `python3 build_moedict_db.py --download` in the add-on folder
3. Install this add-on in Anki (Tools → Add-ons → Install from file)

USAGE:
- Type a Chinese word in your note's input field and tab away — the definition
  fields auto-fill. Toggle with the 典 button in the editor toolbar.
- Tools → Chinese Dict → Batch Lookup…
- Tools → Chinese Dict → Batch Import… (file → Anki notes)
- Tools → Chinese Dict → Quick CSV Export…
- Tools → Chinese Dict → Settings… (per-note-type field mapping)
"""

import os
import sys

_addon_dir = os.path.dirname(os.path.abspath(__file__))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

# Add bundled vendor packages (opencc, etc.) to sys.path
_vendor_dir = os.path.join(_addon_dir, "vendor")
if os.path.isdir(_vendor_dir) and _vendor_dir not in sys.path:
    sys.path.insert(0, _vendor_dir)

import logging

from aqt import mw, gui_hooks
from aqt.qt import QAction, QMenu
from aqt.utils import showInfo

_logger = logging.getLogger("chinese_dict")

# Registry of available dictionary backends
_macos_dict = None
_moedict = None


def _get_macos_dict():
    """Get or create the macOS DictionaryServices instance."""
    global _macos_dict
    if _macos_dict is None:
        try:
            from .dict_lookup import MacOSDictionary
            _macos_dict = MacOSDictionary()
        except Exception:
            pass  # Not on macOS or framework unavailable
    return _macos_dict


def _get_moedict():
    """Get or create the Moedict (offline SQLite) instance."""
    global _moedict
    if _moedict is None:
        try:
            from .moedict import MoedictClient
            _moedict = MoedictClient()
        except Exception:
            pass
    return _moedict


def get_all_sources() -> dict:
    """
    Return a dict of {display_name: lookup_callable} for all available
    dictionary sources. Each callable has the signature: word -> str|None
    """
    sources = {}

    macos_d = _get_macos_dict()
    if macos_d:
        sources["macOS: All active dictionaries"] = macos_d

    moe = _get_moedict()
    if moe:
        mode = "offline" if moe.is_offline else "online"
        sources[f"MOE 國語辭典 ({mode})"] = moe

    # Also list individual macOS dicts if private API is available
    if macos_d:
        try:
            dicts = macos_d.list_dictionaries()
            chinese_kw = ["汉语", "漢語", "Chinese", "國語", "中文", "辭典", "词典"]
            for name, short in dicts:
                if any(kw in name for kw in chinese_kw):
                    sources[f"macOS: {name}"] = (macos_d, name)
        except Exception:
            pass

    return sources


def _on_batch_lookup():
    from .gui import BatchLookupDialog
    dialog = BatchLookupDialog(mw, get_all_sources)
    dialog.exec()


def _on_batch_import():
    from .gui import BatchImportDialog
    dialog = BatchImportDialog(mw, get_all_sources)
    dialog.exec()


def _on_export_csv():
    from .gui import ExportCSVDialog
    dialog = ExportCSVDialog(mw, get_all_sources)
    dialog.exec()


def _on_settings():
    from .gui import SettingsDialog
    dialog = SettingsDialog(mw)
    dialog.exec()


def _on_list_dictionaries():
    lines = []

    macos_d = _get_macos_dict()
    if macos_d:
        dicts = macos_d.list_dictionaries()
        if dicts:
            lines.append("macOS Dictionaries:")
            chinese_kw = ["汉语", "漢語", "Chinese", "國語", "中文", "辭典", "词典"]
            for name, short in sorted(dicts):
                marker = " ✓" if any(kw in name for kw in chinese_kw) else ""
                lines.append(f"  {name} ({short}){marker}")
        else:
            lines.append("macOS: Could not enumerate (private API unavailable).")
    else:
        lines.append("macOS DictionaryServices: not available")

    lines.append("")

    moe = _get_moedict()
    if moe and moe.is_offline:
        lines.append("MOE 教育部重編國語辭典: ✓ (offline SQLite)")
    elif moe:
        lines.append("MOE 教育部重編國語辭典: online only (run build_moedict_db.py for offline)")
    else:
        lines.append("MOE 教育部重編國語辭典: not available")

    showInfo("\n".join(lines))


def _setup_menu():
    menu = QMenu("Chinese Dict", mw)

    a1 = QAction("Batch Lookup…", mw)
    a1.triggered.connect(_on_batch_lookup)
    menu.addAction(a1)

    a2 = QAction("Batch Import… (file → Anki)", mw)
    a2.triggered.connect(_on_batch_import)
    menu.addAction(a2)

    a3 = QAction("Quick CSV Export…", mw)
    a3.triggered.connect(_on_export_csv)
    menu.addAction(a3)

    menu.addSeparator()

    a_settings = QAction("Settings… (auto-fill field mapping)", mw)
    a_settings.triggered.connect(_on_settings)
    menu.addAction(a_settings)

    a4 = QAction("List Available Dictionaries", mw)
    a4.triggered.connect(_on_list_dictionaries)
    menu.addAction(a4)

    mw.form.menubar.addMenu(menu)


gui_hooks.main_window_did_init.append(_setup_menu)

# Register editor hooks for auto-fill as you type
try:
    from .editor import register_hooks as _register_editor_hooks
    _register_editor_hooks()
except Exception:
    _logger.exception("Failed to register editor hooks")
