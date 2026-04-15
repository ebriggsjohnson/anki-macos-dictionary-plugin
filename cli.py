#!/usr/bin/env python3
"""
Standalone CLI for looking up Chinese words from macOS dictionaries and/or MOE dict.

Usage:
    python3 cli.py 学习 被 规矩
    python3 cli.py --source macos 学习
    python3 cli.py --source moe 學習
    python3 cli.py --source both --file words.txt --output defs.csv
    python3 cli.py --raw 学习
    python3 cli.py --list-dicts
    python3 cli.py --parts pos,definitions,examples 学习

Parts: pinyin, bopomofo, pos, definitions, examples, usage_notes
"""

import argparse
import csv
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(
        description="Look up Chinese words — macOS dictionaries and/or MOE 國語辭典"
    )
    parser.add_argument("words", nargs="*", help="Chinese words to look up")
    parser.add_argument("--file", "-f", help="Read words from file (one per line)")
    parser.add_argument("--stdin", action="store_true", help="Read words from stdin")
    parser.add_argument("--output", "-o", help="Write CSV to file (default: stdout)")
    parser.add_argument(
        "--source", "-s", choices=["macos", "moe", "both"], default="both",
        help="Dictionary source (default: both)"
    )
    parser.add_argument(
        "--parts", "-p", default="pos,definitions,examples",
        help="Comma-separated parts to include: pinyin,bopomofo,pos,definitions,examples,usage_notes"
    )
    parser.add_argument("--raw", action="store_true", help="Print raw text (macOS only)")
    parser.add_argument("--list-dicts", action="store_true", help="List available dictionaries")
    parser.add_argument("--html", action="store_true", help="Output formatted HTML (default for CSV)")
    parser.add_argument("--dict", "-d", help="Select specific macOS dictionary by partial name")

    args = parser.parse_args()
    parts = set(args.parts.split(","))

    # --- List dicts mode ---
    if args.list_dicts:
        _list_dicts()
        return

    # --- Gather words ---
    words = list(args.words) if args.words else []
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                w = line.strip()
                if w and not w.startswith("#"):
                    words.append(w)
    if args.stdin:
        for line in sys.stdin:
            w = line.strip()
            if w:
                words.append(w)

    if not words:
        parser.print_help()
        sys.exit(1)

    # --- Raw mode (macOS only) ---
    if args.raw:
        from dict_lookup import MacOSDictionary
        d = MacOSDictionary()
        if args.dict:
            d.select_dictionary(args.dict)
        for word in words:
            result = d.lookup(word)
            print(f"=== {word} ===")
            print(result or "[Not found]")
            print()
        return

    # --- Formatted lookup ---
    use_macos = args.source in ("macos", "both")
    use_moe = args.source in ("moe", "both")

    macos_dict = None
    moe_client = None

    if use_macos:
        try:
            from dict_lookup import MacOSDictionary
            macos_dict = MacOSDictionary()
            if args.dict:
                macos_dict.select_dictionary(args.dict)
        except Exception as e:
            print(f"macOS dict unavailable: {e}", file=sys.stderr)

    if use_moe:
        try:
            from moedict import MoedictClient
            moe_client = MoedictClient()
            mode = "offline" if moe_client.is_offline else "online"
            print(f"MOE dict: {mode}", file=sys.stderr)
        except Exception as e:
            print(f"MOE dict unavailable: {e}", file=sys.stderr)

    if not macos_dict and not moe_client:
        print("No dictionary sources available.", file=sys.stderr)
        sys.exit(1)

    from formatter import format_macos_entry, format_moe_entry_from_db
    from convert import to_simplified, to_traditional

    out_file = (
        open(args.output, "w", encoding="utf-8-sig", newline="")
        if args.output else sys.stdout
    )

    writer = csv.writer(out_file)
    header = ["Word"]
    if macos_dict:
        header.append("macOS Definition")
    if moe_client:
        header.append("MOE Definition")
    writer.writerow(header)

    for word in words:
        row = [word]

        if macos_dict:
            simp_word = to_simplified(word)
            raw = macos_dict.lookup(simp_word)
            if not raw and simp_word != word:
                raw = macos_dict.lookup(word)
            if raw:
                row.append(format_macos_entry(simp_word, raw, parts))
            else:
                row.append("")

        if moe_client:
            trad_word = to_traditional(word)
            if moe_client.is_offline and moe_client._conn:
                html = format_moe_entry_from_db(trad_word, moe_client._conn, parts)
                if not html and trad_word != word:
                    html = format_moe_entry_from_db(word, moe_client._conn, parts)
            else:
                entry = moe_client.lookup_parsed(trad_word)
                if entry and entry.raw_json:
                    from formatter import format_moe_entry_online
                    html = format_moe_entry_online(trad_word, entry.raw_json, parts)
                else:
                    html = ""
            row.append(html)

        writer.writerow(row)

    if args.output:
        out_file.close()
        print(f"Wrote {len(words)} entries to {args.output}", file=sys.stderr)


def _list_dicts():
    try:
        from dict_lookup import MacOSDictionary
        d = MacOSDictionary()
        dicts = d.list_dictionaries()
        if dicts:
            print("macOS Dictionaries:")
            kw = ["汉语", "漢語", "Chinese", "國語", "中文", "辭典", "词典"]
            for name, short in sorted(dicts):
                mark = " ✓" if any(k in name for k in kw) else ""
                print(f"  {name} ({short}){mark}")
        else:
            print("macOS: could not enumerate (private API unavailable)")
    except Exception as e:
        print(f"macOS: unavailable ({e})")

    print()

    try:
        from moedict import MoedictClient
        c = MoedictClient()
        mode = "offline (SQLite)" if c.is_offline else "online (API)"
        print(f"MOE 教育部重編國語辭典: {mode}")
    except Exception as e:
        print(f"MOE: unavailable ({e})")


if __name__ == "__main__":
    main()
