# Adding a new dictionary source

This package is scaffolding for expanding the add-on beyond Chinese. It's
not wired through yet — today `editor.py`, `gui.py`, and `cli.py` hard-code
the two Chinese sources (macOS 现代汉语规范词典 and MOE 國語辭典). When you
add a second language, migrate those modules to iterate
`sources.iter_sources()` instead and everything below becomes the real
extension point.

## The interface

A `Source` bundles:

- A backend that returns raw dictionary text for a word
- A formatter that turns that text into HTML
- Language-specific input normalization (simplified↔traditional, kana↔kanji,
  diacritic folding, whatever)
- Metadata: `id`, `display_name`, `language`, `available_parts`

See `base.py` for the full contract.

## Worked example: adding 新明解国語辞典 (macOS Japanese)

1. **Create the backend** if one doesn't exist. For macOS dictionaries you
   can reuse `dict_lookup.MacOSDictionary` by passing the dictionary name
   substring. For others (online APIs, SQLite files) write a new module.

2. **Write a formatter** that turns the raw text into HTML. Each dictionary
   has its own output shape — study the raw output first with the CLI:
   ```bash
   python3 cli.py --raw --dict "新明解" 勉強
   ```

3. **Write the Source subclass**:
   ```python
   # sources/japanese_shinmeikai.py
   from typing import Set
   from .base import Source, SourceResult

   class JapaneseShinmeikaiSource(Source):
       id = "macos_shinmeikai"
       display_name = "macOS 新明解国語辞典"
       language = "ja"
       available_parts = ["headword", "reading", "pos", "definitions", "examples"]
       default_parts = frozenset(["pos", "definitions", "examples"])
       default_field_keywords = ["japanese", "jp", "shinmeikai", "kokugo"]

       def __init__(self):
           from ..dict_lookup import MacOSDictionary
           self._dict = MacOSDictionary()
           self._dict.select_dictionary("新明解")

       def is_available(self):
           return self._dict is not None

       def lookup(self, word, parts):
           raw = self._dict.lookup(word)
           if not raw:
               return SourceResult(found=False)
           html = format_shinmeikai_entry(word, raw, parts)  # your formatter
           return SourceResult(html=html, raw=raw, found=True)
   ```

4. **Register it** somewhere that runs at add-on load. Simplest: inside the
   package `__init__.py`:
   ```python
   from .sources import register
   from .sources.japanese_shinmeikai import JapaneseShinmeikaiSource
   register(JapaneseShinmeikaiSource())
   ```

5. **Migrate call sites**. Once more than one language exists, rewrite the
   `_lookup_and_fill` helper in `editor.py` (and the corresponding loops
   in `gui.py` / `cli.py`) to iterate `sources.iter_sources()` instead of
   calling macOS/MOE directly.

## Design notes

**Why per-source parts?** Every dictionary emits different structural
information. Japanese dicts have readings but no pinyin; Chinese dicts
have POS tags in a specific closed set; etymologies only appear in some
English dicts. Hardcoding a cross-language part vocabulary doesn't work,
so each Source publishes its own `available_parts`.

**Why input normalization per source?** A user typing `学习` expects
lookups in both simplified (macOS) and traditional (MOE) dictionaries to
succeed. Rather than doing s↔t conversion at the call site, each Source
knows what form it wants and converts internally. Same for future Japanese
sources that may want hiragana→kanji hints, etc.

**Why field-name keywords?** The auto-detection in `editor._resolve_fields`
looks at the user's note-type field names and tries to guess which Anki
field should receive each source's output. Keeping a default keyword list
on the Source itself means adding a new language doesn't require editing
the resolver.

**Why not make sources pluggable via entry points / config.json?** YAGNI
for now. The registry is a plain dict, and new languages get added by
editing `__init__.py`. Move to entry points only if a third-party shows
up wanting to ship sources out-of-tree.
