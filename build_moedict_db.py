#!/usr/bin/env python3
"""
Build a SQLite database from the MOE dictionary JSON data.

Usage:
    python3 build_moedict_db.py                          # uses dict-revised.json in same dir
    python3 build_moedict_db.py path/to/dict-revised.json
    python3 build_moedict_db.py --download               # download + build in one step

Produces: moedict.db (~25-35MB) for fast offline lookups.

Data source: https://github.com/g0v/moedict-data
License: CC BY-ND 3.0 Taiwan (content), CC0 (reformatting by @kcwu)
"""

import json
import os
import re
import sqlite3
import sys
import time


def strip_html(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def build_db(json_path: str, db_path: str):
    print(f"Reading {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded {len(data)} entries.")

    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            radical TEXT,
            stroke_count INTEGER,
            non_radical_stroke_count INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE heteronyms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            pinyin TEXT,
            bopomofo TEXT,
            FOREIGN KEY (entry_id) REFERENCES entries(id)
        )
    """)

    c.execute("""
        CREATE TABLE definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            heteronym_id INTEGER NOT NULL,
            pos TEXT,
            def_text TEXT,
            examples TEXT,
            quotes TEXT,
            sort_order INTEGER,
            FOREIGN KEY (heteronym_id) REFERENCES heteronyms(id)
        )
    """)

    c.execute("CREATE INDEX idx_entries_title ON entries(title)")
    c.execute("CREATE INDEX idx_heteronyms_entry ON heteronyms(entry_id)")
    c.execute("CREATE INDEX idx_definitions_heteronym ON definitions(heteronym_id)")

    start = time.time()
    entry_count = 0
    het_count = 0
    def_count = 0

    for item in data:
        title = item.get("title", "")
        # Skip entries with unicode escapes that aren't real characters
        if not title or title.startswith("{"):
            continue

        c.execute(
            "INSERT INTO entries (title, radical, stroke_count, non_radical_stroke_count) VALUES (?, ?, ?, ?)",
            (
                title,
                item.get("radical", "").strip(),
                item.get("stroke_count"),
                item.get("non_radical_stroke_count"),
            ),
        )
        entry_id = c.lastrowid
        entry_count += 1

        for h in item.get("heteronyms", []):
            pinyin = h.get("pinyin", "")
            bopomofo = h.get("bopomofo", "")

            c.execute(
                "INSERT INTO heteronyms (entry_id, pinyin, bopomofo) VALUES (?, ?, ?)",
                (entry_id, pinyin, bopomofo),
            )
            het_id = c.lastrowid
            het_count += 1

            for i, d in enumerate(h.get("definitions", [])):
                def_text = strip_html(d.get("def", ""))
                pos = d.get("type", "")

                examples = [strip_html(e) for e in d.get("example", [])]
                quotes = [strip_html(q) for q in d.get("quote", [])]

                c.execute(
                    "INSERT INTO definitions (heteronym_id, pos, def_text, examples, quotes, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        het_id,
                        pos,
                        def_text,
                        json.dumps(examples, ensure_ascii=False) if examples else None,
                        json.dumps(quotes, ensure_ascii=False) if quotes else None,
                        i,
                    ),
                )
                def_count += 1

    conn.commit()

    # Add FTS (full-text search) for fuzzy lookups
    c.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            title,
            content=entries,
            content_rowid=id
        )
    """)
    c.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
    conn.commit()

    elapsed = time.time() - start
    db_size = os.path.getsize(db_path) / (1024 * 1024)

    print(f"Built {db_path} in {elapsed:.1f}s")
    print(f"  Entries:     {entry_count:,}")
    print(f"  Heteronyms:  {het_count:,}")
    print(f"  Definitions: {def_count:,}")
    print(f"  DB size:     {db_size:.1f} MB")

    conn.close()


def download_json(dest_dir: str) -> str:
    """Download dict-revised.json.xz from GitHub and decompress it."""
    import urllib.request
    import lzma

    xz_url = "https://raw.githubusercontent.com/g0v/moedict-data/master/dict-revised.json.xz"
    xz_path = os.path.join(dest_dir, "dict-revised.json.xz")
    json_path = os.path.join(dest_dir, "dict-revised.json")

    if os.path.exists(json_path):
        print(f"Already have {json_path}")
        return json_path

    print(f"Downloading {xz_url}...")
    urllib.request.urlretrieve(xz_url, xz_path)
    print(f"Downloaded {os.path.getsize(xz_path) / (1024*1024):.1f} MB")

    print("Decompressing...")
    with lzma.open(xz_path, "rb") as xz_f:
        with open(json_path, "wb") as out_f:
            out_f.write(xz_f.read())
    print(f"Decompressed to {os.path.getsize(json_path) / (1024*1024):.1f} MB")

    return json_path


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if "--download" in sys.argv:
        json_path = download_json(script_dir)
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        json_path = sys.argv[1]
    else:
        json_path = os.path.join(script_dir, "dict-revised.json")

    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        print("Run with --download to fetch it, or provide the path as an argument.")
        sys.exit(1)

    db_path = os.path.join(script_dir, "moedict.db")
    build_db(json_path, db_path)


if __name__ == "__main__":
    main()
