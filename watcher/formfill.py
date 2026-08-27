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
    # Older files stored the same answer without the field id.
    without_id = answer_key(section, label)
    if without_id in answers:
        return answers[without_id]
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
    # A signature date is worked out now, never replayed.
    part = date_part_today(label, section)
    if part is not None:
        return part

    key = key_for(label)
    if key is None:
        # Nothing recorded: fall back to a safe default where one applies.
        return default_for(label)
    key = prior_degree_key(label, key)
    value = profile.get(key)
    if value in (None, ""):
        return None
    value = str(value)
    if expects_yes_no(label) and value.strip().lower() not in _YES_NO_VALUES:
        # The form wants yes or no; the profile holds something else.
        return None
    return value


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def choose_option(label, options, profile, section="", identity="", entry=0):
    """Pick the dropdown option matching your saved answer.

    Returns None when nothing clearly matches. Guessing here is how a form ends
    up claiming the wrong graduation year or visa status.
    """
    wanted = value_for(label, profile, section, identity, entry)
    if wanted is None or not options:
        return None

    lowered = {str(o).strip().lower(): o for o in options if str(o).strip()}
    target = wanted.strip().lower()

    if target in lowered:
        return lowered[target]

    # Yes/no answers are written many ways.
    if target in ("yes", "no"):
        for text, original in lowered.items():
            if re.match(r"^%s\b" % target, text):
                return original

    # Otherwise require a decisive token overlap rather than a loose guess.
    want_tokens = _tokens(wanted)
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
    (re.compile(r"previously\s+(?:been\s+)?(?:employed|worked)|"
                r"(?:worked|employed)\s+(?:for|at|with)\s+(?:this|our|the)\s+"
                r"(?:company|firm|organi[sz]ation)|former\s+employee|"
                r"current\s+or\s+former\s+employee|previous\s+employment\s+with",
                re.I), "No"),
)


def default_for(label):
    """A safe default for a question you have not answered before."""
    text = normalise(label)
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
    if not _SIGNATURE_SECTION.search(normalise(section)):
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
