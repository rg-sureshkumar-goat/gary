"""Which recruiting cycle a posting is for.

Internship titles almost always name a season and year -- "Summer 2027",
"2027 Summer Analyst", "Fall 2026 Co-op". That is useful twice over:

  * it is strong evidence the posting is an internship even when the word
    "intern" never appears, as in "2027 Summer Analyst Program"
  * it says which cycle the role belongs to, so a 2027 graduate can ignore
    postings aimed at 2026

Years are read conservatively: a bare four-digit number is only treated as a
cycle year when it sits next to a season word or an internship word, because
titles are full of unrelated numbers (job codes, "Analyst II", "Q1 2027").
"""
import datetime
import re

SEASONS = {
    "summer": "Summer", "fall": "Fall", "autumn": "Fall",
    "winter": "Winter", "spring": "Spring",
}

_SEASON_WORD = r"(summer|fall|autumn|winter|spring)"
_YEAR = r"(20\d{2})"
_SHORT_YEAR = r"'(\d{2})"

# "Summer 2027", "Summer '27", "Summer of 2027"
_SEASON_THEN_YEAR = re.compile(
    _SEASON_WORD + r"\s*(?:of\s+)?(?:" + _YEAR + r"|" + _SHORT_YEAR + r")", re.I)
# "2027 Summer Analyst"
_YEAR_THEN_SEASON = re.compile(_YEAR + r"\s+" + _SEASON_WORD, re.I)
# "Summer Analyst 2027" -- season, a few words, then the year
_SEASON_GAP_YEAR = re.compile(
    _SEASON_WORD + r"(?:\W+\w+){0,3}\W+" + _YEAR, re.I)
# A year next to internship wording, with no season named.
_YEAR_NEAR_INTERN = re.compile(
    r"(?:" + _YEAR + r"\W{0,3}(?:intern|internship|co-?op|analyst|associate|"
    r"placement|program|programme)|(?:intern|internship|co-?op|placement|"
    r"program|programme)\W{0,3}" + _YEAR + r")", re.I)
# "Class of 2028" describes graduation, not the work cycle.
_CLASS_OF = re.compile(r"class\s+of\s+" + _YEAR, re.I)


_STANDALONE_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_SHORT_YEAR_TOKEN = re.compile(r"'(\d{2})(?!\d)")
_INTERN_WORD = re.compile(
    r"\b(intern|interns|internship|internships|co-?op|placement|analyst|"
    r"associate|program|programme|scholar|trainee)\b", re.I)


def parse_season(title, today=None):
    """Return {"season": str|None, "year": int|None} or None if nothing found.

    Rather than matching season and year in a fixed order, each is found
    independently and then combined. Job titles put them anywhere -- "2027
    Global Banking Program - Summer Analyst" separates them by five words --
    and positional patterns miss those.
    """
    text = " ".join(str(title or "").split())
    if not text:
        return None
    today = today or datetime.date.today()
    horizon = today.year + 6

    def plausible(year):
        return today.year - 1 <= year <= horizon

    # A "Class of 2028" year describes graduation, not the work cycle, so it is
    # only used when the title offers nothing better.
    class_years = {int(m.group(1)) for m in _CLASS_OF.finditer(text)}
    years = [int(m.group(1)) for m in _STANDALONE_YEAR.finditer(text)
             if plausible(int(m.group(1)))]
    years += [2000 + int(m.group(1)) for m in _SHORT_YEAR_TOKEN.finditer(text)
              if plausible(2000 + int(m.group(1)))]

    preferred = [y for y in years if y not in class_years] or years
    year = preferred[0] if preferred else None

    season_match = re.search(_SEASON_WORD, text, re.I)
    season = SEASONS[season_match.group(1).lower()] if season_match else None

    if season and year:
        return {"season": season, "year": year}
    if season:
        return {"season": season, "year": None}
    if year and _INTERN_WORD.search(text):
        # A bare year only means a cycle when the title is about early careers;
        # otherwise it is a job code or a fiscal quarter.
        return {"season": None, "year": year}
    return None


def label(parsed):
    """'Summer 2027', '2027', 'Summer', or '' -- for display."""
    if not parsed:
        return ""
    season, year = parsed.get("season"), parsed.get("year")
    if season and year:
        return "%s %d" % (season, year)
    if year:
        return str(year)
    return season or ""


def wanted(parsed, years):
    """Does this posting belong to a cycle the user cares about?

    Postings with no discernible year always pass -- plenty of real listings
    simply don't say, and dropping those would lose good roles.
    """
    if not years:
        return True
    if not parsed or not parsed.get("year"):
        return True
    return parsed["year"] in years
