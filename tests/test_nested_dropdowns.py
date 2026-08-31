"""A dropdown whose options open into further options.

Workday's "How did you hear about us?" holds categories rather than answers:
Social Media opens to reveal LinkedIn. Reading only the first layer sees
category names and concludes the answer is absent, when it is one click away.

Every category is opened in turn, what is inside is recorded against it, and
the choice is made over all of it -- then the category is re-entered to commit
the option that lives there.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply
from playwright.sync_api import sync_playwright


def a_tree(tree):
    return """
      <div><button id="b" aria-haspopup="listbox"
        aria-label="How Did You Hear About Us?">Select One</button>
      <div id="chosen"></div></div>
      <div id="host"></div>
      <script>
        const TREE = %s;
        let level = null;
        const draw = () => {
          const items = level ? TREE[level] : Object.keys(TREE);
          document.getElementById('host').innerHTML = '<div role="listbox">' +
            items.map(o => '<div role="option">'+o+'</div>').join('') +
            '</div>';
        };
        document.getElementById('b').addEventListener('click',
          () => { level = null; draw(); });
        document.addEventListener('mousedown', e => {
          const o = e.target.closest('#host [role=option]'); if (!o) return;
          const t = o.textContent;
          if (!level && TREE[t] && TREE[t].length) {
            level = t; setTimeout(draw, 5); return;
          }
          document.getElementById('chosen').textContent = t;
          document.getElementById('host').innerHTML = ''; level = null;
        });
      </script>
    """ % tree


PROFILE = {"referral": "Company Website", "first_name": "RG"}

failures = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    context.set_default_timeout(4000)

    # The whole tree is mapped, and each option remembers its category.
    page = context.new_page()
    page.set_content(a_tree('{"Social Media":["LinkedIn","Facebook"],'
                            '"Job Board":["Indeed"],"Other":[]}'))
    found = apply.nested_options(page, page.query_selector("#b"))
    if found.get("LinkedIn") != "Social Media":
        failures.append("LinkedIn was not found inside Social Media: %r" % found)
    if found.get("Indeed") != "Job Board":
        failures.append("Indeed was not found inside Job Board: %r" % found)
    if "Other" not in found:
        failures.append("a category holding nothing was dropped: %r" % found)
    page.close()

    # Choosing from inside a category, and committing there.
    for name, tree, wanted in (
            ("LinkedIn inside Social Media",
             '{"Social Media":["LinkedIn","Facebook"],"Job Board":["Indeed"],'
             '"Other":[]}', "LinkedIn"),
            ("the employer's own page inside a category",
             '{"Company Sources":["Tencent Careers Page","Employee Referral"],'
             '"Job Board":["Indeed"]}', "Tencent Careers Page"),
            ("nothing suitable anywhere",
             '{"Print":["Newspaper","Magazine"],"Agency":["Recruiter"]}', "")):
        page = context.new_page()
        page.set_content(a_tree(tree))
        apply.fill(page, PROFILE, dry_run=False, company="Tencent")
        kept = page.inner_text("#chosen").strip()
        if kept != wanted:
            failures.append("%s: the page kept %r, wanted %r"
                            % (name, kept or None, wanted or None))
        page.close()

    browser.close()

total = 3 + 3
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
