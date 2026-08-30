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

# --- phone device type ------------------------------------------------------- #
# Employers word this every way, and the answer is always the same kind of
# thing. The label must not be mistaken for the phone-number field.
from watcher.formfill import key_for  # noqa: E402

if key_for("Phone Device Type") != "phone_type":
    failures.append("phone device type mapped to %r" % key_for("Phone Device Type"))
if key_for("Phone Number") != "phone":
    failures.append("phone number was captured by the device-type pattern")
if key_for("Mobile Phone") != "phone":
    failures.append("a phone-number label was captured by device type")

PHONE = {"phone_type": "Mobile",
         "fallbacks": {"phone_type": ["Mobile Phone", "Cell Phone", "Cell",
                                      "Cellular", "Mobile Device"]}}
for options, expected in [
    (["Home", "Mobile", "Work"], "Mobile"),
    (["Home Phone", "Mobile Phone", "Work Phone"], "Mobile Phone"),
    (["Home", "Cell", "Work"], "Cell"),
    (["Landline", "Cellular", "Office"], "Cellular"),
    (["Landline", "Mobile Device", "Fax"], "Mobile Device"),
    # Nothing resembling a mobile: blank, not an arbitrary pick.
    (["Landline", "Fax", "Pager"], None),
]:
    got = choose_option("Phone Device Type", options, PHONE)
    if got != expected:
        failures.append("phone type from %r -> %r, expected %r"
                        % (options, got, expected))

# --- phone sub-fields ---------------------------------------------------------- #
# Workday splits a phone into four controls. The general phone rule claimed all
# of them, typing the number into the dial-code picker and the extension box.
PHONE_FIELDS = [
    ("Phone Number", "phone"),
    ("Country Phone Code", "phone_country_code"),
    ("Phone Country Code", "phone_country_code"),
    ("Country Code", "phone_country_code"),
    ("Phone Extension", "phone_extension"),
    ("Extension", "phone_extension"),
    ("Phone Device Type", "phone_type"),
]
for label, expected in PHONE_FIELDS:
    if key_for(label) != expected:
        failures.append("%-22s -> %r, expected %r" % (label, key_for(label), expected))

from watcher.formfill import value_for  # noqa: E402
NUMBER_ONLY = {"phone": "(817) 818-7051", "phone_type": "Mobile",
               "phone_country_code": "United States"}
if value_for("Phone Extension", NUMBER_ONLY) is not None:
    failures.append("a phone number was typed into the extension box")
if value_for("Country Phone Code", NUMBER_ONLY) == "(817) 818-7051":
    failures.append("a phone number was typed into the dial-code picker")
if value_for("Phone Number", NUMBER_ONLY) != "(817) 818-7051":
    failures.append("the phone number no longer reaches the number field")

# Working out which degree an entry holds must not ask value_for, which
# consults the fallback chain, which asks this. That was circular, and
# recursed until the stack ran out on any profile with no recorded education
# answers -- the shape most profiles have before a form has been filled.
bare = {"degree": "Masters", "undergrad_degree": "Bachelors",
        "fallbacks": {"degree": ["M.S"], "undergrad_degree": ["B.S"]}}
for entry, wanted in ((1, "M.S"), (2, "B.S")):
    if choose_option("Degree", ["M.S", "B.S", "Ph.D"], bare, "From", "degree",
                     entry) != wanted:
        failures.append("entry %d picked the wrong degree from a bare profile"
                        % entry)
if choose_option("Degree", ["M.S", "B.S"], {"university": "UT"}, "From",
                 "degree", 2) is not None:
    failures.append("a profile with no degrees produced one anyway")

# Yes/no matching still works alongside fallbacks.
sponsor = {"sponsorship": "No"}
if choose_option("Will you require sponsorship?", ["Yes", "No"], sponsor) != "No":
    failures.append("yes/no matching regressed")

total = len(CASES) + 1 + 2 + 1 + 2 + 1 + 3 + 6 + len(PHONE_FIELDS) + 3 + 3
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
