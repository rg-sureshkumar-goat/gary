"""First-sight seeding: a newly watched company must not text its whole backlog.

Run with:  python3 -m tests.test_seeding
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import agent  # noqa: E402

failures = []

# Two companies; "Old Co" is already known, "New Co" has never been checked.
FAKE = {
    "Old Co": [
        {"id": "old:1", "title": "Corporate Finance Intern", "location": "New York, NY",
         "url": "https://x/1", "posted_at": None, "company": "Old Co", "source": "t"},
        {"id": "old:2", "title": "Consulting Summer Analyst", "location": "Chicago",
         "url": "https://x/2", "posted_at": None, "company": "Old Co", "source": "t"},
    ],
    "New Co": [
        {"id": "new:1", "title": "Finance Intern", "location": "Boston, MA",
         "url": "https://y/1", "posted_at": None, "company": "New Co", "source": "t"},
        {"id": "new:2", "title": "Investment Banking Summer Analyst", "location": "Dallas, TX",
         "url": "https://y/2", "posted_at": None, "company": "New Co", "source": "t"},
    ],
}

sent = []


class Args(object):
    dry_run = False
    seed = False
    only = None
    no_browser = True
    only_browser = False
    headed = False
    announce_new_companies = False
    token = "T"
    chat_id = "C"

    def __init__(self, config, state):
        self.config = config
        self.state = state


def setup(tmp):
    config = os.path.join(tmp, "config.json")
    state = os.path.join(tmp, "seen.json")
    rules = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config.json")))["rules"]
    json.dump({"workers": 2, "rules": rules, "companies": [
        {"name": "Old Co", "ats": "test"}, {"name": "New Co", "ats": "test"},
    ]}, open(config, "w"))
    # Old Co is already seeded, and one of its roles already seen.
    json.dump({"seen": {"old:1": "2026-08-01"}, "broken": {},
               "seeded_companies": ["Old Co"]}, open(state, "w"))
    return config, state


def fake_collect(companies, workers=8, headless=True):
    jobs = []
    for c in companies:
        jobs.extend(FAKE[c["name"]])
    return jobs, {}


def fake_notify(token, chat, jobs, header=None):
    sent.extend(jobs)
    return 1


tmp = tempfile.mkdtemp()
config, state = setup(tmp)

agent.collect = fake_collect
agent.notifier.notify = fake_notify
agent.notifier.send = lambda *a, **k: None
# This test is about the seeding diff, not credentials; the real preflight
# would call Telegram, so stub it out.
agent.notifier.check_credentials = lambda token, chat: None

agent.run(Args(config, state))

titles = sorted(j["id"] for j in sent)
if titles != ["old:2"]:
    failures.append("first run should text only Old Co's unseen role, got %r" % titles)

saved = json.load(open(state))
for jid in ("new:1", "new:2", "old:2"):
    if jid not in saved["seen"]:
        failures.append("%s should have been recorded as seen" % jid)
if "New Co" not in saved["seeded_companies"]:
    failures.append("New Co should now be marked as seeded")

# Second run: New Co posts a genuinely new role -- that one must be sent.
sent[:] = []
FAKE["New Co"].append(
    {"id": "new:3", "title": "Corporate Development Intern", "location": "Austin, TX",
     "url": "https://y/3", "posted_at": None, "company": "New Co", "source": "t"})
agent.run(Args(config, state))
titles = sorted(j["id"] for j in sent)
if titles != ["new:3"]:
    failures.append("second run should text only New Co's brand-new role, got %r" % titles)

total = 6
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
