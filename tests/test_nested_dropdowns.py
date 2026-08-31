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
          // A row that opens carries the arrow a person would click, which is
          // how a category is told from an answer -- not by its wording.
          document.getElementById('host').innerHTML = '<div role="listbox">' +
            items.map(o => '<div role="option" aria-expanded="false">' + o +
              (level ? '' : '<span class="chevron"></span>') + '</div>')
              .join('') + '</div>';
        };
        document.getElementById('b').addEventListener('click',
          () => { level = null; draw(); });
        document.addEventListener('mousedown', e => {
          const o = e.target.closest('#host [role=option]'); if (!o) return;
          const t = o.textContent.trim();
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

    # A flat list must never be mistaken for categories. Guessing from wording
    # did exactly that: a list of universities is full of the word
    # "University", and Gary clicked through it and selected the wrong school.
    page = context.new_page()
    page.set_content(
        '<button id="b" aria-haspopup="listbox" aria-label="School">'
        'Select One</button>'
        '<div><div role="listbox">'
        '<div role="option">Aalborg University</div>'
        '<div role="option">University of Texas - Austin</div>'
        '<div role="option">Texas A&amp;M University</div>'
        '</div></div>')
    if apply._looks_like_categories(page, page.query_selector("#b")):
        failures.append("a flat list of universities was read as categories")
    page.close()

    # And a list whose rows carry the arrow that opens them is.
    page = context.new_page()
    page.set_content(a_tree('{"Social Media":["LinkedIn"],"Job Board":["Indeed"]}'))
    page.query_selector("#b").click()
    page.wait_for_timeout(300)
    if not apply._looks_like_categories(page, page.query_selector("#b")):
        failures.append("rows that open were not recognised as categories")
    page.close()

    # The same list built as Workday actually builds it: a selectinput
    # multiselect, which takes a different path through the code. The
    # exploration had been written into the other one only, so this question
    # went unanswered on a real application while the answer sat one click
    # inside a category.
    page = context.new_page()
    page.set_content("""
      <div data-automation-id="formField-source">
        <label for="q">How Did You Hear About Us?</label>
        <div data-uxi-widget-type="selectinput"
             data-automation-id="multiSelectContainer">
          <div data-automation-id="multiselectInputContainer">
            <input id="q"></div>
        </div><div id="chosen"></div></div>
      <div id="host"></div>
      <script>
        const TREE = {'Social Media':['LinkedIn','Facebook'],
                      'Job Board':['Indeed'],'Other':[]};
        let level = null;
        const draw = () => {
          const items = level ? TREE[level] : Object.keys(TREE);
          document.getElementById('host').innerHTML = '<div role="listbox">' +
            items.map(o => '<div role="option" aria-expanded="false">' + o +
              (level ? '' : '<span class="chevron"></span>') + '</div>')
              .join('') + '</div>';
        };
        const box = document.getElementById('q');
        box.addEventListener('click', () => { level = null; draw(); });
        box.addEventListener('keydown',
          () => setTimeout(() => { level = null; draw(); }, 5));
        document.addEventListener('mousedown', e => {
          const o = e.target.closest('#host [role=option]'); if (!o) return;
          const t = o.textContent.trim();
          if (!level && TREE[t] && TREE[t].length) {
            level = t; setTimeout(draw, 5); return;
          }
          document.getElementById('chosen').textContent = t;
          document.getElementById('host').innerHTML = ''; level = null;
        });
      </script>
    """)
    apply.fill(page, PROFILE, dry_run=False, company="Tencent")
    if page.inner_text("#chosen").strip() != "LinkedIn":
        failures.append("a selectinput multiselect kept %r, wanted LinkedIn"
                        % page.inner_text("#chosen").strip())
    page.close()

    # A control that must be selected from rather than typed into. Gary typed
    # at it and reported that nothing matched; the list held the answer all
    # along. Looking comes first, and typing is a last resort for lists too
    # long to show themselves.
    page = context.new_page()
    page.set_content("""
      <div data-automation-id="formField-source">
        <label for="q">How Did You Hear About Us?</label>
        <div data-uxi-widget-type="selectinput"
             data-automation-id="multiSelectContainer">
          <div data-automation-id="multiselectInputContainer">
            <input id="q" readonly></div>
        </div><div id="chosen"></div></div>
      <div id="host"></div>
      <script>
        const OPTS = ['Employee Referral','LinkedIn','Job Board'];
        const box = document.getElementById('q');
        const draw = () => {
          document.getElementById('host').innerHTML = '<div role="listbox">' +
            OPTS.map(o => '<div role="option">'+o+'</div>').join('') + '</div>';
        };
        box.addEventListener('click', draw);
        document.addEventListener('mousedown', e => {
          const o = e.target.closest('#host [role=option]'); if (!o) return;
          document.getElementById('chosen').textContent =
            o.textContent.trim();
          document.getElementById('host').innerHTML = '';
        });
      </script>
    """)
    apply.fill(page, PROFILE, dry_run=False, company="Tencent")
    if page.inner_text("#chosen").strip() != "LinkedIn":
        failures.append("a control that cannot be typed into kept %r"
                        % page.inner_text("#chosen").strip())
    page.close()

    browser.close()

total = 3 + 3 + 2 + 1 + 1
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
