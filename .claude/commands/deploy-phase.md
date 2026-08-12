---
description: Builds and audits the deployment artifacts for one Spendly phase. Pass the phase e.g. /deploy-phase 1 (docker), 2 (cloud vm), 3 (kubernetes), cicd, or 0 (prerequisite code changes)
argument-hint: "0 | 1 | 2 | 3 | cicd"
allowed-tools: Read, Glob, Grep, Bash(git status), Bash(git diff), Bash(python -m pytest*), Skill
---

Run the deployment pipeline for the phase given in $ARGUMENTS.

This command orchestrates two subagents — `spendly-devops-engineer` builds, then
`spendly-devops-reviewer` audits what was built. Both load the `spendly-devops`
skill and work from its phase references.

## Argument resolution

Accept a phase number or an alias:

| $ARGUMENTS | Phase | Reference the agents will read |
|---|---|---|
| `0`, `prep`, `phase0` | 0 — prerequisite code changes | `SKILL.md` only |
| `1`, `docker`, `container` | 1 — Docker + Compose | `references/phase-1-docker.md` |
| `2`, `vm`, `ec2`, `azure` | 2 — cloud VM | `references/phase-2-cloud-vm.md` |
| `3`, `k8s`, `kubernetes`, `eks`, `aks` | 3 — managed Kubernetes | `references/phase-3-kubernetes.md` |
| `cicd`, `ci`, `actions`, `pipeline` | CI/CD | `references/cicd.md` |

If no argument is provided, stop immediately and say:

"Please provide a phase. Usage: /deploy-phase <0|1|2|3|cicd>
  0     prerequisite code changes (env-var DB path, secret key, seed gate, health routes)
  1     Docker + Compose
  2     AWS EC2 or Azure VM
  3     managed Kubernetes (EKS / AKS)
  cicd  GitHub Actions pipelines
Phases build on each other — start at 0."

If $ARGUMENTS matches nothing in the table, report what was passed, print the same
usage block, and stop.

---

## Pre-flight

Run these before invoking any subagent.

1. **Confirm the skill exists.** Read `.claude/skills/spendly-devops/SKILL.md`. If
   it is missing, stop and say: "The spendly-devops skill is missing. The deploy
   pipeline depends on it."

2. **Show the working tree.** Run `git status --porcelain`. Report what is already
   dirty so the user can tell the agents' changes apart from their own. Do not
   block on a dirty tree — deployment work is often iterative — but if there are
   uncommitted changes, say so explicitly before proceeding.

3. **Check phase ordering.** For phases 1, 2, 3, and cicd, grep for the four
   phase-0 markers:

   - `SPENDLY_DB_PATH` in `database/db.py`
   - `SPENDLY_SECRET_KEY` in `app.py`
   - `SPENDLY_SEED` in `app.py`
   - `healthz` in `app.py`

   If any are absent, tell the user phase 0 is incomplete and that the engineer
   will implement it as part of this run. Do not stop — the engineer is instructed
   to close phase 0 first. Just make it visible.

4. **Baseline the test suite.** Run `python -m pytest -q`. Record the pass/fail
   counts so a regression introduced by phase 0 is attributable. Three failures in
   `tests/test_06_date_filter_profile.py::TestQueryHelpers` are known and
   pre-existing — see `SKILL.md`. Any other failure: report it and ask whether to
   continue before invoking the engineer.

---

## Step 1 — Build

Invoke the **`spendly-devops-engineer`** subagent with:

- The resolved phase number and name
- The reference file it must read, from the table above
- The pre-flight results: dirty files, phase-0 marker status, pytest baseline
- Any specifics the user gave — domain name, cloud, region, registry, instance
  type, cluster name. If the user gave none and the phase needs them, instruct the
  agent to use clearly-marked `<placeholder>` values rather than inventing
  realistic-looking ones.
- Instruction: load the `spendly-devops` skill first, close phase 0 if it is open,
  then produce only this phase's artifacts. Do not commit, push, or mutate live
  cloud or cluster state.

Wait for it to finish and confirm which files it wrote before continuing.

If it reports it could not proceed, stop and report why. Do not run the reviewer
on nothing.

---

## Step 2 — Audit

Invoke the **`spendly-devops-reviewer`** subagent with:

- The same phase and reference file
- The list of files the engineer wrote or changed
- Instruction: load the `spendly-devops` skill, audit against that phase's
  verification checklist and failure-mode table, and report read-only findings.
  Do not edit anything.

The reviewer must run **after** the engineer, on what the engineer produced —
these two are sequential, unlike the parallel pair in `/code-review-feature`.

---

## Step 3 — Unified report

Combine both agents' output into one report. De-duplicate: if the engineer already
flagged something in "Flagged for the user" and the reviewer raised it too, merge
into a single entry noting both.

```
Deploy Pipeline — Phase <N>: <name>

## Phase 0 status
[the four markers: present / implemented this run]

## Files written
[from the engineer, path + one line each]

## Application changes
[from the engineer, file:line + why]

## Review findings
🔴 Critical      [count + one line each]
🟠 Runtime       [count + one line each]
🟠 Constraint    [CLAUDE.md violations]
🟡 Suggestions   [count]
✅ Done right    [what the reviewer confirmed correct]

## Test suite
[baseline vs after, and whether phase 0 changed anything]

## Action plan
[Ordered checklist, most severe first: 🔴, then 🟠 runtime, then 🟠 constraint,
then 🟡. Empty list is a valid and good outcome — say so.]

## Verdict
✅ APPROVED — artifacts ready, next step is <specific command>
🟡 APPROVED WITH SUGGESTIONS — deployable, 🟡 items can wait
❌ CHANGES REQUESTED — 🔴 or 🟠 present, fix before deploying

## Handover
- **Done:** what now exists and works
- **Not done / not verified:** be explicit
- **Next:** the exact command to run, or `/deploy-phase <next>`
- **Needs your decision:** new dependencies, CLAUDE.md amendments, the SQLite
  scaling question at phase 3 — or "nothing"
```

---

## Step 4 — Hand back

After the report, ask:

"Do you want me to apply the action plan now?"

Wait for explicit confirmation before changing anything. Then stop and return
control — do not roll into the next phase, do not commit, do not deploy.

---

## Rules

- Do NOT edit files yourself. The engineer writes; the reviewer reads; you
  orchestrate and report.
- Do NOT run the reviewer before the engineer, or in parallel with it.
- Do NOT commit, push, tag, or open a PR. That is `/ship-feature`.
- Do NOT run `kubectl apply`, `docker push`, `terraform apply`, `aws`, or `az`
  against real state. Print the command; let the user run it.
- Do NOT skip pre-flight, and do NOT present a partial pipeline as complete. If
  either subagent fails or returns nothing, say which one and stop.
- Do NOT proceed past phase 3 into a datastore migration. If the user wants
  horizontal scale, surface the options table from `SKILL.md` and stop for a
  decision — "SQLite only" is a `CLAUDE.md` rule and changing it is the user's
  call.
- If the artifacts for the requested phase already exist, say so and ask whether
  to review-only, update, or regenerate — do not silently overwrite.
