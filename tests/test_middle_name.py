"""A middle name is its own field, not the whole name.

Every name box on a form contains the word "name", and an unqualified one is
answered with the name the candidate goes by. "Middle Name" is not
unqualified: answering it that way put the full legal name into a box beside
first and last, which on a submitted form reads as a mistake by the
candidate.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import names as names_lib

WITHOUT = {
    "first_name": "RG",
    "last_name": "Sureshkumar",
    "legal_first_name": "Ramganesh",
    "legal_last_name": "Sureshkumar Kamalanathan",
    "full_name": "RG Sureshkumar",
}
WITH = dict(WITHOUT, middle_name="Kumar")

failures = []

# Nothing recorded: the field stays empty rather than borrowing another name.
for label in ("Middle Name", "Middle Initial", "MI"):
    got = names_lib.name_for(label, WITHOUT)
    if got is not None:
        failures.append("%r was answered %r with no middle name on file"
                        % (label, got))

# Recorded: the name, or just its initial where that is what is asked.
if names_lib.name_for("Middle Name", WITH) != "Kumar":
    failures.append("a recorded middle name was not used")
if names_lib.name_for("Middle Initial", WITH) != "K":
    failures.append("an initial was not shortened")

# The fields either side of it still work.
if names_lib.name_for("First Name", WITHOUT) != "RG":
    failures.append("the first name stopped working")
if names_lib.name_for("Last Name", WITHOUT) != "Sureshkumar":
    failures.append("the last name stopped working")

# Workday ids every name box "legalName" whether or not the form asks for a
# legal name at all, so that id only distinguishes anything when a preferred
# name is also on the form. On a form with one set of name boxes, the
# candidate wants the name he goes by -- Tencent's form put his full legal
# name in where RG belonged.
ONE_SET = dict(WITHOUT)
for label, ident, wanted in (
        ("First Name", "name--legalName--firstName", "RG"),
        ("Last Name", "name--legalName--lastName", "Sureshkumar")):
    got = names_lib.name_for(label, ONE_SET, (), "", ident,
                             preferred_on_form=False)
    if got != wanted:
        failures.append("one set of name boxes: %r gave %r, wanted %r"
                        % (label, got, wanted))

# Where a form asks for both, the distinction is real and is kept.
for ident, wanted in (("legalNameSection_firstName", "Ramganesh"),
                      ("preferredNameSection_firstName", "RG")):
    got = names_lib.name_for("First Name", ONE_SET, (), "", ident,
                             preferred_on_form=True)
    if got != wanted:
        failures.append("both asked for: %r gave %r, wanted %r"
                        % (ident, got, wanted))

# A title is left empty, however it is asked and whatever the gender says.
from watcher import infer, lists
from watcher.formfill import reasoned_option

TITLED = {"gender": "Male", "first_name": "RG"}
for label in ("Prefix", "Title", "Salutation"):
    if infer.answer(label, TITLED)[0] is not None:
        failures.append("%r was given a title" % label)
if lists.answer(["Select One", "Mr.", "Ms.", "Dr."], TITLED)[0] is not None:
    failures.append("a list of titles was answered")
if reasoned_option("Prefix", ["Select One", "Mr.", "Ms."], TITLED)[0] is not None:
    failures.append("a title was reasoned into place")

total = 3 + 2 + 2 + 4 + 5
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
