"""A list left open belongs to the control before this one.

Workday leaves a dropdown's list on the page after it has been used, and every
control read afterwards found it. On a real application a prefix, a region and
a "how did you hear about us" question were each offered the same set of
dialling codes -- so all three went unanswered while the answers sat in the
profile.

Also here: what an employer calls a phone code. "Country/Region/Territory
Phone Code" was read as a phone field and offered the candidate's number.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply
from watcher.formfill import key_for, value_for
from playwright.sync_api import sync_playwright

PROFILE = {"phone": "(817) 818-7051", "phone_country_code": "United States",
           "state": "Texas"}

failures = []

# A phone code, however an employer words it.
for label in ("Country/Region/Territory Phone Code", "Country Phone Code",
              "Phone Code", "Dialing Code"):
    if key_for(label) != "phone_country_code":
        failures.append("%r was read as %r" % (label, key_for(label)))
    if value_for(label, PROFILE) == PROFILE["phone"]:
        failures.append("%r was answered with the phone number" % label)
# And a number field is still a number field.
if value_for("Phone Number", PROFILE) != PROFILE["phone"]:
    failures.append("the phone number field stopped working")

PAGE = """
  <div><button id="b1" aria-haspopup="listbox" aria-label="Country Phone Code">
    Select One</button></div>
  <div><button id="b2" aria-haspopup="listbox" aria-label="Prefix">
    Select One</button></div>
  <div id="host"><div role="listbox">
    <div role="option">United States of America (+1)</div>
    <div role="option">Canada (+1)</div></div></div>
  <script>
    document.getElementById('b2').addEventListener('click', () => {
      document.getElementById('host').innerHTML =
        '<div role="listbox"><div role="option">Mr.</div>' +
        '<div role="option">Ms.</div></div>';
    });
  </script>
"""

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)
    page = context.new_page()
    page.set_content(PAGE)

    seen = list(apply.gather_options(page, page.query_selector("#b2"), []))
    if any("+1" in option for option in seen):
        failures.append("read the previous control's list: %r" % seen)
    if sorted(seen) != ["Mr.", "Ms."]:
        failures.append("did not read the control's own options: %r" % seen)

    browser.close()

total = 4 + 4 + 1 + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
