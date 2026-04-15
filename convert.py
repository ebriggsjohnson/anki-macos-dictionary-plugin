"""
Simplified ↔ Traditional Chinese character conversion.

Uses opencc-python-reimplemented (pure Python, no C deps).
Install: pip install opencc-python-reimplemented

Falls back gracefully if not installed — returns the input unchanged.
"""

from typing import Optional

_s2t = None  # simplified → traditional
_t2s = None  # traditional → simplified
_available = None


def is_available() -> bool:
    """Check if opencc is installed."""
    global _available
    if _available is None:
        try:
            from opencc import OpenCC
            _available = True
        except ImportError:
            _available = False
    return _available


def _get_s2t():
    global _s2t
    if _s2t is None:
        from opencc import OpenCC
        _s2t = OpenCC("s2t")
    return _s2t


def _get_t2s():
    global _t2s
    if _t2s is None:
        from opencc import OpenCC
        _t2s = OpenCC("t2s")
    return _t2s


def to_traditional(text: str) -> str:
    """Convert simplified → traditional. Returns input unchanged if opencc unavailable."""
    if not is_available():
        return text
    return _get_s2t().convert(text)


def to_simplified(text: str) -> str:
    """Convert traditional → simplified. Returns input unchanged if opencc unavailable."""
    if not is_available():
        return text
    return _get_t2s().convert(text)
