"""Expiry reminders. Run with:  python3 -m tests.test_reminders"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.reminders import due  # noqa: E402

failures = []
TODAY = datetime.date(2026, 8, 25)


def at(days):
    return (TODAY + datetime.timedelta(days=days)).isoformat()


R = [{"name": "GitHub token", "expires": at(90), "warn_days": [14, 7, 3, 1]}]

# Far out: silence.
if due(R, set(), TODAY):
    failures.append("fired 90 days early")

# Each threshold fires exactly once, and only the tightest one that applies.
for days, expect in [(15, 0), (14, 1), (10, 1), (7, 1), (2, 1), (1, 1), (0, 1)]:
    r = [{"name": "GitHub token", "expires": at(days), "warn_days": [14, 7, 3, 1]}]
    got = due(r, set(), TODAY)
    if len(got) != expect:
        failures.append("at %d days out expected %d reminder(s), got %d"
                        % (days, expect, len(got)))

# Once sent, a threshold stays quiet.
r = [{"name": "GitHub token", "expires": at(7), "warn_days": [14, 7, 3, 1]}]
first = due(r, set(), TODAY)
if len(first) != 1:
    failures.append("expected one reminder at 7 days")
sent = {k for k, _ in first}
if due(r, sent, TODAY):
    failures.append("re-sent a reminder that had already gone out")

# A tighter threshold still fires later.
later = due(r, sent, TODAY + datetime.timedelta(days=5))
if len(later) != 1:
    failures.append("the 1-day threshold should still fire after the 7-day one")

# Overdue nags daily, but only once per day.
overdue = [{"name": "GitHub token", "expires": at(-3), "warn_days": [14]}]
today_nag = due(overdue, set(), TODAY)
if len(today_nag) != 1 or "expired 3 days ago" not in today_nag[0][1]:
    failures.append("overdue reminder wrong: %r" % (today_nag,))
if due(overdue, {k for k, _ in today_nag}, TODAY):
    failures.append("overdue reminder repeated within the same day")
if not due(overdue, {k for k, _ in today_nag}, TODAY + datetime.timedelta(days=1)):
    failures.append("overdue reminder should nag again the next day")

# Replacing the credential (new date) re-arms every threshold.
renewed = [{"name": "GitHub token", "expires": at(7 + 90), "warn_days": [14, 7, 3, 1]}]
if due(renewed, sent, TODAY + datetime.timedelta(days=90)):
    pass  # fine either way; the point is the keys differ
old_keys = {k for k, _ in first}
new_first = due([{"name": "GitHub token", "expires": at(97), "warn_days": [14, 7, 3, 1]}],
                old_keys, TODAY + datetime.timedelta(days=90))
if not new_first:
    failures.append("a renewed credential should re-arm its warnings")

# Junk dates are ignored rather than crashing.
for bad in (None, "", "not-a-date", 12345):
    try:
        due([{"name": "x", "expires": bad}], set(), TODAY)
    except Exception as exc:
        failures.append("crashed on expires=%r: %s" % (bad, exc))

# The message body is appended when present.
withmsg = [{"name": "GitHub token", "expires": at(1), "message": "Do the thing."}]
got = due(withmsg, set(), TODAY)
if not got or "Do the thing." not in got[0][1]:
    failures.append("reminder dropped its message body")

total = 20
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
