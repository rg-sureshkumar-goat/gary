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
# Larger reasons better about the questions that reach this point, and the
# machine has the memory for it. Override with GARY_LOCAL_MODEL; whatever is
# installed is used if this one is not.
LOCAL_MODEL = os.environ.get("GARY_LOCAL_MODEL", "qwen2.5:32b")
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


def installed_model():
    """The model to ask on this machine, or None if there is nothing to ask.

    The preferred one if it is installed, otherwise the largest that is --
    size is a fair proxy for how well it will reason about a question the
    rules could not answer, and a missing name should not silently mean no
    judgement at all.
    """
    try:
        with urllib.request.urlopen("%s/api/tags" % LOCAL_URL, timeout=2) as r:
            held = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    models = held.get("models") or []
    names = [str(m.get("name", "")) for m in models]
    if LOCAL_MODEL in names:
        return LOCAL_MODEL
    if not models:
        return None
    biggest = max(models, key=lambda m: m.get("size") or 0)
    return str(biggest.get("name")) or None


def local_available():
    """A model server answering on this machine, with something to ask."""
    return installed_model() is not None


def available():
    """Can anything be asked at all?"""
    return local_available() or hosted_available()


# "None of the above" is a claim, not a way of saying nothing is known. A
# model asked to choose from a list reaches for it when the facts are silent,
# and no instruction reliably stops that -- so it is refused here instead.
# Only the forms that mean "nothing here applies". "Neither party" and "None
# of my degrees" are real answers, and refusing those would be its own error.
_NOTHING_APPLIES = re.compile(
    r"^(?:none|neither)$|"
    r"^(?:none|neither)\s+of\s+(?:the\s+)?(?:above|these|them)$|"
    r"^(?:none|neither)\s+(?:apply|applies)$|"
    r"^not\s+applicable$|^n/?a$|^does\s+not\s+apply$", re.I)


def _refuses(chosen):
    """Is this an answer the model should not have reached from silence?"""
    return bool(_NOTHING_APPLIES.match(str(chosen or "").strip()))



def _worked_out(profile, today=None):
    """Conclusions drawn from the dates, rather than the dates themselves.

    Every mistake the local model made was date arithmetic: a degree ending
    next year read as one already completed, a class year misread, an
    internship term guessed at. Telling it today's date did not fix that --
    it compared dates correctly on one question and fumbled the next.

    Python does not fumble arithmetic. So the sums are done here and the model
    is handed what they mean, leaving it the judgement it is actually for.
    """
    import datetime
    today = today or datetime.date.today()

    def when(value):
        """A stored date as (year, month), or None."""
        text = str(value or "")
        year = re.search(r"(19|20)\d{2}", text)
        if not year:
            return None
        month = re.match(r"\s*(\d{1,2})\s*[/-]", text)
        return int(year.group(0)), int(month.group(1)) if month else 6

    def past(value):
        found = when(value)
        if not found:
            return None
        return (found[0], found[1]) <= (today.year, today.month)

    out = {"today's date": today.isoformat()}

    started = [k for k in ("education_1_start", "education_2_start")
               if past(profile.get(k))]
    if past(profile.get("education_1_start")) and not past(
            profile.get("education_1_end")):
        out["currently studying"] = "a master's degree, in progress"
    elif past(profile.get("education_2_start")) and not past(
            profile.get("education_2_end")):
        out["currently studying"] = "a bachelor's degree, in progress"
    elif started:
        out["currently studying"] = "no, studies are finished"

    finished = []
    if past(profile.get("education_2_end")):
        finished.append("bachelor's")
    if past(profile.get("education_1_end")):
        finished.append("master's")
    out["degrees completed so far"] = (", ".join(finished) if finished
                                       else "none yet -- high school only")

    months = 0
    for entry in (1, 2):
        begin = when(profile.get("work_%d_start" % entry))
        end = when(profile.get("work_%d_end" % entry)) or (today.year,
                                                           today.month)
        if not begin:
            continue
        end = min(end, (today.year, today.month))
        months = max(months, (end[0] - begin[0]) * 12 + (end[1] - begin[1]))
    if months > 0:
        out["work experience so far"] = "about %d month%s" % (
            months, "" if months == 1 else "s")

    graduating = when(profile.get("education_1_end")) or when(
        profile.get("graduation"))
    if graduating:
        out["graduates finally in"] = "%d" % graduating[0]
        # An internship is taken in the summer before graduating.
        out["seeking an internship for"] = "summer %d" % (
            graduating[0] - 1 if graduating[1] <= 8 else graduating[0])
    return out


def _facts(profile):
    """What is known about the candidate, minus documents and secrets.

    Answers the candidate has given on earlier applications are included, not
    just the profile's own fields. Without them the model cannot see that "do
    you have any relatives employed here" was answered no, and so cannot tell
    that "does anyone in your household work here" is the same question. That
    recognition is the whole reason for asking a model rather than a pattern.
    """
    out = _worked_out(profile)
    for key, value in sorted((profile or {}).items()):
        if not isinstance(value, str) or _PRIVATE.search(key):
            continue
        value = value.strip()
        if value and len(value) <= 120:
            out[key] = value

    # What the candidate has answered before, phrased as they were asked. The
    # shorter forms only, so the prompt stays small and reads as facts rather
    # than a transcript.
    answered = {}
    for question, value in sorted((profile.get("custom_answers") or {}).items()):
        if not isinstance(value, str):
            continue
        question, value = question.strip(), value.strip()
        if not question or not value or len(question) > 70 or len(value) > 70:
            continue
        if _PRIVATE.search(question):
            continue
        answered[question] = value
        if len(answered) >= 40:
            break
    if answered:
        out["answers you have given before"] = answered
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
- Dates decide what has happened and what has not. Compare every date to
  today's date above. A date after today has not happened yet: a degree ending
  after today is in progress and has NOT been completed, whatever else is
  known about it, and a job ending after today is still current. A question
  asking what has been completed is asking what is finished as of today.
- "None of the above", "Neither of the above" and "Not applicable" are claims
  about the candidate, not ways of saying you do not know. Choose one only if
  the facts positively establish it. If the facts are silent, choose null.
- Silence is not evidence. Nothing in the facts saying a thing is false; it
  only means it was not recorded, and null is the answer.
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


# A title before a name. The candidate wants none, and a gender on file would
# otherwise imply one, so it has to be refused explicitly.
_A_TITLE = re.compile(r"^(?:name\s+)?(?:prefix|title|salutation|honorific)\b",
                      re.I)


def decide(question, options, profile):
    """The option a model judges right: (option, why) or (None, why-not)."""
    options = [str(o) for o in (options or []) if str(o).strip()]
    if not options or not question:
        return None, None
    if _A_TITLE.match(" ".join(str(question).split())):
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
            elif _refuses(chosen):
                chosen, why = None, ("\"%s\" is a claim about you, and nothing "
                                     "on file establishes it" % chosen)
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
    elif _refuses(chosen):
        why = ("\"%s\" is a claim about you, and nothing on file establishes "
               "it" % chosen)
        chosen = None
    _remember(key, {"choice": chosen, "reasoning": why})
    return chosen, (why or None)


def _ask_local(question, options, facts):
    """Put the question to the model running on this machine.

    Its reply is required to be JSON naming one of the options, and is checked
    against the list afterwards either way -- a small model asked to choose
    from a list will sometimes paraphrase, and a paraphrase is not a choice.
    """
    body = json.dumps({
        "model": installed_model() or LOCAL_MODEL,
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


TEXT_PROMPT = """You are filling in a job application on behalf of the \
candidate described below. Answer one question.

What is known about the candidate:
%s

The question on the form:
%s

Give the short answer that belongs in this box, or nothing.

Rules:
- "answer" is what should be typed into the field: a word, a number, a date, a
  short phrase. Never a sentence of explanation, never more than about ten
  words.
- Choose null unless the facts above settle it. Do not guess at anything the
  candidate has not told you.
- Never write prose on their behalf: reasons for applying, descriptions of
  themselves, cover letters, explanations of their interest, or anything a
  person would recognise as written by someone else. Those are theirs to
  write, and null is the answer.
- Never invent a name, a referral, an employer, a salary they have not stated,
  or anything about their history that is not listed.
- Dates and durations above are already worked out. Use them as given.
- "reasoning" is one short sentence naming the fact you used."""

TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["answer", "reasoning"],
    "additionalProperties": False,
}

# Questions whose answer is the candidate's own writing. A model producing
# these would be putting words in their mouth on a document they sign.
_THEIRS_TO_WRITE = re.compile(
    r"why\s+(?:do|are|would)|tell\s+us|describe|explain|in\s+your\s+own\s+"
    r"words|what\s+(?:interests|excites|motivates)|cover\s+letter|"
    r"essay|paragraph|\bstatement\b|elaborate|expand\s+on", re.I)

# A person Gary has never been told about. "Who referred you to this role?"
# was answered "Company Website" -- the source the candidate heard about the
# job from, offered as the name of a person who put them forward. Naming
# somebody on an application they sign is not a thing to be reasoned into.
_A_PERSON = re.compile(
    r"\bwho\b|referr(?:ed|er)\s+(?:you|by)|name\s+of\s+the\s+person|"
    r"whom\s+|contact\s+name|reference\s+name|supervisor|manager'?s?\s+name|"
    r"emergency\s+contact", re.I)


def decide_text(question, profile):
    """The short answer for a text box: (answer, why) or (None, why-not).

    A box with no options offers nothing to match against, so the rules reach
    it least often -- which makes it exactly where judgement earns its place.
    What is refused is prose: an answer a person would recognise as written by
    someone else has no business on a form the candidate signs.
    """
    question = " ".join(str(question or "").split())
    if not question or len(question) < 8:
        return None, None
    if _THEIRS_TO_WRITE.search(question) or _A_PERSON.search(question):
        return None, None
    if not local_available() and not hosted_available():
        return None, None

    facts = _facts(profile)
    key = _key("text:" + question, [], facts)
    held = _remembered(key)
    if held is not None:
        return held.get("choice"), held.get("reasoning")

    answer, why = _ask_text(question, facts)
    if answer is not None:
        answer = " ".join(str(answer).split())
        # A short answer belongs in a box; a paragraph is prose by another
        # name, whatever the question looked like.
        if not answer or len(answer) > 80 or len(answer.split()) > 12:
            answer, why = None, "the answer would have been prose"
    _remember(key, {"choice": answer, "reasoning": why})
    return answer, (why or None)


def _ask_text(question, facts):
    """Put an open question to whichever model is available."""
    prompt = TEXT_PROMPT % (json.dumps(facts, indent=2), question)
    if local_available():
        body = json.dumps({
            "model": installed_model() or LOCAL_MODEL,
            "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system",
                 "content": "You answer with JSON only, matching "
                            '{"answer": <text or null>, "reasoning": "<one '
                            'short sentence>"}.'},
                {"role": "user", "content": prompt},
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
        return answer.get("answer"), str(answer.get("reasoning") or "").strip()

    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=HOSTED_MODEL, max_tokens=1024,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium",
                           "format": {"type": "json_schema",
                                      "schema": TEXT_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return None, None
    if getattr(response, "stop_reason", None) == "refusal":
        return None, None
    try:
        text = next(b.text for b in response.content if b.type == "text")
        answer = json.loads(text)
    except Exception:
        return None, None
    return answer.get("answer"), str(answer.get("reasoning") or "").strip()
