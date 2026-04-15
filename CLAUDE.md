# CLAUDE.md — design decisions

A running log of why this code looks the way it does. Update when you make
a non-obvious choice; a future reader (AI or human) saves time by not
re-litigating resolved questions.

## Scope

Anki add-on that auto-fills Chinese definition fields from two sources:
- macOS built-in 现代汉语规范词典 (simplified, via DictionaryServices)
- Taiwan MOE 教育部重編國語辭典 (traditional, 162k entries, offline SQLite
  built from g0v/moedict-data)

Also ships a CLI for the same lookups outside Anki.

The add-on is Chinese-only today but the `sources/` directory scaffolds the
path to a generic multi-language framework. See `sources/README.md`.

## Architecture

```
__init__.py          Anki add-on entry point; registers menu + editor hooks;
                     lazy-loads the two dictionary backends as module globals
editor.py            Editor integration: auto-fill on field unfocus, 典 toggle
                     button in toolbar, error-only file logging
gui.py               Qt dialogs: BatchLookup, BatchImport, ExportCSV, Settings
cli.py               Standalone CLI
dict_lookup.py       ctypes bindings to macOS DictionaryServices
moedict.py           MOE dictionary client (offline SQLite primary, online fallback)
formatter.py         Raw text → HTML for each source
convert.py           Simplified↔traditional via bundled opencc
build_moedict_db.py  One-time DB builder: downloads JSON, writes SQLite
sources/             Scaffolding for future multi-language support (not wired in)
vendor/opencc/       Bundled pure-Python opencc to avoid install friction
config.json          Anki add-on defaults (keywords, default parts, per-note
                     overrides); accessed via mw.addonManager.getConfig()
```

## Design decisions

### macOS dictionary access: ctypes, not PyObjC
Anki bundles its own Python. PyObjC is a big dependency with C compilation
that doesn't travel well between Anki's bundled Python and the user's system
Python. The `DCSCopyTextDefinition` function only needs a few CoreServices
and CoreFoundation symbols, and `ctypes` makes that trivial — zero install
friction on any Mac.

### MOE dictionary: SQLite, not JSON
`dict-revised.json` is ~136MB. Parsing it on every lookup is too slow, and
loading it into a dict takes noticeable memory. `build_moedict_db.py`
converts the JSON to SQLite once (~109MB DB). Lookups are microseconds
and memory-resident only on demand. The JSON file is downloaded on first
run and can be deleted afterward — it's in `.gitignore`.

### opencc: vendored, pure-Python
`opencc-python-reimplemented` is pure Python (1.2MB) — no C extensions,
no compilation. Vendoring it under `vendor/opencc/` and prepending to
`sys.path` in `__init__.py` means users don't `pip install` anything.
The alternative (native opencc) would require a platform-specific binary
in Anki's sandboxed Python environment — too much pain.

### Auto-conversion: always on, at the Source layer
When a user types `学习`, we want macOS dict to look up `学习` (simplified)
and MOE to look up `學習` (traditional). Two options were considered:
1. Convert at the call site (GUI / editor) before each lookup
2. Have each Source internally normalize its input

We picked #1 initially (see the `to_simplified` / `to_traditional` calls
sprinkled through `editor.py` and `gui.py`). When the codebase grows to
more languages, the plan is to move this into `Source.normalize_input()`
(see `sources/base.py`) so the call site just passes the user's raw input.

### Field-name auto-detection, not required configuration
Most users don't want to configure anything before their first auto-fill
works. The resolver in `editor._resolve_fields()` guesses which field is
input, which is macOS output, which is MOE output, using substring keyword
matches against the user's field names (e.g., a field called "Xiandai Hanyu
Def" matches "xiandai" / "hanyu"). Users can override per-note-type in
Settings, but defaults should Just Work for common naming schemes.

### Fill-empty-only by default
The editor hook only writes to a target field if it's empty. This way
re-tabbing through a note doesn't clobber edits the user made to the
auto-generated content. `overwrite_existing` in config opts out.

### Toolbar button: toggleable + state sync
`editor.addButton(toggleable=True)` gives Anki-native toggle visuals but
only reflects the per-click state, not persisted config state. On
`editor_did_load_note` we run a small snippet of JS that sets the
`highlighted` class to match `is_auto_enabled()` so the button's appearance
always reflects the saved config.

### Per-source "parts" checkboxes
Different sources emit different structural info (pinyin, bopomofo, POS,
definitions, examples, usage notes). Rather than a global "show examples"
toggle, each source publishes its own `available_parts` and users pick
what to include per source. This matters when a user has pinyin in a
dedicated field and doesn't want it duplicated inside the macOS definition.

### HTML inline styles, not CSS classes
Anki card styling is managed in the user's note templates, not add-on
assets. Inline styles on the generated HTML guarantee a consistent look
regardless of the user's template. Colors/fonts are muted (grays, one
accent blue for POS) so it blends with arbitrary card designs.

### Single-sense entries in the macOS formatter
Simple macOS dictionary entries like `汉语 hànyǔ 名 汉民族的语言。...` have no
①②③ sense markers. The parser originally skipped these and produced empty
output. Fix: when no sense numbers are found, treat the whole remaining
text as a single unnumbered sense. Same POS/definition/examples splitting
applies.

### MOE example prefix stripping
MOE data includes examples prefixed with `如：「…」`. Our formatter prepends
`例：` to the example block, which produced double labels (`例：如：「…」`).
The formatter now strips leading `如：` / `例：` from each example before
rendering.

### Logging: error-only, file-based
Debug-level logging made troubleshooting easy during development but
clutters the add-on folder and slows down normal use. The logger is
configured at `WARNING` level writing to `debug.log` (gitignored). Any
exception inside a hook goes there; routine lookups are silent.

### Why not publish to AnkiWeb yet
The add-on does platform-specific things (macOS dictionaries) that won't
work for Linux/Windows users. AnkiWeb listing a macOS-only add-on is
acceptable but probably wants a second pass of polish (fewer implicit
dependencies, better "macOS dict unavailable" messaging) before wide
distribution.

## Known limitations / TODOs

- **Multi-language**: sources framework scaffolded (`sources/`) but not
  wired. Call sites in `editor.py`, `gui.py`, `cli.py` still hard-code
  the two Chinese sources. Migrate when adding language #2.
- **Duplicated lookup logic**: the "simplified→lookup→fallback" pattern
  is copy-pasted across `editor.py`, three dialogs in `gui.py`, and
  `cli.py`. Consolidate into one helper when the Source refactor lands.
- **Individual macOS dict selection**: `MacOSDictionary.select_dictionary()`
  exists but isn't plumbed through the GUI's SourceConfig panels.
  Currently batch/auto-fill always hits "all active dictionaries".
- **Linux/Windows**: macOS dict is obviously macOS-only. MOE + CLI work
  cross-platform but the Anki add-on presents macOS-specific UI without
  gracefully degrading on other OSes.
- **Tests**: there are none. The formatter in particular has enough
  parsing logic that it deserves a small pytest suite with recorded raw
  inputs.
