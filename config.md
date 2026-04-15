# Chinese Dict config

- **auto_generate**: master switch for auto-fill as you type. Can also be toggled via the 典 button in the editor toolbar.
- **overwrite_existing**: if true, re-running lookup clobbers fields that already have content. Default false — only fills empty fields.
- **input_field_keywords**: field-name substrings that identify the "word" field (what gets looked up).
- **macos_field_keywords** / **moe_field_keywords**: field-name substrings that identify the target fields for each source.
- **macos_def_keywords**: fallback keywords for the macOS target field if no more-specific match is found.
- **macos_parts** / **moe_parts**: default parts to include in the formatted HTML entry. Valid values: `pinyin`, `bopomofo`, `pos`, `definitions`, `examples`, `usage_notes`.
- **per_note_type**: overrides per note type name. Example:
  ```json
  "per_note_type": {
    "MyChineseCard": {
      "input_field": "Front",
      "macos_field": "Xiandai Hanyu Def",
      "moe_field": "MOE Def"
    }
  }
  ```
