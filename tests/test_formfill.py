"""Matching saved answers to application-form fields.

The failure that matters here is not a blank box -- it is a *confidently wrong*
answer submitted to an employer under the user's name. So the tests lean on
what must never be filled and what must be left alone.

Run with:  python3 -m tests.test_formfill
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.formfill import (  # noqa: E402
    key_for, is_credential, value_for, choose_option, normalise)

failures = []

PROFILE = {
    "first_name": "Ada", "last_name": "Lovelace",
    "preferred_first_name": "Ada", "email": "ada@example.com",
    "phone": "555-0100", "university": "New York University",
    "graduation": "May 2027", "gpa": "3.8",
    "sponsorship": "No", "work_authorization": "Yes",
    "major": "Finance",
}

# --- credentials are never filled, whatever the label ----------------------- #
for label in ["Password", "Confirm Password", "Create a password", "PIN",
              "Security Question", "One-Time Code", "Social Security Number",
              "SSN", "Credit Card Number", "CVV", "Bank Account Number"]:
    if not is_credential(label):
        failures.append("not recognised as a credential: %r" % label)
    if key_for(label) is not None:
        failures.append("credential field mapped to a profile key: %r" % label)
    if value_for(label, dict(PROFILE, password="hunter2")) is not None:
        failures.append("a credential field would have been filled: %r" % label)

# --- label mapping, including order-sensitive cases ------------------------- #
CASES = [
    ("First Name *", "first_name"),
    ("Legal first name", "first_name"),
    ("Given Name", "first_name"),
    # Must beat the plain "first name" pattern.
    ("Preferred First Name", "preferred_first_name"),
    ("What name do you go by?", "preferred_first_name"),
    ("Last Name", "last_name"),
    ("Surname", "last_name"),
    ("Email Address (required)", "email"),
    ("Mobile Phone", "phone"),
    ("LinkedIn Profile", "linkedin"),
    ("Please select your university.", "university"),
    ("What college do you attend?", "university"),
    ("Expected graduation date", "graduation"),
    ("Anticipated Graduation Year", "graduation"),
    ("Cumulative GPA", "gpa"),
    ("Will you now or in the future require sponsorship?", "sponsorship"),
    ("Are you legally authorized to work in the United States?",
     "work_authorization"),
    ("How did you hear about this opportunity?", "referral"),
    ("Field of Study", "major"),
]
for label, expected in CASES:
    got = key_for(label)
    if got != expected:
        failures.append("%-52s -> %r, expected %r" % (label[:50], got, expected))

# An unrecognised question is left alone rather than guessed at.
for label in ["Which Lincoln office are you interested in?",
              "Describe a time you led a team", "Reference 1 name"]:
    if value_for(label, PROFILE) is not None:
        failures.append("guessed at an unrecognised question: %r" % label)

# A key missing from the profile means the field stays empty.
if value_for("LinkedIn Profile", PROFILE) is not None:
    failures.append("filled a field whose profile key is absent")

# --- dropdowns: match confidently or not at all ----------------------------- #
if choose_option("Please select your university.",
                 ["Columbia University", "New York University", "Yale"],
                 PROFILE) != "New York University":
    failures.append("failed to match the university option")

if choose_option("Will you now or in the future require sponsorship?",
                 ["Yes", "No"], PROFILE) != "No":
    failures.append("failed to match a yes/no answer")

if choose_option("Are you legally authorized to work in the United States?",
                 ["Yes, I am authorized", "No, I am not"],
                 PROFILE) != "Yes, I am authorized":
    failures.append("failed to match a yes-prefixed option")

# A GPA threshold question cannot be answered from a GPA number -- the profile
# says "3.8" and the options are Yes/No. Leaving it blank is correct.
if choose_option("Is your cumulative GPA above a 3.5?", ["Yes", "No"],
                 PROFILE) is not None:
    failures.append("guessed at a threshold question from a raw GPA")

# No plausible option means no selection.
if choose_option("Please select your university.",
                 ["Harvard University", "Stanford University"],
                 PROFILE) is not None:
    failures.append("picked a university that is not the user's")

if choose_option("Preferred office", ["Chicago", "New York"], PROFILE) is not None:
    failures.append("answered a question absent from the profile")

if choose_option("Please select your university.", [], PROFILE) is not None:
    failures.append("returned a choice from an empty option list")

# --- label tidying ----------------------------------------------------------- #
if normalise("  First   Name * (required) ") != "First Name":
    failures.append("normalise left decoration in: %r"
                    % normalise("  First   Name * (required) "))

total = 11 * 3 + len(CASES) + 3 + 1 + 7 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
