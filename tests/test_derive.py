"""Turning recorded answers into facts that transfer between employers.

Verbatim answers only match the wording they were recorded from. Houlihan asks
"will you now or in the future require Houlihan Lokey to file a petition";
Lincoln asks "will you now or in the future require sponsorship". Same
question, no match -- until the answers are distilled into canonical fields.

Run with:  python3 -m tests.test_derive
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.derive import derive, education_entries, classify_entries  # noqa: E402
from watcher.formfill import value_for  # noqa: E402

failures = []

RECORDED = {"answers": {
    "education 1 :: degree": "Masters",
    "education 1 :: overall result (gpa) :: gradeaverage": "4.0",
    "education 2 :: degree": "Bachelors",
    "education 2 :: overall result (gpa) :: gradeaverage": "3.74",
    "work history 1 :: company :: companyname": "Austin Film Festival",
    "will you now or in the future require houlihan lokey to file a petition": "No",
    "are you legally authorized to work in the united states": "Yes",
}}

entries = education_entries(RECORDED["answers"])
if sorted(entries) != [1, 2]:
    failures.append("education entries not found: %r" % entries)
if entries.get(1, {}).get("gpa") != "4.0":
    failures.append("entry 1 GPA not picked up: %r" % entries.get(1))

# Which entry is which is decided by the degree, not the order it was listed.
graduate, undergrad = classify_entries(entries)
if graduate != 1 or undergrad != 2:
    failures.append("entries classified wrongly: graduate=%r undergrad=%r"
                    % (graduate, undergrad))
# Reverse the order on the form: the answer must not change.
flipped = {1: {"degree": "Bachelors", "gpa": "3.74"},
           2: {"degree": "Masters", "gpa": "4.0"}}
g, u = classify_entries(flipped)
if g != 2 or u != 1:
    failures.append("listing the bachelor's first confused the classification")

profile = dict(RECORDED)
found = dict(derive(profile))
for key, expected in [("degree", "Masters"), ("gpa", "4.0"),
                      ("undergrad_degree", "Bachelors"),
                      ("undergrad_gpa", "3.74"),
                      ("sponsorship", "No"),
                      ("work_authorization", "Yes")]:
    if profile.get(key) != expected:
        failures.append("%s -> %r, expected %r" % (key, profile.get(key), expected))

# The point of all this: another employer's wording now matches.
if value_for("Please provide your undergraduate GPA.", profile) != "3.74":
    failures.append("a differently worded GPA question still does not match")
if value_for("Will you now or in the future require sponsorship?", profile) != "No":
    failures.append("a differently worded sponsorship question still does not match")

# A value already set by hand is never overwritten.
manual = dict(RECORDED, gpa="3.90")
derive(manual)
if manual["gpa"] != "3.90":
    failures.append("deriving overwrote a value set by hand")

# Deriving twice changes nothing further.
again = derive(profile)
if again:
    failures.append("deriving a second time changed something: %r" % again)

# Nothing recorded, nothing invented.
empty = {}
if derive(empty) or empty:
    failures.append("derived fields from an empty profile: %r" % empty)

# A single unlabelled degree is treated as the current one, not the previous.
single = {"answers": {"education 1 :: degree": "", "education 1 :: overall result (gpa)": "3.5"}}
derive(single)
if single.get("gpa") != "3.5":
    failures.append("a lone education entry was not treated as the current degree")

total = 4 + 6 + 2 + 1 + 1 + 1 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
