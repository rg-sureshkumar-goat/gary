"""Answering from what is known, and refusing to invent.

Every application asks something new, and the details already given are
usually enough. The line that matters is between deriving an answer from a
fact the candidate provided and inventing one they never gave: they certify
the application is true when they submit it, so a confident guess is worse
than a blank they can fill in seconds.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import infer

TODAY = datetime.date(2026, 8, 28)

PROFILE = {
    "education_1_end": "05/2028",
    "education_2_end": "05/2027",
    "graduation": "05/31/2028",
    "work_authorization": "Yes",
    "sponsorship": "No",
    "education_2_start": "08/2024",
    "education_1_start": "07/2026",
    "work_1_end": "04/2026",
    "work_2_end": "12/2025",
}

DERIVED = [
    ("Are you 18 years of age or older?", "Yes"),
    ("Are you legally authorized to work in the United States?", "Yes"),
    ("Do you now or will you at any point in the future require sponsorship "
     "to work in the United States?", "No"),
    ("Regardless of whether you require immigration sponsorship, do you have "
     "any reason to believe that your basis for employment authorization in "
     "the U.S. will change within the next 1-3 years?", "No"),
    ("Do you have another job(s) that you plan to continue if you become "
     "employed by Ecolab?", "No"),
    # Prior dealings with an employer default to no, as the candidate asked.
    ("Have you ever participated in the recruitment process with Ecolab or "
     "any of its subsidiaries?", "No"),
    ("Have you previously applied to this company?", "No"),
    # Willing to work where the job is, however the question is framed. A
    # phrasing that names a city is the same question, not a new one.
    ("Are you willing to relocate for this position?", "Yes"),
    ("Are you able to work in-person at our Saint Paul office?", "Yes"),
    ("Would you be able to relocate to Saint Paul, MN for the summer?", "Yes"),
    ("Can you commute to our Chicago office daily?", "Yes"),
    ("Are you open to working on-site?", "Yes"),
    # Which degree is asked about matters: they finish a year apart, and the
    # lists these are chosen from are written as a month and a year.
    ("Select the month and year you are expecting to graduate with your "
     "bachelor's degree.", "May 2027"),
    ("When do you expect to graduate with your master's degree?", "May 2028"),
]

# Facts the candidate has never given. Nothing on file implies them.
REFUSED = [
    # No pay advertised, so the calculation has no input.
    "What's your desired annual salary expectation? (Please express in gross "
    "amount in USD)",
    # The details of prior contact are the candidate's, even though whether
    # there was any defaults to no.
    "When did you previously apply, and for which role?",
    "Why do you want to work here?",
    "Who referred you to this position?",
    "Describe a time you led a team.",
]

failures = []

for question, wanted in DERIVED:
    got, why = infer.answer(question, PROFILE, today=TODAY)
    if got != wanted:
        failures.append("%r answered %r, wanted %r" % (question[:40], got, wanted))
    elif not why:
        failures.append("%r gave no reason; the candidate signs for it"
                        % question[:40])

for question in REFUSED:
    got, _ = infer.answer(question, PROFILE, today=TODAY)
    if got is not None:
        failures.append("invented an answer to %r: %r" % (question[:40], got))

# "graduat" sits inside "undergraduate", so a yes-or-no question about having
# finished a degree was being answered with a month. A date must actually be
# asked for.
from watcher.formfill import value_for

if value_for("Have you completed your undergraduate degree?", PROFILE) != "No":
    failures.append("a yes/no question about a degree was answered with a date")
if value_for("What is your degree?", dict(PROFILE, degree="Masters")) != "Masters":
    failures.append("asking which degree no longer answers with the degree")
if value_for("Select the month and year you are expecting to graduate with "
             "your bachelor's degree.", PROFILE) != "May 2027":
    failures.append("asking when a degree ends answered with its name")

# What is finished as of today, by the calendar rather than by a model's
# reading of it: a local model repeatedly called a degree ending next year
# completed, and this is arithmetic, not judgement.
got, _ = infer.answer("What is your highest level of education completed?",
                      PROFILE, today=TODAY)
if got != "High School":
    failures.append("highest completed gave %r; no degree has finished by "
                    "August 2026" % got)
done = dict(PROFILE, education_2_end="05/2025")
got, _ = infer.answer("What is your highest level of education completed?",
                      done, today=TODAY)
if got != "Bachelor":
    failures.append("a bachelor's finished in 2025 gave %r" % got)

# Legal authorisation shares some wording with the relocation question and is
# a different thing: it turns on his authorisation, not his willingness.
for question, wanted in (
        ("Are you legally authorized to work in the United States?", "Yes"),
        ("Are you eligible to work in the US without sponsorship?", "No")):
    got, _ = infer.answer(question, PROFILE, today=TODAY)
    if got != wanted:
        failures.append("%r answered %r, wanted %r -- authorisation is not "
                        "relocation" % (question[:44], got, wanted))

# A threshold nothing on file settles.
got, _ = infer.answer("Are you 21 years of age or older?", PROFILE, today=TODAY)
if got is not None:
    failures.append("claimed an age it cannot know: %r" % got)

# A job still running means the question cannot be answered from dates.
current = dict(PROFILE, work_1_end="12/2027")
got, _ = infer.answer("Do you have another job(s) that you plan to continue?",
                      current, today=TODAY)
if got is not None:
    failures.append("said no other job while one is still running")

# Nothing known at all: no answer, not a guess.
got, _ = infer.answer("Are you 18 years of age or older?", {}, today=TODAY)
if got is not None:
    failures.append("claimed an age with nothing on file")

# A salary is asked for once the posting's advertised pay has been read, and
# is entered with a dollar sign, as the candidate asked.
paid = dict(PROFILE, desired_salary="$49,920",
            desired_salary_reason="24/hour x 40 hours x 52 weeks")
got, why = infer.answer("What's your desired annual salary expectation?",
                        paid, today=TODAY)
if got != "$49,920":
    failures.append("the salary was %r, wanted '$49,920'" % got)
if got and not got.startswith("$"):
    failures.append("the salary was entered without a dollar sign")
if not why:
    failures.append("the salary gave no reason; the candidate signs for it")

total = len(DERIVED) + len(REFUSED) + 3 + 3 + 3 + 2 + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
