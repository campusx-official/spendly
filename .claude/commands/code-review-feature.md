---
description: Runs parallel security and quality code 
  review for a specific Spendly feature. Pass the spec 
  name as argument e.g. /code-review-feature 03-login
allowed-tools: Bash(git diff), Bash(git diff --staged), Bash(git status), Read, Glob
---

Run the full code review pipeline for the feature 
specified in $ARGUMENTS.

If no argument is provided, stop immediately and say:
"Please provide a spec name. Usage: /code-review-feature 
<spec-name> e.g. /code-review-feature 03-login"

## Pre-flight Check

Before invoking any subagents, collect **everything that changed** — not just the
diff. A feature that adds new files produces an empty `git diff`, so a
diff-only pre-flight would wrongly report "no changes".

- Run `git status --porcelain` to list new (`??`) and modified files
- Run `git diff` for unstaged changes to tracked files
- Run `git diff --staged` for staged changes
- For each untracked file, `Read` it in full — that is its diff

Combine into a single change set and pass the file list to both reviewers.

If all three are empty, stop immediately and say:
"No changes detected. Implement the feature before running code review."

**If the change set is only deployment artifacts** (Dockerfile, `compose.yaml`,
`deploy/**`, `.github/workflows/**`), stop and say:
"These are deployment artifacts. Use `/deploy-phase <phase>` — it runs
spendly-devops-reviewer, which audits against the deploy checklists. This command
reviews application code."

If it is a **mix**, review the application code here and say in the final report
which deploy artifacts were skipped and why.

---

## Step 1: Parallel Review

Invoke both subagents simultaneously with the same 
context:

**spendly-security-reviewer** receives:
- The combined diff from the pre-flight check
- Spec file for context: `.claude/specs/$ARGUMENTS.md`
- Source files to reference: `app.py` and 
  `database/` directory
- Instruction: Review only the changed code for 
  security vulnerabilities. Do not comment on quality 
  or style.

**spendly-quality-reviewer** receives:
- The combined diff from the pre-flight check
- Spec file for context: `.claude/specs/$ARGUMENTS.md`
- Source files to reference: `app.py`, `database/` 
  directory, and `templates/` directory
- Instruction: Review only the changed code for quality, 
  Flask best practices, and maintainability. Do not 
  comment on security concerns.

Both subagents must run in parallel. Do not wait for 
one to finish before starting the other.

---

## Step 2: Unified Report

Once both subagents have completed, combine their 
findings into a single unified report. De-duplicate 
any overlapping findings — if both agents flagged the 
same line for different reasons, merge them into one 
finding with both perspectives noted.

Structure the combined report as:
Code Review Report — $ARGUMENTS
Security Findings
[spendly-security-reviewer output]
Quality Findings
[spendly-quality-reviewer output]
Combined Action Plan
Ordered checklist of everything that needs to be fixed,
prioritized by severity:

[Critical/High security findings first]
[Quality CHANGES REQUESTED items second]
[Medium/Low security findings third]
[Quality APPROVED WITH SUGGESTIONS items last]

Overall Verdict
APPROVED — ready to commit
APPROVED WITH SUGGESTIONS — can commit, address
suggestions in future steps
CHANGES REQUESTED — must fix before committing,
see action plan above
---

## Step 3: Ask for Approval

After presenting the unified report, ask:

"Do you want me to implement the action plan now?"

Wait for explicit user confirmation before making 
any changes. Do not touch any files until the user 
approves.

---

## Rules
- Do NOT edit any files before user approval
- Do NOT start one reviewer before the other — 
  both must run in parallel
- Do NOT skip the pre-flight diff check
- Do NOT proceed if the spec file at 
  `.claude/specs/$ARGUMENTS.md` does not exist — 
  report it and stop
- If either subagent fails or returns no output, 
  report it and do not present a partial review 
  as complete
