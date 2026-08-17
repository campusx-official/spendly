# tests/test_hooks.py
#
# Regression coverage for the Claude Code hooks in .claude/hooks/.
#
# These are not Spendly features, but they gate every Bash call and every prompt
# in a session, so a bug in them is expensive: protect_paths.py shipped with five
# separate false positives, each of which blocked an ordinary command.
#
#   git add -A                  "dd" verb matched inside "add"
#   echo 'confirm ...'          "rm" verb matched inside "confirm"
#   -> arrows in prose          read as a truncating redirect
#   >/dev/null                  same, on a discard redirect
#   <noreply@anthropic.com>     closing > of an angle-bracketed email
#
# Every one is pinned below. Note also that the guard matches substrings of the
# command text, which is why these cases live in a file: a shell command that
# merely contains "rm spendly.db" as test data gets blocked by the very hook it
# is trying to exercise.
#
# The hooks are invoked as subprocesses over their real stdin/stdout JSON
# contract, so these tests exercise exactly what Claude Code exercises.

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"

BLOCK = 2
ALLOW = 0


def run_hook(script, payload):
    """Invoke a hook the way Claude Code does: JSON on stdin, exit code out."""
    result = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# protect_paths.py - PreToolUse guard
# ---------------------------------------------------------------------------


class TestProtectPaths:
    @pytest.mark.parametrize(
        "command",
        [
            'echo "" > spendly.db',          # truncating redirect
            "echo x >spendly.db",            # redirect, no space
            "rm -f spendly.db",              # real delete
            "rm -rf /var/lib/spendly",       # real delete, deploy data dir
            "truncate -s 0 .env",            # truncate
            "shred spendly.db",              # shred
            "mkfs.ext4 /var/lib/spendly",    # reformat
            "git rm spendly.db",             # git rm WITHOUT --cached deletes on disk
            # A real input+output redirect pair. The ANGLE_TOKEN strip must not
            # swallow this one, because "< input.txt >" contains whitespace.
            "cat < input.txt > spendly.db",
        ],
    )
    def test_destructive_commands_are_blocked(self, command):
        code, _, stderr = run_hook("protect_paths.py", {"tool_input": {"command": command}})
        assert code == BLOCK, f"should have blocked: {command}"
        assert "BLOCKED" in stderr, "must explain itself on stderr for the model"

    @pytest.mark.parametrize(
        "command,why",
        [
            ("git add -A", "'add' contains 'dd' but is not the dd command"),
            ("echo 'confirm spendly.db'", "'confirm' contains 'rm' but is not rm"),
            ("echo 'flow -> spendly.db'", "'->' is an arrow, not a redirect"),
            ("echo 'n => spendly.db'", "'=>' is a fat arrow, not a redirect"),
            ("ls spendly.db >/dev/null 2>&1", "discarding output destroys nothing"),
            ("cat spendly.db > /dev/null", "same, with a space"),
            ("echo log >> spendly.db", "append does not truncate"),
            ("git rm --cached spendly.db", "index-only, file stays on disk"),
            ("git rm -r --cached database/", "index-only, recursive"),
            ("cat spendly.db", "reading is not destroying"),
            ("sqlite3 spendly.db 'SELECT 1'", "querying is not destroying"),
            ("ls -la", "no protected path, no destructive verb"),
            (
                'git commit -m "touches spendly.db\n\n'
                'Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"',
                "the closing > of an email in angle brackets is not a redirect",
            ),
            (
                'gh pr create -b "see <placeholder> and spendly.db"',
                "<placeholder> is not a redirect either",
            ),
        ],
    )
    def test_safe_commands_are_allowed(self, command, why):
        code, _, _ = run_hook("protect_paths.py", {"tool_input": {"command": command}})
        assert code == ALLOW, f"false positive ({why}): {command}"

    def test_destructive_verb_without_protected_path_is_allowed(self):
        code, _, _ = run_hook(
            "protect_paths.py", {"tool_input": {"command": "rm -rf build/"}}
        )
        assert code == ALLOW, "the guard protects specific paths, not all deletes"

    def test_malformed_payload_fails_open(self):
        result = subprocess.run(
            [sys.executable, str(HOOKS / "protect_paths.py")],
            input="not json",
            capture_output=True,
            text=True,
        )
        assert result.returncode == ALLOW, "a crashing guard must not break the session"


# ---------------------------------------------------------------------------
# devops_router.py - UserPromptSubmit auto-routing
# ---------------------------------------------------------------------------


class TestDevopsRouter:
    @pytest.mark.parametrize(
        "prompt",
        [
            "can you dockerize this app so I can run it locally",
            "put this on an EC2 instance with https",
            "why is my pod stuck in Pending",
            "set up github actions to run tests on every PR",
            "how do I deploy this",
            "I want to host this on the cloud",
            "add a readiness probe",
            "the container keeps losing my data on restart",
            "we need this on an azure vm behind nginx",
            "kubectl says imagepullbackoff",
        ],
    )
    def test_devops_prompts_route(self, prompt):
        code, stdout, _ = run_hook("devops_router.py", {"prompt": prompt})
        assert code == ALLOW
        assert "devops-routing" in stdout, f"should have routed: {prompt}"
        assert "spendly-devops-engineer" in stdout, "must name the subagent"
        assert "spendly-devops" in stdout, "must name the skill"

    @pytest.mark.parametrize(
        "prompt",
        [
            "add a delete button to the transactions table",
            "run the server and check the landing page",
            "add an image to the hero section",
            "write tests for the edit expense route",
            "make the profile page look better",
            "the container div needs more padding",
            "restore the deleted expense row",
            "fix the failing sql injection tests",
            "add a chart to the analytics page",
        ],
    )
    def test_feature_work_stays_quiet(self, prompt):
        code, stdout, _ = run_hook("devops_router.py", {"prompt": prompt})
        assert code == ALLOW
        assert stdout.strip() == "", f"false positive on feature work: {prompt}"

    def test_explicit_slash_command_is_not_intercepted(self):
        code, stdout, _ = run_hook("devops_router.py", {"prompt": "/deploy-phase 1"})
        assert code == ALLOW
        assert stdout.strip() == "", "the user already chose a path"

    def test_empty_prompt_is_a_noop(self):
        code, stdout, _ = run_hook("devops_router.py", {"prompt": "   "})
        assert code == ALLOW
        assert stdout.strip() == ""


# ---------------------------------------------------------------------------
# format_python.py - PostToolUse formatter
# ---------------------------------------------------------------------------


class TestFormatPython:
    def test_non_python_file_is_ignored_silently(self):
        code, _, stderr = run_hook(
            "format_python.py", {"tool_input": {"file_path": "static/css/style.css"}}
        )
        assert code == ALLOW
        assert stderr.strip() == ""

    def test_python_file_never_fails_the_tool_call(self):
        # black may or may not be installed; either way this hook must exit 0,
        # because PostToolUse runs after the edit already happened.
        code, _, _ = run_hook(
            "format_python.py", {"tool_input": {"file_path": "app.py"}}
        )
        assert code == ALLOW
