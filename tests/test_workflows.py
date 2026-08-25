"""The commands CI actually runs must parse.

A reusable workflow that hardcoded the subcommand, plus callers that also
passed it, produced `watcher.agent run run --no-browser` -- which argparse
rejects, so every scheduled run failed before touching a career site. The
workflow YAML was valid and the Python was fine; only the composition was
wrong, and nothing tested the composition.

Run with:  python3 -m tests.test_workflows
"""
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.agent import build_parser  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WF = os.path.join(ROOT, ".github", "workflows")

failures = []


def read(name):
    with open(os.path.join(WF, name)) as fh:
        return fh.read()


# The reusable workflow's command template, e.g.
#   run: python -m watcher.agent ${{ inputs.args }}
state = read("_state.yml")
m = re.search(r"run:\s*(python -m watcher\.agent[^\n]*)", state)
if not m:
    failures.append("could not find the agent command in _state.yml")
    template = ""
else:
    template = m.group(1).strip()

# Each caller's args, e.g.   args: "run --no-browser"
callers = {}
for name in ("watch-fast.yml", "watch-browser.yml"):
    text = read(name)
    a = re.search(r'^\s*args:\s*"([^"]*)"', text, re.M)
    if not a:
        failures.append("no args: found in %s" % name)
        continue
    callers[name] = a.group(1)

parser = build_parser()

for name, args in callers.items():
    composed = template.replace("${{ inputs.args }}", args)
    argv = shlex.split(composed)
    # Drop "python -m watcher.agent"
    if argv[:3] != ["python", "-m", "watcher.agent"]:
        failures.append("%s: unexpected command prefix %r" % (name, argv[:3]))
        continue
    tail = argv[3:]
    if tail.count("run") != 1:
        failures.append("%s composes %r -- the subcommand appears %d times"
                        % (name, " ".join(tail), tail.count("run")))
        continue
    try:
        parsed = parser.parse_args(tail)
    except SystemExit:
        failures.append("%s composes %r, which the agent cannot parse"
                        % (name, " ".join(tail)))
        continue
    if parsed.command != "run":
        failures.append("%s: parsed command was %r" % (name, parsed.command))

# The two lanes must actually select different sets of companies.
fast = parser.parse_args(["run", "--no-browser"])
slow = parser.parse_args(["run", "--only-browser"])
if not fast.no_browser or fast.only_browser:
    failures.append("the fast lane should exclude browser companies")
if not slow.only_browser or slow.no_browser:
    failures.append("the browser lane should run only browser companies")

# expand.yml invokes the agent directly; check those lines too.
for line in re.findall(r"python -m watcher\.agent ([^\n]+)", read("expand.yml")):
    tail = shlex.split(line.strip())
    try:
        parser.parse_args(tail)
    except SystemExit:
        failures.append("expand.yml runs %r, which the agent cannot parse" % line.strip())

# Both watch workflows must share the state concurrency group, or two runs
# can clobber state/seen.json.
groups = set(re.findall(r"group:\s*([\w-]+)", state + read("expand.yml")))
if len(groups) != 1:
    failures.append("workflows disagree on the concurrency group: %r" % sorted(groups))

total = 2 * len(callers) + 2 + 1 + 1
if failures:
    print("FAILED %d check(s):" % len(failures))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
