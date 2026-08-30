"""Recognising what a dropdown is asking from the options it offers.

The words an employer puts above a control are unreliable: the same question
appears as "Ethnicity", as "What race or ethnicity do you most closely
identify with?", and as nothing at all beyond "Select One". The options,
though, say plainly what is being asked. A list holding Asian, White, Black or
African American and Two or More Races is asking about race, whatever sits
above it, and the only sensible answer is the race on file.

Recognising the list carries more weight than matching the wording, because
the wording is what misleads -- it is how an answer stored under one name came
to be offered to a different question that happened to share it.
"""

import re

# A kind of list, the vocabulary that identifies it, and the profile fields
# that answer it, in order of preference.
KINDS = (
    ("race", (
        r"south\s+asian", r"east\s+asian", r"southeast\s+asian",
        r"american\s+indian", r"alaska\s+native", r"\basian\b",
        r"black\s+or\s+african", r"african\s+american",
        r"native\s+hawaiian", r"pacific\s+islander", r"two\s+or\s+more\s+races",
        r"\bwhite\b", r"hispanic\s+or\s+latino",
     ), ("race_detail", "race", "ethnicity")),
    ("gender", (
        r"^male$", r"^female$", r"non[\s-]?binary", r"gender\s+diverse",
     ), ("gender",)),
    ("veteran", (
        r"protected\s+veteran", r"not\s+a\s+veteran", r"^veteran$",
        r"armed\s+forces\s+service\s+medal", r"disabled\s+veteran",
     ), ("veteran",)),
    ("disability", (
        r"have\s+a\s+disability", r"do\s+not\s+have\s+a\s+disability",
        r"had\s+one\s+in\s+the\s+past",
     ), ("disability",)),
)

# Present on nearly every list and identifying nothing.
_FILLER = re.compile(r"^(select\s+one|select|choose|--|none|n/?a|"
                     r"i\s+(do\s+not|don'?t)\s+(wish|want)\s+to\s+answer|"
                     r"prefer\s+not\s+to\s+(say|answer)|decline\s+to\s+(self.)?"
                     r"identify)\.?$", re.I)


def _bare(option):
    """An option without its trailing country qualifier."""
    text = " ".join(str(option or "").split())
    return re.sub(r"\s*\([^)]*\)\s*$", "", text).strip().rstrip(".")


def kind_of(options):
    """Which kind of list this is, or None.

    Two matching options are required. One is a coincidence -- "White" appears
    on plenty of lists that are not about race.
    """
    bare = [_bare(o) for o in options or []]
    bare = [b for b in bare if b and not _FILLER.match(b)]
    if len(bare) < 2:
        return None
    best, best_hits = None, 0
    for name, vocabulary, _fields in KINDS:
        hits = sum(1 for b in bare
                   if any(re.search(word, b, re.I) for word in vocabulary))
        if hits >= 2 and hits > best_hits:
            best, best_hits = name, hits
    return best


# A list of titles. The candidate wants none, and a gender on file would
# otherwise pick one for him.
_TITLES = re.compile(r"^(?:mr|mrs|ms|miss|mx|dr|prof|sir|madam)\.?$", re.I)


def is_a_title_list(options):
    """Is this list offering Mr., Ms., Dr. and the like?"""
    seen = sum(1 for o in options or [] if _TITLES.match(_bare(o)))
    return seen >= 2


def answer(options, profile):
    """The fact that answers this list: (value, why) or (None, None)."""
    if is_a_title_list(options):
        return None, None
    kind = kind_of(options)
    if not kind:
        return None, None
    fields = next(f for name, _v, f in KINDS if name == kind)
    from . import options as option_reading

    known = [profile.get(f) for f in fields]
    picked, _fact = option_reading.best(options, [k for k in known if k])
    if picked is not None:
        field = next(f for f in fields if profile.get(f))
        return picked, ("a list of %s options, answered from your %s"
                        % (kind, field))

    # Stated one way, offered another: "I am not a Protected Veteran" against
    # "I am not a veteran". Fall back to the matcher the rest of the form uses.
    from . import formfill
    lowered = {str(o).strip().lower(): o for o in options if str(o).strip()}
    for field in fields:
        value = profile.get(field)
        if value in (None, ""):
            continue
        found = formfill._match_option(str(value), dict(lowered))
        # The looser matcher will settle for a narrower category -- it read
        # "Asian" onto "East Asian" -- so what it finds still has to be
        # something the option actually asserts.
        if found is not None and option_reading.asserts(found, value):
            return found, ("a list of %s options, answered from your %s"
                           % (kind, field))
    return None, None


# How the candidate heard about the role. Employers word their own site many
# ways -- "Company Website", "Corporate Site", "Tencent Careers Page" -- and
# what they have in common is the employer's name or a word meaning "us",
# beside a word meaning a website.
_OURS = r"(?:compan(?:y|ies)|corporate|organi[sz]ation|employer|our|internal)"
# A word meaning a website. "Careers" is not one of them on its own -- a
# career fair is not a website -- but careers beside one of these is.
_A_SITE = r"(?:web\s*site|website|\bsite\b|\bpage\b|portal)"
_CAREERS = r"careers?"
_SOCIAL = re.compile(r"linked\s*in|social\s+media", re.I)


def heard_about_us(options, company="", prefer_social=False):
    """The option meaning the employer's own site, or their social media.

    Gary knows which employer this is, so an option naming them beside a word
    for a website is their site -- however this particular form phrases it.
    That is a rule about employers in general rather than a list of the ways
    one employer writes its name.
    """
    # An employer writes its own name short: "Sila Website" for Sila
    # Nanotechnologies. The distinctive first word identifies it as well as
    # the whole name does, and better than the whole name matches.
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(company or "")) if w]
    parts = []
    if words:
        parts.append(re.escape(" ".join(words)))
        lead = words[0]
        if len(lead) >= 4 and lead.lower() not in (
                "the", "group", "company", "corp", "inc", "global", "united"):
            parts.append(re.escape(lead))
    named = "|".join(parts)
    ours = []
    social = []
    for option in options or []:
        text = _bare(option)
        if _FILLER.match(text):
            continue
        if _SOCIAL.search(text):
            social.append(option)
        site = re.search(_A_SITE, text, re.I)
        careers = re.search(_CAREERS, text, re.I)
        if not site and not (careers and re.search(_OURS, text, re.I)):
            continue
        if named and re.search(named, text, re.I):
            ours.insert(0, option)          # names this employer: strongest
        elif site and (careers or re.search(_OURS, text, re.I)):
            ours.append(option)
    if not prefer_social and ours:
        return ours[0]
    if social:
        return social[0]
    return ours[0] if ours else None
