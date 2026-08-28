"""Turning a posting's advertised pay into a salary expectation.

An hourly rate is annualised -- forty hours a week for a full-time role,
twenty for a part-time one, fifty-two weeks -- and an annual figure is taken
as it stands. The result carries a dollar sign, which the candidate asked for
explicitly.

Postings write pay many ways, and some omit the dollar sign entirely: Ecolab's
read "Annual or Hourly Compensation Range: 22 - 24", which names both words
and marks neither. The size of the number settles it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import pay

CASES = [
    ("Annual or Hourly Compensation Range: 22 - 24 Many factors are taken "
     "into consideration", "$49,920"),
    ("The hourly rate for this position is $25.00 per hour.", "$52,000"),
    ("Salary Range: $70,000 - $85,000 annually", "$85,000"),
    ("This part-time role pays $20 per hour.", "$20,800"),
    ("Pay range: $18.50 - $21.75 / hr", "$45,240"),
]

# A posting with no pay in it. A company's revenue is not a wage.
SILENT = [
    "Building on a century of innovation, with annual sales of $15 billion "
    "and more than 48,000 associates, Ecolab delivers science-based "
    "solutions.",
    "We offer a competitive benefits package and a collaborative culture.",
]

failures = []

for text, wanted in CASES:
    got, why = pay.desired(text)
    if got != wanted:
        failures.append("%r gave %r, wanted %r" % (text[:40], got, wanted))
    elif not why:
        failures.append("%r gave no reasoning" % text[:40])

for text in SILENT:
    got, _ = pay.desired(text)
    if got is not None:
        failures.append("invented %r from a posting with no pay: %r"
                        % (got, text[:50]))

# A description Workday has collapsed. innerText omits what is hidden, and
# the compensation line was inside it, so the page appeared to advertise
# nothing at all.
import apply
from playwright.sync_api import sync_playwright

COLLAPSED = """
  <h1>Undergrad Finance and Accounting Internship</h1>
  <div style="display:none">
    Annual or Hourly Compensation Range: 22 - 24 Many factors are considered.
  </div>
"""

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)
    page = context.new_page()
    page.set_content(COLLAPSED)
    if "Compensation Range" in page.evaluate("() => document.body.innerText"):
        failures.append("the fixture is not actually collapsed")
    holder = {}
    apply.read_advertised_pay(page, holder)
    if holder.get("desired_salary") != "$49,920":
        failures.append("a collapsed description gave %r, wanted '$49,920'"
                        % holder.get("desired_salary"))
    browser.close()

total = len(CASES) + len(SILENT) + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
