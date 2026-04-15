"""
Base Source interface.

A Source is one (dictionary, formatter) pair plus any language-specific
preprocessing. Every concrete source — 现代汉语规范词典, MOE 國語辭典,
小学館日中, Oxford, Larousse, etc. — subclasses this.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class SourceResult:
    """What a Source returns from a lookup attempt."""
    html: str = ""            # formatted HTML ready to drop into an Anki field
    raw: Optional[str] = None  # raw dictionary text (for debugging / CSV export)
    found: bool = False        # True if the word was found at all


class Source:
    """
    Abstract base class for a dictionary source.

    Subclasses must set class attributes (`id`, `display_name`, `language`,
    `available_parts`, `default_parts`) and implement `is_available()` and
    `lookup()`. Everything else has sensible defaults.
    """

    # Unique, stable id used in config ("macos_xiandai", "moe", "jmdict", …)
    id: str = ""

    # Human-readable label shown in the UI
    display_name: str = ""

    # ISO language code for the target language ("zh-Hans", "zh-Hant", "ja", …)
    language: str = ""

    # Parts the user can toggle on/off for this source. Suggested vocabulary:
    #   "headword", "reading", "pinyin", "bopomofo", "furigana", "pos",
    #   "definitions", "examples", "usage_notes", "etymology"
    # Pick whichever apply.
    available_parts: List[str] = []

    # Default subset of `available_parts` that's on unless the user overrides.
    default_parts: Set[str] = frozenset()

    # Default field-name keywords used to auto-map this source to an Anki field
    # when the user selects a note type. e.g. ["xiandai", "hanyu", "simplified"]
    default_field_keywords: List[str] = []

    # --- Required API -------------------------------------------------- #

    def is_available(self) -> bool:
        """Fast check that the backend is usable right now."""
        raise NotImplementedError

    def lookup(self, word: str, parts: Set[str]) -> SourceResult:
        """
        Look up `word` and return a SourceResult with HTML restricted to
        the requested `parts`. Subclasses handle input normalization
        (simplified↔traditional, kana↔kanji, …) internally.
        """
        raise NotImplementedError

    # --- Optional overrides ------------------------------------------- #

    def normalize_input(self, word: str) -> str:
        """
        Convert a user-typed word into whatever form the backend expects.
        Defaults to no-op. Chinese sources override to simp↔trad convert.
        """
        return word
