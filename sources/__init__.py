"""
Dictionary source framework.

A Source represents one dictionary backend: it knows how to look up a word,
format the raw result as HTML, and what "parts" (pinyin, POS, examples, …)
it can emit. Everything language-specific lives inside a Source subclass.

To add a new language:
  1. Write a subclass of `Source` in a new file (e.g. `japanese_macos.py`)
  2. Import and register it in `_register_all()` below (or call `register()`
     from your own module at add-on load time)
  3. editor.py and the GUI dialogs iterate `iter_sources()` to discover
     whatever is registered

This package is scaffolding — today the add-on still wires up its two
hard-coded Chinese sources directly in __init__.py / editor.py / gui.py.
When you add language #2, migrate the wiring to use `iter_sources()` and
the hard-coded paths can go away.

See sources/README.md for a worked example.
"""

from .base import Source, SourceResult

_REGISTRY: dict = {}


def register(source: Source) -> None:
    """Add a Source to the global registry. Call from add-on load."""
    _REGISTRY[source.id] = source


def iter_sources():
    """Yield all registered Source instances."""
    return list(_REGISTRY.values())


def get_source(source_id: str):
    return _REGISTRY.get(source_id)


__all__ = ["Source", "SourceResult", "register", "iter_sources", "get_source"]
