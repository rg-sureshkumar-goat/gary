"""Answering "where do you want to work?" on an application.

The rule, in order:

  1. If several locations can be chosen, choose every one the role is open in.
  2. If the question asks for a fallback office, take an option that keeps
     every office open. Naming the first choice again is not an answer.
  3. If only one can be chosen, take the office the role is posted in, and
     failing that the company's US headquarters -- but only when the role is
     actually open there.
  4. Otherwise leave it blank. A guess here can route an application to an
     office the role was never open in.

Matching is on city, because a dropdown says "Chicago, IL" where a posting says
"Chicago - 550 Van Buren", and neither is a substring of the other.
"""
import re

LOCATION_QUESTION = re.compile(
    r"which\s+(?:office|location|city)|office\s+(?:are|you|preference|location)|"
    r"location\s+preference|preferred\s+(?:office|location|city|work\s+location)|"
    r"where\s+would\s+you\s+(?:like|prefer)|interested\s+in\s+joining|"
    r"select\s+(?:your\s+)?(?:office|location)|work\s+location", re.I)

_STATE_ABBR = re.compile(r"\b([A-Z]{2})\b")
_NOISE = re.compile(r"\b(usa|united states|us|remote|hybrid|onsite|office|"
                    r"metro|area|greater|downtown)\b", re.I)


def is_location_question(label):
    return bool(LOCATION_QUESTION.search(" ".join(str(label or "").split())))


def city_of(text):
    """The city part of a location string, normalised for comparison.

    "Chicago - 550 Van Buren", "Chicago, IL" and "CHICAGO" all reduce to
    "chicago"; a street address or building name is dropped.
    """
    text = str(text or "")
    text = re.split(r"[-–—(]", text)[0]
    text = text.split(",")[0]
    text = _NOISE.sub(" ", text)
    text = re.sub(r"[^a-zA-Z ]", " ", text)
    words = text.split()
    # A trailing state abbreviation is not part of the city name:
    # "Los Angeles CA USA" and "Los Angeles, CA" must compare equal.
    from .geo import STATE_CODES
    while words and words[-1].upper() in STATE_CODES:
        words.pop()
    return " ".join(w.lower() for w in words)


def split_locations(text):
    """Break a posting's location field into separate places."""
    if not text:
        return []
    parts = re.split(r";|\band\b|\||/|•", str(text))
    out = []
    for part in parts:
        for piece in re.split(r",(?=\s*[A-Z][a-z])", part):
            city = city_of(piece)
            if city and city not in out:
                out.append(city)
    return out


def options_for(options, open_locations):
    """Every dropdown option matching a location the role is open in."""
    wanted = set()
    for place in open_locations or []:
        city = city_of(place)
        if city:
            wanted.add(city)
    if not wanted:
        return []
    picked = []
    for option in options or []:
        if city_of(option) in wanted:
            picked.append(option)
    return picked


def pick_single(options, open_locations, headquarters):
    """The one option to choose when only one is allowed.

    The office the role is posted in comes first. Keying on the headquarters
    alone left the question blank at most employers, because a posted role is
    usually not at headquarters -- Berkeley Research Group offered Boston,
    Chicago, Los Angeles and New York for a Boston role while being
    headquartered in Emeryville, so nothing matched.

    The headquarters is still used when the role is genuinely open there --
    otherwise the application would name an office it was never posted for.
    """
    for posted in (open_locations or []):
        city = city_of(posted)
        if not city:
            continue
        for option in options or []:
            if city_of(option) == city:
                return option
    if not headquarters:
        return None
    hq = city_of(headquarters)
    if not hq:
        return None
    open_cities = {city_of(p) for p in (open_locations or []) if city_of(p)}
    if open_cities and hq not in open_cities:
        return None
    for option in options or []:
        if city_of(option) == hq:
            return option
    return None


def headquarters_for(company, table):
    """The US headquarters city for an employer, matched loosely by name."""
    if not company or not table:
        return None
    def squash(text):
        return re.sub(r"[^a-z0-9]", "", str(text or "").lower())
    target = squash(company)
    if not target:
        return None
    best, best_len = None, 0
    for name, city in table.items():
        if str(name).startswith("_"):
            continue
        key = squash(name)
        if not key:
            continue
        if key in target or target in key:
            # Prefer the longest match, so "Bank of America" beats "Bain".
            if len(key) > best_len:
                best, best_len = city, len(key)
    return best


# A question asking where else you would go, having already asked where you
# want to go.
_SECOND_CHOICE = re.compile(r"secondary|second\s+choice|alternat|"
                            r"next\s+preference|other\s+office", re.I)

# An option that keeps every office open rather than naming one.
_ANY_OFFICE = re.compile(r"any\s+location|any\s+office|any\s+of\s+the|"
                         r"no\s+preference|open\s+to\s+any|flexible", re.I)


def second_choice(options):
    """What to answer when asked for a fallback office.

    Naming the office the role is posted in again is not an answer -- it is
    the first choice repeated. An option that keeps everywhere open says the
    true thing; failing that the question is left alone.
    """
    for option in options or []:
        if _ANY_OFFICE.search(str(option)):
            return option
    return None


def answer(options, open_locations, company, table, multiple=False,
           question=""):
    """What to select for a location question.

    Returns a list: every open location when several may be chosen, a single
    headquarters when only one may be, and an empty list when neither applies
    -- which leaves the question for you.
    """
    if multiple:
        return options_for(options, open_locations)
    if _SECOND_CHOICE.search(str(question or "")):
        alternative = second_choice(options)
        return [alternative] if alternative else []
    single = pick_single(options, open_locations,
                         headquarters_for(company, table))
    return [single] if single else []
