#!/usr/bin/env python3
"""
PostToolUse hook for TrintzERP.

Runs after Claude edits/writes a file and does a fast, targeted sanity check
based on the file type:
  - .py  -> ast.parse (catches syntax errors immediately)
  - .js  -> node vm compile check
  - styles.css -> brace balance ({ count == } count)

Reads the hook payload (JSON) from stdin. Emits a non-zero exit + message on
stdout only when something is wrong, so a clean edit stays silent.

This encodes the manual checks we ran after every edit during development.
"""
import json
import os
import subprocess
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # no payload -> nothing to check

    # tool_input holds the file path for Edit/Write
    ti = payload.get("tool_input", {}) or {}
    path = ti.get("file_path") or ti.get("path")
    if not path or not os.path.isfile(path):
        return 0

    ext = os.path.splitext(path)[1].lower()
    base = os.path.basename(path)

    try:
        text = open(path, encoding="utf-8").read()
    except Exception:
        return 0

    # ── Python ─────────────────────────────────────────────────────────────
    if ext == ".py":
        import ast
        try:
            ast.parse(text)
        except SyntaxError as e:
            print(f"[syntax-check] Python syntax error in {base}: "
                  f"line {e.lineno}: {e.msg}")
            return 2  # exit 2 => surfaced to Claude as feedback
        return 0

    # ── JavaScript ─────────────────────────────────────────────────────────
    if ext == ".js":
        try:
            r = subprocess.run(
                ["node", "-e",
                 "new (require('vm').Script)("
                 "require('fs').readFileSync(process.argv[1],'utf8'))",
                 path],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode != 0:
                first = (r.stderr.strip().splitlines() or ["parse error"])[0]
                print(f"[syntax-check] JS syntax error in {base}: {first}")
                return 2
        except FileNotFoundError:
            return 0  # node not installed -> skip silently
        except Exception:
            return 0
        return 0

    # ── styles.css: brace balance ──────────────────────────────────────────
    if base == "styles.css":
        opens, closes = text.count("{"), text.count("}")
        if opens != closes:
            print(f"[syntax-check] styles.css brace imbalance: "
                  f"{opens} '{{' vs {closes} '}}' — a rule is likely unclosed.")
            return 2
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
