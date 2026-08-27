"""Which form of a name goes in which box.

A plain "First Name" cannot be answered on its own: it means the legal name on
a form that offers a preferred-name field elsewhere, and the name you go by on
a form that doesn't. So the whole form has to be read first.

Run with:  python3 -m tests.test_names
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.names import (  # noqa: E402
    name_for, is_name_field, is_preferred_toggle, form_offers_preferred,
    form_uses_legal)

failures = []

P = {
    "first_name": "RG", "last_name": "Sureshkumar",
    "legal_first_name": "Ramganesh",
    "legal_last_name": "Sureshkumar Kamalanathan",
    "preferred_first_name": "RG", "preferred_last_name": "Sureshkumar",
    "preferred_name": "RG Sureshkumar",
}


def check(label, labels, expected, note=""):
    got = name_for(label, P, labels)
    if got != expected:
        failures.append("%-24s %-34s -> %r, expected %r"
                        % (note, label, got, expected))


# --- 1. a plain form: the name you go by ------------------------------------- #
PLAIN = ["First Name", "Last Name", "Email", "Phone"]
check("First Name", PLAIN, "RG", "plain form")
check("Last Name", PLAIN, "Sureshkumar", "plain form")
check("Given Name", PLAIN, "RG", "plain form")
check("Surname", PLAIN, "Sureshkumar", "plain form")

# --- 2. the form says "legal": always the legal name ------------------------- #
LEGAL = ["Legal First Name", "Legal Last Name", "Preferred First Name"]
check("Legal First Name", LEGAL, "Ramganesh", "explicit legal")
check("Legal Last Name", LEGAL, "Sureshkumar Kamalanathan", "explicit legal")
check("Legal Name", LEGAL, "Ramganesh Sureshkumar Kamalanathan", "explicit legal")
# A preferred field on the same form still takes the preferred name.
check("Preferred First Name", LEGAL, "RG", "explicit legal")

# --- 3. no "legal", but a preferred section exists --------------------------- #
BOTH = ["First Name", "Last Name", "Preferred First Name", "Preferred Last Name"]
check("First Name", BOTH, "Ramganesh", "preferred exists")
check("Last Name", BOTH, "Sureshkumar Kamalanathan", "preferred exists")
check("Preferred First Name", BOTH, "RG", "preferred exists")
check("Preferred Last Name", BOTH, "Sureshkumar", "preferred exists")

# A single preferred-name box wants both parts.
check("Preferred Name", ["First Name", "Preferred Name"], "RG Sureshkumar",
      "one preferred box")
# Other wordings for the same idea.
check("What name do you go by?", ["First Name", "What name do you go by?"],
      "RG Sureshkumar", "goes-by wording")

# --- when both blocks are labelled identically ------------------------------- #
# Workday labels the legal and preferred blocks with the same "First Name" and
# "Last Name", and only the field ids tell them apart. Reading the label alone
# put the legal name into the preferred boxes on a real BRG application.
IDENTICAL = ["First Name", "Last Name", "First Name", "Last Name"]
BY_ID = [
    ("legalNameSection_firstName", "First Name", "Ramganesh"),
    ("legalNameSection_lastName", "Last Name", "Sureshkumar Kamalanathan"),
    ("preferredNameSection_firstName", "First Name", "RG"),
    ("preferredNameSection_lastName", "Last Name", "Sureshkumar"),
    # Lower-case ids, as they come back from a recording.
    ("legalnamefirstname", "First Name", "Ramganesh"),
    ("preferrednamefirstname", "First Name", "RG"),
    ("preferrednamelastname", "Last Name", "Sureshkumar"),
]
for ident, lab, expected in BY_ID:
    got = name_for(lab, P, IDENTICAL, "Preferred Name", ident)
    if got != expected:
        failures.append("%-32s %-11s -> %r, expected %r"
                        % (ident, lab, got, expected))

# The heading decides it when the id says nothing.
for section, lab, expected in [("Legal Name", "First Name", "Ramganesh"),
                               ("Legal Name", "Last Name", "Sureshkumar Kamalanathan"),
                               ("Preferred Name", "First Name", "RG"),
                               ("Preferred Name", "Last Name", "Sureshkumar")]:
    got = name_for(lab, P, IDENTICAL, section, "")
    if got != expected:
        failures.append("under %r: %s -> %r, expected %r"
                        % (section, lab, got, expected))

# An id that mentions neither leaves the form-level rule in charge.
if name_for("First Name", P, IDENTICAL, "", "textInput1") != "Ramganesh":
    failures.append("a neutral id should not disturb the form-level rule")

# --- recognising fields and toggles ------------------------------------------ #
for label in ["First Name", "Last Name", "Full Name", "Surname", "Given Name"]:
    if not is_name_field(label):
        failures.append("not recognised as a name field: %r" % label)
for label in ["Email", "Phone", "Cumulative GPA", "Which office?"]:
    if is_name_field(label):
        failures.append("mistaken for a name field: %r" % label)

for label in ["I have a preferred name", "Do you go by a different name?",
              "Add a preferred name"]:
    if not is_preferred_toggle(label):
        failures.append("preferred-name toggle not recognised: %r" % label)
if is_preferred_toggle("I agree to the terms"):
    failures.append("an unrelated checkbox was treated as a name toggle")

if not form_offers_preferred(BOTH):
    failures.append("failed to see a preferred-name field on the form")
if form_offers_preferred(PLAIN):
    failures.append("saw a preferred-name field where there is none")
if not form_uses_legal(LEGAL):
    failures.append("failed to see that the form asks for a legal name")
if form_uses_legal(BOTH):
    failures.append("saw a legal-name field where there is none")

# Not a name field at all.
if name_for("Email", P, PLAIN) is not None:
    failures.append("answered a non-name field")

total = 4 + 4 + 4 + 2 + 5 + 4 + 4 + 4 + 1 + len(BY_ID) + 4 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
