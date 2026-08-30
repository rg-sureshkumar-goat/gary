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

total = 3 + 2 + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
