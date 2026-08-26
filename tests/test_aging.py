"""Long-open postings. Run with:  python3 -m tests.test_aging"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.aging import parse_posted, age_of, select_aged  # noqa: E402

TODAY = datetime.date(2026, 8, 25)
failures = []


def check(label_, got, want):
    if got != want:
        failures.append("%-40s got %r, want %r" % (label_, got, want))


# --- reading a board's posted date ------------------------------------------ #
check("iso date", parse_posted("2026-06-01", TODAY), (85, True))
check("today", parse_posted("Today", TODAY), (0, True))
check("yesterday", parse_posted("Yesterday", TODAY), (1, True))
check("n days ago", parse_posted("6 Days Ago", TODAY), (6, True))
# Workday stops counting -- a floor, not a measurement.
check("30+ days ago", parse_posted("30+ Days Ago", TODAY), (30, False))
check("months ago", parse_posted("2 Months Ago", TODAY), (60, True))
check("month and day", parse_posted("August 12,", TODAY), (13, True))
check("unreadable", parse_posted("nonsense", TODAY), None)
check("empty", parse_posted("", TODAY), None)

# --- combining the board's date with Gary's own history --------------------- #
check("floor alone stays inexact",
      age_of({"posted_at": "30+ Days Ago"}, None, TODAY), (30, False))
check("history sharpens a floor",
      age_of({"posted_at": "30+ Days Ago"}, "2026-05-01", TODAY), (116, True))
check("exact date needs no history",
      age_of({"posted_at": "2026-06-01"}, None, TODAY), (85, True))
check("history alone",
      age_of({"posted_at": None}, "2026-06-01", TODAY), (85, True))
check("nothing known", age_of({"posted_at": None}, None, TODAY), (None, False))

# --- selecting what to recommend -------------------------------------------- #
def job(i, posted=None):
    return {"id": str(i), "company": "C", "title": "Finance Intern",
            "url": "u", "posted_at": posted}

matches = [
    job(1, "2026-05-01"),      # 116 days, exact -> qualifies
    job(2, "2026-08-20"),      # 5 days -> too new
    job(3, "30+ Days Ago"),    # floor of 30 -> cannot prove 60
    job(4, None),              # unknown, but Gary has watched it a while
]
seen = {"4": {"f": "2026-05-01", "l": "2026-08-25"}}

picked = select_aged(matches, seen, min_days=60, today=TODAY)
ids = sorted(j["id"] for j in picked)
check("selects only provable long-open roles", ids, ["1", "4"])

# A "30+ days" floor becomes provable once Gary has watched it long enough.
seen_with_history = dict(seen, **{"3": {"f": "2026-04-01", "l": "2026-08-25"}})
picked = select_aged(matches, seen_with_history, min_days=60, today=TODAY)
check("history rescues a floored posting",
      sorted(j["id"] for j in picked), ["1", "3", "4"])

# Sorted oldest first, and the age is reported.
picked = select_aged(matches, seen_with_history, min_days=60, today=TODAY)
check("oldest first", [j["days_open"] for j in picked],
      sorted([j["days_open"] for j in picked], reverse=True))

# Recently recommended roles are held back, then return later.
recent = {"1": "2026-08-20", "4": "2026-08-20"}
check("recent recommendations suppressed",
      select_aged(matches, seen, min_days=60, recommended=recent, today=TODAY), [])
old = {"1": "2026-05-01", "4": "2026-05-01"}
check("stale recommendations resurface",
      sorted(j["id"] for j in select_aged(matches, seen, min_days=60,
                                          recommended=old, today=TODAY)),
      ["1", "4"])

# Legacy state stored a bare string; it must still be read as a first sighting.
check("legacy state format",
      sorted(j["id"] for j in select_aged([job(9, None)], {"9": "2026-05-01"},
                                          min_days=60, today=TODAY)),
      ["9"])

total = 21
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
