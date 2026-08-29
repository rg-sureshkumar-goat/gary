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
    return True


def key_for_question(question):
    """The form a question is stored under, so other wordings still match it."""
    text = " ".join(str(question or "").split()).lower()
    text = re.sub(r"\s*\*+\s*$", "", text).strip().rstrip("?:.").strip()
    # The employer's own name makes an answer useless everywhere else.
    return text


def remember(profile, path, question, value, corrected=False):
    """Record an answer in the profile on disk. True if anything changed.

    The profile holds the candidate's personal details and stays on their
    machine, so this writes there rather than anywhere shared.
    """
    if not worth_keeping(question, value):
        return False
    key = key_for_question(question)
    value = " ".join(str(value).split())

    answers = profile.setdefault("custom_answers", {})
    if answers.get(key) == value:
        return False
    if key in answers and not corrected:
        # Already known and not contradicted: leave the earlier answer alone.
        return False
    answers[key] = value

    if not path:
        return True
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
    except Exception:
        stored = {}
    stored.setdefault("custom_answers", {})[key] = value
    try:
        temporary = "%s.writing" % path
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(stored, handle, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except Exception:
        return False
    return True
