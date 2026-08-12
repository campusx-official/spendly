---
description: Writes and runs tests for a specific Spendly feature. Pass the spec name as argument e.g. /test-feature 05-backend-connection
allowed-tools: Read, Glob, Agent, Bash(python -m pytest*)
---

Run the full testing pipeline for the feature specified 
in $ARGUMENTS.

If no argument is provided, stop immediately and say:
"Please provide a spec name. Usage: /test-feature 
<spec-name> e.g. /test-feature 05-backend-connection"

If `.claude/specs/$ARGUMENTS.md` does not exist, stop 
immediately and say:
"Spec file not found at .claude/specs/$ARGUMENTS.md. 
Please check the spec name and try again."

---

## Step 1: Write Tests

Invoke the **spendly-test-writer** subagent with the 
following context:

- Spec file to base tests on: 
  `.claude/specs/$ARGUMENTS.md`
- Source files to read for structure:
  - `app.py`
  - `database/db.py` and `database/queries.py` — the DB layer is **two** modules
- Reference test file to copy the isolation pattern from:
  `tests/test_06_date_filter_profile.py` — it patches `database.db.DB_PATH` to a
  tempfile *before* importing `app`, which is the only thing that stops a test run
  from writing to the developer's real `spendly.db`
- Output test file to create:
  `tests/test_$ARGUMENTS.py` — normalise the name to underscores
  (`test_10_foo.py`, not `test_10-foo.py`)
- Instruction: Write tests based on what the spec says 
  the feature SHOULD do. Do NOT derive test logic from 
  reading the implementation. Cover happy paths, edge 
  cases, auth guards, validation errors, and DB side 
  effects.

Wait for spendly-test-writer to fully complete and 
confirm the test file has been written before 
proceeding to Step 2.

---

## Step 2: Run Tests

Once spendly-test-writer has finished, invoke the 
**spendly-test-runner** subagent with the following 
context:

- Test file to execute:
  `tests/test_$ARGUMENTS.py`
- Spec file for context:
  `.claude/specs/$ARGUMENTS.md`
- Source files to analyze against when diagnosing 
  failures:
  - `app.py`
  - `database/` directory
- Run command:
  `python -m pytest tests/test_$ARGUMENTS.py -v`
- Known baseline: the full suite is **186 passed, 0 failed**. Any failure in the new
  file is a real defect in either the test or the feature — never dismiss one as
  pre-existing without checking `git diff`.
- Instruction: Run ONLY the specified test file. Do 
  NOT run the full test suite. Analyze any failures by 
  cross-referencing the test code, the spec, and the 
  source files. Classify each failure as a bug or a 
  missing feature.

---

## Handoff Rules

- Do NOT start Step 2 until Step 1 is fully complete
- Do NOT attempt to fix any code regardless of what 
  the test results show
- Do NOT run any tests beyond `tests/test_$ARGUMENTS.py`
- If spendly-test-writer reports it could not write 
  the test file, stop and report the reason — do NOT 
  proceed to Step 2

---

## Final Output

After both subagents complete, produce a combined 
summary:

### Testing Pipeline Report — $ARGUMENTS

**Step 1 — Tests Written**
- List each test written with a one-line description 
  of which spec requirement it validates

**Step 2 — Test Results**
- Mirror the spendly-test-runner's structured report

**Verdict**
One of:
- ✅ Ready for code review — all tests pass
- ❌ Needs fixes — list the failing tests and their root causes
