# Chinese Dictionary Lookup for Anki

Look up Chinese words from two sources and get well-formatted HTML entries dropped into your Anki card fields:

1. **macOS 现代汉语规范词典** — the built-in simplified Chinese dictionary (via DictionaryServices, zero dependencies)
2. **MOE 教育部重編國語辭典修訂本** — Taiwan's comprehensive traditional Chinese dictionary (162k entries, offline via SQLite)

For each source you choose which parts to include (definitions, examples, POS tags, pinyin, bopomofo, usage notes) and which Anki field to write to. So you can have simplified definitions in one field and traditional in another, each formatted exactly how you want.

---

## Quick start

```bash
cd ~/Projects/macos-chinese-dict

# 1. Enable macOS dictionary
#    Open Dictionary.app → Preferences → check 现代汉语规范词典

# 2. Build the MOE offline database (~17MB download, ~108MB database)
python3 build_moedict_db.py --download

# 3. Test it
python3 cli.py --source both 学习 被 规矩
```

---

## CLI usage

```bash
# Look up words (both sources, CSV output)
python3 cli.py 学习 被 规矩

# macOS dictionary only
python3 cli.py --source macos 学习

# MOE dictionary only (uses traditional characters)
python3 cli.py --source moe 學習

# Choose which parts to include (skip pinyin if you have it elsewhere)
python3 cli.py --parts pos,definitions,examples 学习

# Process a word list file
python3 cli.py --file words.txt --output definitions.csv

# See raw macOS dictionary output (useful for debugging the parser)
python3 cli.py --raw 学习

# Target a specific macOS dictionary
python3 cli.py --dict "现代汉语" 学习

# List all available dictionaries
python3 cli.py --list-dicts
```

Available parts: `pinyin`, `bopomofo`, `pos`, `definitions`, `examples`, `usage_notes`

---

## Anki add-on

Install by copying this folder into your Anki add-ons directory, or zip it and use Tools → Add-ons → Install from file.

A **Chinese Dict** menu appears with three options:

**Batch Lookup** — the main workflow. Two source panels side by side, each with checkboxes for which parts to include and a dropdown for which Anki field to write to. Paste a word list, hit Look Up All, preview results, then Add to Anki.

**Batch Import** — same config, but loads from a file and imports straight into Anki (no preview step). Good for large word lists.

**Quick CSV Export** — paste words, get CSV with HTML entries from both sources.

---

## How the field mapping works

Say your note type has fields: `Word`, `Pinyin`, `SimplifiedDef`, `TraditionalDef`

You'd configure:
- Word field → `Word`
- macOS source → writes to `SimplifiedDef`, with checkboxes: ✅ POS ✅ Definitions ✅ Examples (pinyin unchecked since you have it in another field)
- MOE source → writes to `TraditionalDef`, with checkboxes: ✅ POS ✅ Definitions ✅ Examples

Each field gets a clean HTML `<ol>` with numbered definitions, POS tags in blue, and examples in gray.

---

## File structure

```
macos-chinese-dict/
├── __init__.py          # Anki add-on entry point
├── dict_lookup.py       # macOS DictionaryServices via ctypes
├── moedict.py           # MOE dictionary client (offline SQLite + online fallback)
├── formatter.py         # HTML formatters with toggleable parts
├── parser.py            # Plain-text parser for macOS dict output
├── gui.py               # Anki Qt dialogs
├── cli.py               # Standalone CLI
├── build_moedict_db.py  # Downloads + builds moedict.db from GitHub
└── manifest.json        # Anki add-on metadata
```

---

## Building the MOE database

```bash
# Download and build in one step
python3 build_moedict_db.py --download

# Or if you already have the JSON file
python3 build_moedict_db.py path/to/dict-revised.json
```

This downloads `dict-revised.json.xz` (17MB) from [g0v/moedict-data](https://github.com/g0v/moedict-data), decompresses it, and builds a SQLite database for fast offline lookups. The database is ~108MB.

If you skip this step, the MOE client falls back to the online API at moedict.tw (slower, requires internet).

Data license: CC BY-ND 3.0 Taiwan (content), CC0 (reformatting by @kcwu).

---

## Troubleshooting

**macOS dict returns nothing** — the dictionary isn't enabled. Open Dictionary.app → Preferences, check the box.

**Only English definitions** — drag 现代汉语规范词典 above English dictionaries in Dictionary.app preferences.

**MOE "not found" for simplified characters** — the MOE dictionary uses traditional characters. Look up 學習 not 学习.

**Parser produces weird output** — run `python3 cli.py --raw <word>` to see exactly what macOS returns, then tweak `formatter.py`.
