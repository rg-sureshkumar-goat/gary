"""What gets reported, and what waits its turn.

Gary used to absorb a newly watched employer's existing postings silently and
only announce a count. Those roles are open and they match, so they are now
reported with their details like any other. A per-run cap keeps a bulk
onboarding manageable, and anything over the cap must stay unrecorded so it
arrives on a later run rather than being lost.

Run with:  python3 -m tests.test_seeding
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import agent  # noqa: E402

failures = []
sent = []


def role(company, n):
    return {"id": "%s:%d" % (company, n),
            "title": "Corporate Finance Intern %d" % n,
            "location": "New York, NY", "url": "https://x/%s/%d" % (company, n),
            "posted_at": None, "company": company, "source": "t"}


FAKE = {"Old Co": [role("old", 1), role("old", 2)],
        "New Co": [role("new", 1), role("new", 2)]}
for job in FAKE["Old Co"]:
    job["company"] = "Old Co"
for job in FAKE["New Co"]:
    job["company"] = "New Co"


class Args(object):
    dry_run = False
    seed = False
    only = None
    no_browser = True
    only_browser = False
    headed = False
    tier = "all"
    shard = None
    send_open = False
    recommend_aged = False
    min_age_days = 60
    announce_new_companies = False
    token = "T"
    chat_id = "C"

    def __init__(self, config, state):
        self.config = config
        self.state = state


def setup(tmp, cap=40):
    config = os.path.join(tmp, "config.json")
    state = os.path.join(tmp, "seen.json")
    rules = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                        "config.json")))["rules"]
    rules = dict(rules, max_alerts_per_run=cap)
    json.dump({"workers": 2, "rules": rules, "companies": [
        {"name": "Old Co", "ats": "test"}, {"name": "New Co", "ats": "test"},
    ]}, open(config, "w"))
    # Old Co is known, and one of its roles has already been reported.
    json.dump({"seen": {"old:1": {"f": "2026-08-01", "l": "2026-08-01"}},
               "reported": ["old:1"],
               "broken": {}, "seeded_companies": ["Old Co"]}, open(state, "w"))
    return config, state


agent.collect = lambda companies, workers=8, headless=True: (
    [j for c in companies for j in FAKE[c["name"]]], {})
agent.notifier.notify = lambda token, chat, jobs, header=None: (
    sent.extend(jobs) or 1)
agent.notifier.send = lambda *a, **k: None
agent.notifier.check_credentials = lambda token, chat: None

# --- a newly watched employer's backlog is reported, with details ----------- #
tmp = tempfile.mkdtemp()
config, state = setup(tmp)
agent.run(Args(config, state))

ids = sorted(j["id"] for j in sent)
if ids != ["new:1", "new:2", "old:2"]:
    failures.append("expected the new employer's open roles to be reported "
                    "alongside Old Co's unseen one, got %r" % ids)
for job in sent:
    if not job.get("url") or not job.get("title") or not job.get("company"):
        failures.append("a reported role was missing company/title/link: %r" % job)

saved = json.load(open(state))
for job_id in ("new:1", "new:2", "old:2"):
    if job_id not in saved["reported"]:
        failures.append("%s should be marked reported once sent" % job_id)

# --- nothing is repeated on the next run ------------------------------------ #
sent[:] = []
agent.run(Args(config, state))
if sent:
    failures.append("already-reported roles were sent again: %r"
                    % [j["id"] for j in sent])

# --- over the cap, the remainder waits rather than vanishing ---------------- #
sent[:] = []
tmp2 = tempfile.mkdtemp()
config2, state2 = setup(tmp2, cap=1)
FAKE["New Co"] = [role("new", 1), role("new", 2), role("new", 3)]
for job in FAKE["New Co"]:
    job["company"] = "New Co"

agent.run(Args(config2, state2))
first_batch = [j["id"] for j in sent]
if len(first_batch) != 1:
    failures.append("a cap of 1 should send exactly one role, sent %r" % first_batch)

saved2 = json.load(open(state2))
if len(saved2["reported"]) != 2:   # the one just sent, plus old:1 already there
    failures.append("only sent roles should be marked reported, got %r"
                    % sorted(saved2["reported"]))
# Observation still logs everything, so the long-open digest can date them.
if len(saved2["seen"]) < 4:
    failures.append("every observed role should still be logged for ageing, "
                    "got %r" % sorted(saved2["seen"]))

# Successive runs drain the queue; nothing is lost and nothing repeats.
seen_ids = set(first_batch)
for _ in range(6):
    sent[:] = []
    agent.run(Args(config2, state2))
    batch = [j["id"] for j in sent]
    if set(batch) & seen_ids:
        failures.append("a role was reported twice across runs: %r" % batch)
    seen_ids |= set(batch)

expected = {"old:2", "new:1", "new:2", "new:3"}
if seen_ids != expected:
    failures.append("draining the queue should report every role exactly once; "
                    "got %r, expected %r" % (sorted(seen_ids), sorted(expected)))

total = 12
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
