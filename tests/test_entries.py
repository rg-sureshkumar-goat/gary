"""Repeated entries, verbatim descriptions, defaults, and today's date.

Every application carries two education entries and two jobs whose fields are
labelled identically. Keeping them apart, and reusing the descriptions exactly
as typed, is the difference between a usable pre-fill and a scrambled one.

Run with:  python3 -m tests.test_entries
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.formfill import (  # noqa: E402
    answer_key, block_of, default_for, as_today_token, expand_tokens, value_for)

failures = []
TODAY = datetime.date(2026, 8, 27)

# --- telling education from work history ------------------------------------ #
for section, ident, label, expected in [
    ("From", "degree", "Degree", "education"),
    ("From", "school", "School or University", "education"),
    ("From", "gpa", "Overall Result (GPA)", "education"),
    ("From", "company", "Company", "work history"),
    ("From", "jobTitle", "Job Title", "work history"),
    ("From", "roleDescription", "Role Description", "work history"),
]:
    got = block_of(section, ident, label)
    if got != expected:
        failures.append("%-24s -> %r, expected %r" % (label, got, expected))

# --- two entries must never collide ----------------------------------------- #
if answer_key("From", "Degree", "degree", 1) == answer_key("From", "Degree", "degree", 2):
    failures.append("education 1 and 2 share a key")
if answer_key("From", "Company", "company", 1) == answer_key("From", "Company", "company", 2):
    failures.append("work history 1 and 2 share a key")
if answer_key("From", "Degree", "degree", 1) != "education 1 :: degree":
    failures.append("unexpected education key: %r"
                    % answer_key("From", "Degree", "degree", 1))
if answer_key("From", "Company", "company", 2) != "work history 2 :: company":
    failures.append("unexpected work key: %r"
                    % answer_key("From", "Company", "company", 2))

# --- descriptions are reused exactly as typed ------------------------------- #
DESCRIPTION = "- Tracked $15K+ cash inflow\n- Built a DCF model\n  * sensitivity"
PROFILE = {"answers": {
    "work history 1 :: role description": DESCRIPTION,
    "work history 2 :: role description": "- Second role\n- Another line",
}}
got = value_for("Role Description", PROFILE, "From", "roleDescription", 1)
if got != DESCRIPTION:
    failures.append("description was altered: %r" % got)
if "\n" not in got or "  * sensitivity" not in got:
    failures.append("line breaks or indentation were lost")
second = value_for("Role Description", PROFILE, "From", "roleDescription", 2)
if second == got:
    failures.append("both jobs returned the same description")
if second != "- Second role\n- Another line":
    failures.append("second description wrong: %r" % second)

# --- the same question at a different employer ------------------------------- #
# Answers are keyed partly by the field's id, which differs between Workday
# tenants. An answer recorded at one employer must still be found at the next,
# or every application after the first fills nothing.
RECORDED_AT_A = {"answers": {
    "work history 1 :: role description :: workexperienceroledescription": DESCRIPTION,
    "work history 2 :: role description :: workexperienceroledescription": "second job",
    "work history 1 :: company :: companyname": "Austin Film Festival",
    "work history 2 :: company :: companyname": "Manifesta Film",
    "education 1 :: degree :: degreedropdown": "Masters",
}}
LOOKED_UP_AT_B = [
    ("Role Description", "jobDescription", 1, DESCRIPTION),
    ("Role Description", "jobDescription", 2, "second job"),
    ("Company", "employerName", 1, "Austin Film Festival"),
    ("Company", "employerName", 2, "Manifesta Film"),
    ("Degree", "degreeSelect", 1, "Masters"),
]
for label, ident, entry, expected in LOOKED_UP_AT_B:
    got = value_for(label, RECORDED_AT_A, "Work Experience", ident, entry)
    if got != expected:
        failures.append("%s entry %d at another employer -> %r, expected %r"
                        % (label, entry, str(got)[:30], str(expected)[:30]))

# Entries must still not bleed into one another.
if value_for("Company", RECORDED_AT_A, "Work Experience", "employerName", 1) == \
        value_for("Company", RECORDED_AT_A, "Work Experience", "employerName", 2):
    failures.append("ignoring the field id merged the two work entries")

# --- "have you worked here before" defaults to No --------------------------- #
FOR_DEFAULT_NO = [
    "Have you previously been employed with Houlihan Lokey?",
    "Have you ever worked for this company?",
    "Are you a former employee?",
    "Have you previously worked at our firm?",
    "Previous employment with Citi?",
    # Employers usually name themselves rather than saying "this company".
    "Have you worked at BRG before?",
    "Have you ever worked for Berkeley Research Group?",
    "Have you been employed by this company before?",
    "Have you worked here before?",
    "Prior employment with the company?",
    "Are you a rehire?",
]

# Questions about a field of work, not about this employer. Answering No there
# would be plainly wrong for someone with the experience.
NOT_PRIOR_EMPLOYMENT = [
    "Have you worked in finance before?",
    "Have you worked in consulting previously?",
    "Have you worked on M&A deals before?",
    "Have you worked with clients before?",
]
for label in NOT_PRIOR_EMPLOYMENT:
    if default_for(label) is not None:
        failures.append("industry experience answered as prior employment: %r"
                        % label)
for label in FOR_DEFAULT_NO:
    if default_for(label) != "No":
        failures.append("should default to No: %r -> %r" % (label, default_for(label)))
    if value_for(label, {}) != "No":
        failures.append("default not applied when nothing is recorded: %r" % label)

# The user is in a 4+1, so the bachelor's is not finished yet.
UNDERGRAD_NO = [
    "Have you completed your undergraduate degree?",
    "Have you completed your undergraduate studies?",
    "Have you received your bachelor's degree?",
    "Have you earned your undergraduate degree?",
]
for label in UNDERGRAD_NO:
    if default_for(label) != "No":
        failures.append("should default to No: %r -> %r" % (label, default_for(label)))
# The year question is not a yes/no and must keep its recorded answer.
if default_for("In what year did you complete your undergraduate studies?") is not None:
    failures.append("the undergraduate year question was given a yes/no default")
recorded = {"answers": {"in what year did you complete your undergraduate studies": "2027"}}
if value_for("In what year did you complete your undergraduate studies?", recorded) != "2027":
    failures.append("a recorded undergraduate year was overwritten by a default")

# Unrelated questions get no invented default.
for label in ["Are you willing to relocate?", "Which office interests you?",
              "Are you legally authorized to work in the United States?"]:
    if default_for(label) is not None:
        failures.append("invented a default for %r" % label)

# A recorded answer beats the default, so a real prior employer is respected.
if value_for("Have you previously worked for this company?",
             {"answers": {"have you previously worked for this company": "Yes"}}) != "Yes":
    failures.append("the default overrode a recorded answer")

# --- today's date is worked out at fill time -------------------------------- #
stored = as_today_token(TODAY.strftime("%m/%d/%Y"), TODAY)
if not str(stored).startswith("{today}"):
    failures.append("today's date was stored literally: %r" % stored)
if expand_tokens(stored, datetime.date(2027, 1, 5)) != "01/05/2027":
    failures.append("stored date did not follow the day it is filled: %r"
                    % expand_tokens(stored, datetime.date(2027, 1, 5)))
# The recorded format is kept.
iso = as_today_token(TODAY.strftime("%Y-%m-%d"), TODAY)
if expand_tokens(iso, datetime.date(2027, 1, 5)) != "2027-01-05":
    failures.append("the recorded date format was not preserved")
# A date that is not today is a real answer -- a graduation year, say.
if as_today_token("05/01/2025", TODAY) != "05/01/2025":
    failures.append("a genuine past date was turned into a token")
if as_today_token("Manifesta Film", TODAY) != "Manifesta Film":
    failures.append("ordinary text was mangled by date detection")

# --- problems found on a real Workday recording ----------------------------- #
from watcher.formfill import (  # noqa: E402
    strip_value, usable_identity, is_page_furniture)

# Workday joins a dropdown's question to its selection, so "Degree" reads as
# "Degree Bachelors" once answered. The key then changed with the answer, and
# both education entries were filed as entry 1.
if strip_value("Degree Bachelors", "Bachelors") != "Degree":
    failures.append("a selected value was not stripped from its own label")
if strip_value("Degree Masters", "Masters") != "Degree":
    failures.append("a selected value was not stripped from its own label")
if strip_value("Degree Bachelors", "Bachelors") != strip_value("Degree Masters", "Masters"):
    failures.append("two entries of the same question still differ")
# A label that is only the value must not be emptied.
if strip_value("Yes", "Yes") != "Yes":
    failures.append("a label identical to its value was destroyed")
# An unrelated value is left alone.
if strip_value("Company", "Manifesta Film") != "Company":
    failures.append("stripping altered an unrelated label")

# Generated ids change between sessions and mean nothing.
for bad in ["f7187c9d9ecd10019f31601fd5d00002", "a1b2c3d4e5f60718", "0f9e8d7c6b5a4931"]:
    if usable_identity(bad):
        failures.append("an opaque generated id was used as a key: %r" % bad)
for good in ["companyName", "jobTitle", "gradeAverage", "degree"]:
    if usable_identity(good) != good:
        failures.append("a meaningful field id was discarded: %r" % good)

# Menus and language pickers are not application questions.
for label, ident in [("Settings", "utilityMenuButton"), ("Search", "searchBox"),
                     ("English", "languageSelector")]:
    if not is_page_furniture(label, ident):
        failures.append("page furniture was treated as a question: %r" % label)
if is_page_furniture("Company", "companyName"):
    failures.append("a real field was mistaken for page furniture")

# A specific question must never be dragged into a numbered block: LinkedIn and
# country were being filed under "work history 1".
for question in ["Please provide your LinkedIn profile",
                 "Are you willing to relocate if required?"]:
    if "work history" in answer_key("From", question, "x", 1):
        failures.append("a standalone question was numbered into a block: %r"
                        % question)

# --- entry numbers hidden inside the field id -------------------------------- #
# Workday numbers repeats in the id itself, so two jobs' descriptions looked
# like two different questions and both were filed under work history 1.
from watcher.formfill import (  # noqa: E402
    base_identity, is_option_label, date_part_today)

if base_identity("workExperience6RoleDescription") != \
        base_identity("workExperience7RoleDescription"):
    failures.append("two entries of the same field still look different")
if not base_identity("workExperience6RoleDescription"):
    failures.append("stripping digits emptied a meaningful id")
if base_identity("f7187c9d9ecd10019f31601fd5d00002"):
    failures.append("an opaque id survived digit-stripping")

# With a shared base, occurrence counting separates the two jobs.
k1 = answer_key("From", "Role Description", "workExperienceRoleDescription", 1)
k2 = answer_key("From", "Role Description", "workExperienceRoleDescription", 2)
if k1 == k2:
    failures.append("the two descriptions still share a key")
if not k1.startswith("work history 1") or not k2.startswith("work history 2"):
    failures.append("descriptions were not numbered as jobs: %r / %r" % (k1, k2))

# --- option text is not a question ------------------------------------------- #
for label in ["Yes", "No", "yes", "N/A", "None", "Other"]:
    if not is_option_label(label):
        failures.append("option text treated as a question: %r" % label)
for label in ["Are you at least 18 years of age?", "Company", "Role Description"]:
    if is_option_label(label):
        failures.append("a real question mistaken for option text: %r" % label)

# A control labelled only "Yes" still carries a real answer when the question
# is the heading above it. Discarding those lost the sponsorship question and
# three others from a real recording.
from watcher.formfill import is_reusable_question  # noqa: E402
for heading in ["Are you at least 18 years of age?",
                "Have you ever been dismissed, terminated, or asked to resign?",
                "Will you now or in the future require sponsorship?"]:
    if not is_reusable_question(heading):
        failures.append("a question heading was not recognised: %r" % heading)
# A heading that is not a question must not become one.
for heading in ["From", "Education", "Work Experience", ""]:
    if is_reusable_question(heading):
        failures.append("a section heading was mistaken for a question: %r" % heading)

# --- a signature date split across three boxes ------------------------------- #
WHEN = datetime.date(2027, 1, 5)
for part, expected in [("Day", "5"), ("Month", "1"), ("Year", "2027")]:
    got = date_part_today(part, "Date", WHEN)
    if got != expected:
        failures.append("signature %s -> %r, expected %r" % (part, got, expected))
# Employment and education dates are real answers and must be left alone.
for section in ["From", "To", "Work Experience", "Education"]:
    if date_part_today("Year", section, WHEN) is not None:
        failures.append("an employment/education year was overwritten with today's")
# The whole-date path still works where a form uses one box.
if value_for("Day", {}, "Date") != str(datetime.date.today().day):
    failures.append("split signature date not filled from today")

total = 6 + 4 + 4 + len(FOR_DEFAULT_NO) * 2 + 3 + 1 + 5 + 5 + 7 + 4 + 2 \
        + 5 + 9 + 3 + 4 + 1 + 7 + len(UNDERGRAD_NO) + 2 + len(NOT_PRIOR_EMPLOYMENT) + len(LOOKED_UP_AT_B) + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
