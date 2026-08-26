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


def normalise(label):
    text = re.sub(r"[\*∗]", " ", str(label or ""))
    text = re.sub(r"\(required\)|\(optional\)", " ", text, flags=re.I)
    return " ".join(text.split())


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


def custom_answer(label, profile):
    """An answer you gave to this exact question before.

    Employers ask their own questions -- "Which office are you interested in?"
    -- that no generic key covers. Those are stored verbatim against the
    question text, so the same wording anywhere else is answered the same way.
    """
    answers = profile.get("custom_answers") or {}
    return answers.get(normalise(label).lower().rstrip("?").strip())


def value_for(label, profile):
    """The value to type into this field, or None to leave it alone."""
    if is_credential(label):
        return None
    key = key_for(label)
    if key is None:
        saved = custom_answer(label, profile)
        return str(saved) if saved not in (None, "") else None
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


def choose_option(label, options, profile):
    """Pick the dropdown option matching your saved answer.

    Returns None when nothing clearly matches. Guessing here is how a form ends
    up claiming the wrong graduation year or visa status.
    """
    wanted = value_for(label, profile)
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
