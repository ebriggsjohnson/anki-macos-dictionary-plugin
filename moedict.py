"""
Moedict (萌典) — Taiwan Ministry of Education Dictionary.

Supports two modes:
  1. OFFLINE (default): reads from a local SQLite database (moedict.db)
     Build with: python3 build_moedict_db.py --download
  2. ONLINE fallback: queries the Moedict API if no local DB is found

Data source: https://github.com/g0v/moedict-data
License: CC BY-ND 3.0 Taiwan (content), CC0 (reformatting)
"""

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MoedictEntry:
    """A parsed dictionary entry from Moedict."""
    headword: str
    pinyin: str = ""
    bopomofo: str = ""
    definitions: str = ""
    examples: str = ""
    raw_json: Optional[dict] = field(default=None, repr=False)

    def to_csv_row(self) -> List[str]:
        """Return [headword, pinyin, definitions, examples] for CSV export."""
        return [self.headword, self.pinyin, self.definitions, self.examples]


class MoedictError(Exception):
    pass


_CIRCLED_NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


class MoedictClient:
    """
    Client for the MOE dictionary. Uses local SQLite by default, falls
    back to online API if the DB isn't found.
    """

    def __init__(self, db_path: Optional[str] = None, timeout: int = 10):
        self.timeout = timeout
        self._conn: Optional[sqlite3.Connection] = None
        self._online_only = False

        # Resolve DB path
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "moedict.db"
            )

        if os.path.exists(db_path):
            self._conn = sqlite3.connect(db_path)
            self._conn.row_factory = sqlite3.Row
        else:
            self._online_only = True

    @property
    def is_offline(self) -> bool:
        return self._conn is not None

    def lookup(self, word: str) -> Optional[str]:
        """
        Look up a word and return formatted plain text (same interface
        as MacOSDictionary.lookup). Returns None if not found.
        """
        entry = self.lookup_parsed(word)
        if not entry:
            return None
        parts = [f"{entry.headword} {entry.pinyin}"]
        if entry.bopomofo:
            parts[0] += f" ({entry.bopomofo})"
        parts.append(entry.definitions)
        return " ".join(parts)

    def lookup_parsed(self, word: str) -> Optional[MoedictEntry]:
        """Look up a word and return a parsed MoedictEntry."""
        if self._conn:
            return self._lookup_sqlite(word)
        return self._lookup_online(word)

    # ----------------------------------------------------------------
    # Offline (SQLite)
    # ----------------------------------------------------------------

    def _lookup_sqlite(self, word: str) -> Optional[MoedictEntry]:
        c = self._conn.cursor()

        # Get entry
        c.execute(
            "SELECT id, title FROM entries WHERE title = ?", (word,)
        )
        entry_row = c.fetchone()
        if not entry_row:
            return None

        entry_id = entry_row["id"]
        title = entry_row["title"]

        # Get first heteronym (most common pronunciation)
        c.execute(
            "SELECT id, pinyin, bopomofo FROM heteronyms WHERE entry_id = ? ORDER BY id LIMIT 1",
            (entry_id,),
        )
        het_row = c.fetchone()
        if not het_row:
            return None

        het_id = het_row["id"]
        pinyin = het_row["pinyin"] or ""
        bopomofo = het_row["bopomofo"] or ""

        # Get all definitions for this heteronym
        c.execute(
            "SELECT pos, def_text, examples, quotes FROM definitions WHERE heteronym_id = ? ORDER BY sort_order",
            (het_id,),
        )

        all_defs = []
        all_examples = []

        for i, row in enumerate(c.fetchall()):
            pos = row["pos"] or ""
            def_text = row["def_text"] or ""
            num = _CIRCLED_NUMS[i] if i < len(_CIRCLED_NUMS) else f"({i+1})"

            if pos:
                all_defs.append(f"{num}[{pos}] {def_text}")
            else:
                all_defs.append(f"{num} {def_text}")

            if row["examples"]:
                for ex in json.loads(row["examples"]):
                    if ex:
                        all_examples.append(ex)

        return MoedictEntry(
            headword=title,
            pinyin=pinyin,
            bopomofo=bopomofo,
            definitions=" ".join(all_defs),
            examples=" | ".join(all_examples),
        )

    # ----------------------------------------------------------------
    # Online (API fallback)
    # ----------------------------------------------------------------

    def _lookup_online(self, word: str) -> Optional[MoedictEntry]:
        import urllib.request
        import urllib.error
        import urllib.parse

        encoded = urllib.parse.quote(word)
        url = f"https://www.moedict.tw/{encoded}.json"

        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "AnkiMoedictPlugin/1.0"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return None

        heteronyms = data.get("heteronyms", [])
        if not heteronyms:
            return None

        title = data.get("title", word)
        h = heteronyms[0]

        pinyin = h.get("pinyin", "")
        bopomofo = h.get("bopomofo", "")

        all_defs = []
        all_examples = []

        for i, d in enumerate(h.get("definitions", [])):
            def_text = _strip_html(d.get("def", ""))
            pos = d.get("type", "")
            num = _CIRCLED_NUMS[i] if i < len(_CIRCLED_NUMS) else f"({i+1})"

            if pos:
                all_defs.append(f"{num}[{pos}] {def_text}")
            else:
                all_defs.append(f"{num} {def_text}")

            for ex in d.get("example", []):
                cleaned = _strip_html(ex)
                if cleaned:
                    all_examples.append(cleaned)

        return MoedictEntry(
            headword=title,
            pinyin=pinyin,
            bopomofo=bopomofo,
            definitions=" ".join(all_defs),
            examples=" | ".join(all_examples),
            raw_json=data,
        )

    def list_dictionaries(self):
        """Compatibility method — Moedict is a single dictionary."""
        mode = "offline (SQLite)" if self.is_offline else "online (API)"
        return [("教育部重編國語辭典修訂本 (MOE Revised)", mode)]

    def select_dictionary(self, name):
        """No-op for compatibility with MacOSDictionary interface."""
        pass

    def get_selected_dictionary(self):
        return "教育部重編國語辭典修訂本"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()
