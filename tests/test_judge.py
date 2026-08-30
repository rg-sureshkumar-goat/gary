"""The model fallback, and the limits placed on it.

Rules handle almost every field, but every employer writes at least one
question nobody anticipated. Where the rules give up, the question, the
options and what is known are put to a model. It is asked last, so it never
overrides an answer the rules were sure of, and its answer must be one of the
options verbatim, so it cannot invent a value.

These checks do not call the model. They cover the guarantees around it, which
are what make it safe to consult at all.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import judge

PROFILE = {
    "race": "Asian",
    "gender": "Male",
    "resume": "/Users/someone/Documents/Resume.pdf",
    "transcript": "/Users/someone/Documents/Transcript.pdf",
    "answers": {"a recorded answer": "kept out of the prompt"},
    "role_description": "x" * 400,
}

failures = []

# What the candidate has answered before is sent, not only the profile's own
# fields. Without it the model cannot see that "do you have any relatives
# employed here" was answered no, and so cannot tell that "does anyone in your
# household work here" is the same question -- which is the whole reason for
# asking a model rather than matching a pattern.
WITH_HISTORY = dict(PROFILE, custom_answers={
    "do you have any relatives employed at": "No",
    "seeking an internship": "Summer 2027",
    "password": "should never be sent",
})
sent = judge._facts(WITH_HISTORY)
before = sent.get("answers you have given before") or {}
if "do you have any relatives employed at" not in before:
    failures.append("earlier answers were withheld from the model: %r" % before)
if any("password" in k for k in before):
    failures.append("a credential was sent to the model: %r" % before)

# Documents, secrets and prose are never sent.
facts = judge._facts(PROFILE)
for leaked in ("resume", "transcript", "answers", "role_description"):
    if leaked in facts:
        failures.append("%r was included in what is sent to the model" % leaked)
for kept in ("race", "gender"):
    if kept not in facts:
        failures.append("%r was withheld from the model" % kept)

# Judgement runs on a model on this machine by default, and on the hosted
# model only when a key is set. With neither, it declines rather than failing
# the pass -- the field is simply left for the candidate.
saved = {k: os.environ.pop(k, None)
         for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
url = os.environ.get("GARY_LOCAL_URL")
try:
    if judge.hosted_available():
        failures.append("claimed a hosted credential it does not have")
    # Point the local backend at nothing, so neither is reachable.
    os.environ["GARY_LOCAL_URL"] = "http://127.0.0.1:9"
    judge.LOCAL_URL = "http://127.0.0.1:9"
    if judge.available():
        failures.append("claimed to be available with nothing to ask")
    got, _ = judge.decide("Ethnicity", ["Asian", "White"], PROFILE)
    if got is not None:
        failures.append("answered %r with nothing to ask" % got)
finally:
    judge.LOCAL_URL = url or "http://127.0.0.1:11434"
    if url is None:
        os.environ.pop("GARY_LOCAL_URL", None)
    else:
        os.environ["GARY_LOCAL_URL"] = url
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value

# Every mistake the local model made was date arithmetic -- a degree ending
# next year read as completed, an internship term guessed at. Telling it the
# date did not fix that, so the sums are done here and it is handed what they
# mean. This is what took a measured six-question trial from three right to
# six.
import datetime

DATED = {
    "education_1_start": "07/2026", "education_1_end": "05/2028",
    "education_2_start": "08/2024", "education_2_end": "05/2027",
    "work_1_start": "09/2025", "work_1_end": "04/2026",
}
worked = judge._worked_out(DATED, today=datetime.date(2026, 8, 29))

if "master" not in str(worked.get("currently studying", "")).lower():
    failures.append("a master's begun in July 2026 is not reported as in "
                    "progress: %r" % worked.get("currently studying"))
if "none" not in str(worked.get("degrees completed so far", "")).lower():
    failures.append("a degree ending in 2027 was counted as completed: %r"
                    % worked.get("degrees completed so far"))
if worked.get("seeking an internship for") != "summer 2027":
    failures.append("the internship term was worked out as %r"
                    % worked.get("seeking an internship for"))
if "7 months" not in str(worked.get("work experience so far", "")):
    failures.append("work experience came to %r"
                    % worked.get("work experience so far"))
if "today's date" not in judge._facts(DATED):
    failures.append("the model is not told what today is")

# Once a degree is genuinely finished it counts.
graduated = judge._worked_out(dict(DATED, education_2_end="05/2025"),
                              today=datetime.date(2026, 8, 29))
if "bachelor" not in str(graduated.get("degrees completed so far", "")).lower():
    failures.append("a bachelor's finished in 2025 was not counted: %r"
                    % graduated.get("degrees completed so far"))

# Nothing to choose from is nothing to decide.
if judge.decide("Ethnicity", [], PROFILE)[0] is not None:
    failures.append("chose from an empty list")
if judge.decide("", ["Asian"], PROFILE)[0] is not None:
    failures.append("answered a question with no text")

# A remembered answer is only used when it is still one of the options: an
# employer may reword its list.
key = judge._key("Ethnicity", ["Asian", "White"], judge._facts(PROFILE))
if key == judge._key("Ethnicity", ["Asian", "Black"], judge._facts(PROFILE)):
    failures.append("two different lists share one remembered answer")
if key == judge._key("Gender", ["Asian", "White"], judge._facts(PROFILE)):
    failures.append("two different questions share one remembered answer")

# "None of the above" is a claim, not a way of saying nothing is known. A
# model reaches for it when the facts are silent -- the 32B did, on a question
# about being a first-generation or transfer student, where the profile says
# neither way -- and no instruction reliably stopped it. It is refused here.
for pretend in ("None of the above", "Neither of the above", "Not applicable",
                "N/A", "none of these"):
    if not judge._refuses(pretend):
        failures.append("%r would be accepted from silence" % pretend)
for real in ("Asian", "Male", "No", "Nonprofit experience", "Neither party"):
    if judge._refuses(real):
        failures.append("%r was refused, but it is a real answer" % real)

total = 4 + 3 + 6 + 2 + 2 + 10 + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
