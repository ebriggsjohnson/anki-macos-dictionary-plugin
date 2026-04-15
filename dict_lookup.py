"""
macOS DictionaryServices access via ctypes.
No external dependencies required — uses only the macOS system frameworks.

Supports:
- Looking up words in all active dictionaries (public API)
- Enumerating available dictionaries (private API)
- Looking up words in a *specific* dictionary by name (private API)
"""

import ctypes
import ctypes.util
import platform
import re
from typing import Optional, List, Tuple


class DictionaryServicesError(Exception):
    pass


class CFRange(ctypes.Structure):
    """CoreFoundation CFRange struct."""
    _fields_ = [
        ("location", ctypes.c_long),
        ("length", ctypes.c_long),
    ]


class MacOSDictionary:
    """Access macOS built-in dictionaries via DictionaryServices framework."""

    def __init__(self):
        if platform.system() != "Darwin":
            raise DictionaryServicesError(
                "This add-on requires macOS (DictionaryServices framework)."
            )
        self._load_frameworks()
        self._dict_cache = {}  # name -> dict_ref cache
        self._selected_dict_name: Optional[str] = None  # user's chosen dictionary

    def _load_frameworks(self):
        """Load CoreFoundation and CoreServices frameworks."""
        try:
            self._cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            self._cs = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreServices.framework/CoreServices"
            )
        except OSError as e:
            raise DictionaryServicesError(
                f"Failed to load macOS frameworks: {e}"
            )

        # --- CoreFoundation types and functions ---
        self._cf_index = ctypes.c_long

        # CFStringCreateWithCString
        self._cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self._cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,  # allocator (NULL)
            ctypes.c_char_p,  # c string
            ctypes.c_uint32,  # encoding
        ]

        # CFStringGetLength
        self._cf.CFStringGetLength.restype = self._cf_index
        self._cf.CFStringGetLength.argtypes = [ctypes.c_void_p]

        # CFStringGetCString
        self._cf.CFStringGetCString.restype = ctypes.c_bool
        self._cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p,  # string
            ctypes.c_char_p,  # buffer
            self._cf_index,   # buffer size
            ctypes.c_uint32,  # encoding
        ]

        # CFRelease
        self._cf.CFRelease.restype = None
        self._cf.CFRelease.argtypes = [ctypes.c_void_p]

        # CFArrayGetCount / CFArrayGetValueAtIndex
        self._cf.CFArrayGetCount.restype = self._cf_index
        self._cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        self._cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        self._cf.CFArrayGetValueAtIndex.argtypes = [
            ctypes.c_void_p,
            self._cf_index,
        ]

        # --- DictionaryServices (public API) ---
        self._cs.DCSCopyTextDefinition.restype = ctypes.c_void_p
        self._cs.DCSCopyTextDefinition.argtypes = [
            ctypes.c_void_p,  # dictionary (NULL = all active)
            ctypes.c_void_p,  # text (CFStringRef)
            CFRange,          # range
        ]

        # --- Private APIs (may not exist on all macOS versions) ---
        self._has_private_api = False
        try:
            self._cs.DCSCopyAvailableDictionaries.restype = ctypes.c_void_p
            self._cs.DCSCopyAvailableDictionaries.argtypes = []

            self._cs.DCSDictionaryGetName.restype = ctypes.c_void_p
            self._cs.DCSDictionaryGetName.argtypes = [ctypes.c_void_p]

            self._cs.DCSDictionaryGetShortName.restype = ctypes.c_void_p
            self._cs.DCSDictionaryGetShortName.argtypes = [ctypes.c_void_p]

            self._has_private_api = True
        except AttributeError:
            pass

    # --- Encoding constant ---
    _kCFStringEncodingUTF8 = 0x08000100

    def _make_cfstring(self, text: str) -> ctypes.c_void_p:
        """Create a CFStringRef from a Python string."""
        encoded = text.encode("utf-8")
        cf_str = self._cf.CFStringCreateWithCString(
            None, encoded, self._kCFStringEncodingUTF8
        )
        if not cf_str:
            raise DictionaryServicesError(f"Failed to create CFString for: {text}")
        return cf_str

    def _cfstring_to_python(self, cf_str: ctypes.c_void_p) -> Optional[str]:
        """Convert a CFStringRef to a Python string."""
        if not cf_str:
            return None
        length = self._cf.CFStringGetLength(cf_str)
        buf_size = length * 4 + 1
        buf = ctypes.create_string_buffer(buf_size)
        success = self._cf.CFStringGetCString(
            cf_str, buf, buf_size, self._kCFStringEncodingUTF8
        )
        if success:
            return buf.value.decode("utf-8")
        return None

    # ------------------------------------------------------------------
    # Dictionary enumeration
    # ------------------------------------------------------------------

    def list_dictionaries(self) -> List[Tuple[str, str]]:
        """
        List all available dictionaries (requires private API).
        Returns list of (name, short_name) tuples.
        """
        if not self._has_private_api:
            return []

        result = []
        dicts_array = self._cs.DCSCopyAvailableDictionaries()
        if not dicts_array:
            return []

        try:
            count = self._cf.CFArrayGetCount(dicts_array)
            for i in range(count):
                dict_ref = self._cf.CFArrayGetValueAtIndex(dicts_array, i)
                if not dict_ref:
                    continue
                name_ref = self._cs.DCSDictionaryGetName(dict_ref)
                short_ref = self._cs.DCSDictionaryGetShortName(dict_ref)
                name = self._cfstring_to_python(name_ref) or "Unknown"
                short = self._cfstring_to_python(short_ref) or "Unknown"
                result.append((name, short))
        finally:
            self._cf.CFRelease(dicts_array)

        return result

    def _get_dict_ref_by_name(self, name_substring: str) -> Optional[ctypes.c_void_p]:
        """
        Find a specific dictionary by (partial) name match.
        Returns the DCSDictionaryRef or None.
        """
        if not self._has_private_api:
            return None

        # Check cache first
        if name_substring in self._dict_cache:
            return self._dict_cache[name_substring]

        dicts_array = self._cs.DCSCopyAvailableDictionaries()
        if not dicts_array:
            return None

        found = None
        try:
            count = self._cf.CFArrayGetCount(dicts_array)
            for i in range(count):
                dict_ref = self._cf.CFArrayGetValueAtIndex(dicts_array, i)
                if not dict_ref:
                    continue
                name_ref = self._cs.DCSDictionaryGetName(dict_ref)
                name = self._cfstring_to_python(name_ref) or ""
                if name_substring in name:
                    found = dict_ref
                    self._dict_cache[name_substring] = found
                    break
        finally:
            # NOTE: we intentionally do NOT release dicts_array here because
            # the dict_ref pointers inside it become invalid after release.
            # This is a small intentional leak to keep cached refs alive.
            pass

        return found

    # ------------------------------------------------------------------
    # Dictionary selection
    # ------------------------------------------------------------------

    def select_dictionary(self, name_substring: Optional[str]):
        """
        Select a specific dictionary by partial name match.

        Pass None to use all active dictionaries (default behavior).

        Examples:
            d.select_dictionary("现代汉语规范词典")
            d.select_dictionary("Oxford")
            d.select_dictionary(None)  # use all
        """
        self._selected_dict_name = name_substring

    def get_selected_dictionary(self) -> Optional[str]:
        """Return the currently selected dictionary name filter, or None for all."""
        return self._selected_dict_name

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, word: str) -> Optional[str]:
        """
        Look up a word. Uses the selected dictionary if one is set,
        otherwise searches all active dictionaries.
        """
        # If a specific dictionary is selected, try the private API first
        if self._selected_dict_name and self._has_private_api:
            result = self._lookup_in_dict(word, self._selected_dict_name)
            if result is not None:
                return result
            # Fall through to public API if private lookup failed

        return self._lookup_all(word)

    def _lookup_all(self, word: str) -> Optional[str]:
        """Look up using the public API (all active dictionaries)."""
        cf_word = self._make_cfstring(word)
        try:
            word_len = self._cf.CFStringGetLength(cf_word)
            search_range = CFRange(0, word_len)
            result = self._cs.DCSCopyTextDefinition(None, cf_word, search_range)
            if not result:
                return None
            try:
                return self._cfstring_to_python(result)
            finally:
                self._cf.CFRelease(result)
        finally:
            self._cf.CFRelease(cf_word)

    def _lookup_in_dict(self, word: str, dict_name: str) -> Optional[str]:
        """
        Look up in a specific dictionary via the private API.

        Uses DCSCopyTextDefinition with a non-NULL dictionary ref.
        The public API docs say the first param is "reserved", but in
        practice passing a DCSDictionaryRef works to scope the search.
        """
        dict_ref = self._get_dict_ref_by_name(dict_name)
        if not dict_ref:
            return None

        cf_word = self._make_cfstring(word)
        try:
            word_len = self._cf.CFStringGetLength(cf_word)
            search_range = CFRange(0, word_len)
            result = self._cs.DCSCopyTextDefinition(dict_ref, cf_word, search_range)
            if not result:
                return None
            try:
                return self._cfstring_to_python(result)
            finally:
                self._cf.CFRelease(result)
        finally:
            self._cf.CFRelease(cf_word)
