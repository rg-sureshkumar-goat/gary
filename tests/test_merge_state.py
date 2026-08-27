"""Merging two lanes' state files.

Several lanes write state/seen.json on their own schedules. When two land
together git cannot reconcile them -- a JSON rebase conflicts and the push step
fails, discarding that run's work. This is what happens instead.

Run with:  python3 -m tests.test_merge_state
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.merge_state import merge  # noqa: E402

failures = []

OURS = {
    "seen": {"a": {"f": "2026-08-01", "l": "2026-08-26"},
             "b": {"f": "2026-08-20", "l": "2026-08-26"}},
    "reported": ["a"],
    "recommended": {"a": "2026-08-10"},
    "seeded_companies": ["Alpha", "Beta"],
    "broken": {"Alpha": "HTTP 500"},
    "last_run": "2026-08-26T14:30:00Z",
}
THEIRS = {
    "seen": {"a": {"f": "2026-07-15", "l": "2026-08-25"},
             "c": {"f": "2026-08-24", "l": "2026-08-25"}},
    "reported": ["c"],
    "recommended": {"a": "2026-08-22", "c": "2026-08-25"},
    "seeded_companies": ["Beta", "Gamma"],
    "broken": {"Gamma": "timeout"},
    "last_run": "2026-08-26T14:25:00Z",
}

m = merge(OURS, THEIRS)

# Nothing either side saw may be lost.
if sorted(m["seen"]) != ["a", "b", "c"]:
    failures.append("postings were lost: %r" % sorted(m["seen"]))

# The earliest sighting dates a posting, so it must win; the latest sighting
# shows it is still open.
if m["seen"]["a"]["f"] != "2026-07-15":
    failures.append("merge did not keep the earliest first-sighting: %r"
                    % m["seen"]["a"])
if m["seen"]["a"]["l"] != "2026-08-26":
    failures.append("merge did not keep the latest last-sighting: %r"
                    % m["seen"]["a"])

# Reporting is additive: told by either run means told.
if m["reported"] != ["a", "c"]:
    failures.append("reported roles were lost: %r" % m["reported"])
if sorted(m["seeded_companies"]) != ["Alpha", "Beta", "Gamma"]:
    failures.append("seeded companies were lost: %r" % m["seeded_companies"])

# The most recent recommendation date wins, so nothing is re-sent early.
if m["recommended"]["a"] != "2026-08-22":
    failures.append("older recommendation date won: %r" % m["recommended"])
if m["recommended"].get("c") != "2026-08-25":
    failures.append("a recommendation was dropped")

# The fresher run's view of what is broken is the better one.
if m["broken"] != {"Alpha": "HTTP 500"}:
    failures.append("stale broken-source list won: %r" % m["broken"])
if m["last_run"] != "2026-08-26T14:30:00Z":
    failures.append("last_run should be the later of the two: %r" % m["last_run"])

# Legacy bare-string records must survive the merge.
legacy = merge({"seen": {"x": "2026-08-01"}}, {"seen": {"x": "2026-07-01"}})
if legacy["seen"]["x"]["f"] != "2026-07-01":
    failures.append("legacy string state did not merge: %r" % legacy["seen"])

# Merging with nothing is a no-op, not a wipe.
if merge(OURS, {})["reported"] != ["a"]:
    failures.append("merging against an empty state lost data")
if merge({}, THEIRS)["reported"] != ["c"]:
    failures.append("merging an empty state over data lost it")

# Order must not matter for the additive fields.
a, b = merge(OURS, THEIRS), merge(THEIRS, OURS)
if a["reported"] != b["reported"] or sorted(a["seen"]) != sorted(b["seen"]):
    failures.append("merge is not order-independent")

total = 13
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
