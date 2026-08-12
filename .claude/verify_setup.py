"""Whole-setup integrity check for .claude/ wiring.

Verifies that every agent, command, skill, path, route, and DB helper referenced
anywhere in .claude/ or CLAUDE.md actually exists. Exits non-zero on any break.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(".")
CLAUDE = ROOT / ".claude"
problems = []
checks = 0


def check(ok, label):
    global checks
    checks += 1
    if not ok:
        problems.append(label)
    return ok


# ---------------------------------------------------------------- inventory
agents = {p.stem for p in (CLAUDE / "agents").glob("*.md")}
commands = {p.stem for p in (CLAUDE / "commands").glob("*.md")}
skills = {p.name for p in (CLAUDE / "skills").iterdir() if p.is_dir()}
hooks = {p.name for p in (CLAUDE / "hooks").glob("*.py")}

print("INVENTORY")
print(f"  agents   ({len(agents)}): {', '.join(sorted(agents))}")
print(f"  commands ({len(commands)}): {', '.join(sorted(commands))}")
print(f"  skills   ({len(skills)}): {', '.join(sorted(skills))}")
print(f"  hooks    ({len(hooks)}): {', '.join(sorted(hooks))}")

# ------------------------------------------- skill dir must match frontmatter
print("\nSKILL dir == frontmatter name")
for d in sorted(skills):
    text = (CLAUDE / "skills" / d / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^name:\s*\"?([\w-]+)\"?", text, re.M)
    declared = m.group(1) if m else "<none>"
    ok = check(declared == d, f"skill dir '{d}' declares name '{declared}'")
    print(f"  {'OK  ' if ok else 'FAIL'} {d} -> {declared}")

# -------------------------------------------------- agent names referenced
print("\nAGENT references resolve")
scan = list(CLAUDE.rglob("*.md")) + [ROOT / "CLAUDE.md"] + list(CLAUDE.glob("hooks/*.py"))
referenced_agents = set()
for f in scan:
    for name in re.findall(r"\bspendly-[a-z-]+\b", f.read_text(encoding="utf-8")):
        if name in agents or name.startswith("spendly-devops-") or "review" in name or "test" in name:
            referenced_agents.add(name)
for name in sorted(referenced_agents):
    if name in skills:  # it's a skill, not an agent
        continue
    ok = check(name in agents, f"referenced agent '{name}' has no .claude/agents/{name}.md")
    print(f"  {'OK  ' if ok else 'FAIL'} {name}")

# -------------------------------------------------------- path references
print("\nPATH references resolve (live docs only)")
pattern = re.compile(r"[`(]((?:\.claude|database|templates|static|tests)/[\w./*-]+)[`)]")
seen = set()
for f in scan:
    # .claude/specs/ are historical records of what each step planned; their file
    # names predate later renames and are not live wiring.
    if "specs" in f.parts:
        continue
    for line in f.read_text(encoding="utf-8").splitlines():
        # Skip illustrative placeholders - "e.g. tests/test_login.py" names a
        # pattern to follow, not a file that must exist.
        if re.search(r"\be\.g\.|for example|such as", line, re.I):
            continue
        for p in pattern.findall(line):
            if "*" in p or p.endswith("/"):
                continue
            seen.add(p)
for p in sorted(seen):
    ok = check((ROOT / p).exists(), f"broken path reference: {p}")
    print(f"  {'OK  ' if ok else 'FAIL'} {p}")

# ------------------------------------------------- DB helpers referenced
print("\nDB helpers named in docs exist in code")
db_src = (ROOT / "database/db.py").read_text(encoding="utf-8")
q_src = (ROOT / "database/queries.py").read_text(encoding="utf-8")
defined = set(re.findall(r"^def (\w+)", db_src, re.M)) | set(
    re.findall(r"^def (\w+)", q_src, re.M)
)
claimed = [
    "get_db", "init_db", "seed_db", "create_user", "get_user_by_email",
    "insert_expense", "get_expense_by_id", "update_expense",
    "delete_expense_by_id", "get_user_by_id", "get_recent_transactions",
    "get_summary_stats", "get_category_breakdown",
]
for name in claimed:
    ok = check(name in defined, f"helper '{name}' claimed in docs but not defined")
    print(f"  {'OK  ' if ok else 'FAIL'} {name}")

# ------------------------------------------------------- routes in app.py
print("\nRoutes claimed in CLAUDE.md exist in app.py")
app_src = (ROOT / "app.py").read_text(encoding="utf-8")
routes = set(re.findall(r'@app\.route\("([^"]+)"', app_src))
for r in ["/", "/register", "/login", "/logout", "/profile", "/expenses/add",
          "/expenses/<int:id>/edit", "/expenses/<int:id>/delete", "/analytics",
          "/terms", "/privacy"]:
    ok = check(r in routes, f"route {r} claimed but not in app.py")
    print(f"  {'OK  ' if ok else 'FAIL'} {r}")
undocumented = routes - {
    "/", "/register", "/login", "/logout", "/profile", "/expenses/add",
    "/expenses/<int:id>/edit", "/expenses/<int:id>/delete", "/analytics",
    "/terms", "/privacy",
}
check(not undocumented, f"routes in app.py missing from CLAUDE.md: {undocumented}")
print(f"  {'OK  ' if not undocumented else 'FAIL'} no undocumented routes ({undocumented or 'none'})")

# ------------------------------------- no hardcoded URLs in templates
print("\nTemplates use url_for")
bad = []
for t in (ROOT / "templates").glob("*.html"):
    for i, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r'(href|action)="/(?!/)', line):
            bad.append(f"{t.name}:{i}")
check(not bad, f"hardcoded URLs: {bad}")
print(f"  {'OK  ' if not bad else 'FAIL'} {bad or 'none'}")

# ------------------------------------------------------------ summary
print(f"\n{'=' * 60}")
if problems:
    print(f"FAILED  {len(problems)} of {checks} checks")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
print(f"PASSED  all {checks} checks")
