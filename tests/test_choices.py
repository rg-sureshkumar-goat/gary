"""Radio questions and checkboxes on a page Gary has never seen.

The later pages of an application are almost entirely these: application
questions, voluntary disclosures, self-identification. A radio cannot be
answered on its own -- the question sits above the group and the answer is
which member to click -- so it needs checking against real markup rather than
by reasoning about labels.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply

PAGE = """
<h2>Application Questions</h2>
<fieldset>
  <legend>Have you previously worked for this company?</legend>
  <label><input type="radio" name="prior" value="y"> Yes</label>
  <label><input type="radio" name="prior" value="n"> No</label>
</fieldset>
<fieldset>
  <legend>Will you now or in the future require sponsorship?</legend>
  <label><input type="radio" name="spon" value="y"> Yes</label>
  <label><input type="radio" name="spon" value="n"> No</label>
</fieldset>
<fieldset>
  <legend>Have you completed your undergraduate degree?</legend>
  <label><input type="radio" name="ug" value="y"> Yes</label>
  <label><input type="radio" name="ug" value="n"> No</label>
</fieldset>
<fieldset>
  <legend>I certify that the information given is true and complete</legend>
  <label><input type="radio" name="cert" value="y"> Yes</label>
  <label><input type="radio" name="cert" value="n"> No</label>
</fieldset>
<label><input type="checkbox" id="terms"> I agree to the terms and conditions</label>
<label for="terms">I agree to the terms and conditions</label>
"""

PROFILE = {
    "previous_employee": "No",
    "sponsorship": "No",
    "undergraduate_complete": "No",
}

failures = []

from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content(PAGE)
    filled, skipped = [], []
    apply.fill_choices(page, PROFILE, False, filled, skipped)
    answers = {q: a for q, a in filled}
    left = " | ".join("%s: %s" % (q, why) for q, why in skipped)

    for question, wanted in (
            ("Have you previously worked for this company?", "No"),
            ("Will you now or in the future require sponsorship?", "No"),
            ("Have you completed your undergraduate degree?", "No")):
        got = answers.get(question)
        if got != wanted:
            failures.append("%r answered %r, wanted %r" % (question, got, wanted))

    # An assertion by the candidate is theirs to make, not Gary's.
    if any("certify" in q.lower() for q in answers):
        failures.append("Gary certified the form on the candidate's behalf")
    if "certif" not in left.lower():
        failures.append("the certification was not reported as left alone")
    if page.is_checked("#terms"):
        failures.append("Gary agreed to the terms and conditions")

    # Nothing is re-answered once it holds an answer.
    filled_again, skipped_again = [], []
    apply.fill_choices(page, PROFILE, False, filled_again, skipped_again)
    if any(q in answers for q, _ in filled_again):
        failures.append("an already-answered question was answered again")

    browser.close()

total = 3 + 3 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
