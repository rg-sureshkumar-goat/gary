"""Two different questions that employers both call "ethnicity".

One asks which racial or ethnic group you identify with and expects a category
back. The other asks whether you are Hispanic or Latino and expects yes or no.
Berkeley Research Group spells the first "What race or ethnicity do you most
closely identify with?"; Ecolab spells it "Ethnicity".

Holding the yes-or-no answer under the name "ethnicity" made the second answer
the first: at Ecolab, "Ethnicity" resolved to "No", which is not a group, so
the question was left blank.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.formfill import choose_option

PROFILE = {
    "race": "Asian",
    "ethnicity": "Asian",
    "hispanic_or_latino": "No",
    "custom_answers": {
        "ethnicity": "Asian",
        "race or ethnicity": "Asian",
        "hispanic or latino": "No",
    },
}

GROUPS = ["Select One", "American Indian or Alaska Native", "Asian",
          "Black or African American", "Hispanic or Latino",
          "Native Hawaiian or Other Pacific Islander", "Two or More Races",
          "White", "I do not wish to answer"]
YES_NO = ["Select One", "Yes", "No", "I do not wish to answer"]

# Workday appends the country to each option on some tenants.
QUALIFIED = [o + " (United States of America)" for o in GROUPS[1:]]

CASES = [
    ("Ethnicity", GROUPS, "Asian"),
    ("What race or ethnicity do you most closely identify with?", GROUPS,
     "Asian"),
    ("What race or ethnicity do you most closely identify with?", QUALIFIED,
     "Asian (United States of America)"),
    ("Hispanic or Latino?", YES_NO, "No"),
    ("Are you Hispanic or Latino?", YES_NO, "No"),
]

failures = []
for question, options, wanted in CASES:
    got = choose_option(question, options, PROFILE)
    if got != wanted:
        failures.append("%r answered %r, wanted %r"
                        % (question[:44], got, wanted))

# The group question must never be answered with a yes or no.
for question in ("Ethnicity",
                 "What race or ethnicity do you most closely identify with?"):
    got = choose_option(question, GROUPS, PROFILE)
    if got in ("Yes", "No"):
        failures.append("%r was answered %r, which is not a group"
                        % (question[:44], got))

# Gary should not depend on a field being named the way the employer words the
# question. With the profile as it wrongly was -- "ethnicity" holding the
# Hispanic answer -- the list itself still settles it: "Asian" is the one thing
# on file that appears among the groups offered.
from watcher.formfill import reasoned_option

MISNAMED = {"race": "Asian", "ethnicity": "No", "gender": "Male",
            "state": "Texas", "sponsorship": "No"}

chosen, why = reasoned_option("Ethnicity", GROUPS, MISNAMED)
if chosen != "Asian":
    failures.append("reasoning from the list gave %r, wanted 'Asian'" % chosen)
elif not why:
    failures.append("a reasoned answer gave no working")

chosen, _ = reasoned_option("Gender", ["Select One", "Male", "Female"],
                            MISNAMED)
if chosen != "Male":
    failures.append("reasoning from the list gave %r for gender" % chosen)

# Nothing known is on the list: leave it rather than guess.
chosen, _ = reasoned_option("Preferred office",
                            ["Boston", "Chicago", "New York"], MISNAMED)
if chosen is not None:
    failures.append("guessed %r from a list holding nothing known" % chosen)

# A yes or no fits far too many questions to be evidence of anything.
chosen, _ = reasoned_option("Some unfamiliar question", ["Yes", "No"],
                            MISNAMED)
if chosen is not None:
    failures.append("treated a yes/no list as evidence: %r" % chosen)

# Several facts on one list is genuine ambiguity, and the candidate's to
# resolve.
chosen, _ = reasoned_option("Pick one", ["Asian", "Male"], MISNAMED)
if chosen is not None:
    failures.append("chose %r where two known facts both fit" % chosen)

total = len(CASES) + 2 + 5
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
