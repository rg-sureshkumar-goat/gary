"""Keeping what the candidate types, so the same question is answered next time.

Gary leaves a field blank when nothing settles it, and the candidate fills it
in. That answer is worth keeping: employers ask the same things in different
words, and a question answered by hand once should not need answering again.

A correction counts for more than a blank. If Gary put something there and the
candidate changed it, Gary was wrong, and what they typed replaces what it
believed.

Two rules keep this honest. Gary never learns from its own writing -- only a
value that differs from what it put there is the candidate's -- or it would
spend every application confirming its own mistakes. And it never records
anything from a credential field.
"""

import json
import os
import re

# Wording that means the value is not an answer worth keeping.
_PLACEHOLDER = re.compile(r"^(select\s+one|select|choose|--|none|n/?a|"
                          r"mm|dd|yyyy|mm/dd/yyyy|search|required)\.?$", re.I)

# Never kept, whatever a form calls it.
_SECRET = re.compile(r"password|passcode|pin\b|secret|token|ssn|social\s+"
                     r"security|credit\s+card|card\s+number|cvv|security\s+"
                     r"code|date\s+of\s+birth|\bdob\b", re.I)


# Questions asked once per repeated entry. The words are identical in every
# entry -- "Field of Study" is the same question on the bachelor's and the
# master's -- so an answer learned from one would be given for all of them.
# These already have their own places in the profile.
_PER_ENTRY = re.compile(
    r"^(?:school|university|college|degree|field\s+of\s+study|major|"
    r"overall\s+result|gpa|grade\s+point|company|employer|job\s+title|"
    r"role\s+description|title|location|from|to|month|day|year|"
    r"i\s+currently\s+work\s+here)\b", re.I)


def belongs_to_an_entry(question):
    """Is this a question a form asks once per job or per degree?"""
    return bool(_PER_ENTRY.match(" ".join(str(question or "").split())))


def worth_keeping(question, value):
    """Is this a candidate's answer that will help on another form?"""
    question = " ".join(str(question or "").split())
    value = " ".join(str(value or "").split())
    if not question or not value:
        return False
    if len(question) < 8 or len(question) > 200:
        return False
    if len(value) > 120:
        return False
    if _PLACEHOLDER.match(value) or _PLACEHOLDER.match(question):
        return False
    if _SECRET.search(question) or _SECRET.search(value):
        return False
    if belongs_to_an_entry(question):
        return False
    return True


# Words that carry no meaning on their own and only make a key longer.
_FILLER = frozenset((
    "what", "is", "are", "was", "were", "your", "you", "the", "a", "an", "of",
    "do", "does", "did", "have", "has", "had", "please", "provide", "enter",
    "select", "indicate", "specify", "tell", "us", "to", "for", "in", "on",
    "at", "if", "any", "this", "that", "and", "or", "with", "current",
    "currently", "most", "recent", "his", "her", "their", "our", "my",
))


def key_for_question(question, company=""):
    """The form a question is stored under."""
    text = " ".join(str(question or "").split()).lower()
    # An employer's own name makes an answer useless at every other employer.
    if company:
        text = text.replace(str(company).lower(), " ")
    text = re.sub(r"\s*\*+\s*$", "", text)
    return " ".join(text.split()).strip().rstrip("?:.").strip()


def general_key(question, company=""):
    """A shorter form of the question, so other wordings match it too.

    An answer stored under the whole question answers only that question. The
    candidate's GPA correction was kept under a hundred and eighty characters
    of Fannie Mae's wording -- scale clause and all -- so "Cumulative GPA" at
    the next employer matched nothing and the correction may as well not have
    happened.

    What generalises is the distinctive end of the question: "what is your
    current (or most recent) cumulative gpa on a 4.0 scale?" is asking about a
    cumulative GPA. Everything before that is filler shared with every other
    question on the form.
    """
    text = key_for_question(question, company)
    # Asides, trailing clauses and measurement notes belong to one employer's
    # phrasing rather than to the question.
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.split(r"[?.;:]|,\s*(?:please|if|and|or)\b", text)[0]
    text = re.sub(r"\b(?:on|using|against)\s+an?\s+[\d.]+\s*(?:point\s*)?"
                  r"scale\b", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?%?\b", " ", text)

    # Hyphens are kept: "t-shirt size" is written with one, and a key spelled
    # without it is looked for inside a question that has it, and never found.
    words = [w for w in re.split(r"[^a-z0-9'-]+", text) if w.strip("-")]
    while words and words[0] in _FILLER:
        words.pop(0)
    while words and words[-1] in _FILLER:
        words.pop()
    if len(words) < 2:
        return ""

    # A contiguous run, because a stored phrase is looked for inside the next
    # employer's question and a reshuffled one would never be found. The end
    # of a question carries its subject more often than the beginning, which
    # is where the shared scaffolding lives.
    short = " ".join(words[-3:])
    while len(short) < 10 and len(words) > len(short.split()):
        short = " ".join(words[-(len(short.split()) + 1):])
    return short if len(short) >= 10 else ""


def remember(profile, path, question, value, corrected=False, company=""):
    """Record an answer in the profile on disk. True if anything changed.

    The profile holds the candidate's personal details and stays on their
    machine, so this writes there rather than anywhere shared.
    """
    if not worth_keeping(question, value):
        return False
    value = " ".join(str(value).split())
    # The whole question, so it is answered exactly; and a shorter form, so
    # the same question worded differently at another employer is answered
    # too. Storing only the first is why a correction stopped at one form.
    keys = [k for k in (key_for_question(question, company),
                        general_key(question, company)) if k]
    if not keys:
        return False

    answers = profile.setdefault("custom_answers", {})
    if all(answers.get(k) == value for k in keys):
        return False
    if any(k in answers for k in keys) and not corrected:
        # Already known and not contradicted: leave the earlier answer alone.
        return False
    for k in keys:
        answers[k] = value

    if not path:
        return True
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
    except Exception:
        stored = {}
    held = stored.setdefault("custom_answers", {})
    for k in keys:
        held[k] = value
    try:
        temporary = "%s.writing" % path
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(stored, handle, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except Exception:
        return False
    return True
