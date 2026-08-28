"""Working out a desired salary from what the posting advertises.

Asked for a salary expectation, the sensible answer is the pay the employer
has already advertised, annualised. An hourly rate is multiplied by the hours
of a full-time or part-time week and by fifty-two; an annual figure is taken
as it stands.

Postings write this many ways -- "$22.00/hr", "22 - 24 per hour", "Annual or
Hourly Compensation Range: 22 - 24" -- and some omit the dollar sign entirely,
so a bare pair of small numbers beside the word hourly is still a rate.
"""

import re

FULL_TIME_HOURS = 40
PART_TIME_HOURS = 20
WEEKS = 52

# Above this a figure is a yearly salary, not an hourly rate. No internship
# pays $500 an hour and none pays $40 a year.
HOURLY_CEILING = 200

_MONEY = r"\$?\s*([\d,]+(?:\.\d{1,2})?)"
_RANGE = re.compile(_MONEY + r"\s*(?:-|–|—|to)\s*" + _MONEY, re.I)
_SINGLE = re.compile(_MONEY)

_HOURLY_WORD = re.compile(r"hourly|per\s+hour|/\s*hr\b|an\s+hour|hour\b", re.I)
_ANNUAL_WORD = re.compile(r"annual|per\s+year|/\s*yr\b|a\s+year|salary\s+range",
                          re.I)
_PART_TIME = re.compile(r"part[\s-]*time", re.I)
# Sentences are not split on the full stop: "$18.50" contains one, and
# excluding it cut the amount away from the words that identify it.
_CONTEXT = re.compile(
    r"[^\n]{0,120}(?:compensation|pay\s+range|salary|hourly|per\s+hour|"
    r"rate)[^\n]{0,160}", re.I)

# A company's turnover is not a wage.
_NOT_PAY = re.compile(r"\b(?:billion|million|revenue|sales|market\s+cap)\b",
                      re.I)


def _number(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def advertised(text):
    """The pay a posting advertises: (amount, "hour"|"year", phrase) or None.

    Where a range is given the upper figure is taken. The question asks what
    the candidate wants, and the top of a band the employer has published is
    a defensible thing to want.
    """
    for match in _CONTEXT.finditer(text or ""):
        phrase = " ".join(match.group(0).split())
        if _NOT_PAY.search(phrase):
            continue
        hourly = bool(_HOURLY_WORD.search(phrase))
        annual = bool(_ANNUAL_WORD.search(phrase))
        if not (hourly or annual):
            continue

        found = _RANGE.search(phrase)
        if found:
            amounts = [_number(found.group(1)), _number(found.group(2))]
        else:
            single = _SINGLE.search(phrase)
            amounts = [_number(single.group(1))] if single else []
        amounts = [a for a in amounts if a]
        if not amounts:
            continue
        top = max(amounts)

        # "Annual or Hourly Compensation Range: 22 - 24" says both words. The
        # size of the number settles which it is.
        if top <= HOURLY_CEILING:
            return top, "hour", phrase
        if annual:
            return top, "year", phrase
    return None


def desired(text, part_time=False):
    """The salary to ask for: ("$49,920", why) or (None, why-not)."""
    found = advertised(text)
    if not found:
        return None, "the posting advertises no pay"
    amount, per, phrase = found
    if per == "year":
        return "$%s" % format(int(round(amount)), ","), (
            "the posting's advertised salary (%s)" % phrase[:80])
    hours = PART_TIME_HOURS if part_time or _PART_TIME.search(text or "") \
        else FULL_TIME_HOURS
    annual = amount * hours * WEEKS
    return "$%s" % format(int(round(annual)), ","), (
        "%g/hour x %d hours x %d weeks, from \"%s\""
        % (amount, hours, WEEKS, phrase[:70]))
