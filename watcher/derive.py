"""Turn recorded answers into general facts about you.

Recording verbatim keeps every answer exactly as typed, which is what stops two
degrees being confused. But it only matches a question worded the same way, and
employers word things differently: Houlihan asks "will you now or in the future
require Houlihan Lokey to file a petition", Lincoln asks "will you now or in
the future require sponsorship". Same question, no match.

So the recorded answers are read once and distilled into canonical fields --
gpa, undergrad_gpa, sponsorship, graduation -- which the matcher can apply to
any wording. The verbatim answers stay authoritative; these are the fallback.

Which education entry is which matters and cannot be assumed from its number:
the form may list the master's first or the bachelor's first. It is decided by
what the degree actually says.
"""
import re

GRADUATE = re.compile(r"\bmaster|\bm\.?s\.?\b|\bmsc\b|\bmba\b|\bm\.?fin\b|"
                      r"\bph\.?d\b|\bdoctor|\bgraduate\b", re.I)
UNDERGRAD = re.compile(r"\bbachelor|\bb\.?s\.?\b|\bb\.?a\.?\b|\bundergrad", re.I)

# Which canonical field a repeated-entry question feeds.
ENTRY_FIELDS = [
    ("degree", re.compile(r"\bdegree\b", re.I)),
    ("gpa", re.compile(r"\bgpa\b|grade\s*(?:point|average)|overall\s+result", re.I)),
    ("university", re.compile(r"school|universit|college|institution", re.I)),
    ("major", re.compile(r"\bmajor\b|field\s+of\s+study", re.I)),
    ("graduation", re.compile(r"graduat|completion|\bto\b.*\byear\b", re.I)),
]


def _entry_index(key):
    m = re.match(r"education (\d+) ::", key)
    return int(m.group(1)) if m else None


def _field_of(key):
    tail = key.split("::", 1)[1] if "::" in key else key
    for name, pattern in ENTRY_FIELDS:
        if pattern.search(tail):
            return name
    return None


def education_entries(answers):
    """{entry number: {field: value}} for the education blocks."""
    entries = {}
    for key, value in (answers or {}).items():
        index = _entry_index(key)
        if index is None:
            continue
        field = _field_of(key)
        if field:
            entries.setdefault(index, {})[field] = value
    return entries


def classify_entries(entries):
    """Which education entry is the graduate one, and which the undergraduate.

    Decided by what the degree says, not by the order the form listed them in.
    """
    graduate = undergrad = None
    for index in sorted(entries):
        degree = str(entries[index].get("degree") or "")
        if GRADUATE.search(degree) and graduate is None:
            graduate = index
        elif UNDERGRAD.search(degree) and undergrad is None:
            undergrad = index
    # Only one, and it says nothing: treat it as the current degree.
    if graduate is None and undergrad is None and entries:
        graduate = sorted(entries)[0]
    return graduate, undergrad


def derive(profile):
    """Fill canonical fields from recorded answers. Returns what changed."""
    answers = dict(profile.get("custom_answers") or {})
    answers.update(profile.get("answers") or {})
    changed = []

    def put(key, value):
        if value in (None, "") or profile.get(key) not in (None, ""):
            return
        profile[key] = value
        changed.append((key, value))

    entries = education_entries(answers)
    graduate, undergrad = classify_entries(entries)
    if graduate is not None:
        for field, value in entries[graduate].items():
            put(field, value)
    if undergrad is not None:
        for field, value in entries[undergrad].items():
            put("undergrad_" + field, value)

    # Questions that map to a canonical field whatever their wording.
    from . import formfill
    for question, value in answers.items():
        if "::" in question and not question.startswith(("education", "work history")):
            continue
        if question.startswith(("education", "work history")):
            continue
        key = formfill.key_for(question)
        if key and key not in ("degree", "gpa", "university", "major", "graduation"):
            put(key, value)

    return changed
