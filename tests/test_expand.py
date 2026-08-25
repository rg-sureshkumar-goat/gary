"""Identity checks that stop the expander onboarding the wrong company.

Run with:  python3 -m tests.test_expand
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.expand import names_agree, slugs_for, _norm_name  # noqa: E402
from watcher.sources import _workday_location                  # noqa: E402

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%-52s got %r, want %r" % (label, got, want))


# --- names_agree ----------------------------------------------------------- #
AGREE = [
    ("Stripe", "Stripe"),
    ("Kimberly Clark", "Kimberly-Clark"),
    ("Capital One Services LLC", "Capital One"),
    ("Boeing Company", "Boeing"),
    ("Citigroup Inc.", "Citigroup"),
]
DISAGREE = [
    # The real reason this check exists: Greenhouse slugs are first-come, so
    # `disney` belongs to somebody else entirely.
    ("Sgt. Pepper's Lonely Hearts Club Band", "Disney"),
    ("Bohen Consulting Group", "Boston Consulting Group"),
    ("Acme Widgets", "Boeing"),
    ("", "Boeing"),
]
for claimed, expected in AGREE:
    if not names_agree(claimed, expected):
        failures.append("should agree:    %-40r vs %r" % (claimed, expected))
for claimed, expected in DISAGREE:
    if names_agree(claimed, expected):
        failures.append("should NOT agree:%-40r vs %r" % (claimed, expected))

# --- _norm_name strips corporate noise ------------------------------------- #
check("_norm_name drops suffixes", _norm_name("Boeing Company Inc."), "boeing")
check("_norm_name keeps something", _norm_name("The Group"), "thegroup")

# --- slugs_for prefers the domain root ------------------------------------- #
slugs = slugs_for({"name": "Morgan Stanley", "domain": "morganstanley.com"})
check("slugs_for first is domain root", slugs[0], "morganstanley")
if "morgan-stanley" not in slugs:
    failures.append("slugs_for should offer a hyphenated variant: %r" % slugs)

# --- Workday's "N Locations" fallback -------------------------------------- #
check("workday multi-location falls back to URL",
      _workday_location("2 Locations",
                        "/job/Los-Angeles-CA-USA/Corporate-Development-Intern_R3354"),
      "Los Angeles CA USA (2 Locations)")
check("workday keeps a real location",
      _workday_location("New York, NY", "/job/New-York/Analyst_R1"), "New York, NY")
check("workday derives when blank",
      _workday_location("", "/job/Chicago-IL-USA/Summer-Analyst_R9"), "Chicago IL USA")
check("workday tolerates a junk path", _workday_location("", "/nonsense"), "")

total = len(AGREE) + len(DISAGREE) + 2 + 2 + 4
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
