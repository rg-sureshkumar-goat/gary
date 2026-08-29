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

# Documents, secrets and prose are never sent.
facts = judge._facts(PROFILE)
for leaked in ("resume", "transcript", "answers", "role_description"):
    if leaked in facts:
        failures.append("%r was included in what is sent to the model" % leaked)
for kept in ("race", "gender"):
    if kept not in facts:
        failures.append("%r was withheld from the model" % kept)

# With no credential, it declines rather than failing the pass.
saved = {k: os.environ.pop(k, None)
         for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
try:
    if judge.available():
        failures.append("claimed to be available with no credential")
    got, _ = judge.decide("Ethnicity", ["Asian", "White"], PROFILE)
    if got is not None:
        failures.append("answered %r with no credential" % got)
finally:
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value

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

total = 4 + 2 + 2 + 2 + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
