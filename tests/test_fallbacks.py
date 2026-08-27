"""Falling back when a dropdown has no option matching your answer.

Some values are simply not on the list -- a major like "Arts and Entertainment
Technologies" rarely appears on a Workday dropdown, and the field cannot be
typed into. Rather than leaving it blank or picking something arbitrary, the
alternatives are chosen in advance, in order.

Run with:  python3 -m tests.test_fallbacks
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.formfill import choose_option, fallbacks_for  # noqa: E402

failures = []

PROFILE = {
    "undergrad_major": "Arts and Entertainment Technologies",
    "major": "Finance",
    "fallbacks": {"undergrad_major": ["Other", "Art"]},
}

CASES = [
    ("exact value on the list",
     ["Finance", "Arts and Entertainment Technologies", "Other"],
     "Arts and Entertainment Technologies"),
    ("first fallback only", ["Finance", "Economics", "Other"], "Other"),
    ("second fallback only", ["Finance", "Art", "Biology"], "Art"),
    # Order matters: "Other" is preferred over "Art" when both are offered.
    ("both fallbacks offered", ["Art", "Other", "Finance"], "Other"),
    # Nothing matches: blank is correct, an arbitrary pick is not.
    ("nothing matches", ["Finance", "Economics", "Biology"], None),
    ("empty list", [], None),
]
for name, options, expected in CASES:
    got = choose_option("Undergraduate Major", options, PROFILE)
    if got != expected:
        failures.append("%-26s -> %r, expected %r" % (name, got, expected))

# Fallbacks apply to the field they were set for, not to others.
if choose_option("Major", ["Economics", "Other"], PROFILE) is not None:
    failures.append("a fallback leaked onto the graduate major field")

# A field with no fallbacks configured still behaves as before.
plain = {"major": "Finance"}
if choose_option("Major", ["Finance", "Other"], plain) != "Finance":
    failures.append("an ordinary match broke")
if choose_option("Major", ["Economics", "Other"], plain) is not None:
    failures.append("a field without fallbacks picked something arbitrary")

# Fallbacks can also be attached to an exact question.
by_question = {"fallbacks": {"which office are you interested in": ["Chicago"]}}
if choose_option("Which office are you interested in?",
                 ["New York", "Chicago"], by_question) != "Chicago":
    failures.append("a fallback keyed to a question did not apply")

# Looking up the chain itself.
chain = fallbacks_for("Undergraduate Major", PROFILE)
if chain != ["Other", "Art"]:
    failures.append("fallback chain wrong: %r" % chain)
if fallbacks_for("Phone", PROFILE):
    failures.append("fallbacks appeared for an unrelated field")

# Yes/no matching still works alongside fallbacks.
sponsor = {"sponsorship": "No"}
if choose_option("Will you require sponsorship?", ["Yes", "No"], sponsor) != "No":
    failures.append("yes/no matching regressed")

total = len(CASES) + 1 + 2 + 1 + 2 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
