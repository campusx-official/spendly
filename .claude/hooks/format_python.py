#!/usr/bin/env python3
"""PostToolUse hook - runs black on any .py file Claude writes or edits.

Extracted from an inline one-liner in settings.json so it is readable and
testable. Behaviour is unchanged except that a missing black is now reported
once on stderr instead of failing silently.

black is a dev-only tool and is deliberately not in requirements.txt. Install it
with `pip install black` (or via requirements-dev.txt) or this hook no-ops.
"""

import json
import subprocess
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path.endswith(".py"):
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "black", "--quiet", path],
        capture_output=True,
        text=True,
    )

    # Exit 1 from black is a formatting error in the file; exit 5 / "No module"
    # means black is not installed. Surface the latter rather than hiding it.
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        hint = detail[-1] if detail else f"black exited {result.returncode}"
        if "No module named black" in (result.stderr or ""):
            hint = "black is not installed - run `pip install black` to enable auto-format"
        print(f"format_python hook: {hint}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
