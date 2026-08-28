"""A search box whose list is rendered somewhere else on the page.

Workday's Field of Study is a multiselect: typing into it is a query, not an
answer, and the box empties the moment it loses focus unless one of the
offered options is clicked. Its list is built at the far end of the document
rather than beside the box, so no search upwards from the input reaches it.

Looking page-wide for the list is what once fed the Country button a list of
dialling codes, so the rule that makes it safe is checked here too: an option
is clicked only when it matches what was typed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply

PAGE = """
<div data-automation-id="formField-fieldOfStudy">
  <label for="fos">Field of Study</label>
  <div data-automation-id="multiSelectContainer" data-uxi-widget-type="multiselect">
    <div data-automation-id="multiselectInputContainer">
      <input id="fos" type="text">
    </div>
  </div>
</div>
<div style="position:absolute">
  <div data-automation-id="activeListContainer">
    <div role="option">Accounting</div>
    <div role="option">Finance</div>
    <div role="option">Economics</div>
  </div>
</div>
"""

# The list left open by some other question, holding nothing to do with a
# field of study.
STALE = """
<div data-automation-id="formField-fieldOfStudy">
  <label for="fos">Field of Study</label>
  <div data-automation-id="multiSelectContainer" data-uxi-widget-type="multiselect">
    <div data-automation-id="multiselectInputContainer">
      <input id="fos" type="text">
    </div>
  </div>
</div>
<div style="position:absolute">
  <div data-automation-id="activeListContainer">
    <div role="option">Afghanistan (+93)</div>
    <div role="option">Albania (+355)</div>
  </div>
</div>
"""

failures = []

from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    page.set_content(PAGE)
    box = page.query_selector("#fos")
    box.fill("Finance")
    chosen = apply.commit_typeahead(page, box, "Finance")
    if chosen != "Finance":
        failures.append("the option was not committed: %r" % (chosen,))

    # A major the employer does not offer: the list is there, nothing matches,
    # and that has to be said rather than guessed at.
    page.set_content(PAGE)
    box = page.query_selector("#fos")
    box.fill("Arts and Entertainment Technologies")
    chosen = apply.commit_typeahead(page, box, "Arts and Entertainment Technologies")
    if chosen:
        failures.append("an unrelated option was chosen for a missing major: "
                        "%r" % (chosen,))
    if chosen is None:
        failures.append("a list was present but reported as absent, so the "
                        "fallbacks would never be tried")

    # Someone else's list must never be picked from.
    page.set_content(STALE)
    box = page.query_selector("#fos")
    box.fill("Finance")
    chosen = apply.commit_typeahead(page, box, "Finance")
    if chosen:
        failures.append("picked %r from another question's list" % (chosen,))

    # An ordinary text box while another question's list is open. This is
    # what happened at a second employer: First Name and Address were handed
    # a list they had nothing to do with, no option matched what was typed,
    # and Gary cleared the field it had just filled correctly.
    page.set_content("""
      <label for="fn">First Name</label><input id="fn" type="text">
      <div style="position:absolute">
        <div data-automation-id="activeListContainer">
          <div role="option">United States of America (+1)</div>
          <div role="option">Canada (+1)</div>
        </div>
      </div>
    """)
    box = page.query_selector("#fn")
    box.fill("Ramganesh")
    if apply.commit_typeahead(page, box, "Ramganesh") is not None:
        failures.append("a plain text field claimed another question's list")
    if page.input_value("#fn") != "Ramganesh":
        failures.append("a plain text field was cleared, holding %r"
                        % page.input_value("#fn"))

    # An ordinary text box offers no list at all, and must be left as typed.
    page.set_content('<label for="t">Job Title</label><input id="t">')
    box = page.query_selector("#t")
    box.fill("Associate Producer")
    if apply.commit_typeahead(page, box, "Associate Producer") is not None:
        failures.append("a plain text box was treated as a search box")

    # A list that arrives after a delay. Workday fetches its options, so the
    # list is not there the moment typing stops -- and a list still arriving
    # is indistinguishable from no list at all. Returning early on that made
    # the retry useless for the one case it was written for.
    def arriving(options, delay):
        opts = "".join('<div role="option">%s</div>' % o for o in options)
        return ("""
          <div data-automation-id="formField-fieldOfStudy">
            <div data-automation-id="multiSelectContainer"
                 data-uxi-widget-type="multiselect">
              <div data-automation-id="multiselectInputContainer">
                <input id="late" type="text">
              </div>
            </div>
          </div>
          <div id="host" style="position:absolute"></div>
          <script>
            document.getElementById('late').addEventListener('input', () => {
              setTimeout(() => {
                document.getElementById('host').innerHTML =
                  '<div data-automation-id="activeListContainer">%s</div>';
              }, %d);
            });
          </script>
        """ % (opts, delay))

    page.set_content(arriving(["Finance", "Accounting"], 1100))
    box = page.query_selector("#late")
    box.fill("Finance")
    if apply.commit_typeahead(page, box, "Finance") != "Finance":
        failures.append("a list arriving late was treated as no list")

    # When the answer really is absent, say what was on offer -- guessing at
    # an employer's wording has cost more time here than anything else.
    page.set_content(arriving(["Accounting", "Economics"], 100))
    box = page.query_selector("#late")
    box.fill("Arts and Entertainment Technologies")
    if apply.commit_typeahead(page, box,
                              "Arts and Entertainment Technologies") != "":
        failures.append("a missing answer was not reported as missing")
    if "Accounting" not in (apply._LAST_OFFERED or []):
        failures.append("what the list offered was not recorded")

    browser.close()

total = 7 + 3
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
