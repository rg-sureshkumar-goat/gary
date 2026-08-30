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
# When a degree is expected. Which degree is being asked about matters: the
# bachelor's and the master's finish a year apart.
_GRADUATION = re.compile(r"graduat|completion\s+date|finish.{0,20}degree", re.I)
_UNDERGRAD_ASKED = re.compile(r"bachelor|undergraduate|\bb\.?[sa]\.?\b", re.I)
_GRADUATE_ASKED = re.compile(r"master|graduate\s+degree|\bm\.?[sba]\.?\b|"
                             r"doctorate|phd", re.I)

# A date is being asked for, rather than a fact about a degree.
_WHEN = re.compile(r"\bwhen\b|\bmonth\b|\byear\b|\bdate\b|expect(?:ed|ing)|"
                   r"anticipat", re.I)

# "Highest level of education completed" -- what is finished as of today.
_HIGHEST_COMPLETED = re.compile(
    r"highest\s+(?:level\s+of\s+)?(?:education|degree)|"
    r"(?:education|degree)\s+(?:level\s+)?completed|"
    r"highest\s+.{0,20}\s+attained", re.I)

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")

# A relative or family member employed by the company.
_RELATIVE = re.compile(
    r"\b(?:relative|relatives|family\s+member|family\s+members|immediate\s+"
    r"family|spouse|sibling|parent)\b", re.I)

# The follow-up asking who that person is, which is not a yes or no.
_RELATIVE_NAME = re.compile(
    r"list\s+(?:their|your|the)|name\s+of\s+(?:the\s+)?(?:relative|family)|"
    r"who\s+(?:is|are)\s+(?:they|the)|if\s+(?:you\s+answered\s+)?yes|"
    r"please\s+(?:list|name|specify|provide)", re.I)


def name_of_relative(label):
    """The follow-up naming a relative, which only needs answering if
    the form insists. An unnecessary "N/A" is noise on a form a human reads.
    """
    question = formfill.normalise(label).strip().rstrip("?").lower()
    return bool(_RELATIVE.search(question) and _RELATIVE_NAME.search(question))


_RELOCATE = re.compile(
    r"relocat|willing\s+to\s+move|able\s+to\s+move|"
    r"(?:able|willing|open)\s+to\s+work(?:ing)?\s+(?:in|at|from|on)\b|"
    r"work(?:ing)?\s+(?:in[\s-]?person|on[\s-]?site|onsite|in\s+office)|"
    r"commut|report\s+to\s+(?:the\s+)?office|based\s+in", re.I)

# Legal authorisation is a different question that shares some wording.
_AUTHORISATION = re.compile(r"authori[sz]|eligib|sponsor|visa|legally|"
                            r"work\s+permit|right\s+to\s+work", re.I)

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


def _spell_date(value):
    """A stored date as "May 2027", which is how these lists are written."""
    text = str(value or "").strip()
    if not text:
        return None
    year = _year(text)
    if not year:
        return None
    month = re.match(r"\s*(\d{1,2})\s*[/-]", text)
    if month:
        number = int(month.group(1))
    else:
        named = re.search(r"[A-Za-z]{3,}", text)
        if not named:
            return str(year)
        wanted = named.group(0).lower()[:3]
        number = next((i + 1 for i, name in enumerate(_MONTHS)
                       if name.lower().startswith(wanted)), 0)
    if not 1 <= number <= 12:
        return str(year)
    return "%s %d" % (_MONTHS[number - 1], year)


def _is_no(value):
    return str(value or "").strip().lower() in ("no", "n", "false")


def _is_yes(value):
    return str(value or "").strip().lower() in ("yes", "y", "true")


def asks_when_a_degree_ends(label):
    """Is this asking for the date a degree finishes, rather than its name?

    "Graduate with your bachelor's degree" maps to the degree field, which
    would answer "Bachelors" -- the name of the degree, to a question asking
    when it ends.
    """
    question = formfill.normalise(label).strip().rstrip("?").lower()
    return bool(_GRADUATION.search(question) and _WHEN.search(question)
                and not formfill.expects_yes_no(question))


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

    # When a degree is expected, taken from the entry for that degree. Only
    # where a date is actually being asked for: "graduat" also sits inside
    # "undergraduate", so "have you completed your undergraduate degree?" --
    # a yes or no -- was being answered with a month.
    if asks_when_a_degree_ends(question):
        if _UNDERGRAD_ASKED.search(question):
            source, which = (profile.get("education_2_end")
                             or profile.get("undergrad_graduation"),
                             "your bachelor's")
        elif _GRADUATE_ASKED.search(question):
            source, which = (profile.get("education_1_end")
                             or profile.get("graduation"), "your master's")
        else:
            source, which = (profile.get("graduation")
                             or profile.get("education_1_end"), "your degree")
        spelled = _spell_date(source)
        if spelled:
            return spelled, "the end date you gave for %s (%s)" % (which, source)
        return None, None

    # The highest degree actually finished, by the calendar rather than by a
    # model's reading of it. A local model repeatedly called a degree ending
    # next year completed, and this is arithmetic, not judgement.
    if _HIGHEST_COMPLETED.search(question):
        finished = []
        for entry, name in ((2, "bachelor"), (1, "master")):
            end = profile.get("education_%d_end" % entry)
            year, month = _year(end), None
            match = re.match(r"\s*(\d{1,2})\s*[/-]", str(end or ""))
            if match:
                month = int(match.group(1))
            if not year:
                continue
            if year < today.year or (year == today.year and month
                                     and month <= today.month):
                finished.append(name)
        if "master" in finished:
            return "Master", "your master's ended %s, which is past" % (
                profile.get("education_1_end"))
        if "bachelor" in finished:
            return "Bachelor", "your bachelor's ended %s, which is past" % (
                profile.get("education_2_end"))
        if profile.get("education_2_start") or profile.get("education_1_start"):
            return "High School", ("no degree of yours has finished yet, so "
                                   "high school is the highest completed")
        return None, None

    # Willing to work where the job is. Asked many ways, and a phrasing that
    # names a city -- "able to work in-person at our Saint Paul office" -- is
    # the same question, not a new one.
    if _RELOCATE.search(question) and not _AUTHORISATION.search(question):
        return "Yes", "you are willing to work where the role is"

    # A relative working at the employer. Asked of subsidiaries, competitors
    # and suppliers too, which is the same question.
    if _RELATIVE.search(question) and not _RELATIVE_NAME.search(question):
        return "No", "your default answer about relatives at an employer"

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
