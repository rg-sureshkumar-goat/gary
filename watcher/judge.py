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

MODEL = "claude-opus-5"

# Facts that could never answer a dropdown, and should not be sent anywhere.
_PRIVATE = re.compile(r"resume|cover_letter|transcript|writing_sample|"
                      r"password|token|_id$|answers|fallbacks", re.I)

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     ".gary-cache", "judgements.json")


def available():
    """Is there both a client library and a credential to use it with?"""
    if not (os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _facts(profile):
    """What is known about the candidate, minus documents and secrets."""
    out = {}
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

    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
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
