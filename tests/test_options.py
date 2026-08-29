"""Reading an option as a small statement rather than a name.

Matching an answer to a dropdown by tidying the text and comparing it failed
repeatedly, because an option is not a name. "Asian (Not Hispanic or Latino)
(United States of America)" asserts one thing and qualifies it twice: once by
saying what it is not, once by naming the country the classification belongs
to.

Read that way the reasoning holds whatever an employer writes, which is the
point -- the alternative was a new special case per employer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import options

ASIAN = "Asian (Not Hispanic or Latino) (United States of America)"
HISPANIC = "Hispanic or Latino (United States of America)"
DECLINE = "I do not wish to self-identify (United States of America)"
LIST = ["Select One", ASIAN, HISPANIC, DECLINE,
        "Black or African American (Not Hispanic or Latino) "
        "(United States of America)"]

failures = []


def check(claim, got, wanted):
    if got != wanted:
        failures.append("%s: got %r, wanted %r" % (claim, got, wanted))


# An option is about its head; the qualifiers narrow it.
check("head of a qualified option", options.head_of(ASIAN), "Asian")
check("qualifiers are read", options.qualifiers_of(ASIAN),
      ["Not Hispanic or Latino", "United States of America"])

# The fact the option is about is asserted.
check("Asian is asserted", options.asserts(ASIAN, "Asian") > 0, True)
# A negated qualifier is the opposite of an assertion -- the trap a substring
# search falls into.
check("Hispanic is not asserted by the Asian option",
      options.asserts(ASIAN, "Hispanic or Latino"), 0)
check("the Asian option denies Hispanic origin",
      options.denies(ASIAN, "Hispanic or Latino"), True)
# A fact appearing only in a qualifier says nothing about what the option is
# for. This is what answered a race question with a country.
check("a country in a qualifier asserts nothing",
      options.asserts(HISPANIC, "United States of America"), 0)

# Choosing from the whole list.
check("the list answers Asian", options.best(LIST, ["Asian"])[0], ASIAN)
check("a country answers nothing",
      options.best(LIST, ["United States of America"])[0], None)
check("a fact nobody claims answers nothing",
      options.best(LIST, ["Martian"])[0], None)

# The same reasoning on wording no one has seen yet.
check("a fact named among others",
      options.best(["Asian or Pacific Islander", "White", "Other"],
                   ["Asian"])[0], "Asian or Pacific Islander")
check("an option excluding the fact is not chosen",
      options.best(["White (Other than Hispanic)", "Hispanic"],
                   ["Hispanic"])[0], "Hispanic")

total = 11
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
