---
description: Commit, push, create PR, merge, and clean up after a feature is complete
allowed-tools: Read, Bash, mcp__github__create_pull_request, mcp__github__merge_pull_request, mcp__github__delete_branch
---

## Step 1 — Identify current branch
```bash
git branch --show-current
```
Store this as CURRENT_BRANCH.

## Step 2 — Generate commit message
Run:
```bash
git diff --staged
git diff
git log main..HEAD --oneline
```
Read .claude/specs/ to find the spec for the current feature.

Generate a Conventional Commit message:
- feat: new feature
- fix: bug fix
- chore: config or tooling
- docs: documentation only

Rules:
- Lowercase
- No period at the end
- Under 72 characters
- Describes what the user can now do, not what the code does

Good: "feat: add delete expense button with confirmation dialog"
Bad: "feat: added DELETE route to app.py"

## Step 3 — Commit
```bash
git add .
git commit -m "<generated-message>"
```
Report: "✓ Committed — <message>"

## Step 4 — Push to feature branch
```bash
git push -u origin CURRENT_BRANCH
```
Report: "✓ Pushed — CURRENT_BRANCH"

## Step 5 — Create PR via GitHub MCP
Use the GitHub MCP server to create a pull request
from CURRENT_BRANCH into main.

Title: plain English feature name, no conventional commit prefix
Example: "Add delete expense functionality"

Description:
```markdown
## What this PR does
<one paragraph from the spec overview section>

## Changes
<bullet list of every file changed with one line description each>

## Definition of done
<copy the definition of done checklist from the spec,
mark every item as checked [x]>

## How to test
1. Run python app.py
2. Log in as demo@spendly.com / demo123
3. <specific steps from the spec to verify this feature works>
```

Report: "✓ PR created — <PR URL>"

## Step 6 — Merge PR via GitHub MCP
Use the GitHub MCP server to merge the pull request
just created. Use squash merge.

Report: "✓ PR merged to main"

## Step 7 — Delete remote branch via GitHub MCP
Use the GitHub MCP server to delete CURRENT_BRANCH
from GitHub after the merge.

Report: "✓ Remote branch deleted"

## Step 8 — Switch to main and pull
```bash
git checkout main
git pull origin main
```
Report: "✓ Switched to main — up to date"

## Step 9 — Delete local feature branch
```bash
git branch -D CURRENT_BRANCH
```
Report: "✓ Local branch deleted"

## Final summary
Print:
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
/ship-feature complete
✓ Committed — <message>
✓ Pushed — <branch>
✓ PR created and merged
✓ Remote branch deleted
✓ Switched to main
✓ Local branch deleted
Next: run /create-spec for the next feature
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌

## Rules
- Never commit directly to main
- Always use squash merge
- Always delete both remote and local branch after merge
- If GitHub MCP is not connected stop and say:
  "GitHub MCP is not connected. Run /mcp to check connection."
- If push fails due to no upstream, use git push -u origin CURRENT_BRANCH
- Never proceed to merge if PR creation fails