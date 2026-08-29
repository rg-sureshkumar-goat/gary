"""Asking a model what a form question wants, when the rules cannot tell.

Everything else in Gary is rules: this label means that field, this list is
about race, an option asserts its head. Rules are fast, free and predictable,
and they handle almost every field. What they cannot do is meet a question
nobody anticipated -- and every employer writes at least one.

So where the rules produce no answer, the question, the options and what is
known about the candidate are put to a model, which is asked to choose an
option or to decline. That is the judgement the rules were imitating.

Three things keep it safe. It is consulted only after the rules give up, so it
never overrides a known answer. Its answer must be one of the options offered
verbatim, so it cannot invent a value. And anything it decides is reported as
reasoned, with the model's own explanation, because the candidate signs the
application.

A refusal, an error, a missing key or a missing package all mean the same
thing: no answer, and the field is left for the candidate.
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.request

# Judgement runs on whatever is available, preferring what costs nothing.
#
# A model on this machine is the default: it is free, it needs no account, and
# the candidate's details never leave the computer -- which for a file of
# someone's address, race and disability status is the better arrangement
# regardless of price. The hosted model is used only when a key is set.
LOCAL_URL = os.environ.get("GARY_LOCAL_URL", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("GARY_LOCAL_MODEL", "qwen2.5:14b")
HOSTED_MODEL = "claude-opus-5"

# Facts that could never answer a dropdown, and should not be sent anywhere.
_PRIVATE = re.compile(r"resume|cover_letter|transcript|writing_sample|"
                      r"password|token|_id$|answers|fallbacks", re.I)

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     ".gary-cache", "judgements.json")


def hosted_available():
    """A credential and a client library for the hosted model."""
    if not (os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def local_available():
    """A model server answering on this machine."""
    try:
        with urllib.request.urlopen("%s/api/tags" % LOCAL_URL, timeout=2) as r:
            held = json.loads(r.read().decode("utf-8"))
    except Exception:
        return False
    names = [str(m.get("name", "")) for m in held.get("models") or []]
    if not names:
        return False
    # The named model, or anything if it is not installed under that name.
    return LOCAL_MODEL in names or bool(names)


def available():
    """Can anything be asked at all?"""
    return local_available() or hosted_available()


def _facts(profile):
    """What is known about the candidate, minus documents and secrets.

    Today's date is included. Without it a model reads "education_1_end:
    05/2028" as a degree already held, and answers "highest level of education
    completed" with a master's the candidate will not have for two years.
    """
    import datetime
    out = {"today's date": datetime.date.today().isoformat()}
    for key, value in sorted((profile or {}).items()):
        if not isinstance(value, str) or _PRIVATE.search(key):
            continue
        value = value.strip()
        if value and len(value) <= 120:
            out[key] = value
    return out


def _key(question, options, facts):
    """One question, its options and the facts behind an answer."""
    blob = json.dumps([question, list(options or []), facts], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _remembered(key):
    try:
        with open(CACHE, encoding="utf-8") as handle:
            return json.load(handle).get(key)
    except Exception:
        return None


def _remember(key, answer):
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        try:
            with open(CACHE, encoding="utf-8") as handle:
                held = json.load(handle)
        except Exception:
            held = {}
        held[key] = answer
        with open(CACHE, "w", encoding="utf-8") as handle:
            json.dump(held, handle, indent=2, sort_keys=True)
    except Exception:
        pass


PROMPT = """You are filling in a job application on behalf of the candidate \
described below. Answer one question.

What is known about the candidate:
%s

The question on the form:
%s

The options offered, exactly as written:
%s

Choose the option that is right for this candidate, or choose nothing.

Rules:
- "choice" must be one of the options above, copied character for character,
  or null.
- Choose null unless the facts above settle it. Do not guess at anything the
  candidate has not told you: their opinions, their reasons for applying,
  their salary, a referral, or anything about their history that is not
  listed. A blank field costs them seconds to fill; a wrong answer on a
  submitted application cannot be taken back.
- Read each option as a statement. An option may name something and then
  qualify it -- "Asian (Not Hispanic or Latino) (United States of America)"
  is the Asian option; the brackets say what it is not, and which country's
  classification it belongs to. Neither makes it about Hispanic origin or
  about a country.
- Placeholders such as "Select One" are never an answer.
- Prefer an option that declines to answer only if the candidate's own facts
  say to decline.
- Dates decide what has happened and what has not. A date after today has not
  happened yet: a degree ending next year is in progress, not completed, and a
  job ending next year is current, not past.
- "reasoning" is one short sentence naming the fact you used."""

SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["choice", "reasoning"],
    "additionalProperties": False,
}


def decide(question, options, profile):
    """The option a model judges right: (option, why) or (None, why-not)."""
    options = [str(o) for o in (options or []) if str(o).strip()]
    if not options or not question:
        return None, None
    if not available():
        return None, None

    facts = _facts(profile)
    key = _key(question, options, facts)
    held = _remembered(key)
    if held is not None:
        chosen = held.get("choice")
        return (chosen if chosen in options else None), held.get("reasoning")

    if local_available():
        chosen, why = _ask_local(question, options, facts)
        if chosen is not None or why is not None:
            if chosen is not None and chosen not in options:
                chosen, why = None, ("the model named an option that was not "
                                     "on the list")
            _remember(key, {"choice": chosen, "reasoning": why})
            return chosen, (why or None)
        return None, None

    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=HOSTED_MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": PROMPT % (
                json.dumps(facts, indent=2),
                question,
                "\n".join("- %s" % o for o in options),
            )}],
        )
    except Exception:
        # No credential, no network, a bad request: the field is the
        # candidate's, which is where it would have been anyway.
        return None, None

    # A refusal is not an error here. It means no answer, which is safe.
    if getattr(response, "stop_reason", None) == "refusal":
        return None, None

    try:
        text = next(b.text for b in response.content if b.type == "text")
        answer = json.loads(text)
    except Exception:
        return None, None

    chosen = answer.get("choice")
    why = str(answer.get("reasoning") or "").strip()
    # It must be an option that was actually offered, verbatim.
    if chosen is not None and chosen not in options:
        chosen = None
        why = "the model named an option that was not on the list"
    _remember(key, {"choice": chosen, "reasoning": why})
    return chosen, (why or None)


def _ask_local(question, options, facts):
    """Put the question to the model running on this machine.

    Its reply is required to be JSON naming one of the options, and is checked
    against the list afterwards either way -- a small model asked to choose
    from a list will sometimes paraphrase, and a paraphrase is not a choice.
    """
    body = json.dumps({
        "model": LOCAL_MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system",
             "content": "You answer with JSON only, matching "
                        '{"choice": <one of the options, copied exactly, or '
                        'null>, "reasoning": "<one short sentence>"}.'},
            {"role": "user", "content": PROMPT % (
                json.dumps(facts, indent=2),
                question,
                "\n".join("- %s" % o for o in options),
            )},
        ],
    }).encode("utf-8")
    request = urllib.request.Request(
        "%s/api/chat" % LOCAL_URL, data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            held = json.loads(response.read().decode("utf-8"))
        answer = json.loads(held["message"]["content"])
    except Exception:
        return None, None
    chosen = answer.get("choice")
    why = str(answer.get("reasoning") or "").strip()
    if chosen is not None and not isinstance(chosen, str):
        chosen = None
    return chosen, (why or "judged from your profile")
