"""Filling for real, not working out what would be filled.

A dry run skips every line that writes, so it cannot show a fault in the
writing itself. One such fault -- reaching for a keyboard on a frame, which
has none -- threw part way through a page, aborted the pass, and left every
remaining field untouched. The dry run passed the whole time, and the failure
reached the user twice.

This exercises the writing path against markup shaped like Workday's.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply

PAGE = """
<div data-automation-id="formField-graduation">
  <label>What is the expected date of your graduation?</label>
  <div data-automation-id="dateInputWrapper" role="group">
    <input data-automation-id="dateSectionMonth-input" id="m" aria-label="Month">
    <input data-automation-id="dateSectionDay-input" id="d" aria-label="Day">
    <input data-automation-id="dateSectionYear-input" id="y" aria-label="Year">
  </div>
</div>
<div data-automation-id="formField-travel">
  <label>Are you willing to travel up to 80% for client engagements?</label>
  <label><input type="checkbox" id="tools"> Microsoft Excel (advanced)</label>
</div>
<div data-automation-id="formField-name">
  <label for="fn">First Name</label>
  <input id="fn" type="text">
</div>
"""

PROFILE = {
    "graduation": "05/31/2028",
    "first_name": "RG",
    "custom_answers": {"microsoft excel": "Yes"},
}

failures = []

from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content(PAGE)

    try:
        filled, skipped, _ = apply.fill(page, PROFILE, dry_run=False)
    except Exception as exc:
        failures.append("filling for real raised %s: %s"
                        % (type(exc).__name__, exc))
        filled = []

    got = (page.input_value("#m"), page.input_value("#d"),
           page.input_value("#y"))
    if got != ("05", "31", "2028"):
        failures.append("the date reads %r, wanted ('05', '31', '2028')" % (got,))
    if not page.is_checked("#tools"):
        failures.append("the checkbox after the date was never reached")
    if page.input_value("#fn") != "RG":
        failures.append("the text field after the date was never reached")

    browser.close()

total = 4
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
