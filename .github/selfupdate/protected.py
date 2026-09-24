"""The protected-core check (see PROTECTED.md). Compares a change with the
version it would replace and lists every problem; an empty list passes.

    python .github/selfupdate/protected.py BASE_TREE

BASE_TREE is a checkout of the version currently deployed. The change is
the current directory, committed.
"""

import json
import re
import subprocess
import sys

PROTECTED_PATHS = (".github/", "PROTECTED.md", "ai.py", "store.py", "health.py",
                   "guard.py", "admins.py", "railway.json", "railpack.json",
                   # Claude Code reads these by itself on every run, so a change
                   # here would instruct every later self-update.
                   "CLAUDE.md", "CLAUDE.local.md", ".claude/", ".agents/", ".mcp.json")

# Read out of each tree by importing it, so the values compared are the
# ones the bot would actually run with.
SNAPSHOT = r"""
import json, actions, assistant, automod, conduct, judge, moderator, settings
print(json.dumps({
    "instant_tools": sorted(n for n, t in assistant.TIER.items()
                            if t in (assistant.SELF, assistant.LIGHT)),
    "core_channels": sorted(actions.CORE),
    "fixed_rules": sorted(conduct.FIXED),
    "floor_rule_text": [list(r) for r in conduct.DEFAULT_RULES[3:6]],
    "ranges": {k: [v["min"], v["max"]] for k, v in settings.SETTINGS.items()},
    "block_words": automod.BLOCK_WORDS,
    "block_patterns": automod.BLOCK_PATTERNS,
    "block_rules": [name for name, _, block in automod.plan() if block],
    "hazards": {k: v[0] for k, v in judge.HAZARDS.items()},
    "hidden_rules": sorted(judge.HIDDEN_RULES),
    "support_at": judge.SUPPORT_AT,
    "support_line": moderator.SUPPORT_LINE,
}))
"""
FLOOR_HAZARDS = ("doxxing", "sexual", "scam")

# Added lines that reach for secrets or run code built at runtime.
ACCESS = re.compile(
    r"os\.environ|os\.getenv|getenv\(|environ\[|DISCORD_TOKEN|OPENROUTER_API_KEY"
    r"|ANTHROPIC_API_KEY|\bai\.key\b|\bai\._secrets\b|store\.load\(\s*['\"]ai['\"]"
    r"|ai\.json|\.http\.token|\beval\(|\bexec\(|subprocess|__import__|importlib"
    r"|/proc/|os\.system|os\.popen")
# Added lines that name the stored list of admins, which only admins.py
# (and so only the owner, with /admin) may change.
ADMIN_LIST = re.compile(r"""['"]admins(\.json)?['"]""")
# Anything that looks like a secret itself. A change containing one is
# discarded, never published.
SECRET = re.compile(
    r"sk-ant-[\w-]{10,}|sk-or-v1-[\w-]{10,}|gh[opsu]_[A-Za-z0-9]{20,}"
    r"|github_pat_\w{20,}|[MN][A-Za-z\d]{23,27}\.[\w-]{6}\.[\w-]{27,}")


def path_problems(changed):
    return [f"changes a protected file: {path}" for path in changed
            if any(path == p or (p.endswith("/") and path.startswith(p))
                   for p in PROTECTED_PATHS)]


def value_problems(base, head):
    problems = []
    for name, bounds in base["ranges"].items():
        if name not in head["ranges"]:
            problems.append(f"removes the setting {name}")
        elif head["ranges"][name] != bounds:
            problems.append(f"changes the range of the setting {name} "
                            f"from {bounds} to {head['ranges'][name]}")
    for key, what in (("block_words", "blocked word"),
                      ("block_patterns", "blocked pattern"),
                      ("block_rules", "blocking AutoMod rule")):
        for item in base[key]:
            if item not in head[key]:
                problems.append(f"removes the {what} {item!r}")
    for hazard in FLOOR_HAZARDS:
        if head["hazards"].get(hazard) != base["hazards"].get(hazard):
            problems.append(f"removes or moves the {hazard} question")
    for rule in base["hidden_rules"]:
        if rule not in head["hidden_rules"]:
            problems.append(f"quotes rule {rule} violations in #mod-log")
    if head["support_at"] > base["support_at"]:
        problems.append("raises the score that triggers the self-harm support message")
    if "1564" not in head["support_line"]:
        problems.append("removes Embrace's lifeline from the support message")
    for tool in head["instant_tools"]:
        if tool not in base["instant_tools"]:
            problems.append(f"lets the bot do {tool} without a vote")
    for name in base["core_channels"]:
        if name not in head["core_channels"]:
            problems.append(f"lets a vote rename or delete #{name}")
    for rule in base["fixed_rules"]:
        if rule not in head["fixed_rules"]:
            problems.append(f"lets a vote change rule {rule}")
    if head["floor_rule_text"] != base["floor_rule_text"]:
        problems.append("changes the text of rules 4 to 6")
    return problems


def added_lines(diff):
    """(path, line) for every line the diff adds."""
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("+") and path:
            yield path, line[1:]


def access_problems(diff):
    return [f"{path}: reads secrets or runs code built at runtime: {line.strip()[:120]}"
            for path, line in added_lines(diff) if ACCESS.search(line)]


def admin_problems(diff):
    return [f"{path}: touches the list of admins: {line.strip()[:120]}"
            for path, line in added_lines(diff) if ADMIN_LIST.search(line)]


def contains_secret(text):
    return bool(SECRET.search(text))


def _git(*args, cwd="."):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def snapshot(tree):
    result = subprocess.run([sys.executable, "-c", SNAPSHOT], cwd=tree,
                            capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[-500:])
    return json.loads(result.stdout)


def check(base_tree):
    """Every problem with the committed change, compared with `base_tree`."""
    base_rev = _git("rev-parse", "HEAD", cwd=base_tree).strip()
    changed = _git("diff", "--name-only", "--no-renames", base_rev, "HEAD").split()
    diff = _git("diff", "--no-renames", base_rev, "HEAD")
    problems = path_problems(changed) + access_problems(diff) + admin_problems(diff)
    try:
        problems += value_problems(snapshot(base_tree), snapshot("."))
    except RuntimeError as e:
        problems.append(f"the protected values could not be read from the change: {e}")
    return problems


if __name__ == "__main__":
    found = check(sys.argv[1])
    print("\n".join(found) or "The protected core is untouched.")
    sys.exit(1 if found else 0)
