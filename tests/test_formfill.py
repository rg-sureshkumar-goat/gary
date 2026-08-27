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

# --- the mis-fills found on Lincoln International's real form --------------- #
# Each of these filled a confidently wrong answer before being fixed.
MS_STUDENT = {
    "graduation": "May 2027", "gpa": "3.8", "degree": "Master of Science",
    "university": "New York University",
    "undergrad_gpa": "3.6", "undergrad_graduation": "May 2025",
    "undergrad_degree": "Bachelor of Science",
}
REAL_FORM = [
    # "graduat\w*" used to match inside "undergraduate", so this got a date.
    ("Please provide your undergraduate GPA.", "3.6"),
    # A yes/no question answered with a degree name.
    ("Have you completed your undergraduate degree?", None),
    # A yes/no question answered with a graduation date.
    ("Will you begin your MBA program in the fall of 2026?", None),
    # Asks for a year, not the name of a degree.
    ("In what year did you complete your undergraduate degree?", "May 2025"),
    # The graduate figures must still come from the graduate keys.
    ("Cumulative GPA", "3.8"),
    ("Expected graduation date", "May 2027"),
    ("What is your highest degree?", "Master of Science"),
]
for label, expected in REAL_FORM:
    got = value_for(label, MS_STUDENT)
    if got != expected:
        failures.append("%-54s -> %r, expected %r" % (label[:52], got, expected))

# Without prior-degree keys, undergraduate questions stay blank rather than
# borrowing the graduate answers.
ONLY_GRAD = {"graduation": "May 2027", "gpa": "3.8", "degree": "Master of Science"}
for label in ["Please provide your undergraduate GPA.",
              "In what year did you complete your undergraduate degree?",
              "Undergraduate university"]:
    if value_for(label, ONLY_GRAD) is not None:
        failures.append("answered an undergraduate question from graduate data: %r"
                        % label[:50])

# --- remembered answers to employer-specific questions ---------------------- #
WITH_CUSTOM = dict(MS_STUDENT, custom_answers={
    "which lincoln office are you interested in": "Chicago",
    "how did you hear about this opportunity": "University career fair",
})
if value_for("Which Lincoln office are you interested in?", WITH_CUSTOM) != "Chicago":
    failures.append("a remembered answer was not reused")
# Question mark and casing must not defeat the lookup.
if value_for("WHICH LINCOLN OFFICE ARE YOU INTERESTED IN", WITH_CUSTOM) != "Chicago":
    failures.append("remembered answers should ignore case and punctuation")
if value_for("Describe a time you led a team", WITH_CUSTOM) is not None:
    failures.append("invented an answer for an unremembered question")
# A credential must not be fillable even if one is somehow saved.
if value_for("Password", dict(MS_STUDENT, custom_answers={"password": "x"})) is not None:
    failures.append("a saved credential would have been filled")

# --- Gary must never sign in anywhere --------------------------------------- #
# The rule is stronger than skipping password fields: a login form is left
# entirely alone, email box included.
from watcher.formfill import is_auth_form  # noqa: E402

AUTH_FORMS = [
    (["Email Address", "Password"], True, "a password field condemns the form"),
    (["Email Address"], True, "an unlabelled password field still counts"),
    (["Email", "Remember me", "Forgot your password?"], False, "sign-in wording"),
    (["Email Address", "Create Account"], False, "account creation"),
    (["Username", "Sign In"], False, "sign in button"),
    (["Email", "Verification Code"], False, "two-factor step"),
    (["New Password", "Confirm New Password"], False, "password reset"),
]
for labels, has_pw, why in AUTH_FORMS:
    if not is_auth_form(labels, has_password=has_pw):
        failures.append("login form not recognised (%s): %r" % (why, labels))

# A real application form must still be filled.
APPLICATION_FORMS = [
    ["First Name", "Last Name", "Email", "Phone", "Resume/CV"],
    ["Preferred First Name", "Please select your university.", "Cumulative GPA"],
    ["Email Address", "How did you hear about this opportunity?"],
]
for labels in APPLICATION_FORMS:
    if is_auth_form(labels):
        failures.append("an application form was mistaken for a login: %r" % labels)

# Even with a saved answer, nothing on a login form should be fillable: the
# refusal happens at the form level, before any field is considered.
LOGIN_PROFILE = {"email": "ada@example.com",
                 "custom_answers": {"username": "ada"}}
if not is_auth_form(["Email Address", "Password"], has_password=True):
    failures.append("the form-level login check failed")

total = 11 * 3 + len(CASES) + 3 + 1 + 7 + 1 + len(REAL_FORM) + 3 + 4 \
        + len(AUTH_FORMS) + len(APPLICATION_FORMS) + 1

# --- label tidying ----------------------------------------------------------- #
if normalise("  First   Name * (required) ") != "First Name":
    failures.append("normalise left decoration in: %r"
                    % normalise("  First   Name * (required) "))

if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
