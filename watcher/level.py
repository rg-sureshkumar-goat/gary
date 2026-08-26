"""Which degree level a posting is aimed at.

An MS Finance student sits in an awkward gap: it is a graduate degree, but it
is not an MBA. So two kinds of posting need filtering out --

  * MBA-only programmes ("MBA Finance Leadership Development Program")
  * undergraduate-only ones ("Finance Development Program (Undergraduate)")

-- while a posting that names no level at all must still come through. Most
listings say nothing about degree level, and dropping those would throw away
the majority of genuinely open roles.

So the rule is: if a title names one or more levels and none of them is yours,
drop it. Otherwise keep it.
"""
import re

LEVELS = ("undergraduate", "masters", "mba", "phd")

_PATTERNS = {
    "mba": [
        r"\bmba\b", r"\bm\.b\.a\.?\b", r"\bmba['’]?s\b",
    ],
    "masters": [
        r"\bmasters?\b", r"\bmaster['’]s\b", r"\bm\.s\.?\b", r"\bmsc\b",
        r"\bms\s+(?:in\s+)?(?:finance|accounting|economics|business|analytics)\b",
        r"\bmfin\b", r"\bm\.?fin\b",
        # "Students" plural matters: "Undergraduate and Graduate Students"
        # otherwise reads as undergraduate-only and gets dropped.
        r"\bgraduate\s+students?\b",
        r"\bgraduate[- ]level\b", r"\badvanced\s+degree\b",
        r"\bpost[- ]?graduate\b",
        # A bare "MS" only counts next to a word that makes it a degree --
        # otherwise it catches Microsoft, Morgan Stanley and "MS Office".
        r"\bms\b(?=\s+(?:candidates?|students?|grads?|graduates?|program|"
        r"programme|degree|level|hires?))",
        r"\b(?:ms|mba)\s*/\s*(?:ms|mba)\b",
    ],
    "undergraduate": [
        r"\bundergraduate?s?\b", r"\bundergrad\b", r"\bbachelors?\b",
        r"\bbachelor['’]s\b", r"\bb\.?s\.?/b\.?a\.?\b", r"\bb\.?a\.?/b\.?s\.?\b",
        r"\brising\s+(?:senior|junior|sophomore)\b", r"\bsophomore\b",
        r"\bfreshman\b", r"\bfirst[- ]year\s+student\b",
    ],
    "phd": [
        r"\bph\.?d\.?\b", r"\bdoctoral\b", r"\bdoctorate\b",
    ],
}

_COMPILED = {level: [re.compile(p, re.I) for p in pats]
             for level, pats in _PATTERNS.items()}


def levels_named(text):
    """Every degree level a title explicitly mentions."""
    found = set()
    haystack = " ".join(str(text or "").split())
    if not haystack:
        return found
    for level, patterns in _COMPILED.items():
        for pattern in patterns:
            if pattern.search(haystack):
                found.add(level)
                break
    return found


def suits(text, my_level):
    """Is this posting open to someone at `my_level`?

    A posting that names no level suits everyone -- that is the common case,
    and treating silence as exclusion would discard most real listings.
    """
    if not my_level or my_level == "any":
        return True
    named = levels_named(text)
    if not named:
        return True
    return my_level in named


def explain(text, my_level):
    """Why a posting was dropped, for --dry-run output."""
    named = sorted(levels_named(text))
    if not named:
        return ""
    return "aimed at %s, not %s" % ("/".join(named), my_level)
