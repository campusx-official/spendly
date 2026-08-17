#!/usr/bin/env python3
"""PreToolUse hook - blocks destructive Bash commands aimed at protected paths.

Extracted from an inline one-liner in settings.json. Exit code 2 is what tells
Claude Code to deny the tool call and feed stderr back to the model.

Deliberately conservative: it blocks the obvious footguns and does not attempt to
be a sandbox. Anything that reaches a shell can still evade a substring matcher
this is a guardrail against accidents, not a security boundary.
"""

import json
import re
import sys

# Paths worth an explicit confirmation before destruction.
PROTECTED = [
    "spendly.db",
    "spendly-backup.db",
    ".env",
    "migrations/",
    # Deploy artifacts and live state added for the DevOps phases.
    "/var/lib/spendly",
    "/data/spendly.db",
    "letsencrypt",
]

# Destructive verbs. Each is matched with a leading AND trailing word boundary,
# which is load-bearing in both directions:
#   - without a leading \b, "rm" matches inside "confirm" and "dd" matches inside
#     "git add", so ordinary commands get blocked whenever they also mention a
#     protected path
#   - without a trailing \b, "dd" matches "ddrescue" and so on
DESTRUCTIVE_VERBS = [
    r"rm",
    r"unlink",
    r"truncate",
    r"shred",
    r"mkfs(\.\w+)?",
    r"dd",
]

# Shell truncation redirect (`> file`), which silently empties a file.
#
# Narrow deliberately. A bare `>` appears constantly in prose, diagrams, and
# comparisons, so this excludes:
#   ->  =>  >=  >>     arrows, fat arrows, comparisons, and appends
#                      (append does not truncate, so it is not our problem)
# and requires the target to look like a path or filename rather than any
# non-space character.
#
# `/dev/null` and friends are also excluded: discarding output is the single most
# common redirect in any script and destroys nothing.
TRUNCATING_REDIRECT = r"(?<![-=<>])>(?![>=])\s*(?!/dev/)[\w./~$'\"]"

# Angle-bracketed tokens with no internal whitespace are never redirects:
# <noreply@anthropic.com>, <placeholder>, <div>. Their closing ">" would
# otherwise read as one - which blocked a commit whose only sin was a
# Co-Authored-By trailer. Stripped before the redirect check.
#
# Requires no internal whitespace on purpose, so a genuine "cmd < in > out"
# is left intact.
ANGLE_TOKEN = r"<[^<>\s]+>"

# Operations that read as destructive but touch only git's index, leaving the
# file on disk untouched. Untracking a committed database is exactly the fix this
# repo needs, so blocking it would push people toward plumbing workarounds.
INDEX_ONLY = [
    r"git\s+rm\s+(-r\s+)?--cached\b",
    r"git\s+rm\s+--cached\b",
]


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command:
        return 0

    # Index-only git operations are safe regardless of which path they name.
    if any(re.search(p, command) for p in INDEX_ONLY):
        return 0

    hit_verb = next(
        (v for v in DESTRUCTIVE_VERBS if re.search(r"\b" + v + r"\b", command)), None
    )
    if not hit_verb and re.search(TRUNCATING_REDIRECT, re.sub(ANGLE_TOKEN, "", command)):
        hit_verb = "> redirect"
    if not hit_verb:
        return 0

    hit_path = next((p for p in PROTECTED if p in command), None)
    if not hit_path:
        return 0

    print(
        f"BLOCKED: destructive command targets a protected path: {hit_path}\n"
        f"Command was: {command}\n"
        "If this is intentional, take a backup first "
        '(sqlite3 <db> "VACUUM INTO \'<backup>\'") and tell the user what you '
        "are about to destroy before retrying.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
