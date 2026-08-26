"""Recruiting-cycle detection. Run with:  python3 -m tests.test_season"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.season import parse_season, label, wanted  # noqa: E402

TODAY = datetime.date(2026, 8, 25)
failures = []


def check(title, expected):
    got = label(parse_season(title, TODAY))
    if got != expected:
        failures.append("%-58s -> %r, expected %r" % (title[:56], got, expected))


# Season and year adjacent, in either order.
check("Corporate Development Intern (Summer 2027)", "Summer 2027")
check("Summer 2027 Intern - Finance", "Summer 2027")
check("Fall 2026 Co-op", "Fall 2026")
check("Spring 2027 Finance Internship", "Spring 2027")
check("Winter 2027 Analyst Programme", "Winter 2027")
check("Summer '27 Analyst", "Summer 2027")

# Separated by several words -- the case positional matching got wrong.
check("2027 Commercial & Investment Bank - Global Investment Banking "
      "Program - Summer Analyst", "Summer 2027")
check("Summer Analyst, Corporate Finance 2027", "Summer 2027")

# A bare year counts only alongside early-careers wording.
check("2027 Financial Analyst Intern", "2027")
check("2026 MBA Finance Leadership Program Internship", "2026")
check("Q1 2027 Revenue Manager", "")
check("Senior Manager, FY2027 Planning", "")
check("Analyst II - Financial Reporting", "")

# Season with no year, and neither.
check("Summer Internship - Finance", "Summer")
check("Finance Intern", "")

# Graduation year is a fallback, not the preferred reading.
check("Summer Internship (Class of 2028)", "Summer 2028")
check("2027 Summer Analyst (Class of 2028)", "Summer 2027")

# Implausible years are ignored: job codes, old postings.
check("Intern - Requisition 2019 Finance", "")
check("Finance Intern 2099", "")

# --- the year filter -------------------------------------------------------- #
s2027 = parse_season("Summer 2027 Intern", TODAY)
s2026 = parse_season("Summer 2026 Intern", TODAY)
undated = parse_season("Finance Intern", TODAY)

if not wanted(s2027, [2027]):
    failures.append("target year should keep a matching cycle")
if wanted(s2026, [2027]):
    failures.append("target year should drop a different cycle")
if not wanted(undated, [2027]):
    failures.append("an undated posting must not be dropped by a year filter")
if not wanted(s2026, []):
    failures.append("an empty year list must keep everything")
if not wanted(s2026, [2026, 2027]):
    failures.append("multiple target years should both be honoured")

total = 20 + 5
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
