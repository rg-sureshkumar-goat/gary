"""One institution, many spellings.

A form's list writes a university its own way -- "University of Texas -
Austin", "UT Austin" -- while the candidate's profile has "The University of
Texas at Austin". Typing that in full found nothing on a real application, and
an empty list left nothing to reason about, so the field went unanswered while
Gary held the answer.

Three things follow, and this covers all of them: search on less than the full
name, compare the words that identify a thing rather than its spelling, and
where the words still do not settle it, judge among the options actually on
offer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply
from playwright.sync_api import sync_playwright

WANTED = "The University of Texas at Austin"

failures = []

# Shorter queries, so a search that matches letters has something to show.
shorter = apply.shorter_queries(WANTED)
if "University of Texas" not in shorter:
    failures.append("no query short enough to find a differently written "
                    "tail: %r" % shorter)
if WANTED in shorter:
    failures.append("the full name was offered as a shorter query")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)

    # Spellings that differ only in articles, connectors and punctuation are
    # the same institution, and are matched without any model being asked.
    for spelling in ("University of Texas - Austin",
                     "The University of Texas at Austin",
                     "University of Texas at Austin"):
        page = context.new_page()
        page.set_content(
            '<input id="s" role="combobox" aria-haspopup="true">'
            '<div><div role="listbox">'
            '<div role="option">%s</div>'
            '<div role="option">University of Texas at Dallas</div>'
            '</div></div>' % spelling)
        box = page.query_selector("#s")
        box.fill(WANTED)
        if apply.commit_typeahead(page, box, WANTED) != spelling:
            failures.append("%r was not recognised as the same school"
                            % spelling)
        page.close()

    # Two options both covering the words would be ambiguous, and neither is
    # taken.
    page = context.new_page()
    page.set_content(
        '<input id="s" role="combobox" aria-haspopup="true">'
        '<div><div role="listbox">'
        '<div role="option">University of Texas at Austin</div>'
        '<div role="option">University of Texas at Austin School of Law</div>'
        '</div></div>')
    box = page.query_selector("#s")
    box.fill(WANTED)
    got = apply.commit_typeahead(page, box, WANTED)
    if got not in ("University of Texas at Austin", ""):
        failures.append("chose %r where two options both fit" % got)
    page.close()

    browser.close()

total = 2 + 3 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
