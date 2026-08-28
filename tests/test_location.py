"""Answering "which office do you want?" on an application.

The rule: every open location when several may be chosen; the company's US
headquarters when only one may be, and only if the role is open there;
otherwise blank. A guess routes an application to an office it was never
posted for.

Run with:  python3 -m tests.test_location
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.location import (  # noqa: E402
    is_location_question, city_of, split_locations, options_for, pick_single,
    headquarters_for, answer)

failures = []
HQ = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                 "headquarters.json")))

# --- recognising the question ----------------------------------------------- #
for label in ["Which Lincoln office are you interested in joining?",
              "Preferred office location", "Which city would you like to work in?",
              "Location preference", "Select your work location"]:
    if not is_location_question(label):
        failures.append("not recognised as a location question: %r" % label)
for label in ["Please provide your undergraduate GPA.", "First Name",
              "Will you now or in the future require sponsorship?"]:
    if is_location_question(label):
        failures.append("mistaken for a location question: %r" % label)

# --- comparing places written differently ------------------------------------ #
for text, expected in [("Chicago - 550 Van Buren", "chicago"),
                       ("Chicago, IL", "chicago"),
                       ("New York, NY, United States", "new york"),
                       ("CHICAGO", "chicago"),
                       ("Los Angeles CA USA (2 Locations)", "los angeles")]:
    if city_of(text) != expected:
        failures.append("city_of(%r) -> %r, expected %r"
                        % (text, city_of(text), expected))

if split_locations("Chicago, IL; New York, NY; Los Angeles, CA") != \
        ["chicago", "new york", "los angeles"]:
    failures.append("splitting a multi-location posting failed: %r"
                    % split_locations("Chicago, IL; New York, NY; Los Angeles, CA"))

OPTIONS = ["Chicago", "New York", "Los Angeles", "San Francisco", "Boston"]
OPEN = ["Chicago, IL", "New York, NY", "Los Angeles, CA"]

# --- several may be chosen: take them all ------------------------------------ #
picked = options_for(OPTIONS, OPEN)
if picked != ["Chicago", "New York", "Los Angeles"]:
    failures.append("multi-select did not take every open location: %r" % picked)
if "Boston" in picked or "San Francisco" in picked:
    failures.append("multi-select chose an office the role is not open in")
if options_for(OPTIONS, []) != []:
    failures.append("with no known locations, nothing should be chosen")

# --- only one may be chosen: the US headquarters, if open there -------------- #
if pick_single(OPTIONS, OPEN, "Chicago") != "Chicago":
    failures.append("did not take the headquarters when the role is open there")
# Headquarters exists but the role is not open there: take the office the
# role is actually posted in, which the candidate asked for after the
# headquarters rule left Berkeley Research Group's question blank.
if pick_single(OPTIONS, ["New York, NY"], "Chicago") != "New York":
    failures.append("did not take the office the role is posted in")
# The headquarters is never named for a role that is not open there, even
# when the posted office is missing from the list.
if pick_single(["Boston", "Chicago"], ["Austin, TX"], "Chicago") is not None:
    failures.append("chose a headquarters the role is not open in")
# Headquarters is not on the dropdown at all.
if pick_single(["Boston", "Austin"], OPEN, "Chicago") is not None:
    failures.append("chose an option that is not the headquarters")
# No headquarters known, but the role is posted somewhere on the list.
if pick_single(OPTIONS, OPEN, None) != "Chicago":
    failures.append("ignored the posted office when no headquarters is known")
# Nothing known at all: blank, never a guess.
if pick_single(OPTIONS, [], None) is not None:
    failures.append("guessed an office with nothing to go on")

# --- looking up the headquarters --------------------------------------------- #
for company, expected in [("Lincoln International", "Chicago"),
                          ("Houlihan Lokey", "Los Angeles"),
                          ("Bank of America", "Charlotte"),
                          ("JPMorgan Chase", "New York")]:
    got = headquarters_for(company, HQ)
    if got != expected:
        failures.append("%s -> %r, expected %r" % (company, got, expected))
if headquarters_for("Some Firm Nobody Has Heard Of", HQ) is not None:
    failures.append("invented a headquarters for an unknown employer")

# --- the whole rule ----------------------------------------------------------- #
if answer(OPTIONS, OPEN, "Lincoln International", HQ, multiple=True) != \
        ["Chicago", "New York", "Los Angeles"]:
    failures.append("multi-select path wrong")
if answer(OPTIONS, OPEN, "Lincoln International", HQ, multiple=False) != ["Chicago"]:
    failures.append("single-select path did not take the headquarters")
if answer(OPTIONS, ["New York, NY"], "Lincoln International", HQ,
          multiple=False) != ["New York"]:
    failures.append("single-select should take the office the role is in")
if answer(OPTIONS, OPEN, "Unknown Employer", HQ, multiple=False) != ["Chicago"]:
    failures.append("an unknown employer still has a posted office")
# With nowhere known and no headquarters, it stays the candidate's to answer.
if answer(OPTIONS, [], "Unknown Employer", HQ, multiple=False) != []:
    failures.append("guessed an office with nothing to go on")

total = 8 + 3 + 5 + 1 + 3 + 4 + 5 + 4
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
