"""Decides whether a posting is a corporate-finance or consulting internship.

Matching is phrase-based with word boundaries, so "intern" never fires on
"internal" or "international" -- a mistake that otherwise floods the feed.
"""
import re

from . import geo

_CACHE = {}


def _pattern(phrases):
    """One compiled alternation for a list of phrases, whitespace-tolerant."""
    key = tuple(phrases)
    if key not in _CACHE:
        parts = []
        for phrase in phrases:
            escaped = r"\s+".join(re.escape(w) for w in phrase.split())
            # \b works on the outer edges; phrases are plain words here.
            parts.append(r"\b%s\b" % escaped)
        _CACHE[key] = re.compile("|".join(parts), re.IGNORECASE) if parts else None
    return _CACHE[key]


def _hits(text, phrases):
    pat = _pattern(phrases)
    if pat is None:
        return []
    seen, out = set(), []
    for m in pat.finditer(text):
        norm = " ".join(m.group(0).lower().split())
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def classify(job, rules):
    """Return (matched: bool, reason: dict). Reason explains the decision."""
    title = job.get("title") or ""
    location = job.get("location") or ""
    haystack = title
    if rules.get("search_location_too"):
        haystack = "%s %s" % (title, location)

    # 1. Must read as an internship / summer programme.
    level = _hits(haystack, rules.get("internship_terms", []))
    if not level:
        return False, {"why": "not an internship"}

    # 2. Must belong to a role family we care about.
    groups = []
    matched_terms = []
    for group, phrases in (rules.get("role_groups") or {}).items():
        hits = _hits(haystack, phrases)
        if hits:
            groups.append(group)
            matched_terms.extend(hits)
    if not groups:
        return False, {"why": "no target role family"}

    # 3. Drop known-irrelevant functions (engineering, marketing, clinical...).
    blocked = _hits(haystack, rules.get("exclude_terms", []))
    if blocked:
        return False, {"why": "excluded: %s" % ", ".join(blocked)}

    # 4. United States only, when asked for.
    if rules.get("us_only"):
        if not geo.passes(location, title, True,
                          keep_unknown=rules.get("keep_unknown_locations", True)):
            return False, {"why": "not a US location (%s)" % (location or "unstated")}

    # 5. Optional explicit location allow-list, on top of the US gate.
    allowed = rules.get("locations_allow") or []
    if allowed and location:
        if not _hits(location, allowed):
            return False, {"why": "location %r not in allow-list" % location}

    return True, {
        "groups": sorted(groups),
        "level": level[0],
        "terms": matched_terms[:4],
    }


def filter_jobs(jobs, rules):
    kept = []
    for job in jobs:
        ok, reason = classify(job, rules)
        if ok:
            job = dict(job)
            job["match"] = reason
            kept.append(job)
    return kept
