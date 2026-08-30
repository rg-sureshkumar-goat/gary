"""Reading what a dropdown asks from the options it offers.

The words above a control are unreliable -- the same question appears as
"Ethnicity", as "What race or ethnicity do you most closely identify with?",
and as nothing beyond "Select One". The options say plainly what is being
asked, so they are consulted first. Answering from the wording instead is how
a list of ethnic categories came to be answered "Hispanic or Latino" for a
candidate whose profile says Asian.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import lists

PROFILE = {
    "race": "Asian",
    "race_detail": "South Asian",
    "gender": "Male",
    "veteran": "I am not a veteran",
    "disability": "No, I do not have a disability and have not had one in the past",
    "hispanic_or_latino": "No",
    "state": "Texas",
}

RACE = ["Select One",
        "American Indian or Alaska Native (United States of America)",
        "Asian (United States of America)",
        "Black or African American (United States of America)",
        "Hispanic or Latino (United States of America)",
        "Native Hawaiian or Other Pacific Islander (United States of America)",
        "Two or More Races (United States of America)",
        "White (United States of America)"]

# How Workday actually spells these: every option qualified, sometimes twice.
# Stripping only the last bracket left "Asian (Not Hispanic or Latino) (United
# States of America)" unmatchable, and a stored country then matched the
# qualifier on "Hispanic or Latino (United States of America)" -- so a
# question about race was answered with the wrong group.
DOUBLY_QUALIFIED = [
    "Select One",
    "American Indian or Alaska Native (Not Hispanic or Latino) "
    "(United States of America)",
    "Asian (Not Hispanic or Latino) (United States of America)",
    "Black or African American (Not Hispanic or Latino) "
    "(United States of America)",
    "Hispanic or Latino (United States of America)",
    "I do not wish to self-identify (United States of America)",
]

# A form that divides Asian into narrower categories. Answering one of those
# from a profile that says only "Asian" is choosing an identity for the
# candidate; the finer fact has to come from them.
FINE = ["Black or of African descent", "East Asian", "South Asian",
        "Southeast Asian", "Middle Eastern or North African",
        "White or Caucasian", "I don't wish to answer"]

CASES = [
    ("a finely divided race list", FINE, "South Asian"),
    ("doubly qualified race list", DOUBLY_QUALIFIED,
     "Asian (Not Hispanic or Latino) (United States of America)"),
    ("race", RACE, "Asian (United States of America)"),
    ("race, plainly worded", ["Asian", "White", "Black or African American",
                              "Two or More Races"], "Asian"),
    ("gender", ["Select One", "Male", "Female", "Non-Binary"], "Male"),
    ("veteran", ["Select One", "I am not a veteran",
                 "I identify as one or more classifications of a protected "
                 "veteran"], "I am not a veteran"),
    # An employer that distinguishes not-a-veteran from a-veteran-who-is-not-
    # protected. A stored "I am not a Protected Veteran" is true of both, and
    # matched the wrong one -- the fact has to say which.
    ("veteran, finely divided",
     ["Select One", "I do not wish to self-identify",
      "I identify as one or more of the classifications of a protected veteran",
      "I identify as a veteran, just not a protected veteran",
      "I am not a veteran"],
     "I am not a veteran"),
    ("disability", ["Yes, I have a disability, or have had one in the past",
                    "No, I do not have a disability and have not had one in "
                    "the past", "I do not want to answer"],
     "No, I do not have a disability and have not had one in the past"),
]

# Lists that are not of a recognisable kind, and must be left to the ordinary
# matching rather than guessed at here.
UNRECOGNISED = [
    ["Select One", "Yes", "No", "I do not wish to answer"],
    ["Boston, MA", "Chicago, IL", "New York, NY"],
    ["Select One", "White"],          # one hit is a coincidence, not a kind
    ["Select One"],
]

failures = []

for name, options, wanted in CASES:
    got, why = lists.answer(options, PROFILE)
    if got != wanted:
        failures.append("%s answered %r, wanted %r" % (name, got, wanted))
    elif not why:
        failures.append("%s gave no working" % name)

for options in UNRECOGNISED:
    got, _ = lists.answer(options, PROFILE)
    if got is not None:
        failures.append("read a kind into %r and answered %r"
                        % (options[:3], got))

# The specific failure this exists to prevent.
for options in (RACE, DOUBLY_QUALIFIED):
    got, _ = lists.answer(options, PROFILE)
    if str(got or "").startswith("Hispanic"):
        failures.append("a race list was answered with Hispanic or Latino")

# A country must never match the country named in an option's qualifier.
from watcher.formfill import reasoned_option

WITH_COUNTRY = dict(PROFILE, country="United States of America")
got, _ = reasoned_option("Select One", DOUBLY_QUALIFIED, WITH_COUNTRY)
# The right answer contains the words "Not Hispanic or Latino", so what is
# checked is that the Hispanic option itself was not chosen.
if str(got or "").startswith("Hispanic"):
    failures.append("a stored country matched an option's qualifier: %r" % got)
if got != "Asian (Not Hispanic or Latino) (United States of America)":
    failures.append("reasoning gave %r on the doubly qualified list" % got)

# Without the finer fact the question is left alone rather than guessed at.
from watcher import options as option_reading

coarse_only = {k: v for k, v in PROFILE.items() if k != "race_detail"}
got, _ = lists.answer(FINE, coarse_only)
if got is not None:
    failures.append("chose %r for a candidate who only said Asian" % got)
# A word in front narrows a category; a term extended after itself does not.
if option_reading.asserts("East Asian", "Asian"):
    failures.append("'Asian' was taken to assert 'East Asian'")
if not option_reading.asserts("Asian or Pacific Islander", "Asian"):
    failures.append("'Asian' no longer answers 'Asian or Pacific Islander'")

total = len(CASES) + len(UNRECOGNISED) + 1 + 2 + 3
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
