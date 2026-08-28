"""Matching your saved answers to the fields on an application form.

Application forms ask the same things in slightly different words: "First
Name", "Given name", "Legal first name". This maps a form label onto a key in
your profile, and picks the closest option from a dropdown.

Two rules this module enforces, both deliberate:

  * anything that looks like a credential is never filled, whatever the label
    says. Passwords and account creation stay with you.
  * a field is left blank rather than guessed at. A wrong graduation year or
    GPA on a submitted application is worse than an empty box you notice and
    fill in yourself.
"""
import re

# Never touched, regardless of what the profile contains.
CREDENTIAL = re.compile(
    r"pass\s*word|passcode|\bpin\b|security\s+question|verification\s+code|"
    r"one[- ]time|\botp\b|secret|credit\s+card|card\s+number|cvv|"
    r"social\s+security|\bssn\b|bank\s+account|routing", re.I)

# label patterns -> profile key. First match wins, so order matters:
# "preferred first name" must be tried before "first name".
FIELD_PATTERNS = [
    ("preferred_first_name", r"preferred\s+(?:first\s+)?name|go(?:es)?\s+by|nickname"),
    ("first_name",  r"\bfirst\s*name\b|\bgiven\s*name\b|\bforename\b"),
    ("last_name",   r"\blast\s*name\b|\bsurname\b|\bfamily\s*name\b"),
    ("full_name",   r"\bfull\s*name\b|^name$|legal\s+name"),
    ("email",       r"\be-?mail\b"),
    ("phone_type",  r"phone\s+device\s+type|\bdevice\s+type\b|phone\s+type|"
                    r"type\s+of\s+phone"),
    # A dial-code picker, not a number field.
    ("phone_country_code",
                    r"country\s+phone\s+code|phone\s+country\s+code|"
                    r"\bcountry\s+code\b|dial(?:l?ing)?\s+code"),
    # An extension is its own thing and is usually blank.
    ("phone_extension",
                    r"\bextension\b|\bext\.?\b(?!\w)"),
    ("phone",       r"\bphone\b|\bmobile\b|\btelephone\b|\bcell\b"),
    ("linkedin",    r"linked\s*in"),
    ("github",      r"git\s*hub"),
    ("website",     r"portfolio|personal\s+(?:web)?site|\bwebsite\b"),
    ("address",     r"street\s+address|address\s+line\s*1|^address$"),
    ("city",        r"\bcity\b|\btown\b"),
    ("state",       r"\bstate\b|\bprovince\b|\bregion\b"),
    ("postal_code", r"zip|postal\s+code|post\s*code"),
    ("country",     r"\bcountry\b"),
    ("university",  r"\buniversity\b|\bcollege\b|\bschool\b|\binstitution\b"),
    # "In what year did you complete your undergraduate degree?" asks for a
    # year, not a degree name, so year-questions are matched before degrees.
    ("graduation",  r"\b(?:what|which)\s+year\b|\byear\s+did\s+you\b|"
                    r"\byear\s+of\s+(?:graduation|completion)\b"),
    ("degree",      r"\bdegree\b|qualification"),
    ("major",       r"\bmajor\b|field\s+of\s+study|discipline|concentration"),
    # GPA first: "undergraduate GPA" is a GPA question, not a date one.
    ("gpa",         r"\bgpa\b|grade\s+point"),
    # \b matters -- without it "graduat\w*" matches inside "undergraduate",
    # so "undergraduate GPA" and "undergraduate degree" both read as dates.
    ("graduation",  r"\bgraduat\w*\s*(?:date|year|month)?|expected\s+completion|"
                    r"anticipated\s+graduation"),
    ("work_authorization",
                    r"authoriz\w+\s+to\s+work|legally\s+authorized|"
                    r"work\s+authorization|eligible\s+to\s+work"),
    ("sponsorship", r"sponsor\w*|visa\s+status|require\s+sponsorship|"
                    r"now\s+or\s+in\s+the\s+future"),
    ("start_date",  r"available\s+start|start\s+date|earliest\s+start"),
    ("referral",    r"how\s+did\s+you\s+hear|referral\s+source|hear\s+about"),
    ("pronouns",    r"pronoun"),
    ("gender",      r"\bgender\b"),
    ("race",        r"\brace\b|ethnicity"),
    ("veteran",     r"veteran"),
    ("disability",  r"disabilit"),
]

_COMPILED = [(key, re.compile(pat, re.I)) for key, pat in FIELD_PATTERNS]


# Wording that marks a form as authentication rather than an application.
AUTH_SIGNALS = re.compile(
    r"sign\s*[- ]?in|sign\s*[- ]?up|log\s*[- ]?in|log\s*[- ]?on|"
    r"create\s+(?:an\s+)?account|forgot\s+(?:your\s+)?password|"
    r"remember\s+me|reset\s+(?:your\s+)?password|new\s+password|"
    r"verify\s+your\s+email|two[- ]factor|verification\s+code", re.I)


def is_auth_form(labels, has_password=False):
    """Is this a sign-in or account-creation form?

    The guarantee the user asked for is stronger than skipping fields labelled
    "password": a login form is left *entirely* alone, email box included. So
    the presence of any password field condemns the whole form, and the usual
    sign-in wording does too.
    """
    if has_password:
        return True
    joined = " | ".join(normalise(l) for l in labels if l)
    return bool(AUTH_SIGNALS.search(joined))


# Generated ids carry no meaning and change between sessions, so they make a
# useless and unstable key suffix.
_OPAQUE_ID = re.compile(r"^[0-9a-f]{12,}$|[0-9a-f]{16,}", re.I)

# Page furniture rather than form fields.
_NOT_A_FIELD = re.compile(
    r"utilitymenu|menubutton|navigation|breadcrumb|languageselector|"
    r"searchbox|search[-_]?field|cookie|skip[-_]?to", re.I)


def usable_identity(identity):
    """Whether a field id is meaningful enough to key on."""
    text = str(identity or "").strip()
    if not text or _OPAQUE_ID.search(text):
        return ""
    return text


def base_identity(identity):
    """A field id with its entry number removed.

    Workday numbers repeated fields inside the id itself --
    workExperience6RoleDescription, workExperience7RoleDescription. Those are
    the same question on two different jobs, so the digits have to come out
    before the two can be recognised as a repeat of each other.
    """
    return re.sub(r"\d+", "", usable_identity(identity))


# A control whose label is only its own option text tells us nothing: the
# question is elsewhere on the page.
_OPTION_ONLY = re.compile(r"^(yes|no|true|false|n/?a|none|other)$", re.I)


def is_option_label(label):
    return bool(_OPTION_ONLY.match(normalise(label).strip().rstrip(".")))


def is_page_furniture(label, identity=""):
    """Menus, language pickers and search boxes are not application questions."""
    return bool(_NOT_A_FIELD.search("%s %s" % (identity or "", label or "")))


def strip_value(label, value):
    """Remove a selected option that has been appended to its own question.

    Workday joins a dropdown's question and its current selection through
    aria-labelledby, so "Degree" reads as "Degree Bachelors" once answered --
    and the key then changes with the answer, which stops two entries from
    being recognised as the same question.
    """
    text = normalise(label)
    val = " ".join(str(value or "").split())
    if not val or len(val) > 60:
        return text
    if text.lower().endswith(" " + val.lower()):
        trimmed = text[: -len(val)].strip(" :-,")
        if trimmed:
            return trimmed
    if text.lower() == val.lower():
        return text
    return text


def normalise(label):
    text = re.sub(r"[\*∗]", " ", str(label or ""))
    # "(required)" and a bare trailing "Required" both appear; strip either, or
    # the same question is remembered twice under different keys.
    text = re.sub(r"\((?:required|optional)\)", " ", text, flags=re.I)
    text = re.sub(r"\b(?:required|optional)\s*$", " ", text, flags=re.I)
    return " ".join(text.split())


# Labels too generic to reuse across forms. Workday splits a date into three
# selects each labelled only "Month"/"Day"/"Year", and its work-history section
# has "Company" and "Location". Remembering an answer under those keys would
# put an employment year into a graduation-year field on the next form.
GENERIC_LABELS = {
    "day", "month", "year", "date", "from", "to", "start", "end",
    "company", "employer", "location", "city", "state", "country", "region",
    "language", "title", "job title", "role", "role description", "position",
    "name", "type", "level", "status", "other", "yes", "no", "select",
    "description", "details", "comments", "notes", "school", "degree",
    "major", "field of study", "gpa",
}


def is_reusable_question(label):
    """Is this label specific enough to remember an answer against?

    Only questions that identify themselves are stored. A bare "Year" says
    nothing about which year is being asked for, so an answer saved under it
    would be applied to unrelated fields on every later form.
    """
    text = normalise(label).lower().rstrip("?").strip()
    if not text or text in GENERIC_LABELS:
        return False
    # Option text captured instead of a question. "No, I do not require
    # sponsorship" is an answer; storing it as a question key is meaningless
    # however many words it runs to.
    if re.match(r"^(yes|no)\b", text):
        return False
    # A real question either asks something or is several words long.
    return "?" in normalise(label) or len(text.split()) >= 4


def key_for(label):
    """Which profile key a form label corresponds to, or None."""
    text = normalise(label)
    if not text or CREDENTIAL.search(text):
        return None
    for key, pattern in _COMPILED:
        if pattern.search(text):
            return key
    return None


def is_credential(label):
    return bool(CREDENTIAL.search(normalise(label)))


# Questions phrased as yes/no. Answering one with a date or a degree name is
# how "Have you completed your undergraduate degree?" became "Master of
# Science" -- a confidently wrong answer submitted under the user's name.
_YES_NO_QUESTION = re.compile(
    r"^\s*(will|have|has|are|is|do|does|did|can|would|should|were|was)\b"
    r".*\?\s*$", re.I | re.S)

_YES_NO_VALUES = {"yes", "no", "y", "n", "true", "false"}


def expects_yes_no(label):
    return bool(_YES_NO_QUESTION.match(normalise(label)))


# A master's student has two degrees, and forms ask about both. "Undergraduate
# GPA" must not be answered from the graduate GPA, so these labels look for an
# undergrad_-prefixed key and stay blank if the profile has none.
_PRIOR_DEGREE = re.compile(r"\bundergraduate?\b|\bundergrad\b|\bbachelors?\b|"
                           r"\bbachelor['’]s\b", re.I)
_PRIOR_KEYS = ("university", "degree", "major", "graduation", "gpa")


_UNDERGRAD_DEGREE = re.compile(r"bachelor|\bb\.?s\.?\b|\bb\.?a\.?\b|"
                              r"undergrad", re.I)


def _entry_is_prior(profile, entry):
    """Does this education entry hold the earlier degree?

    Decided by what that entry's recorded degree says, not by its number --
    a form may list the master's first or the bachelor's first.
    """
    answers = dict(profile.get("custom_answers") or {})
    answers.update(profile.get("answers") or {})
    prefix = "education %d ::" % entry
    for key, value in answers.items():
        if key.startswith(prefix) and "degree" in key:
            return bool(_UNDERGRAD_DEGREE.search(str(value)))
    # No recorded answer under that wording: ask what this entry's degree
    # resolves to. Without this the second entry keeps the master's chain, so
    # an employer whose list does not say "Bachelors" outright falls back to
    # M.S -- the entry ends up claiming the wrong degree entirely.
    settled = value_for("Degree", profile, "", "", entry)
    if settled:
        return bool(_UNDERGRAD_DEGREE.search(str(settled)))
    return False


def prior_degree_key(label, key):
    """Redirect a question about a previous degree to its own profile key."""
    if key in _PRIOR_KEYS and _PRIOR_DEGREE.search(normalise(label)):
        return "undergrad_" + key
    return key


# Which repeated block a field belongs to, inferred from the section heading
# and the field's own id. Workday labels an education date and a job date
# identically ("From"), so the block has to be worked out from context.
_EDUCATION = re.compile(r"educat|school|universit|college|degree|gpa|"
                        r"grade\s*point|major|field\s+of\s+study", re.I)
_WORK = re.compile(r"work|employ|experien|company|employer|job\s*title|"
                   r"role|position|responsib", re.I)


def block_of(section, identity, question):
    """"education", "work history", or the section as given."""
    hay = " ".join([str(section or ""), str(identity or ""), str(question or "")])
    if _EDUCATION.search(hay):
        return "education"
    if _WORK.search(hay):
        return "work history"
    return normalise(section).lower().strip()


def answer_key(section, question, identity="", entry=0):
    """Key for one recorded answer.

    `entry` numbers repeated blocks: an application carries two education
    entries and two jobs, and their fields are labelled identically. Numbering
    them keeps the first job's description from overwriting the second's.
    """
    """How a recorded answer is stored.

    A specific question stands on its own. A generic one is scoped by the
    section it sits under and by the field's own id, because "Year" under
    Education and "Year" under Work Experience are different questions sharing
    a word -- and on some forms even the section heading is just "From".
    """
    q = normalise(question).lower().rstrip("?").strip()
    if not q:
        return ""
    # A question specific enough to stand alone is never part of a repeated
    # block -- numbering it drags unrelated fields into "work history 1".
    if is_reusable_question(question):
        return q
    parts = []
    block = block_of(section, identity, question)
    if block:
        parts.append("%s %d" % (block, entry) if entry else block)
    parts.append(q)
    ident = re.sub(r"[^a-z0-9]+", "", usable_identity(identity).lower())
    if ident and ident != re.sub(r"[^a-z0-9]+", "", q):
        parts.append(ident)
    return " :: ".join(parts)


def custom_answer(label, profile, section="", identity="", entry=0):
    """An answer you gave to this exact question before.

    Answers are recorded verbatim against the question text rather than mapped
    onto a canonical field, so two different questions can never overwrite each
    other -- which is what scrambled a profile holding two degrees.
    """
    answers = dict(profile.get("answers") or {})
    answers.update(profile.get("custom_answers") or {})   # older files
    key = answer_key(section, label, identity, entry)
    if key in answers:
        return answers[key]

    # The same question at a different employer carries a different field id,
    # so an answer recorded at one Workday tenant would never be found at
    # another. Compare on block, entry and question, ignoring the id.
    def without_identity(k):
        parts = [p.strip() for p in str(k).split("::")]
        if len(parts) >= 3:
            parts = parts[:2]
        return " :: ".join(parts)

    wanted = without_identity(answer_key(section, label, identity, entry))
    for stored, value in answers.items():
        if without_identity(stored) == wanted:
            return value

    # Older files stored the same answer without the field id or entry number.
    for candidate in (answer_key(section, label, "", entry),
                      answer_key(section, label)):
        if candidate in answers:
            return answers[candidate]
    # A specific question matches wherever it appears, section or not.
    plain = normalise(label).lower().rstrip("?").strip()
    if is_reusable_question(label) and plain in answers:
        return answers[plain]
    # Answers recorded before keys carried an inferred block were scoped by
    # the raw section heading ("from :: degree"). Without these fallbacks,
    # changing the key scheme silently orphans an entire profile.
    sect = normalise(section).lower().strip()
    if sect:
        legacy = "%s :: %s" % (sect, plain)
        if legacy in answers:
            return answers[legacy]
    if plain in answers:
        return answers[plain]

    # A phrase recorded once, matched wherever an employer's wording contains
    # it. The same question is asked in wildly different words -- "non-compete"
    # turns up inside a sentence three lines long -- so an answer tied to one
    # exact sentence is an answer that works at one employer and nowhere else.
    # The longest phrase wins, so a more specific note beats a general one.
    best = None
    haystack = " %s " % plain
    for stored, value in answers.items():
        phrase = normalise(str(stored)).lower().rstrip("?").strip()
        if len(phrase) < 10 or "::" in phrase:
            continue
        if (" %s " % phrase) in haystack or phrase in plain:
            if best is None or len(phrase) > len(best[0]):
                best = (phrase, value)
    if best:
        return best[1]
    return None


def value_for(label, profile, section="", identity="", entry=0):
    """The value to type into this field, or None to leave it alone.

    A verbatim answer to this exact question wins over any canonical field:
    it is what you actually typed, and it cannot have been confused with a
    different question.
    """
    if is_credential(label):
        return None
    saved = custom_answer(label, profile, section, identity, entry)
    if saved not in (None, ""):
        return str(expand_tokens(saved))
    # A dated entry's own month/year, kept per entry because the boxes are
    # labelled only "Month" and "Year".
    dated = entry_date(label, section, profile,
                       block_of(section, identity, label), entry)
    if dated is not None:
        return dated

    # A date belonging to the candidate -- graduation, availability -- comes
    # from what they told Gary, not from today's calendar.
    owned = date_part_of(label, section, profile)
    if owned is not None:
        return owned

    # A signature date is worked out now, never replayed.
    part = date_part_today(label, section)
    if part is not None:
        return part

    key = key_for(label)
    if key is not None:
        key = prior_degree_key(label, key)
        # An education block holding the earlier degree must read the
        # undergrad_ fields, or the second entry inherits the current
        # degree's major and GPA.
        if entry and key in _PRIOR_KEYS and _entry_is_prior(profile, entry):
            key = "undergrad_" + key
        value = profile.get(key)
        if value not in (None, ""):
            value = str(value)
            # The form wants yes or no; a degree name is not an answer to
            # "have you completed your undergraduate degree?".
            if not (expects_yes_no(label)
                    and value.strip().lower() not in _YES_NO_VALUES):
                return value

    # Last resort. This has to sit after the canonical lookup, not instead of
    # it: a question can map to a field and still have a sensible default when
    # that field holds nothing usable for it.
    return default_for(label)


def _tokens(text):
    """Words for comparison, with apostrophes and plurals levelled.

    Dropdowns say "Master's Degree" where a profile says "Masters"; without
    this they share no token at all and the degree is never selected.
    """
    # Filler words carry no meaning and create false matches: "Master of
    # Science" and "Bachelor of Science" share two of three words otherwise.
    stop = {"of", "the", "in", "and", "a", "an", "for", "to", "at", "on"}
    cleaned = str(text or "").lower().replace("\u2019", "'").replace("'s", "")
    # Dotted abbreviations split into meaningless letters: "M.S." becomes
    # {m, s}, which shares nothing with "Masters". Collapse them first.
    cleaned = re.sub(r"(?<=[a-z])\.(?=[a-z])", "", cleaned)
    cleaned = re.sub(r"(?<=[a-z])\.(?![a-z])", " ", cleaned)
    words = [w for w in re.findall(r"[a-z0-9]+", cleaned) if w not in stop]
    out = set()
    for word in words:
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        out.add(word)
    return out


def fallbacks_for(label, profile, section="", identity="", entry=0):  # noqa: C901
    """Alternatives to try when a dropdown has no option matching your answer.

    Some values simply are not offered: a major like "Arts and Entertainment
    Technologies" rarely appears on a Workday list, and the field cannot be
    typed into. Rather than leaving it blank or picking something arbitrary,
    you say in advance what to fall back to, in order.
    """
    table = profile.get("fallbacks") or {}
    out = []

    # Which canonical field this question maps to, and whether this entry
    # holds an earlier degree and so has a chain of its own.
    key = key_for(label)
    if key:
        key = prior_degree_key(label, key)
        if entry and key in _PRIOR_KEYS and _entry_is_prior(profile, entry):
            key = "undergrad_" + key

    def add(values):
        for value in values or []:
            if value not in out:
                out.append(value)

    # The entry's own chain comes first, so a bachelor's entry never reaches
    # for the master's alternatives.
    if key:
        add(table.get(key))

    # Then by the exact question, for employer-specific wording. A chain named
    # after the general field -- "degree" -- belongs to the later degree, and
    # offering it to the earlier one is how an entry comes to claim an M.S.
    superseded = (key[len("undergrad_"):]
                  if key and key.startswith("undergrad_") else "")
    for candidate in (answer_key(section, label, identity, entry),
                      normalise(label).lower().rstrip("?").strip()):
        if superseded and candidate == superseded:
            continue
        add(table.get(candidate))
    return out


def choose_option(label, options, profile, section="", identity="", entry=0):
    """Pick the dropdown option matching your saved answer.

    Returns None when nothing clearly matches. Guessing here is how a form ends
    up claiming the wrong graduation year or visa status.
    """
    wanted = value_for(label, profile, section, identity, entry)
    if not options:
        return None

    lowered = {str(o).strip().lower(): o for o in options if str(o).strip()}

    # Try your answer first, then whatever you said to fall back to.
    candidates = [wanted] if wanted is not None else []
    candidates += fallbacks_for(label, profile, section, identity, entry)
    for candidate in candidates:
        picked = _match_option(str(candidate), lowered)
        if picked is not None:
            return picked
    return None


# Phone-country pickers append a dial code: "United States +1". It defeats a
# token comparison against "United States of America".
_DIAL_CODE = re.compile(r"\s*\+\d{1,4}\s*$")


def _match_option(wanted, lowered):
    """Match one value against a dropdown's options, or None."""
    target = wanted.strip().lower()
    if not target:
        return None
    lowered = dict(lowered)
    for text, original in list(lowered.items()):
        bare = _DIAL_CODE.sub("", text).strip()
        if bare and bare not in lowered:
            lowered[bare] = original
        # "M.S." should also be findable as "ms".
        undotted = re.sub(r"(?<=[a-z])\.(?=[a-z])", "", text).replace(".", "").strip()
        if undotted and undotted not in lowered:
            lowered[undotted] = original

    if target in lowered:
        return lowered[target]

    # Yes/no answers are written many ways.
    if target in ("yes", "no"):
        for text, original in lowered.items():
            if re.match(r"^%s\b" % target, text):
                return original

    # Otherwise require a decisive token overlap rather than a loose guess.
    want_tokens = _tokens(target)
    if not want_tokens:
        return None
    best, best_score = None, 0.0
    for text, original in lowered.items():
        opt_tokens = _tokens(text)
        if not opt_tokens:
            continue
        overlap = len(want_tokens & opt_tokens)
        if not overlap:
            continue
        score = overlap / float(len(want_tokens | opt_tokens))
        if score > best_score:
            best, best_score = original, score
    return best if best_score >= 0.5 else None


# Questions with a sensible default when nothing has been recorded.
DEFAULT_ANSWERS = (
    # Prior employment with this employer. Worded many ways, and employers
    # usually name themselves rather than saying "this company".
    (re.compile(
        r"(?:previously|ever|before)\b[^?]{0,40}?\b(?:worked|employed)|"
        r"\b(?:worked|employed)\b[^?]{0,45}?\b(?:before|previously|prior)\b|"
        r"\b(?:worked|employed)\s+here\b|"
        r"\b(?:former|previous|prior)\s+(?:employee|employment)\b|"
        r"\bre-?hire\b", re.I), "No"),
    # The user is part-way through a 4+1, so the bachelor's is not finished.
    # This needs revisiting when they graduate.
    (re.compile(r"(?:have\s+you\s+)?(?:completed|finished|received|earned|"
                r"obtained)\s+(?:your\s+)?(?:undergraduate|bachelor'?s?)"
                r"(?:\s+(?:degree|studies))?|"
                r"undergraduate\s+degree\s+(?:completed|conferred)", re.I), "No"),
)


# "Have you worked in finance before?" asks about a field, not about this
# employer, and answering No there would be plainly wrong.
_NOT_PRIOR_EMPLOYMENT = re.compile(
    r"\bwork(?:ed|ing)?\s+in\s+(?!this\b|our\b|the\s+(?:company|firm|"
    r"organi[sz]ation))|\bwork(?:ed|ing)?\s+on\b|\bwork(?:ed|ing)?\s+with\s+"
    r"(?:clients|customers|teams|data|models)\b", re.I)


def default_for(label):
    """A safe default for a question you have not answered before."""
    text = normalise(label)
    if _NOT_PRIOR_EMPLOYMENT.search(text):
        return None
    for pattern, answer in DEFAULT_ANSWERS:
        if pattern.search(text):
            return answer
    return None


# A date captured while recording is the day you recorded it, not the day the
# application is sent. It is stored as this token and worked out at fill time.
TODAY_TOKEN = "{today}"

_DATE_FORMATS = [
    ("%m/%d/%Y", re.compile(r"^\d{2}/\d{2}/\d{4}$")),
    ("%m/%d/%y", re.compile(r"^\d{2}/\d{2}/\d{2}$")),
    ("%Y-%m-%d", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("%d/%m/%Y", None),
    ("%B %d, %Y", re.compile(r"^[A-Za-z]+ \d{1,2}, \d{4}$")),
    ("%d %B %Y", re.compile(r"^\d{1,2} [A-Za-z]+ \d{4}$")),
    ("%m-%d-%Y", re.compile(r"^\d{2}-\d{2}-\d{4}$")),
]


def as_today_token(value, today=None):
    """If a captured value is today's date, store the token instead.

    Signature dates must be the day the application is submitted. Replaying the
    day it was recorded would put a stale, wrong date on every application.
    """
    import datetime
    today = today or datetime.date.today()
    text = str(value or "").strip()
    if not text:
        return value
    for fmt, pattern in _DATE_FORMATS:
        if pattern is not None and not pattern.match(text):
            continue
        try:
            parsed = datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if parsed == today:
            return "%s|%s" % (TODAY_TOKEN, fmt)
    return value


def expand_tokens(value, today=None):
    """Turn a stored token back into a real value at fill time."""
    import datetime
    text = str(value or "")
    if not text.startswith(TODAY_TOKEN):
        return value
    today = today or datetime.date.today()
    fmt = text.split("|", 1)[1] if "|" in text else "%m/%d/%Y"
    try:
        return today.strftime(fmt)
    except ValueError:
        return today.strftime("%m/%d/%Y")


_DATE_PART = re.compile(r"^(day|month|year|mm|dd|yyyy|yy)$", re.I)
_SIGNATURE_SECTION = re.compile(
    r"date|sign|today|acknowledg|certif|declaration|submit", re.I)

# Dates that belong to the candidate rather than to the act of signing. The
# pattern above matches the bare word "date", so "What is the expected date of
# your graduation?" was read as a signature and filled with today.
_NOT_TODAY = re.compile(
    r"graduat|birth|\bdob\b|start\s+date|available|availability|"
    r"expected|anticipated|complet|expir|issue", re.I)


def date_part_of(label, section, profile):
    """One piece of a date the candidate owns, asked as separate boxes.

    "What is the expected date of your graduation?" is put as Month, Day and
    Year controls whose own labels say nothing. The question above them is
    what identifies the date, and the answer comes from the profile rather
    than from the calendar.
    """
    text = normalise(label).strip().rstrip(":").lower()
    if not _DATE_PART.match(text):
        return None
    if not _NOT_TODAY.search(normalise(section)):
        return None
    settled = custom_answer(section, profile) or _by_key(section, profile)
    if not settled:
        return None
    month, year = _split_date(str(settled))
    day = None
    match = re.search(r"\b(\d{1,2})\b[/-](\d{1,2})\b[/-](\d{2,4})", str(settled))
    if match:
        day = match.group(2)
    if text in ("day", "dd"):
        return day
    if text in ("month", "mm"):
        return month
    if text in ("year", "yyyy"):
        return year
    if text == "yy" and year:
        return year[-2:]
    return None


def _by_key(question, profile):
    """The profile value a question maps to, without the yes/no handling."""
    key = key_for(question)
    if not key:
        return None
    value = profile.get(key)
    return None if value in (None, "") else str(value)


def date_part_today(label, section, today=None):
    """The right piece of today's date for a split date control.

    Workday asks for a signature date as three separate boxes, so a whole date
    is never visible to the today-detection. Replaying the recorded day would
    put a stale date on every application.
    """
    import datetime
    text = normalise(label).strip().rstrip(":").lower()
    if not _DATE_PART.match(text):
        return None
    context = "%s %s" % (normalise(section), normalise(label))
    if not _SIGNATURE_SECTION.search(context) or _NOT_TODAY.search(context):
        return None
    today = today or datetime.date.today()
    if text in ("day", "dd"):
        return str(today.day)
    if text in ("month", "mm"):
        return str(today.month)
    if text in ("year", "yyyy"):
        return str(today.year)
    if text == "yy":
        return today.strftime("%y")
    return None


# Dates on a repeated entry are asked as bare "Month" and "Year" boxes under a
# "From" or "To" heading. Nothing in the label says which job or which degree
# they belong to, so a recording cannot tell them apart -- which is how work
# dates ended up in the education entries. They are stored explicitly instead.
_FROM = re.compile(r"\bfrom\b|\bstart\b|\bbegan\b", re.I)
_TO = re.compile(r"\bto\b|\bend\b|\bthrough\b|actual\s+or\s+expected|"
                 r"expected\s+graduation|completion", re.I)
_MONTH = re.compile(r"^month$|^mm$", re.I)
_YEAR = re.compile(r"^year$|^yyyy$", re.I)

_BLOCK_KEY = {"work history": "work", "education": "education"}


def _split_date(value):
    """"09/2024" or "May 2027" -> (month, year) as strings."""
    text = " ".join(str(value or "").split())
    if not text:
        return None, None
    m = re.match(r"^(\d{1,2})\s*[/-]\s*(\d{4})$", text)
    if m:
        return str(int(m.group(1))), m.group(2)
    m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", text)
    if m:
        months = {n.lower(): i for i, n in enumerate(
            ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"], 1)}
        name = m.group(1).lower()[:3]
        for full, num in months.items():
            if full.startswith(name):
                return str(num), m.group(2)
        return None, m.group(2)
    m = re.match(r"^(\d{4})$", text)
    if m:
        return None, m.group(1)
    return None, None


def entry_date(label, section, profile, block, entry):
    """The month or year for a dated entry, or None if this isn't one."""
    text = normalise(label).strip().rstrip(":")
    wants_month = bool(_MONTH.match(text))
    wants_year = bool(_YEAR.match(text))
    if not (wants_month or wants_year):
        return None
    key_block = _BLOCK_KEY.get(block)
    if not key_block or not entry:
        return None

    context = "%s %s" % (normalise(section), text)
    if _TO.search(context):
        which = "end"
    elif _FROM.search(context):
        which = "start"
    else:
        return None

    stored = profile.get("%s_%d_%s" % (key_block, entry, which))
    if stored in (None, ""):
        return None
    month, year = _split_date(stored)
    return month if wants_month else year
