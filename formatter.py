"""
Format dictionary entries as clean HTML for Anki card fields.

Each formatter takes raw data + a set of included parts, and returns
an HTML string ready to drop into an Anki note field.

Toggleable parts:
  - pinyin       (pronunciation in romanization)
  - bopomofo     (zhuyin / ㄅㄆㄇㄈ — MOE only)
  - pos          (part-of-speech tags like 动/名/形)
  - definitions  (the actual meanings)
  - examples     (example phrases/sentences)
  - usage_notes  (用法说明 — macOS dict only)
"""

import re
import json
from dataclasses import dataclass
from typing import Set, Optional, List


# All possible parts a user can toggle
ALL_PARTS = {"pinyin", "bopomofo", "pos", "definitions", "examples", "usage_notes"}

# Sensible defaults
DEFAULT_PARTS_MACOS = {"pos", "definitions", "examples"}
DEFAULT_PARTS_MOE = {"pos", "definitions", "examples"}


# ------------------------------------------------------------------ #
#  macOS 现代汉语规范词典 formatter                                      #
# ------------------------------------------------------------------ #

# Sense numbering
_SENSE_NUM = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
_POS_TAGS = {"名", "动", "形", "副", "介", "连", "助", "叹", "拟声", "数", "量", "代"}
_TONE_CHARS = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")
_USAGE_MARKER = "用法说明"


def format_macos_entry(headword: str, raw_text: str, parts: Set[str]) -> str:
    """
    Format a raw macOS dictionary entry as HTML.

    Args:
        headword: the word being looked up
        raw_text: raw text from DCSCopyTextDefinition
        parts: set of part names to include (from ALL_PARTS)

    Returns:
        HTML string, or "" if raw_text is empty/None
    """
    if not raw_text:
        return ""

    working = raw_text.strip()

    # Extract usage notes
    usage_notes = ""
    usage_idx = working.find(_USAGE_MARKER)
    if usage_idx >= 0:
        usage_notes = working[usage_idx + len(_USAGE_MARKER):].strip()
        working = working[:usage_idx].strip()

    # Extract pinyin from the front: "学习 xuéxí ①动 ..."
    pinyin = ""
    remaining = working
    if working.startswith(headword):
        remaining = working[len(headword):].strip()

    pin_match = re.match(
        r"^([a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ\s·]+?)(?=\s*[①②③④⑤⑥⑦⑧⑨⑩\u4e00-\u9fff〈])",
        remaining,
    )
    if pin_match:
        pinyin = pin_match.group(1).strip()
        remaining = remaining[pin_match.end():].strip()

    # Split into numbered senses
    sense_parts = _SENSE_NUM.split(remaining)
    sense_nums = _SENSE_NUM.findall(remaining)

    # If no sense numbers, treat the whole remaining text as one unnumbered sense
    if not sense_nums and remaining.strip():
        sense_nums = [""]
        sense_parts = ["", remaining.strip()]

    senses = []
    for i, num in enumerate(sense_nums):
        raw_sense = sense_parts[i + 1].strip() if i + 1 < len(sense_parts) else ""

        # Extract POS
        pos = ""
        pos_match = re.match(r"^([\u4e00-\u9fff]{1,2})\s+", raw_sense)
        if pos_match and pos_match.group(1) in _POS_TAGS:
            pos = pos_match.group(1)
            raw_sense = raw_sense[pos_match.end():].strip()

        # Split definition from examples at first 。
        def_parts = raw_sense.split("。", 1)
        definition = def_parts[0].strip()
        example_text = def_parts[1].strip() if len(def_parts) > 1 else ""

        examples = []
        if example_text:
            for chunk in re.split(r"\s*[|｜]\s*", example_text):
                chunk = chunk.strip().rstrip("。")
                if chunk:
                    examples.append(chunk)

        # Also check if definition has | examples appended
        if "|" in definition or "｜" in definition:
            sub = re.split(r"\s*[|｜]\s*", definition)
            definition = sub[0].strip()
            examples = [s.strip() for s in sub[1:] if s.strip()] + examples

        senses.append({"num": num, "pos": pos, "def": definition, "examples": examples})

    # Build HTML
    html = []

    if "pinyin" in parts and pinyin:
        html.append(f'<span class="pinyin" style="color:#888; font-style:italic;">{pinyin}</span>')

    if senses:
        html.append('<ol style="margin:0.3em 0; padding-left:1.5em;">')
        for s in senses:
            html.append("<li>")

            if "pos" in parts and s["pos"]:
                html.append(f'<span class="pos" style="color:#2a7ae2; font-size:0.85em; margin-right:0.3em;">[{s["pos"]}]</span>')

            if "definitions" in parts and s["def"]:
                html.append(f'<span class="def">{s["def"]}</span>')

            if "examples" in parts and s["examples"]:
                ex_html = " &#x7C; ".join(
                    f'<span style="color:#666;">{ex}</span>' for ex in s["examples"]
                )
                html.append(f'<div class="examples" style="margin-top:0.15em; font-size:0.9em; color:#555;">例：{ex_html}</div>')

            html.append("</li>")
        html.append("</ol>")

    if "usage_notes" in parts and usage_notes:
        html.append(f'<div class="usage" style="margin-top:0.4em; font-size:0.85em; color:#888; border-top:1px solid #eee; padding-top:0.3em;">用法：{usage_notes}</div>')

    return "\n".join(html)


# ------------------------------------------------------------------ #
#  MOE 教育部重編國語辭典 formatter                                      #
# ------------------------------------------------------------------ #

def format_moe_entry_from_db(headword: str, db_conn, parts: Set[str]) -> str:
    """
    Look up + format an MOE entry directly from the SQLite database.

    Args:
        headword: the word to look up
        db_conn: sqlite3 connection to moedict.db
        parts: set of part names to include

    Returns:
        HTML string, or "" if not found
    """
    import sqlite3

    c = db_conn.cursor()
    c.execute("SELECT id FROM entries WHERE title = ?", (headword,))
    entry_row = c.fetchone()
    if not entry_row:
        return ""

    entry_id = entry_row[0] if isinstance(entry_row, tuple) else entry_row["id"]

    # Get first heteronym
    c.execute(
        "SELECT id, pinyin, bopomofo FROM heteronyms WHERE entry_id = ? ORDER BY id LIMIT 1",
        (entry_id,),
    )
    het_row = c.fetchone()
    if not het_row:
        return ""

    if isinstance(het_row, tuple):
        het_id, pinyin, bopomofo = het_row
    else:
        het_id = het_row["id"]
        pinyin = het_row["pinyin"] or ""
        bopomofo = het_row["bopomofo"] or ""

    c.execute(
        "SELECT pos, def_text, examples, quotes FROM definitions WHERE heteronym_id = ? ORDER BY sort_order",
        (het_id,),
    )

    senses = []
    for row in c.fetchall():
        if isinstance(row, tuple):
            pos, def_text, examples_json, quotes_json = row
        else:
            pos = row["pos"] or ""
            def_text = row["def_text"] or ""
            examples_json = row["examples"]
            quotes_json = row["quotes"]

        examples = json.loads(examples_json) if examples_json else []
        senses.append({"pos": pos or "", "def": def_text or "", "examples": examples})

    return _build_moe_html(pinyin, bopomofo, senses, parts)


def format_moe_entry_online(headword: str, api_data: dict, parts: Set[str]) -> str:
    """
    Format an MOE entry from Moedict API JSON response.
    """
    heteronyms = api_data.get("heteronyms", [])
    if not heteronyms:
        return ""

    h = heteronyms[0]
    pinyin = h.get("pinyin", "")
    bopomofo = h.get("bopomofo", "")

    senses = []
    for d in h.get("definitions", []):
        def_text = _strip_html(d.get("def", ""))
        pos = d.get("type", "")
        examples = [_strip_html(e) for e in d.get("example", []) if e]
        senses.append({"pos": pos, "def": def_text, "examples": examples})

    return _build_moe_html(pinyin, bopomofo, senses, parts)


def _build_moe_html(pinyin: str, bopomofo: str, senses: list, parts: Set[str]) -> str:
    """Shared HTML builder for MOE entries."""
    html = []

    pron_bits = []
    if "pinyin" in parts and pinyin:
        pron_bits.append(f'<span style="color:#888; font-style:italic;">{pinyin}</span>')
    if "bopomofo" in parts and bopomofo:
        pron_bits.append(f'<span style="color:#888;">{bopomofo}</span>')
    if pron_bits:
        html.append(" ".join(pron_bits))

    if senses:
        html.append('<ol style="margin:0.3em 0; padding-left:1.5em;">')
        for s in senses:
            html.append("<li>")

            if "pos" in parts and s["pos"]:
                html.append(f'<span class="pos" style="color:#2a7ae2; font-size:0.85em; margin-right:0.3em;">[{s["pos"]}]</span>')

            if "definitions" in parts and s["def"]:
                html.append(f'<span class="def">{s["def"]}</span>')

            if "examples" in parts and s["examples"]:
                ex_items = []
                for ex in s["examples"]:
                    # Strip leading labels the MOE data already includes (如：、例：)
                    ex = re.sub(r"^[如例]\uff1a", "", ex.strip())
                    if ex:
                        ex_items.append(f'<span style="color:#666;">{ex}</span>')
                if ex_items:
                    html.append(f'<div class="examples" style="margin-top:0.15em; font-size:0.9em; color:#555;">例：{"　".join(ex_items)}</div>')

            html.append("</li>")
        html.append("</ol>")

    return "\n".join(html)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()
