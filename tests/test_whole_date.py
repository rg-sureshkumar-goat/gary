"""A date asked as three boxes that are not directly typeable.

Workday builds a date from Month, Day and Year spin controls in one wrapper.
Each input carries tabindex="-1" and sits behind a display element, so it
never becomes "actionable": clicking or typing through the usual path waits
its full timeout on every one, and the pass stalls for minutes. On a real
application that looked exactly like Gary had died on the page.

The markup here mirrors that. An earlier version of this test used plain
visible inputs, passed, and the stall still reached the user -- a fixture that
is easier to drive than the real thing proves nothing.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply

# tabindex="-1" and a display element in front, as Workday builds it.
FULL = """
<div data-automation-id="dateInputWrapper" role="group">
  <div id="sec-m" tabindex="-1">
    <div aria-hidden="true" data-automation-id="dateSectionMonth-display"
         style="position:absolute;inset:0;background:#fff">MM</div>
    <input data-automation-id="dateSectionMonth-input" id="m" aria-label="Month"
           role="spinbutton" tabindex="-1" style="opacity:0">
  </div>
  <div id="sec-d" tabindex="-1">
    <div aria-hidden="true" data-automation-id="dateSectionDay-display"
         style="position:absolute;inset:0;background:#fff">DD</div>
    <input data-automation-id="dateSectionDay-input" id="d" aria-label="Day"
           role="spinbutton" tabindex="-1" style="opacity:0">
  </div>
  <div id="sec-y" tabindex="-1">
    <div aria-hidden="true" data-automation-id="dateSectionYear-display"
         style="position:absolute;inset:0;background:#fff">YYYY</div>
    <input data-automation-id="dateSectionYear-input" id="y" aria-label="Year"
           role="spinbutton" tabindex="-1" style="opacity:0">
  </div>
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
    context = browser.new_context()
    context.set_default_timeout(4000)
    page = context.new_page()

    page.set_content(FULL)
    group = apply.whole_date_group(page, page.query_selector("#m"))
    if not group:
        failures.append("a full date group was not recognised")
    else:
        started = time.time()
        ok = apply.type_whole_date(page, group, "5", "31", "2028")
        took = time.time() - started
        if not ok:
            failures.append("typing the date failed")
        got = (page.input_value("#m"), page.input_value("#d"),
               page.input_value("#y"))
        if got != ("05", "31", "2028"):
            failures.append("date typed as %r, wanted ('05', '31', '2028')"
                            % (got,))
        # A control that cannot be driven must fail fast, not hold the pass.
        if took > 5:
            failures.append("typing took %.1fs; a pass must not stall" % took)

    page.set_content(PAIR)
    if apply.whole_date_group(page, page.query_selector("#m")) is not None:
        failures.append("a month/year pair was treated as a whole date")

    browser.close()

total = 4
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
