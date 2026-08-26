"""How long a posting has been open, and which long-open ones to recommend.

A role that has sat on a board for months is usually still taking applications,
and Gary would otherwise never mention it -- new postings are all it reports.

Two sources of evidence, and they are not equally good:

  * the board's own posted date. Greenhouse, Oracle and RSS feeds give an exact
    day. Workday gives relative text, and it stops counting at "30+ Days Ago" --
    a floor of 30, which cannot prove 60.
  * when Gary first saw the posting. Exact, but only as old as Gary's history.

So a posting qualifies on whichever evidence is strong enough. "30+ Days Ago"
on its own never qualifies for a 60-day threshold; it has to be corroborated by
Gary having watched the posting for that long.
"""
import datetime
import re

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DAYS_AGO = re.compile(r"^(\d+)\s*(\+)?\s*days?\s+ago", re.I)
_MONTHS_AGO = re.compile(r"^(\d+)\s*(\+)?\s*months?\s+ago", re.I)
_MONTH_DAY = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})", re.I)


def parse_posted(value, today=None):
    """(days_ago, exact) from a board's posted date, or None if unreadable.

    `exact` is False when the board only gives a lower bound, e.g. Workday's
    "30+ Days Ago" -- which means at least 30 days, not exactly 30.
    """
    if not value:
        return None
    today = today or datetime.date.today()
    text = " ".join(str(value).split())
    low = text.lower()

    m = _ISO.match(text)
    if m:
        try:
            when = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        return max((today - when).days, 0), True

    if low.startswith("today") or low.startswith("just posted"):
        return 0, True
    if low.startswith("yesterday"):
        return 1, True

    m = _DAYS_AGO.match(low)
    if m:
        return int(m.group(1)), not m.group(2)

    m = _MONTHS_AGO.match(low)
    if m:
        return int(m.group(1)) * 30, not m.group(2)

    # "August 12," -- a month and day with no year.
    m = _MONTH_DAY.match(text)
    if m and m.group(1).lower() in MONTHS:
        month, day = MONTHS[m.group(1).lower()], int(m.group(2))
        for year in (today.year, today.year - 1):
            try:
                when = datetime.date(year, month, day)
            except ValueError:
                continue
            if when <= today:
                return (today - when).days, True
    return None


def _days_since(iso, today):
    m = _ISO.match(str(iso or ""))
    if not m:
        return None
    try:
        when = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return max((today - when).days, 0)


def age_of(job, first_seen_iso, today=None):
    """(days_open, exact) using the strongest evidence available."""
    today = today or datetime.date.today()
    best, exact = None, False

    posted = parse_posted(job.get("posted_at"), today)
    if posted:
        best, exact = posted

    watched = _days_since(first_seen_iso, today)
    if watched is not None:
        # Gary's own history is exact, so prefer it whenever it is the
        # stronger claim -- it can turn a "30+" floor into a real number.
        if best is None or watched > best or (not exact and watched >= best):
            best, exact = watched, True

    if best is None:
        return None, False
    return best, exact


def select_aged(matches, seen, min_days=60, recommended=None, today=None,
                repeat_after_days=45):
    """Long-open postings worth recommending.

    Only postings whose age can actually be established are returned: a floor
    like "30+ days" is not treated as proof of 60. Anything recommended
    recently is held back so the digest doesn't repeat itself every week.
    """
    today = today or datetime.date.today()
    recommended = recommended or {}
    out = []

    for job in matches:
        record = seen.get(job["id"])
        first = record.get("f") if isinstance(record, dict) else record
        days, exact = age_of(job, first, today)
        if days is None or days < min_days:
            continue
        if not exact:
            # A lower bound below the threshold proves nothing.
            continue
        last = _days_since(recommended.get(job["id"]), today)
        if last is not None and last < repeat_after_days:
            continue
        enriched = dict(job)
        enriched["days_open"] = days
        out.append(enriched)

    out.sort(key=lambda j: -j["days_open"])
    return out
