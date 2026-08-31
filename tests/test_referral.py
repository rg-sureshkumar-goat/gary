"""Where the candidate says he heard about a role.

His rule is the employer's own website, or LinkedIn if that is not offered.
Employers word their own site differently every time -- "Company Website",
"Career Website", "Sila Website", "Tencent Careers Page" -- and matching those
one at a time is a list that never ends.

Gary knows which employer it is filling for, so an option naming that employer
beside a word for a website is that employer's site. A careers page is one
too. A career fair is not.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import lists
from watcher.formfill import is_referral_question

CASES = [
    # Every wording seen on a real application today.
    ("Tencent", ["Select One", "Tencent Careers Page", "Employee Referral",
                 "Job Board", "Other"], "Tencent Careers Page"),
    ("Ecolab", ["Select One", "Social Media - LinkedIn", "Career Website",
                "Referral"], "Career Website"),
    ("Berkeley Research Group", ["Select One", "Career Website", "LinkedIn",
                                 "Job Fair"], "Career Website"),
    ("Sila Nanotechnologies", ["Select One", "Sila Website", "Indeed"],
     "Sila Website"),
    ("Acme", ["Select One", "Company Website", "LinkedIn"], "Company Website"),
    # No site offered: LinkedIn, as he asked.
    ("Acme", ["Select One", "Career Fair", "LinkedIn"], "LinkedIn"),
    # Neither offered: his to answer.
    ("Acme", ["Select One", "Employee Referral", "Newspaper"], None),
]

failures = []

for company, options, wanted in CASES:
    got = lists.heard_about_us(options, company)
    if got != wanted:
        failures.append("%s: %r gave %r, wanted %r"
                        % (company, options[1:3], got, wanted))

for question in ("How Did You Hear About Us?", "How did you find this job?",
                 "Referral Source", "Where did you hear about this role?"):
    if not is_referral_question(question):
        failures.append("%r was not recognised as the question" % question)
for question in ("What is your major?", "Are you willing to relocate?"):
    if is_referral_question(question):
        failures.append("%r was mistaken for the question" % question)

# Workday's multiselect gives its input no role, no aria-haspopup and no
# marks of any kind, so "How Did You Hear About Us?" was handled as a plain
# text box: typed into rather than driven, and matched against whichever list
# happened to be open -- a set of dialling codes, on a real application. What
# identifies it is the widget built around it.
#
# A stale list left open is covered by tests/test_stale_lists.py; leaving one
# here as well made the outcome depend on which control was reached first.
import apply
from playwright.sync_api import sync_playwright

PAGE = """
  <div><label for="q">How Did You Hear About Us?</label>
    <div data-automation-id="multiSelectContainer"
         data-uxi-widget-type="multiselect">
      <div data-automation-id="multiselectInputContainer"><input id="q"></div>
    </div><div id="chosen"></div></div>
  <div id="host"></div>
  <script>
    const box = document.getElementById('q');
    const OPTS = %s;
    const open = () => {
      document.getElementById('host').innerHTML = '<div role="listbox">' +
        OPTS.map(o => '<div role="option">'+o+'</div>').join('') + '</div>';
    };
    box.addEventListener('click', open);
    box.addEventListener('keydown', () => setTimeout(open, 5));
    document.addEventListener('mousedown', e => {
      const o = e.target.closest('#host [role=option]'); if (!o) return;
      document.getElementById('chosen').textContent = o.textContent;
      document.getElementById('host').innerHTML = '';
    });
  </script>
"""

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)
    for name, options, wanted in (
            ("no company site offered",
             '["Employee Referral","LinkedIn","Job Board"]', "LinkedIn"),
            ("the company's own page",
             '["Tencent Careers Page","LinkedIn"]', "Tencent Careers Page"),
            ("neither offered", '["Employee Referral","Newspaper"]', "")):
        page = context.new_page()
        page.set_content(PAGE % options)
        # A profile of the shape Gary always has. A bare one behaves
        # differently here for reasons belonging to the fixture rather than
        # to the code under test.
        apply.fill(page, {"referral": "Company Website", "first_name": "RG",
                          "last_name": "Sureshkumar", "city": "Pflugerville",
                          "state": "Texas", "phone": "(817) 818-7051",
                          "email": "rs@example.com"},
                   dry_run=False, company="Tencent")
        kept = page.inner_text("#chosen").strip()
        if kept != wanted:
            failures.append("%s: the page kept %r, wanted %r"
                            % (name, kept or None, wanted or None))
        page.close()
    browser.close()

total = len(CASES) + 4 + 2 + 3
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
