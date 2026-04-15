"""
Editor integration — auto-fill definition fields when the user types a word.

Flow:
- User types a word in the "input" field of a note and tabs/clicks away
- The editor_did_unfocus_field hook fires
- We look up the word in the configured sources (currently: macOS 现代汉语规范词典
  and MOE 教育部重編國語辭典) and populate their target fields.
- Fields are only filled if empty (unless overwrite_existing is set), so user
  edits are never clobbered.

Also adds a 典 toggle button to the editor toolbar to turn auto-fill on/off.

This module is intentionally Chinese-specific right now. When expanding to
other languages, see sources/README.md — the plan is to iterate over a
registry of Source objects here instead of the hard-coded macOS/MOE pair.
"""

import logging
import os
import re
from typing import Optional, List, Dict

from aqt import mw, gui_hooks
from aqt.utils import tooltip


# Error-only logger to a file next to the add-on. Kept quiet in normal use.
_logger = logging.getLogger("chinese_dict")
if not _logger.handlers:
    _log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
    _fh = logging.FileHandler(_log_path, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(_fh)
    _logger.setLevel(logging.WARNING)


# ------------------------------------------------------------------ #
#  Config                                                              #
# ------------------------------------------------------------------ #

def _cfg() -> dict:
    """Return the merged add-on config (Anki defaults from config.json)."""
    addon = __name__.split(".")[0]
    cfg = mw.addonManager.getConfig(addon)
    if cfg is None:
        # Fallback when getConfig can't locate the add-on (e.g. non-standard layout)
        import json
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    return cfg


def _save_cfg(cfg: dict):
    mw.addonManager.writeConfig(__name__.split(".")[0], cfg)


def is_auto_enabled() -> bool:
    return bool(_cfg().get("auto_generate", True))


def set_auto_enabled(v: bool):
    cfg = _cfg()
    cfg["auto_generate"] = bool(v)
    _save_cfg(cfg)


# ------------------------------------------------------------------ #
#  Field resolution                                                    #
# ------------------------------------------------------------------ #

def _find_field_by_keywords(field_names: List[str], keywords: List[str]) -> Optional[int]:
    """Return the first field index whose lowercase name contains a keyword."""
    lowers = [n.lower() for n in field_names]
    for kw in keywords:
        kw_low = kw.lower()
        for i, name in enumerate(lowers):
            if kw_low in name:
                return i
    return None


def _resolve_fields(model_name: str, field_names: List[str]) -> Dict[str, Optional[int]]:
    """
    Decide which field index is the input and which ones receive each source's
    output. Per-note-type overrides (from settings) win; otherwise we match by
    keyword substrings from the config.
    """
    cfg = _cfg()
    overrides = cfg.get("per_note_type", {}).get(model_name, {})

    def _by_name(key: str) -> Optional[int]:
        name = overrides.get(key)
        if name and name in field_names:
            return field_names.index(name)
        return None

    input_idx = _by_name("input_field")
    macos_idx = _by_name("macos_field")
    moe_idx = _by_name("moe_field")

    if input_idx is None:
        input_idx = _find_field_by_keywords(
            field_names, cfg.get("input_field_keywords", ["front", "word", "hanzi"])
        )
        if input_idx is None and field_names:
            input_idx = 0

    if macos_idx is None:
        macos_idx = _find_field_by_keywords(field_names, cfg.get("macos_field_keywords", []))
        if macos_idx is None:
            macos_idx = _find_field_by_keywords(
                field_names, cfg.get("macos_def_keywords", ["definition", "def"])
            )

    if moe_idx is None:
        moe_idx = _find_field_by_keywords(
            field_names, cfg.get("moe_field_keywords", ["moe", "traditional"])
        )

    return {"input": input_idx, "macos": macos_idx, "moe": moe_idx}


# ------------------------------------------------------------------ #
#  Lookup + fill                                                       #
# ------------------------------------------------------------------ #

def _lookup_and_fill(note, word: str, mapping: Dict[str, Optional[int]]) -> bool:
    """
    Look up the word in each configured source and populate the mapped fields.
    Returns True if any field changed (signals the editor to reload).
    """
    cfg = _cfg()
    overwrite = bool(cfg.get("overwrite_existing", False))
    macos_parts = set(cfg.get("macos_parts", ["pos", "definitions", "examples"]))
    moe_parts = set(cfg.get("moe_parts", ["pos", "definitions", "examples"]))

    try:
        from . import _get_macos_dict, _get_moedict
        from .convert import to_simplified, to_traditional
        from .formatter import (
            format_macos_entry, format_moe_entry_from_db, format_moe_entry_online,
        )
    except Exception as e:
        _logger.exception("import error during lookup")
        tooltip(f"Chinese Dict: import error: {e}")
        return False

    changed = False

    # macOS 现代汉语规范词典 — simplified characters
    macos_idx = mapping.get("macos")
    if macos_idx is not None and macos_idx < len(note.fields):
        if overwrite or not note.fields[macos_idx].strip():
            macos_d = _get_macos_dict()
            if macos_d is not None:
                try:
                    simp_word = to_simplified(word)
                    raw = macos_d.lookup(simp_word)
                    if not raw and simp_word != word:
                        raw = macos_d.lookup(word)
                    if raw:
                        html = format_macos_entry(simp_word, raw, macos_parts)
                        if html:
                            note.fields[macos_idx] = html
                            changed = True
                except Exception:
                    _logger.exception("macOS lookup failed for %r", word)

    # MOE 教育部重編國語辭典 — traditional characters
    moe_idx = mapping.get("moe")
    if moe_idx is not None and moe_idx < len(note.fields):
        if overwrite or not note.fields[moe_idx].strip():
            moe = _get_moedict()
            if moe is not None:
                try:
                    trad_word = to_traditional(word)
                    html = ""
                    if moe.is_offline and getattr(moe, "_conn", None):
                        html = format_moe_entry_from_db(trad_word, moe._conn, moe_parts)
                        if not html and trad_word != word:
                            html = format_moe_entry_from_db(word, moe._conn, moe_parts)
                    else:
                        entry = moe.lookup_parsed(trad_word)
                        if entry and entry.raw_json:
                            html = format_moe_entry_online(trad_word, entry.raw_json, moe_parts)
                    if html:
                        note.fields[moe_idx] = html
                        changed = True
                except Exception:
                    _logger.exception("MOE lookup failed for %r", word)

    return changed


# ------------------------------------------------------------------ #
#  Hooks                                                               #
# ------------------------------------------------------------------ #

def on_editor_did_unfocus_field(changed_by_user: bool, note, current_field_idx: int) -> bool:
    """Editor hook: when a field loses focus, auto-fill definitions if applicable."""
    if not is_auto_enabled():
        return False

    try:
        model = note.note_type() if hasattr(note, "note_type") else note.model()
    except Exception:
        _logger.exception("could not get note model")
        return False
    if not model:
        return False

    field_names = [f["name"] for f in model["flds"]]
    mapping = _resolve_fields(model["name"], field_names)

    input_idx = mapping.get("input")
    if input_idx is None or current_field_idx != input_idx:
        return False

    word = note.fields[current_field_idx].strip()
    if not word:
        return False

    # Strip any HTML Anki may have inserted (rich text)
    word = re.sub(r"<[^>]+>", "", word).strip()
    if not word:
        return False

    return _lookup_and_fill(note, word, mapping)


# ------------------------------------------------------------------ #
#  Toolbar button: 典                                                  #
# ------------------------------------------------------------------ #

_BUTTON_ID = "chinese_dict_toggle"


def _on_toggle_clicked(editor):
    new_state = not is_auto_enabled()
    set_auto_enabled(new_state)
    tooltip(f"Chinese Dict auto-fill: {'ON' if new_state else 'OFF'}", period=1200)
    _sync_button_state(editor)


def _sync_button_state(editor):
    """Match the toolbar button's highlight to the current auto-gen state."""
    state = "true" if is_auto_enabled() else "false"
    editor.web.eval(
        f"""
        setTimeout(function() {{
            const btn = document.getElementById('{_BUTTON_ID}');
            if (!btn) return;
            btn.classList.toggle('highlighted', {state});
            btn.setAttribute('aria-pressed', '{state}');
        }}, 50);
        """
    )


def on_editor_did_init_buttons(buttons, editor):
    btn = editor.addButton(
        icon=None,
        cmd=_BUTTON_ID,
        func=_on_toggle_clicked,
        tip="Chinese Dict auto-fill (toggle)",
        label="典",
        id=_BUTTON_ID,
        toggleable=True,
        disables=False,
    )
    buttons.append(btn)


def on_editor_did_load_note(editor):
    try:
        _sync_button_state(editor)
    except Exception:
        _logger.exception("failed to sync button state")


# ------------------------------------------------------------------ #
#  Registration                                                        #
# ------------------------------------------------------------------ #

def register_hooks():
    gui_hooks.editor_did_unfocus_field.append(on_editor_did_unfocus_field)
    gui_hooks.editor_did_init_buttons.append(on_editor_did_init_buttons)
    gui_hooks.editor_did_load_note.append(on_editor_did_load_note)
