"""Answering a question from what is already known, rather than recorded.

Every employer asks something new, and the details already given are usually
enough. Requiring an exact recorded answer for each wording turns every new
application into another round of questions.

The line is between deriving and inventing. Deriving is answering "are you at
least eighteen?" from dates already given, or "will your work authorisation
change?" from an authorisation already stated -- the answer follows from a
fact the candidate provided. Inventing is supplying a fact they never gave: a
salary expectation, a referral, a reason for wanting the job. Those are left
for them, because a blank they fill costs seconds and a wrong answer on a
submitted application cannot be taken back.

Every answer worked out here is reported as inferred, since the candidate
certifies the application is true when they submit it.
"""

import datetime
import re

from . import formfill


_AGE = re.compile(r"\b(?:are|am)\s+you\s+.*?\b(\d{2})\s*(?:years?)?\s*"
                  r"(?:of\s+age\s+)?or\s+older|at\s+least\s+(\d{2})\s+years",
                  re.I)
_AUTHORISED = re.compile(r"legally\s+authori[sz]ed|authori[sz]ed\s+to\s+work|"
                         r"eligible\s+to\s+work", re.I)
_SPONSORSHIP = re.compile(r"sponsorship|visa\s+petition|immigration-related", re.I)
_BASIS_CHANGES = re.compile(r"basis\s+for\s+employment\s+authori[sz]ation.*"
                            r"change|authori[sz]ation.*will\s+change", re.I)
_ANOTHER_JOB = re.compile(r"another\s+job|other\s+employment|"
                          r"outside\s+employment|plan\s+to\s+continue", re.I)

# Asked of the candidate alone. No fact on file implies these, and a
# confident guess at one is worse than a blank.
_SALARY = re.compile(r"salary|compensation|wage|pay\s+expectation|"
                     r"desired\s+pay|expected\s+pay", re.I)

# Prior dealings with this employer. The candidate's standing default is no.
_PRIOR_CONTACT = re.compile(
    r"(?:ever|previously|before).{0,40}(?:particip|appl|interview|"
    r"recruit|employed|worked)|"
    r"(?:particip|appl|interview).{0,30}(?:with|at|for)\s+(?:us|this|the)\s+"
    r"(?:company|organi[sz]ation|employer)|career\s+fair", re.I)

# Asked of the candidate alone. Nothing on file implies these, and a
# confident guess at one is worse than a blank they can fill in seconds.
# Questions about prior dealings with an employer used to sit here; they now
# have a stated default, so only requests for the details of that contact --
# when, which role -- are still left alone, handled where the default is
# applied.
_NEVER = re.compile(r"why\s+do\s+you|tell\s+us|describe|"
                    r"in\s+your\s+own\s+words|referred\s+by|referral|"
                    r"cover\s+letter", re.I)


def _year(value):
    """The four-digit year in a stored date, or None."""
    found = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(found.group(0)) if found else None


def _is_no(value):
    return str(value or "").strip().lower() in ("no", "n", "false")


def _is_yes(value):
    return str(value or "").strip().lower() in ("yes", "y", "true")


def answer(label, profile, today=None):
    """What can be worked out for this question: (value, why) or (None, None).

    The reason is returned so it can be shown to the candidate, who is the one
    signing for it.
    """
    question = formfill.normalise(label).strip().rstrip("?").lower()
    if not question or _NEVER.search(question):
        return None, None
    today = today or datetime.date.today()

    # What the employer already advertises, annualised. Worked out from the
    # posting rather than asked for, and reported so it can be seen.
    if _SALARY.search(question):
        wanted = profile.get("desired_salary")
        if wanted:
            return str(wanted), (profile.get("desired_salary_reason")
                                 or "the pay this posting advertises")
        return None, None

    # Prior dealings with this employer default to no, as the candidate asked.
    # A question wanting the details of prior contact is still theirs.
    if _PRIOR_CONTACT.search(question) and not re.search(
            r"when|which\s+role|details|describe|explain", question):
        return "No", "your default answer for prior contact with an employer"

    # Old enough. An undergraduate degree begun years ago, or a job held,
    # settles eighteen. Nothing here settles a higher threshold.
    age = _AGE.search(question)
    if age:
        threshold = int(age.group(1) or age.group(2))
        if threshold > 18:
            return None, None
        started = min([y for y in (_year(profile.get("education_2_start")),
                                   _year(profile.get("education_1_start")),
                                   _year(profile.get("work_1_start")),
                                   _year(profile.get("work_2_start")))
                       if y] or [0])
        if started and today.year - started >= 1:
            return "Yes", ("at university since %d, so over 18" % started)
        return None, None

    if _BASIS_CHANGES.search(question):
        if _is_no(profile.get("sponsorship")) and _is_yes(
                profile.get("work_authorization")):
            return "No", ("authorised to work and needing no sponsorship, so "
                          "no change expected")
        return None, None

    if _SPONSORSHIP.search(question):
        stated = profile.get("sponsorship")
        if stated:
            return str(stated), "your stated sponsorship requirement"
        return None, None

    if _AUTHORISED.search(question):
        stated = profile.get("work_authorization")
        if stated:
            return str(stated), "your stated work authorisation"
        return None, None

    # Another job being kept on. Every job on file having ended says no.
    if _ANOTHER_JOB.search(question):
        ends = [profile.get("work_1_end"), profile.get("work_2_end")]
        given = [e for e in ends if e]
        if not given:
            return None, None
        for end in given:
            year = _year(end)
            month = re.match(r"\s*(\d{1,2})\s*[/-]", str(end))
            if year is None:
                return None, None
            if year > today.year:
                return None, None
            if year == today.year and month and int(month.group(1)) >= today.month:
                return None, None
        return "No", "every job in your history has an end date in the past"

    return None, None
