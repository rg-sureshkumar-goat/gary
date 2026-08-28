"""A control that cannot be read back is still not answered forever.

This is the failure that kept reaching the user: a Workday dropdown publishes
its selection somewhere the page does not report, so every pass believed the
field was unanswered and opened it again. Bounding that cannot rely on
recognising the value -- by assumption it cannot be read -- so it relies on
the control keeping its identity between passes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply

# A dropdown that never admits what was chosen: the button's text stays
# "Select One" no matter how often an option is picked.
PAGE = """
<script>window.picked = 0;</script>
<div>
  <label for="c">Country</label>
  <button id="c" aria-haspopup="listbox" aria-label="Country">Select One</button>
  <div role="listbox">
    <div role="option" onclick="window.picked++">United States of America</div>
    <div role="option" onclick="window.picked++">Canada</div>
  </div>
</div>
"""

PROFILE = {"country": "United States of America"}

failures = []

from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content(PAGE)

    for _ in range(6):
        try:
            apply.fill(page, PROFILE)
        except Exception as exc:
            failures.append("filling raised %s" % exc)
            break

    picked = page.evaluate("() => window.picked")
    if picked > apply.MAX_WRITES:
        failures.append("the dropdown was answered %d times over six passes; "
                        "at most %d is allowed" % (picked, apply.MAX_WRITES))

    # The mark a control is tracked by has to survive between passes, and has
    # to tell two controls apart.
    first = apply.mark_of(page, page.query_selector("#c"))
    again = apply.mark_of(page, page.query_selector("#c"))
    other = apply.mark_of(page, page.query_selector("[role=option]"))
    if not first:
        failures.append("a control could not be marked at all")
    if first != again:
        failures.append("a control's mark changed between readings: %r then %r"
                        % (first, again))
    if first == other:
        failures.append("two different controls share one mark")

    browser.close()

total = 4
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
