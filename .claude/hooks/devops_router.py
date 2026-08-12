#!/usr/bin/env python3
"""UserPromptSubmit hook - auto-routes DevOps-shaped prompts to the Spendly
DevOps pipeline, so a teammate who has never heard of /deploy-phase still gets
the skill, the subagent, and the handover protocol.

Contract: reads the hook payload as JSON on stdin. For UserPromptSubmit, anything
printed to stdout is injected into the model's context before it sees the prompt.
Printing nothing is a no-op.

Fails open, always. A hook that crashes the session is worse than a hook that
misses a match, so every error path exits 0 silently.
"""

import json
import re
import sys

# Patterns are anchored at the START of a word only, so "docker" catches
# "dockerize" and "dockerfile", and "deploy" catches "deployment". Short or
# ambiguous acronyms carry their own trailing \b - without it `acr` matches
# "across".
#
# Unambiguous infrastructure vocabulary - any single hit routes.
STRONG = [
    r"docker",  # docker, dockerfile, dockerize, dockerignore, docker-compose
    r"compose\.ya?ml",
    r"containeri[sz]",  # containerise/containerize/containerized
    r"deploy",  # deploy, deploys, deployment, deploying
    r"k8s\b",
    r"kubernetes",
    r"kubectl",
    r"kustomize",
    r"helm\b",
    r"eks\b",
    r"aks\b",
    r"gke\b",
    r"pvc\b",
    r"persistent ?volume",
    r"ingress",
    r"statefulset",
    r"daemonset",
    r"pods?\b",
    r"crashloopbackoff",
    r"imagepullbackoff",
    r"ec2\b",
    r"azure vm",
    r"nginx",
    r"certbot",
    r"let'?s ?encrypt",
    r"systemd",
    r"gunicorn",
    r"wsgi\b",
    r"waitress",
    r"ecr\b",
    r"acr\b",
    r"github ?action",
    r"oidc\b",
    r"terraform",
    r"cloudformation",
    r"bicep\b",
    r"healthz",
    r"readyz",
    r"liveness",
    r"readiness",
    r"hpa\b",
    r"autoscal",
    r"load ?balanc",
    r"security group",
    r"ebs\b",
    r"managed disk",
    r"self.?host",
    r"on.?prem",
]

# Ambiguous in a Flask app - "run the server", "add an image to the hero",
# ".container needs padding". Two or more DISTINCT hits are needed before
# routing, which is what keeps everyday feature work quiet.
WEAK = [
    r"host",
    r"production",
    r"staging",
    r"roll ?out",
    r"ship",
    r"go live",
    r"scal(e|ing)",
    r"container",
    r"image",
    r"volume",
    r"backup",
    r"restore",
    r"snapshot",
    r"persist",
    r"restart",
    r"pipeline",
    r"ci/?cd",
    r"cluster",
    r"server",
    r"vm\b",
    r"cloud",
    r"aws\b",
    r"azure",
    r"replica",
    r"probe",
    r"registry",
    r"secret ?key",
    r"env(ironment)? ?var",
    r"infra",
    r"monitor",
    r"observability",
    r"uptime",
    r"downtime",
]

GUIDANCE = """\
<devops-routing source=".claude/hooks/devops_router.py">
This prompt matched Spendly DevOps triggers ({hits}). Handle it through the
DevOps pipeline rather than ad hoc:

1. Load the `spendly-devops` skill BEFORE producing any artifact. If the Skill
   tool is unavailable, read `.claude/skills/spendly-devops/SKILL.md` plus the
   phase file it routes you to under `.claude/skills/spendly-devops/references/`.
2. Delegate the work to the `spendly-devops-engineer` subagent via the Agent
   tool. For audit-only requests use `spendly-devops-reviewer` instead.
3. Phase 0 in SKILL.md is a hard prerequisite for phases 1-3. Verify it before
   writing a Dockerfile, manifest, or workflow.
4. When the subagent returns, relay its `## Handover` block to the user in your
   own words - what changed, what is verified, what is still open - then stop and
   await direction.
5. Never commit, push, or touch live cloud or cluster state without explicit
   approval in this conversation.

The explicit equivalent is `/deploy-phase <0|1|2|3|cicd>`, which also runs the
reviewer. Mention it once so the user knows it exists.
</devops-routing>"""


def matches(patterns, text):
    """Distinct patterns that hit, as readable labels for the report line."""
    found = []
    for pattern in patterns:
        if re.search(r"\b" + pattern, text):
            label = re.sub(r"\\b|\\.|[()?\[\]{}+*^$|]", "", pattern.split("|")[0])
            found.append(label.strip())
    return found


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return 0

    # An explicit slash command means the user already chose a path.
    if prompt.startswith("/"):
        return 0

    lowered = prompt.lower()
    strong_hits = matches(STRONG, lowered)
    weak_hits = matches(WEAK, lowered)

    if strong_hits:
        hits = ", ".join(sorted(set(strong_hits))[:4])
    elif len(set(weak_hits)) >= 2:
        hits = ", ".join(sorted(set(weak_hits))[:4])
    else:
        return 0

    print(GUIDANCE.format(hits=hits))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never break the session over a routing hint
        sys.exit(0)
