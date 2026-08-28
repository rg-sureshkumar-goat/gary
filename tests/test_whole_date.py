"""A date asked as three boxes that advance as you type.

Workday builds a date from Month, Day and Year spin controls in one wrapper,
and each one hands focus to the next as digits arrive. Filling them
separately makes every entry push the next along -- a month of "5" arrived as
a year of 2005 on a real application. The group has to be typed in order.

Month/Year pairs, which education and work entries use, fill correctly one at
a time and must keep doing so.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply

FULL = """
<div data-automation-id="dateInputWrapper" role="group">
  <input data-automation-id="dateSectionMonth-input" id="m" aria-label="Month">
  <input data-automation-id="dateSectionDay-input" id="d" aria-label="Day">
  <input data-automation-id="dateSectionYear-input" id="y" aria-label="Year">
</div>
"""

PAIR = """
<div data-automation-id="dateInputWrapper" role="group">
  <input data-automation-id="dateSectionMonth-input" id="m" aria-label="Month">
  <input data-automation-id="dateSectionYear-input" id="y" aria-label="Year">
</div>
"""

failures = []

from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    page.set_content(FULL)
    group = apply.whole_date_group(page, page.query_selector("#m"))
    if not group:
        failures.append("a full date group was not recognised")
    elif not apply.type_whole_date(page, group, "5", "31", "2028"):
        failures.append("typing the date failed")
    else:
        got = (page.input_value("#m"), page.input_value("#d"),
               page.input_value("#y"))
        if got != ("05", "31", "2028"):
            failures.append("date typed as %r, wanted ('05', '31', '2028')"
                            % (got,))

    # A month-and-year pair is not a whole date and keeps its old handling.
    page.set_content(PAIR)
    if apply.whole_date_group(page, page.query_selector("#m")) is not None:
        failures.append("a month/year pair was treated as a whole date")

    browser.close()

total = 3
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
