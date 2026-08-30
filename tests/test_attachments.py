"""A document goes to the slot that asks for it, and the resume goes once.

Greenhouse reveals its cover-letter input only after Attach is clicked, so a
later pass sees a single file field again. Counting slots per pass then calls
the second one the first, and the resume was attached to both the resume
section and the cover letter section of a real application.

Both inputs are labelled only "Attach", so the wording settles nothing either.
What settles it is that a document is attached once.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply
from playwright.sync_api import sync_playwright

RESUME = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "a-resume.pdf")
with open(RESUME, "wb") as handle:
    handle.write(b"%PDF-1.4\n%fixture\n")

PROFILE = {"resume": RESUME}

failures = []


def attached(page):
    return [value for label, value in page if "ttach" in label.lower()]


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)
    page = context.new_page()

    # Two slots, revealed one at a time, both labelled only "Attach".
    apply._ATTACHED.clear()
    apply._UNREADABLE_FILLED.clear()
    page.set_content('<label for="a">Attach</label><input id="a" type="file">')
    first, _, _ = apply.fill(page, PROFILE, dry_run=False)
    if not attached(first):
        failures.append("the resume was not attached to the first slot")

    page.set_content('<label for="b">Attach</label><input id="b" type="file">')
    second, left, _ = apply.fill(page, PROFILE, dry_run=False)
    if attached(second):
        failures.append("the resume was attached a second time: %r"
                        % attached(second))
    if not any("attach it yourself" in why for _l, why in left):
        failures.append("the second slot was not reported back: %r" % left)

    # A slot that says what it wants is judged by that, not by its order.
    apply._ATTACHED.clear()
    apply._UNREADABLE_FILLED.clear()
    page.set_content('<div><h3>Cover Letter</h3><label for="c">Attach</label>'
                     '<input id="c" type="file"></div>')
    _f, left, _ = apply.fill(page, PROFILE, dry_run=False)
    if attached(_f):
        failures.append("the resume was attached to a cover letter slot")
    if not any("cover letter" in why for _l, why in left):
        failures.append("the cover letter slot was not named: %r" % left)

    # And a resume slot still gets the resume, whatever came before it.
    apply._ATTACHED.clear()
    apply._UNREADABLE_FILLED.clear()
    page.set_content('<div><h3>Resume/CV*</h3><label for="d">Attach</label>'
                     '<input id="d" type="file"></div>')
    got, _, _ = apply.fill(page, PROFILE, dry_run=False)
    if not attached(got):
        failures.append("a slot asking for a resume did not get one")

    browser.close()

os.remove(RESUME)

total = 6
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
