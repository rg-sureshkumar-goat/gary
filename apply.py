#!/usr/bin/env python3
"""Pre-fill a job application, then hand it to you to check and submit.

    .venv/bin/python apply.py "https://boards.greenhouse.io/acme/jobs/123"

Opens the application in a visible browser, fills every field it recognises
from profile.json, attaches your resume, and stops. You read it over and press
Submit yourself.

Two things it will not do, by design:

  * enter passwords or create accounts. Sites like Workday require an account
    before you can apply; log in yourself, then run this on the form.
  * click Submit. An application goes to a real employer under your name, and
    a mis-filled graduation year or GPA is a misrepresentation you would be
    answering for. The last look is yours.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from watcher.browser import LAUNCH_ARGS, STEALTH, UA, _require_playwright  # noqa: E402
from watcher import formfill  # noqa: E402
from watcher import location as location_lib  # noqa: E402
from watcher import names as names_lib  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(ROOT, "profile.json")
HEADQUARTERS = os.path.join(ROOT, "headquarters.json")

# Anything that would send the form. Located so it can be pointed out to you --
# and never clicked.
SUBMIT_WORDS = ("submit", "apply now", "send application", "finish")


def open_browser(playwright, headless, session_dir):
    """A browser that can remember a sign-in, if a session directory is given.

    Workday makes you sign in before showing the application. Keeping the
    browser profile on disk means you log in once by hand rather than every
    run -- your credentials are still only ever typed by you.
    """
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)
        try:
            ctx = playwright.chromium.launch_persistent_context(
                session_dir, headless=headless, args=LAUNCH_ARGS, user_agent=UA,
                locale="en-US", viewport={"width": 1400, "height": 1000})
            return None, ctx
        except Exception as exc:
            # A browser from an earlier run can outlive its Python process and
            # keep the profile locked. Without this the launch fails silently
            # and you carry on looking at the stale window.
            if "already in use" not in str(exc) and "existing browser" not in str(exc):
                raise
            raise SystemExit(
                "A browser from a previous run is still holding the saved\n"
                "session, so this one could not start -- you would have been\n"
                "left looking at the old window. Close every Chrome for\n"
                "Testing window, or run:\n"
                "    pkill -f 'user-data-dir=%s'\n"
                "then try again." % session_dir)
    browser = playwright.chromium.launch(headless=headless, args=LAUNCH_ARGS)
    ctx = browser.new_context(user_agent=UA, locale="en-US",
                              viewport={"width": 1400, "height": 1000})
    return browser, ctx


def close_browser(browser, ctx):
    try:
        ctx.close()
    except Exception:
        pass
    if browser:
        try:
            browser.close()
        except Exception:
            pass


def load_profile(path):
    if not os.path.exists(path):
        print("No profile.json found.\n"
              "  cp profile.example.json profile.json   then fill it in.\n"
              "  It is gitignored, so it stays off GitHub.")
        return None
    with open(path) as fh:
        profile = json.load(fh)
    return {k: v for k, v in profile.items() if not k.startswith("_")}


# Text a widget shows about itself rather than the question being asked.
# Fields whose placement has been wrong often enough to be worth narrating.
TRACE = re.compile(r"^(month|year|degree|field of study)\b", re.I)

STATUS_TEXT = re.compile(
    r"^\d*\s*items?\s+selected$|^select\s+one$|^select$|^choose$|"
    r"^search$|^required$|^\s*$", re.I)


def label_for(page, element):
    """The visible question text for a form control.

    Order matters. The container fallback is last and deliberately narrow: on
    Workday it will happily return the heading of a neighbouring question, and
    a label attached to the wrong field is worse than no label at all.
    """
    try:
        return page.evaluate("""el => {
            const clean = s => (s || '').replace(/\s+/g, ' ').trim();

            // aria-labelledby may list several ids; Workday uses that to join
            // a question to its option, and taking only the first loses half.
            const ids = el.getAttribute('aria-labelledby');
            if (ids) {
                const parts = ids.split(/\s+/)
                    .map(id => document.getElementById(id))
                    .filter(Boolean)
                    .map(n => clean(n.innerText || n.textContent));
                const joined = clean(parts.join(' '));
                if (joined) return joined;
            }

            const aria = clean(el.getAttribute('aria-label'));
            if (aria) return aria;

            // A multiselect renders "0 items selected" inside itself; the real
            // question sits in a label just before it.
            let prev = el.previousElementSibling;
            for (let n = 0; n < 3 && prev; n++) {
                const t = clean(prev.innerText || prev.textContent);
                if (t && t.length < 60 && !/items?\s+selected/i.test(t)) return t;
                prev = prev.previousElementSibling;
            }

            if (el.id) {
                const byFor = document.querySelector(
                    `label[for="${CSS.escape(el.id)}"]`);
                if (byFor) return clean(byFor.innerText);
            }

            const wrap = el.closest('label');
            if (wrap) return clean(wrap.innerText);

            // Only accept a container label when that container holds this one
            // field -- otherwise it belongs to a sibling question.
            const group = el.closest('div,fieldset,section');
            if (group &&
                group.querySelectorAll('input,select,textarea').length === 1) {
                const lab = group.querySelector('label,legend');
                if (lab) return clean(lab.innerText);
            }

            return clean(el.getAttribute('placeholder')) ||
                   clean(el.getAttribute('data-automation-id')) ||
                   clean(el.getAttribute('name')) || '';
        }""", element)
    except Exception:
        return ""


def identity_of(frame, element):
    """A stable per-field id, so two fields can never share a key.

    Workday labels its controls with descriptive data-automation-id values
    ("school", "degree", "jobTitle"), which distinguish an education entry from
    a job entry even when both show a date labelled "From".
    """
    try:
        return frame.evaluate(
            "el => el.getAttribute('data-automation-id') || "
            "el.getAttribute('name') || el.id || ''", element) or ""
    except Exception:
        return ""


# Workday renders dropdowns as buttons with a popup rather than <select>, and
# wraps its inputs in data-automation-id containers. Without these selectors a
# Workday form looks empty.
CONTROL_SELECTOR = (
    "input, textarea, select, input[type=file], "
    "button[aria-haspopup='listbox'], button[aria-haspopup], "
    "button[aria-label*='Select One'], button[aria-label*='select one'], "
    "[role=combobox], [role=listbox], "
    "[data-automation-id] input, [data-automation-id] textarea")


def controls(frame):
    """Every fillable control, including custom widgets.

    A comma-separated CSS query already returns each element once even when it
    matches several of the selectors, so no de-duplication is needed. Trying to
    de-duplicate by markup collapses genuinely distinct fields that happen to
    share the same opening tag -- two "Attach" file inputs, for instance.
    """
    return frame.query_selector_all(CONTROL_SELECTOR)


def close_combobox(frame):
    try:
        frame.page.keyboard.press("Escape")
    except Exception:
        pass


def combobox_options(frame, element):
    """Open a typeahead combobox and read what it offers.

    Greenhouse and Workday render most dropdowns this way: an <input> whose
    options do not exist in the DOM until it is opened. Clicking the control
    is necessary to see them -- it selects a value, it never submits anything.
    """
    try:
        # Close anything still open from the previous control, or its listbox
        # is the one we end up reading.
        close_combobox(frame)
        frame.wait_for_timeout(200)
        element.click()
        frame.wait_for_timeout(800)
        # Scope to the listbox this control owns. A page-wide [role=option]
        # query returns whichever list happens to be in the DOM -- on this
        # form the country list came back for the office question.
        options = frame.evaluate("""el => {
            // Workday sets aria-controls only once the control is expanded,
            // so it has to be read after the click, not before. Without this
            // the fallback picks whichever list happens to be open and
            // returns another field's options.
            const id = el.getAttribute('aria-controls') ||
                       el.getAttribute('aria-owns') ||
                       (el.getAttribute('aria-expanded') === 'true' &&
                        el.nextElementSibling &&
                        el.nextElementSibling.id) || null;
            let root = id ? document.getElementById(id) : null;
            if (!root) {
                // Prefer a listbox near this control; a page-wide search finds
                // whichever dropdown was opened last. Only descend from an
                // ancestor that actually contains this control.
                let scope = el;
                for (let hop = 0; hop < 6 && scope; hop++) {
                    scope = scope.parentElement;
                    if (!scope) break;
                    const near = Array.from(scope.querySelectorAll('[role=listbox]'))
                        .filter(b => b.offsetParent !== null);
                    if (near.length) { root = near[0]; break; }
                }
            }
            // No page-wide fallback. A listbox that this control does not
            // own belongs to another question -- that is how the Country
            // button came to be offered a list of dialling codes -- and
            // picking from the wrong list is worse than picking nothing.
            if (!root) return [];
            const seen = new Set();
            return Array.from(root.querySelectorAll(
                    '[role=option], [class*=option], [id*=option], li'))
                .map(o => (o.innerText || '').trim())
                .filter(t => t && !seen.has(t) && seen.add(t))
                .slice(0, 400);
        }""", element)
        options = [o for o in options if o]
        if len(options) == 1:
            # A one-item list is almost always another control's current
            # selection caught by the fallback, not a real set of choices.
            return []
        return options
    except Exception:
        return []


def choose_from_combobox(frame, element, wanted):
    """Pick a named option from an open combobox. True if it was selected."""
    try:
        return bool(frame.evaluate("""([el, wanted]) => {
            const id = el.getAttribute('aria-controls') ||
                       el.getAttribute('aria-owns');
            let root = id ? document.getElementById(id) : null;
            if (!root) {
                let scope = el;
                for (let hop = 0; hop < 6 && scope; hop++) {
                    scope = scope.parentElement;
                    if (!scope) break;
                    const near = Array.from(scope.querySelectorAll('[role=listbox]'))
                        .filter(b => b.offsetParent !== null);
                    if (near.length) { root = near[0]; break; }
                }
            }
            // No page-wide fallback. A listbox that this control does not
            // own belongs to another question -- that is how the Country
            // button came to be offered a list of dialling codes -- and
            // picking from the wrong list is worse than picking nothing.
            if (!root) return false;
            for (const o of root.querySelectorAll(
                    '[role=option], [class*=option], [id*=option], li')) {
                const t = (o.innerText || '').trim();
                if (t && t.toLowerCase() === String(wanted).trim().toLowerCase()) {
                    o.click();
                    return true;
                }
            }
            return false;
        }""", [element, wanted]))
    except Exception:
        return False


def commit_typeahead(frame, element, wanted):
    """Settle a search box that is really a dropdown.

    Workday's Field of Study and School boxes accept typing, but the text is
    only a query: unless one of the offered options is clicked, the box empties
    the moment it loses focus. Typing the answer therefore looks like success
    and leaves the field blank. Returns the option actually chosen, or "".
    """
    try:
        frame.wait_for_timeout(700)
        return frame.evaluate("""([el, wanted]) => {
            const id = el.getAttribute('aria-controls') ||
                       el.getAttribute('aria-owns');
            let root = id ? document.getElementById(id) : null;
            if (!root) {
                let scope = el;
                for (let hop = 0; hop < 6 && scope; hop++) {
                    scope = scope.parentElement;
                    if (!scope) break;
                    const near = Array.from(
                        scope.querySelectorAll('[role=listbox]'))
                        .filter(b => b.offsetParent !== null);
                    if (near.length) { root = near[0]; break; }
                }
            }
            // Workday's multiselect -- Field of Study among them -- renders
            // its list at the far end of the document rather than beside the
            // box, so no search upwards from the input can reach it. Looking
            // page-wide is only safe because of the test below: an option is
            // clicked only when it matches what was just typed, and a list
            // left open by another question holds nothing of the sort.
            if (!root) {
                const open = Array.from(document.querySelectorAll(
                    '[data-automation-id=activeListContainer], [role=listbox]'))
                    .filter(b => b.offsetParent !== null);
                root = open.length ? open[open.length - 1] : null;
            }
            if (!root) return null;
            const options = Array.from(root.querySelectorAll(
                '[role=option], [class*=option], [id*=option], li'))
                .filter(o => o.offsetParent !== null &&
                             (o.innerText || '').trim());
            if (!options.length) return null;
            const want = String(wanted).trim().toLowerCase();
            const text = o => (o.innerText || '').trim();
            let pick = options.find(o => text(o).toLowerCase() === want);
            if (!pick) {
                pick = options.find(o => text(o).toLowerCase().startsWith(want));
            }
            if (!pick) {
                pick = options.find(o => want.startsWith(
                    text(o).toLowerCase()));
            }
            if (!pick) {
                // A near miss on wording -- "Finance" against "Finance,
                // General" -- but never a list about something else.
                pick = options.find(o => text(o).toLowerCase().includes(want) ||
                                         want.includes(text(o).toLowerCase()));
            }
            // Anything else on the list is a different answer, not this one.
            if (!pick) return '';
            const chosen = text(pick);
            pick.click();
            return chosen;
        }""", [element, wanted])
    except Exception:
        return None


def button_state(frame, element):
    """A dropdown button's stable question and its current selection.

    Workday puts both into one accessible name: once "Degree" is answered the
    button reads "Degree M.S", and "State" becomes "State Texas Required".
    Taken at face value the question changes with the answer, so the field
    looks new on every pass -- it is re-answered forever, and two entries
    asking the same thing count as different questions.

    The button's own text is the answer, so the question is what remains of
    the accessible name once the answer and any "Required" hint are taken off
    the end. Where the button has no text, the question is matched against the
    field's own naming instead.
    """
    try:
        got = frame.evaluate("""el => {
            const clean = s => (s || '').replace(/\s+/g, ' ').trim();
            const full = clean(el.getAttribute('aria-label')) ||
                         clean(el.innerText);
            if (!full) return null;
            let rest = full.replace(/\s*required\s*$/i, '');
            const shown = clean(el.innerText);

            // The answer is on the end of the name; what precedes it is the
            // question.
            if (shown && rest.toLowerCase().endsWith(shown.toLowerCase())) {
                const question = clean(rest.slice(0, rest.length - shown.length));
                if (question) return {question: question, value: shown};
            }

            const names = [];
            const field = el.closest('[data-automation-id^=formField-]');
            if (field) {
                const id = field.getAttribute('data-automation-id')
                    .replace(/^formField-/, '');
                names.push(clean(id.replace(/[-_]+/g, ' ')
                    .replace(/([a-z])([A-Z])/g, '$1 $2')));
                for (const lab of field.querySelectorAll(
                        'label, [id$=label], [class*=label]')) {
                    names.push(clean(lab.innerText));
                }
            }
            if (el.id) {
                const byFor = document.querySelector(
                    `label[for="${CSS.escape(el.id)}"]`);
                if (byFor) names.push(clean(byFor.innerText));
            }
            let prev = el.previousElementSibling;
            for (let n = 0; n < 3 && prev; n++) {
                names.push(clean(prev.innerText));
                prev = prev.previousElementSibling;
            }

            let best = '';
            for (const n of names) {
                if (!n || n.length > 60) continue;
                if (rest.toLowerCase().startsWith(n.toLowerCase()) &&
                        n.length > best.length) best = n;
            }
            if (!best) return {question: rest, value: shown};
            return {question: best, value: clean(rest.slice(best.length)) || shown};
        }""", element)
    except Exception:
        return None
    if not got:
        return None
    value = str(got.get("value") or "")
    if value.lower() in ("select one", "select", "required", ""):
        value = ""
    return {"question": str(got.get("question") or ""), "value": value}


def widget_value(frame, element):
    """What a control currently holds, native or custom."""
    try:
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            return element.evaluate(
                "el => el.selectedOptions.length ? "
                "el.selectedOptions[0].textContent.trim() : ''")
        if tag == "button":
            # A Workday dropdown shows its selection as the button's text, or
            # only inside its accessible name.
            text = (element.inner_text() or "").strip()
            if text.lower() not in ("select one", "select", ""):
                return text
            state = button_state(frame, element)
            return (state or {}).get("value", "")

        value = (element.input_value() or "").strip()
        if value:
            return value

        # A typeahead combobox often keeps its input empty and renders the
        # chosen option as a chip beside it. Without reading that back, the
        # field looks unanswered and gets re-selected on every pass.
        role = element.get_attribute("role") or ""
        if role == "combobox" or element.get_attribute("aria-haspopup"):
            shown = frame.evaluate("""el => {
                const holder = el.closest('[data-automation-id], div');
                if (!holder) return '';
                const bits = holder.querySelectorAll(
                    '[data-automation-id*=selectedItem], [class*=selected], '
                    '[role=option][aria-selected=true], li');
                for (const b of bits) {
                    const t = (b.innerText || '').trim();
                    if (t && t.length < 80) return t;
                }
                return '';
            }""", element)
            shown = " ".join(str(shown or "").split())
            if shown.lower() not in ("select one", "select", ""):
                return shown
        return ""
    except Exception:
        return ""


# Frames that are never form content.
SKIP_FRAME = ("recaptcha", "gstatic", "doubleclick", "googletagmanager",
              "addtoany", "googleapis", "facebook", "hotjar")


def form_frames(page):
    """Every frame that could hold the application form.

    Greenhouse, Workday and Lever commonly embed the form in an iframe on the
    employer's own careers page, so searching only the top document finds
    nothing but the site's search box.
    """
    frames = []
    for frame in page.frames:
        url = (frame.url or "").lower()
        if any(bad in url for bad in SKIP_FRAME):
            continue
        try:
            count = len(frame.query_selector_all(CONTROL_SELECTOR))
        except Exception:
            continue
        if count:
            frames.append((frame, count))
    # Richest frame first: that is the application, not a newsletter signup.
    frames.sort(key=lambda f: -f[1])
    return [f for f, _ in frames]


def section_for(frame, element):
    """The heading a field sits under, e.g. "Education" or "My Experience".

    Workday asks "School", "Degree" and "Year" once per education entry and
    again per job. The question alone cannot tell those apart; the section
    heading can.
    """
    try:
        return frame.evaluate("""el => {
            // "From", "To" and "Date" head a date range, not a section. Taking
            // one collapses an education entry and a job entry together.
            const GENERIC = /^(from|to|date|start|end|dates?)\b/i;
            let node = el;
            for (let hop = 0; hop < 10 && node; hop++) {
                node = node.parentElement;
                if (!node) break;
                const heads = node.querySelectorAll(
                    'h1,h2,h3,h4,legend,[role=heading]');
                for (const head of heads) {
                    const text = (head.innerText || '').replace(/\s+/g,' ').trim();
                    if (text && !GENERIC.test(text)) return text.slice(0, 60);
                }
            }
            return '';
        }""", element)
    except Exception:
        return ""


def looks_like_login(frame):
    """Whether this form is a sign-in or account-creation form.

    Gary never authenticates anywhere. A password field condemns the form
    outright -- that guarantee is absolute.

    The wording check is deliberately narrow, though: an application page on
    Workday carries "Sign In" and "Create Account" in its header long after you
    have signed in, and treating that as a login form makes Gary refuse to fill
    a perfectly ordinary application. So wording only counts on a form small
    enough to actually be a sign-in box.
    """
    try:
        if frame.query_selector_all("input[type=password]"):
            return True
    except Exception:
        return True                     # unreadable: assume the worst

    labels = []
    for element in controls(frame):
        try:
            labels.append(label_for(frame, element))
        except Exception:
            continue

    # A real application has many fields; a sign-in box has two or three.
    if len(labels) > 6:
        return False

    return formfill.is_auth_form(labels)


def entries_wanted(profile, block):
    """How many entries of a block the profile has data for."""
    answers = dict(profile.get("custom_answers") or {})
    answers.update(profile.get("answers") or {})
    highest = 0
    for key in answers:
        m = re.match(r"%s (\d+) ::" % re.escape(block), key)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


# The sections a Workday experience page is divided into.
SECTION_TITLES = (r"work\s*experience", r"education", r"certification",
                  r"language", r"skill", r"resume|cv", r"websites?",
                  r"social\s*network", r"application\s*question")


def add_buttons(frame, block):
    """The "Add" controls belonging to a section, e.g. Work Experience.

    Workday builds these sections empty: until Add is pressed there are no
    fields at all, which is why a page can look unfillable.

    Every Add button is labelled just "Add", so the section has to come from
    the page. Testing whether an ancestor's text mentions the section does not
    work -- climb far enough and the container holds the whole page, so every
    button matches every section and the last one wins. Instead each button is
    paired with the nearest section title *before* it in document order.
    """
    words = {"work history": r"work\\s*experience|employment|work\\s*history",
             "education": r"education|school|degree"}.get(block, block)
    try:
        return frame.evaluate("""([words]) => {
            const want = new RegExp(words, 'i');
            const all = Array.from(document.querySelectorAll(
                'button,[role=button],a[role=button]'));

            const isAdd = b => {
                const id = b.getAttribute('data-automation-id') || '';
                const text = ((b.innerText || '') + ' ' +
                              (b.getAttribute('aria-label') || '')).trim();
                return /add-button/i.test(id) || /^\\s*add\\b/i.test(text);
            };

            const out = [];
            all.forEach((b, i) => {
                if (!isAdd(b)) return;
                const text = ((b.innerText || '') + ' ' +
                              (b.getAttribute('aria-label') || '')).trim();
                if (want.test(text)) { out.push(i); return; }

                // Walk up to the smallest container that both starts with this
                // section's name and holds this button. Pairing by "nearest
                // title above" is ambiguous when a title appears more than
                // once, which is what broke this.
                let node = b.parentElement;
                for (let hop = 0; hop < 10 && node; hop++) {
                    const t = (node.innerText || node.textContent || '').trim();
                    if (t) {
                        const head = t.split('\\n')[0].trim();
                        if (want.test(head)) { out.push(i); return; }
                        // Reached a container starting with a different
                        // section: this button is not ours.
                        const OTHER = /^(work\\s*experience|education|certification|language|skill|resume|cv|websites?)/i;
                        if (OTHER.test(head) && !want.test(head)) return;
                    }
                    node = node.parentElement;
                }
            });
            return out;
        }""", [words])
    except Exception:
        return []


# Workday lays My Experience out in a fixed order, so when the section titles
# cannot be read -- collapsed sections report no text at all in some states --
# the Add buttons can be taken positionally instead.
SECTION_ORDER = ("work history", "education")


def add_buttons_by_order(frame, block):
    """Fall back to the Add buttons' position on the page.

    Title matching has proved unreliable across Workday's page states: the
    same section is visible in one state and absent in another. The layout
    order, though, is stable -- Work Experience then Education.
    """
    try:
        indexes = frame.evaluate("""() => {
            const out = [];
            Array.from(document.querySelectorAll(
                'button,[role=button],a[role=button]')).forEach((b, i) => {
                const id = b.getAttribute('data-automation-id') || '';
                const text = ((b.innerText || b.textContent || '') + ' ' +
                              (b.getAttribute('aria-label') || '')).trim();
                if (/add-button/i.test(id) || /^\s*add\b/i.test(text)) out.push(i);
            });
            return out;
        }""")
    except Exception:
        return []
    if not indexes:
        return []
    position = SECTION_ORDER.index(block) if block in SECTION_ORDER else None
    if position is None or position >= len(indexes):
        return []
    return [indexes[position]]


# Fields that only ever belong to one kind of entry. Counting by the section
# heading instead is unreliable: on this page the education fields were read as
# sitting under "Work Experience", so work history looked full and its Add
# button was never pressed.
BLOCK_FIELDS = {
    "work history": re.compile(
        r"\bcompany\b|\bemployer\b|\bjob\s*title\b|\bposition\s*title\b|"
        r"\brole\s*description\b|\bcurrently\s+work\s+here\b", re.I),
    "education": re.compile(
        r"\bschool\b|\buniversity\b|\bdegree\b|\bfield\s+of\s+study\b|"
        r"\boverall\s+result\b|\bgpa\b", re.I),
}


def block_of_element(frame, element):
    """Which entry a control belongs to: ("education", <container key>), or None.

    A "Month" box under a "From" heading says nothing about whether it dates a
    job or a degree, and its own label says less. Workday, though, names the
    container each repeated entry lives in -- workExperience-2, education-1 --
    so the answer is overhead, in markup, rather than inferred from
    neighbouring text. Those names carry a running sequence number rather than
    an ordinal -- education-28 is not the twenty-eighth degree -- so the
    container is returned as an opaque key and numbered by the order it
    appears in.
    """
    try:
        got = frame.evaluate("""el => {
            // The entry is the block of markup holding what identifies it: a
            // job has a title and an employer, a degree a school. Date boxes
            // sit in containers of their own that are named alike, so the
            // nearest name that matches is a field, not an entry.
            const WORK = '[data-automation-id*=jobTitle],' +
                         '[data-automation-id*=company]';
            const STUDY = '[data-automation-id*=school],' +
                          '[data-automation-id*=degree],' +
                          '[data-automation-id*=fieldOfStudy]';
            let node = el;
            for (let hop = 0; hop < 12 && node; hop++) {
                node = node.parentElement;
                if (!node || !node.querySelectorAll) break;
                const work = node.querySelectorAll(WORK).length;
                const study = node.querySelectorAll(STUDY).length;
                // One such field means a container for that field alone. An
                // entry holds several: a job has a title and an employer, a
                // degree a school, a degree and a field of study.
                if (work < 2 && study < 2) continue;
                // Holding both kinds makes it the section, not an entry.
                if (work >= 2 && study >= 2) return null;

                // Two entries share one data-automation-id, so the position
                // in the document is what tells them apart.
                const path = [];
                for (let n = node; n && n.parentElement; n = n.parentElement) {
                    path.push(Array.prototype.indexOf.call(
                        n.parentElement.children, n));
                }
                return {block: work >= 2 ? 'work' : 'education',
                        key: (node.getAttribute('data-automation-id') || '') +
                             ':' + path.join('-')};
            }
            return null;
        }""", element)
    except Exception:
        return None
    if not got:
        return None
    word = str(got.get("block") or "").replace("_", " ").replace("-", " ")
    block = ("work history" if "work" in word or "experience" in word
             else "education")
    return block, str(got.get("key") or "")


def entries_present(frame, block):
    """How many entries of a block are already on the page.

    Counted from fields that belong to this kind of entry and nothing else,
    and as the most times any one of them repeats: two "Company" boxes mean
    two jobs, however many other fields surround them.
    """
    pattern = BLOCK_FIELDS.get(block)
    if pattern is None:
        return 0
    counts = {}
    for element in controls(frame):
        try:
            label = formfill.normalise(label_for(frame, element))
            ident = identity_of(frame, element)
        except Exception:
            continue
        if not pattern.search("%s %s" % (label, ident)):
            continue
        key = formfill.normalise(label).lower() or ident.lower()
        counts[key] = counts.get(key, 0) + 1
    return max(counts.values()) if counts else 0


def open_entry_sections(frame, profile, dry_run=False, log=None):
    """Press Add until each repeated section has room for what we know.

    Clicking Add creates a blank entry; it never submits anything.
    """
    created = []
    try:
        titles = frame.evaluate("""([titles]) => {
            const re = new RegExp('^(' + titles.join('|') + ')\\\\b', 'i');
            return Array.from(document.querySelectorAll(
                'h1,h2,h3,h4,h5,legend,label,div,span,p'))
                .map(e => ((e.innerText || e.textContent || '')).trim())
                .filter(t => t && t.length < 40 && re.test(t))
                .slice(0, 10);
        }""", [list(SECTION_TITLES)])
        if titles and log:
            log("   section titles seen: %s" % ", ".join(sorted(set(titles))))
    except Exception:
        pass
    for block in ("work history", "education"):
        wanted = entries_wanted(profile, block)
        if not wanted:
            continue
        for _ in range(wanted):
            present = entries_present(frame, block)
            by_title = add_buttons(frame, block)
            by_order = add_buttons_by_order(frame, block) if not by_title else []
            if log:
                log("   [%s] wanted=%d present=%d byTitle=%s byOrder=%s"
                    % (block, wanted, present, by_title, by_order))
                if not by_title and not by_order:
                    # Neither method found a button. Show what is on the page
                    # at this exact moment rather than inferring.
                    try:
                        seen = frame.evaluate("""() =>
                            Array.from(document.querySelectorAll(
                                'button,[role=button],a[role=button]'))
                            .map(b => ((b.innerText || b.textContent || '').trim()
                                       + ' ~ ' + (b.getAttribute('aria-label')||'')
                                       + ' ~ ' + (b.getAttribute('data-automation-id')||'')))
                            .slice(0, 30)""")
                        log("      buttons visible to this frame: %d" % len(seen))
                        for b in seen:
                            log("        %s" % b[:88])
                    except Exception as exc:
                        log("      (button query failed: %s: %s)"
                            % (type(exc).__name__, str(exc)[:80]))
            if present >= wanted:
                break
            indexes = by_title or by_order
            if not indexes:
                break
            if dry_run:
                created.append((block, "would press Add"))
                break
            try:
                frame.evaluate("""([i]) => {
                    const b = document.querySelectorAll(
                        'button,[role=button],a[role=button]')[i];
                    if (b) b.click();
                }""", [indexes[0]])
                frame.wait_for_timeout(1400)
                created.append((block, "pressed Add"))
            except Exception:
                break
    if created and log:
        for block, what in created:
            log("   %s: %s" % (block, what))
    return created


# Touch this file to stop Gary filling without ending the session; the
# browser stays open, because closing it loses a part-finished application.
PAUSE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".gary-pause")

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "snapshots")
_SNAPPED = {}
# Three passes at a page, spaced out, is enough to catch it empty, part
# answered and finished, without filling the disk with near-identical copies.
SNAPSHOT_LIMIT = 3
SNAPSHOT_GAP = 40


def snapshot_page(page, frames):
    """Save each distinct page's real markup once, for offline work.

    Diagnosing a form by asking someone to run it again and describe what they
    saw is slow and wastes their time. With the actual markup on disk the same
    faults can be reproduced and fixed against a test, and every remaining page
    can be prepared without another live pass.

    These files hold whatever has been typed into the form, so they stay on
    this machine and out of the repository.
    """
    try:
        heading = ""
        for frame in frames:
            try:
                heading = frame.title() or ""
            except Exception:
                pass
            if heading:
                break
        # Workday keeps one address for the whole application, so naming by
        # URL gave every page the same name and only the first was ever kept.
        # The step's own heading is what distinguishes them.
        step = ""
        for frame in frames:
            try:
                step = frame.evaluate(
                    "() => { const n = document.querySelector("
                    "'[data-automation-id^=applyFlow][data-automation-id$=Page]');"
                    " const h = Array.from(document.querySelectorAll('h1,h2,h3'))"
                    ".map(x => (x.innerText||'').trim()).filter(Boolean);"
                    " return ((n && n.getAttribute('data-automation-id')) || '')"
                    " + ' ' + (h[h.length - 1] || ''); }") or ""
            except Exception:
                step = ""
            if step.strip():
                break
        name = re.sub(r"[^a-z0-9]+", "-",
                      ("%s %s %s" % (page.url.split("?")[0][-40:],
                                     step, heading)).lower()).strip("-")[:90]
        if not name:
            return None
        # Capture a page more than once. The first sight of it is the empty
        # form, and what a control looks like *after* it has been answered is
        # often the interesting part -- a Workday dropdown only reveals how it
        # reports a selection once it holds one.
        import time
        taken, last = _SNAPPED.get(name, (0, 0.0))
        now = time.time()
        if taken >= SNAPSHOT_LIMIT or (taken and now - last < SNAPSHOT_GAP):
            return None
        _SNAPPED[name] = (taken + 1, now)
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        path = os.path.join(SNAPSHOT_DIR,
                            "%s-%d.html" % (name, taken + 1))
        parts = ["<!-- %s -->" % page.url]
        for index, frame in enumerate(frames):
            try:
                parts.append("<!-- frame %d: %s -->\n%s"
                             % (index, frame.url, frame.content()))
            except Exception as exc:
                parts.append("<!-- frame %d unreadable: %s -->" % (index, exc))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(parts))
        return path
    except Exception:
        return None

_RECENTLY_FILLED = {}
_UNREADABLE_FILLED = set()
_LISTED_PAGES = set()
_WRITES = {}
_GAVE_UP = set()
# Two attempts is enough for any field: one to answer it, one if the page
# rebuilt the control underneath. Beyond that something is wrong, and
# rewriting it forever churns the form under the user's hands.
MAX_WRITES = 2


# Three passes over one arrangement of a page: the first presses Add and fills
# what is there, and the rest catch fields that Workday rebuilt underneath --
# answering one date detaches the others, so they cannot all be reached at
# once. Repetition is bounded by the per-field ceiling, not by this.
PASSES_PER_SHAPE = 3


def step_of(frames):
    """Which step of the application this is.

    Workday keeps one address for the whole application, so the URL cannot
    tell My Information from My Experience. The step's own name can.
    """
    for frame in frames:
        try:
            got = frame.evaluate(
                "() => { const n = document.querySelector("
                "'[data-automation-id^=applyFlow][data-automation-id$=Page]');"
                " const h = Array.from(document.querySelectorAll('h1,h2,h3'))"
                ".map(x => (x.innerText||'').trim()).filter(Boolean);"
                " return ((n && n.getAttribute('data-automation-id')) || '')"
                " + '/' + (h[h.length - 1] || ''); }")
        except Exception:
            continue
        if got and got.strip("/"):
            return got.strip()
    return ""


def page_shape(frames):
    """What the page is offering right now.

    Two readings that match mean nothing has changed -- no new entry, no new
    step -- and there is nothing further to fill.

    An open dropdown is not a change to the page. Counting its options as
    controls made answering one question look like a new arrangement, which
    earned another pass, which answered it again: the form was rewritten under
    the user's hands for as long as it stayed open.
    """
    marks = []
    for frame in frames:
        try:
            marks.extend(frame.evaluate("""(selector) =>
                Array.from(document.querySelectorAll(selector))
                    .filter(el => !el.closest('[role=listbox]') &&
                                  el.getAttribute('role') !== 'option')
                    .map(el => (el.getAttribute('data-automation-id') ||
                                el.getAttribute('name') ||
                                el.getAttribute('id') || '?'))""",
                CONTROL_SELECTOR))
        except Exception:
            marks.append("?")
    return (step_of(frames), tuple(sorted(str(m) for m in marks)))


def mark_of(frame, element):
    """A token that stays with this control for as long as it exists.

    Every attempt to build a key out of what a field looks like has come apart
    in the same way: a Workday dropdown's label absorbs its own answer, its
    address changes within a step, its identity is sometimes absent. A key
    that shifts is a new field every pass, and every limit meant to stop
    repeated writing quietly resets.

    Marking the element itself cannot drift. If Workday rebuilds the control
    the mark goes with it, which is the one case where filling it again is the
    right thing to do.
    """
    try:
        return frame.evaluate("""el => {
            let mark = el.getAttribute('data-gary-mark');
            if (!mark) {
                window.__garyMark = (window.__garyMark || 0) + 1;
                mark = 'g' + window.__garyMark;
                el.setAttribute('data-gary-mark', mark);
            }
            return mark;
        }""", element) or ""
    except Exception:
        return ""


def _too_soon(key, seconds=25):
    """Was this field answered a moment ago?

    Some controls cannot be read back reliably, and without this they are
    re-answered on every pass -- which reopens dropdowns under the user.

    Only an answer counts. Stamping a field merely for being looked at meant
    that anything unreachable on the first pass -- a date box Workday had just
    rebuilt -- was then barred for the next twenty-five seconds, while the
    passes meant to catch it ran a second and a half apart. The retries could
    never do anything.
    """
    import time
    last = _RECENTLY_FILLED.get(key, 0)
    return (time.time() - last) < seconds


def _mark_answered(key):
    """Record that a field has just been answered."""
    import time
    _RECENTLY_FILLED[key] = time.time()


# Wording that makes a tick an assertion by you rather than a fact about you.
CONSENT = re.compile(
    r"\bi\s+(agree|consent|certify|acknowledg|authoriz|confirm|declare)|"
    r"terms\s+(and|&)\s+conditions|privacy\s+(policy|notice)|"
    r"\bconsent\b|\bcertif|\backnowledg|\battest", re.I)


# Which answer to a question of agreement means yes.
AFFIRMATIVE = re.compile(r"^(yes|y|i\s+(agree|certify|consent|acknowledg|"
                         r"confirm|do)|agree|accept|true)\b", re.I)


def radio_groups(frame):
    """The radio questions on the page, as {question: [(label, element)]}.

    A radio is not a field with a value, it is one option among several, so it
    cannot be answered on its own -- the question lives above the group and
    the answer is which member to click.
    """
    groups = {}
    for element in frame.query_selector_all("input[type=radio]"):
        try:
            if not element.is_visible() or not element.is_enabled():
                continue
            name = (element.get_attribute("name") or
                    element.get_attribute("data-automation-id") or "")
            question = frame.evaluate("""el => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const set = el.closest('fieldset');
                if (set) {
                    const legend = set.querySelector('legend');
                    if (legend) return clean(legend.innerText);
                }
                const group = el.closest('[role=radiogroup], [role=group]');
                if (group) {
                    const by = group.getAttribute('aria-labelledby');
                    if (by) {
                        const node = document.getElementById(by);
                        if (node) return clean(node.innerText);
                    }
                    const aria = group.getAttribute('aria-label');
                    if (aria) return clean(aria);
                }
                return '';
            }""", element)
            question = formfill.normalise(question or "")
            if not question:
                question = formfill.normalise(section_for(frame, element))
            answer = formfill.normalise(label_for(frame, element))
            groups.setdefault(question or name, []).append((answer, element))
        except Exception:
            continue
    return groups


def fill_choices(frame, profile, dry_run, filled, skipped):
    """Answer the radio questions and tick the factual checkboxes.

    Anything worded as your own assertion -- agreeing to terms, certifying
    the form is true -- is answered only when your profile says to, and is
    always listed in what was filled so you see it before submitting. You sign
    in and press submit yourself, so the assertion is still yours at the moment
    it counts.
    """
    agree = str(profile.get("accept_agreements") or "").strip().lower() in (
        "yes", "true", "y", "1", "on")
    for question, members in radio_groups(frame).items():
        options = [answer for answer, _ in members if answer]
        if not options:
            continue
        already = False
        for _, element in members:
            try:
                if element.is_checked():
                    already = True
                    break
            except Exception:
                pass
        if already:
            continue
        if CONSENT.search(question or ""):
            if not agree:
                skipped.append((question, "an assertion of yours -- answer it "
                                          "yourself"))
                continue
            affirmative = None
            for option in options:
                if AFFIRMATIVE.match(option.strip()):
                    affirmative = option
                    break
            if affirmative is None:
                skipped.append((question, "cannot tell which answer agrees"))
                continue
            for answer, element in members:
                if answer != affirmative:
                    continue
                if not dry_run:
                    try:
                        element.check()
                    except Exception:
                        try:
                            element.click()
                        except Exception:
                            break
                filled.append((question, affirmative + "  (your agreement)"))
                break
            continue
        choice = formfill.choose_option(question, options, profile,
                                        question, "", 0)
        if choice is None:
            skipped.append((question, "no confident match among: " +
                            ", ".join(o[:20] for o in options[:5])))
            continue
        for answer, element in members:
            if answer != choice:
                continue
            if not dry_run:
                try:
                    element.check()
                except Exception:
                    try:
                        element.click()
                    except Exception:
                        break
            filled.append((question, choice))
            break

    for element in frame.query_selector_all("input[type=checkbox]"):
        try:
            if not element.is_visible() or not element.is_enabled():
                continue
            if element.is_checked():
                continue
            label = formfill.normalise(label_for(frame, element))
            if not label or names_lib.is_preferred_toggle(label):
                continue
            if CONSENT.search(label):
                if not agree:
                    skipped.append((label, "an assertion of yours -- tick it "
                                           "yourself"))
                    continue
                if not dry_run:
                    element.check()
                filled.append((label, "ticked  (your agreement)"))
                continue
            wanted = formfill.value_for(label, profile, "", "", 0)
            if wanted is None:
                continue
            if str(wanted).strip().lower() not in ("yes", "true", "y", "on",
                                                   "checked", "1"):
                continue
            if not dry_run:
                element.check()
            filled.append((label, "ticked"))
        except Exception:
            continue


def fill(page, profile, dry_run=False, open_locations=None, company="",
         hq_table=None):
    filled, skipped, credentials = [], [], []
    frames = form_frames(page)
    if not frames:
        return filled, skipped, credentials

    frame = frames[0]
    seen_counts = {}
    entry_order = {}
    file_slots = 0
    step = step_of(frames) or page.url.split("?")[0]

    # Workday's repeated sections start empty. Press Add first, or there are
    # no fields on the page to fill.
    # One-time inventory of every control on the page, so a field that is
    # never filled can be told apart from one that is never seen.
    saved = snapshot_page(page, frames)
    if saved:
        print("   page markup saved: %s" % saved)

    global _LISTED_PAGES
    try:
        sig = tuple(sorted(formfill.normalise(label_for(frame, el))
                           for el in controls(frame)))
        if sig and sig not in _LISTED_PAGES:
            _LISTED_PAGES.add(sig)
            print("   controls Gary can see (%d):" % len(sig))
            for lab in sig:
                print("      %r" % (lab[:70] or "(no label)"))
    except Exception:
        pass

    fill_choices(frame, profile, dry_run, filled, skipped)

    opened = open_entry_sections(frame, profile, dry_run, log=print)
    for block, what in opened:
        filled.append(("Add %s" % block, what))

    # Read every label first. A plain "First Name" means the legal name on a
    # form that has a preferred-name field elsewhere, and the name you go by on
    # a form that hasn't -- so it cannot be answered field by field.
    all_labels = []
    for element in controls(frame):
        try:
            all_labels.append(formfill.normalise(label_for(frame, element)))
        except Exception:
            continue

    # Tick whatever reveals the preferred-name boxes, then look again: those
    # fields do not exist in the DOM until it is ticked.
    if not names_lib.form_uses_legal(all_labels):
        toggled = False
        for element in frame.query_selector_all(
                "input[type=checkbox], input[type=radio]"):
            try:
                if not element.is_visible():
                    continue
                label = formfill.normalise(label_for(frame, element))
                if names_lib.is_preferred_toggle(label) and not element.is_checked():
                    if not dry_run:
                        element.check()
                        frame.wait_for_timeout(600)
                    filled.append((label, "ticked, to enter a preferred name"))
                    toggled = True
            except Exception:
                continue
        if toggled:
            all_labels = []
            for element in controls(frame):
                try:
                    all_labels.append(formfill.normalise(label_for(frame, element)))
                except Exception:
                    continue
    if looks_like_login(frame):
        print("\nThis is a sign-in or account-creation form, so nothing was "
              "filled.\nSign in yourself, then re-run on the application form.")
        return filled, skipped, credentials

    for element in controls(frame):
        try:
            kind_probe = (element.get_attribute("type") or "").lower()
            if kind_probe != "file" and (not element.is_visible()
                                         or not element.is_enabled()):
                continue
            kind = (element.get_attribute("type") or "").lower()
            tag = element.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue

        if tag == "button":
            # CONTROL_SELECTOR only admits buttons that carry a popup or a
            # "Select One" label, so reaching here means a dropdown, whatever
            # its type attribute says.
            pass
        elif kind in ("hidden", "submit", "button", "checkbox", "radio"):
            continue

        label = formfill.normalise(label_for(frame, element))
        _ident_early = identity_of(frame, element)
        field_key = mark_of(frame, element) or "%s|%s|%s" % (
            page.url, label, _ident_early)
        if STATUS_TEXT.match(label or ""):
            # The widget described itself; look to its heading instead.
            label = formfill.normalise(section_for(frame, element)) or label
        if tag == "button":
            # "Degree M.S" is the question and the answer in one string. Keep
            # only the question, so the field keeps its identity once answered.
            state = button_state(frame, element)
            if state and state.get("question"):
                label = formfill.normalise(state["question"])
        section = formfill.normalise(section_for(frame, element))
        ident = identity_of(frame, element)
        if formfill.is_page_furniture(label, ident):
            continue
        # Count repeats on an id with its entry number removed, or
        # workExperience6/7 look like two different questions.
        base = formfill.answer_key(section, label,
                                   formfill.base_identity(ident))
        block = formfill.block_of(section, ident, label)
        # A bare "Month" or "Year" cannot be placed from its own label, and
        # block_of falls back to returning the section -- "from", "to" -- which
        # is not a block at all. The container Workday puts the entry in knows
        # both which block it is and which entry.
        placed = block_of_element(frame, element)
        if placed:
            block, container = placed
            order = entry_order.setdefault(block, [])
            if container not in order:
                order.append(container)
            entry = order.index(container) + 1
        elif block in ("education", "work history"):
            counter = (block, base)
            seen_counts[counter] = seen_counts.get(counter, 0) + 1
            entry = seen_counts[counter]
        else:
            entry = 0
        if block not in ("education", "work history"):
            block = formfill.block_of(section, ident, label)

        if TRACE.match(label or ""):
            try:
                current = widget_value(frame, element)
            except Exception:
                current = "?"
            print("   trace %-15s sec=%-18s block=%-13s entry=%s "
                  "holds=%-10s dated=%-8s generic=%s"
                  % (label[:15], repr(section)[:18], repr(block)[:13], entry,
                     repr(current)[:10],
                     repr(formfill.entry_date(label, section, profile,
                                              block, entry))[:8],
                     repr(formfill.value_for(label, profile, section,
                                             ident, entry))[:12]))

        # A password field is never filled, whatever it is labelled.
        if kind == "password" or formfill.is_credential(label):
            credentials.append(label or "(unlabelled password field)")
            continue

        if kind == "file":
            file_slots += 1
            # A hidden input still accepts a file; requiring visibility means
            # the resume is never attached.
            # Greenhouse labels both file inputs "Attach"; the first is the
            # resume and the second the cover letter. Sending the resume twice
            # looks careless to an employer.
            if "cover" in label.lower():
                which = "cover_letter"
            elif "resume" in label.lower() or "cv" in label.lower():
                which = "resume"
            else:
                which = "resume" if file_slots == 1 else "cover_letter"
            path = os.path.expanduser(str(profile.get(which) or ""))
            if path and os.path.exists(path):
                if field_key in _UNREADABLE_FILLED:
                    continue
                if not dry_run:
                    element.set_input_files(path)
                    # A file input never reports its value back, so without
                    # this the resume is attached again every few seconds.
                    _UNREADABLE_FILLED.add(field_key)
                filled.append((label or which, os.path.basename(path)))
            elif path:
                skipped.append((label or which, "file not found: %s" % path))
            continue

        # Everything below this point can write to the form, so the limits
        # apply from here. They used to sit further down, past the branch that
        # handles Workday's dropdowns -- which is every dropdown on the page,
        # so nothing that mattered was ever bounded by them.
        try:
            if (widget_value(frame, element) or "").strip():
                continue
        except Exception:
            pass
        if field_key in _UNREADABLE_FILLED or field_key in _GAVE_UP:
            continue
        if _WRITES.get(field_key, 0) >= MAX_WRITES:
            _GAVE_UP.add(field_key)
            skipped.append((label, "left alone after %d attempts -- it did "
                                   "not hold the answer" % MAX_WRITES))
            continue
        if _too_soon(field_key):
            continue

        if tag == "select":
            options = element.evaluate(
                "el => Array.from(el.options).map(o => o.textContent.trim())")

            # "Which office are you interested in?" follows its own rule:
            # every open location if several may be chosen, otherwise the US
            # headquarters when the role is open there, otherwise blank.
            if location_lib.is_location_question(label):
                multiple = bool(element.evaluate("el => el.multiple"))
                picks = location_lib.answer(options, open_locations, company,
                                            hq_table, multiple)
                if picks:
                    if not dry_run:
                        if multiple:
                            element.select_option(label=picks)
                        else:
                            element.select_option(label=picks[0])
                    filled.append((label, ", ".join(picks)))
                else:
                    skipped.append((label, "no location Gary can be sure of "
                                           "-- choose it yourself"))
                continue
            choice = formfill.choose_option(label, options, profile, section,
                                            ident, entry)
            if choice:
                if not dry_run:
                    _WRITES[field_key] = _WRITES.get(field_key, 0) + 1
                    _mark_answered(field_key)
                    element.select_option(label=choice)
                filled.append((label, choice))
            else:
                skipped.append((label, "no confident match -- pick it yourself"))
            continue

        # A typeahead combobox: options only exist once it is opened.
        aria_label = (element.get_attribute("aria-label") or "").lower()
        is_combo = (element.get_attribute("role") == "combobox"
                    or element.get_attribute("aria-haspopup") in ("true", "listbox")
                    or (tag == "button" and "select one" in aria_label))
        if is_combo and tag != "select":
            if not dry_run:
                _WRITES[field_key] = _WRITES.get(field_key, 0) + 1
                _mark_answered(field_key)
            options = combobox_options(frame, element)
            if location_lib.is_location_question(label):
                picks = location_lib.answer(options, open_locations, company,
                                            hq_table, multiple=False)
                choice = picks[0] if picks else None
                reason = "no location Gary can be sure of -- choose it yourself"
            else:
                choice = formfill.choose_option(label, options, profile,
                                                section, ident, entry)
                reason = "no confident match -- pick it yourself"
            if choice and not dry_run and choose_from_combobox(frame, element, choice):
                filled.append((label, choice))
                # If it still reads as empty, remember it as done.
                try:
                    if not (widget_value(frame, element) or "").strip():
                        _UNREADABLE_FILLED.add(field_key)
                except Exception:
                    _UNREADABLE_FILLED.add(field_key)
            elif choice and dry_run:
                filled.append((label, choice))
            else:
                close_combobox(frame)
                # Say what was on offer. Guessing at an employer's wording is
                # what has cost the most time here.
                if options:
                    shown = ", ".join(str(o)[:28] for o in options[:8])
                    if len(options) > 8:
                        shown += ", ... (%d total)" % len(options)
                    reason = "%s | offered: %s" % (reason, shown)
                skipped.append((label, reason))
            continue

        # Names follow their own rule, decided by the whole form.
        value = names_lib.name_for(label, profile, all_labels, section, ident)
        if value is None:
            value = formfill.entry_date(label, section, profile, block, entry)
        if value is None:
            value = formfill.value_for(label, profile, section, ident, entry)
        if value:
            if not dry_run:
                _WRITES[field_key] = _WRITES.get(field_key, 0) + 1
                _mark_answered(field_key)
                try:
                    close_combobox(frame)
                    element.fill(value)
                    # If a list appeared, the typing was only a search and the
                    # answer is not recorded until an option is clicked.
                    chosen = commit_typeahead(frame, element, value)
                    if chosen:
                        value = chosen
                    elif chosen == "":
                        # A list appeared and did not hold the answer, so try
                        # what you said to fall back to. None of this applies
                        # to an ordinary text box, which offers no list.
                        for spare in formfill.fallbacks_for(
                                label, profile, section, ident, entry):
                            element.fill(spare)
                            chosen = commit_typeahead(frame, element, spare)
                            if chosen:
                                value = chosen
                                break
                        else:
                            # Leaving the query text behind would look filled
                            # and submit blank.
                            element.fill("")
                            close_combobox(frame)
                            skipped.append(
                                (label, "offered no option matching %r" % value))
                            continue
                except Exception:
                    # Not a text box after all -- Workday styles several
                    # dropdowns as plain buttons with no role and no
                    # aria-haspopup, so they only reveal themselves by
                    # refusing to be typed into. Treat it as a dropdown.
                    options = combobox_options(frame, element)
                    choice = formfill.choose_option(label, options, profile,
                                                    section, ident, entry)
                    if choice and choose_from_combobox(frame, element, choice):
                        filled.append((label, choice))
                        _UNREADABLE_FILLED.add(field_key)
                    else:
                        close_combobox(frame)
                        why = "not a text field; "
                        if options:
                            why += "offered: " + ", ".join(
                                str(o)[:24] for o in options[:6])
                            if len(options) > 6:
                                why += ", ... (%d)" % len(options)
                        else:
                            why += "no options readable"
                        skipped.append((label, why))
                    continue
                try:
                    if not (widget_value(frame, element) or "").strip():
                        _UNREADABLE_FILLED.add(field_key)
                except Exception:
                    _UNREADABLE_FILLED.add(field_key)
            filled.append((label, value))
        elif label:
            skipped.append((label, "not in your profile"))

    if filled:
        snapshot_page(page, frames)
    return filled, skipped, credentials


def report(filled, skipped, credentials, page, frame=None):
    print("\n--- filled %d field(s) ---" % len(filled))
    for label, value in filled:
        print("   %-42s %s" % (label[:42], str(value)[:44]))

    if skipped:
        print("\n--- left for you (%d) ---" % len(skipped))
        for label, why in skipped:
            print("   %-42s %s" % (label[:42], why))

    if credentials:
        print("\n--- not touched: credential fields ---")
        for label in credentials:
            print("   %s" % label[:60])

    scope = frame or page
    buttons = []
    for el in scope.query_selector_all("button, input[type=submit]"):
        try:
            text = (el.inner_text() or el.get_attribute("value") or "").strip()
        except Exception:
            continue
        if text and any(w in text.lower() for w in SUBMIT_WORDS):
            buttons.append(text)
    if buttons:
        print("\nSubmit control on this page: %r -- left for you to click."
              % buttons[0])

    # A CAPTCHA is a deliberate wall against automation. Solving one is not
    # something this tool will attempt.
    if any("recaptcha" in (f.url or "").lower() or "captcha" in (f.url or "").lower()
           for f in page.frames):
        print("This form is behind a CAPTCHA, so it has to be finished by hand.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="the application page")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be filled, change nothing")
    parser.add_argument("--locations",
                        help="where the role is open, e.g. "
                             "\"Chicago, IL; New York, NY\". Used to answer "
                             "office-preference questions.")
    parser.add_argument("--watch", action="store_true",
                        help="keep the window open and fill each page as you "
                             "reach it. Needed on Workday, where the form only "
                             "appears after you sign in and click Apply.")
    parser.add_argument("--poll-seconds", type=int, default=3)
    parser.add_argument("--company", default="",
                        help="the employer, for looking up their US "
                             "headquarters when only one office may be chosen")
    parser.add_argument("--wait-ms", type=int, default=6000)
    parser.add_argument("--session", default=os.path.join(ROOT, ".browser-session"),
                        help="directory holding the browser profile, so a "
                             "Workday sign-in survives between runs. You log "
                             "in yourself; nothing is typed for you.")
    parser.add_argument("--no-session", action="store_true",
                        help="use a throwaway browser profile instead")
    parser.add_argument("--headless", action="store_true",
                        help="inspect a form without opening a window; only "
                             "sensible with --dry-run, since you cannot review "
                             "or submit a form you cannot see")
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    if profile is None:
        return 1

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        headless = args.headless and args.dry_run
        browser, ctx = open_browser(p, headless, None if args.no_session
                                    else args.session)
        ctx.add_init_script(STEALTH)
        # Mark this window, so there is never any doubt which one Gary is
        # filling. Several rounds were lost to working in a different window
        # from the one being watched.
        ctx.add_init_script("""
            (() => {
              const show = () => {
                if (document.getElementById('gary-banner')) return;
                if (!document.body) return;
                const bar = document.createElement('div');
                bar.id = 'gary-banner';
                bar.textContent = 'GARY IS FILLING THIS WINDOW';
                bar.style.cssText = [
                  'position:fixed', 'top:0', 'left:0', 'right:0',
                  'z-index:2147483647', 'background:#1d4ed8', 'color:#fff',
                  'font:600 12px/28px system-ui,sans-serif',
                  'text-align:center', 'letter-spacing:.08em',
                  'pointer-events:none'].join(';');
                document.body.appendChild(bar);
              };
              if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', show);
              } else { show(); }
              setInterval(show, 2000);
            })();
        """)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("opening %s" % args.url)
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait_ms)

        frames = form_frames(page)
        if not frames:
            print("No form fields found. The application may open behind an "
                  "'Apply' button -- click through to it, then re-run on that "
                  "page.")
        hq_table = {}
        if os.path.exists(HEADQUARTERS):
            with open(HEADQUARTERS) as fh:
                hq_table = json.load(fh)
        open_locations = location_lib.split_locations(args.locations or "")

        if args.watch:
            # Workday builds the application over several pages that only
            # exist after signing in, so a single pass on load fills nothing.
            print("\nSign in and click Apply. Each page is filled as you reach")
            print("it -- check every field, and submit it yourself.")
            print("Close the window when you're done.\n")
            print("To make Gary stop touching the form without closing this")
            print("window, create the file %s" % PAUSE_FILE)
            print("and delete it to resume.\n")
            reported_buttons = set()
            passes = {}
            mishaps = 0
            paused = False
            while True:
                try:
                    current = ctx.pages[-1] if ctx.pages else None
                    if current is None or current.is_closed():
                        break
                    if os.path.exists(PAUSE_FILE):
                        if not paused:
                            paused = True
                            print("\nPaused -- the window is yours. Delete "
                                  "%s to resume." % PAUSE_FILE)
                        current.wait_for_timeout(1500)
                        continue
                    if paused:
                        paused = False
                        print("\nResumed.")
                    frames = form_frames(current)
                    if frames and not looks_like_login(frames[0]):
                        # Only work when the page has actually changed. A form
                        # is filled once, not scrubbed over and over: any
                        # mistake in matching a field then turns into the
                        # thing being rewritten under the user's hands, which
                        # is far worse than the field being left alone.
                        shape = page_shape(frames)
                        done = passes.get(shape, 0)
                        if done >= PASSES_PER_SHAPE:
                            current.wait_for_timeout(1500)
                            continue
                        passes[shape] = done + 1
                        f, sk, cr = fill(current, profile, args.dry_run,
                                         open_locations, args.company,
                                         hq_table)
                        if not f:
                            try:
                                here = tuple(sorted(
                                    formfill.normalise(label_for(frames[0], el))
                                    for el in controls(frames[0])))
                                heads = frames[0].evaluate(
                                    "() => Array.from(document.querySelectorAll("
                                    "'h1,h2,h3')).slice(0,6)"
                                    ".map(h => (h.innerText||'').trim()).join(' | ')")
                                here = (here, heads[:120])
                            except Exception:
                                here = (current.url,)
                            if here not in reported_buttons:
                                reported_buttons.add(here)
                                try:
                                    buttons = frames[0].evaluate("""() =>
                                        Array.from(document.querySelectorAll(
                                          'button,[role=button],a[role=button]'))
                                        .map(b => ((b.innerText||'').trim() + ' | ' +
                                                   (b.getAttribute('aria-label')||'') + ' | ' +
                                                   (b.getAttribute('data-automation-id')||'')))
                                        .filter(t => t.replace(/[| ]/g,''))
                                        .slice(0, 40)""")
                                    print("--- no fields filled ---")
                                    print("   url      : %s" % current.url[:100])
                                    print("   headings : %s" % frames[0].evaluate(
                                        "() => Array.from(document.querySelectorAll("
                                        "'h1,h2,h3')).slice(0,6)"
                                        ".map(h => (h.innerText||'').trim())"
                                        ".filter(Boolean).join(' | ')")[:150])
                                    print("   controls : %d" % len(controls(frames[0])))
                                    for b in buttons:
                                        print("   button: %s" % b[:90])
                                except Exception:
                                    pass
                        else:
                            print("--- filled %d ---" % len(f))
                            for lab, val in f:
                                print("   %-36s %s" % (lab[:36], str(val)[:36]))
                            left = [x for x in sk if x[0] not in {y[0] for y in f}]
                            # Print them all: truncating this hid the reason
                            # Degree was being rejected for several rounds.
                            for lab, why in left:
                                print("   %-34s (left: %s)" % (lab[:34], why[:170]))
                    mishaps = 0
                    current.wait_for_timeout(args.poll_seconds * 1000)
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    # Workday navigates constantly, which destroys the page's
                    # execution context mid-read. That is normal and must not
                    # close the window -- only a genuinely gone page should.
                    text = str(exc).lower()
                    if ("closed" in text or "crashed" in text
                            or "target page" in text):
                        break
                    mishaps += 1
                    if mishaps == 1 or mishaps % 20 == 0:
                        print("   (page busy: %s -- still watching)"
                              % type(exc).__name__)
                    if mishaps > 200:
                        print("   too many errors in a row; stopping")
                        break
                    try:
                        import time as _t
                        _t.sleep(args.poll_seconds)
                    except Exception:
                        pass

            print("\nWindow closed.")
            close_browser(browser, ctx)
            return 0

        filled, skipped, credentials = fill(page, profile, args.dry_run,
                                            open_locations, args.company,
                                            hq_table)
        report(filled, skipped, credentials, page,
               frames[0] if frames else None)

        if not headless:
            print("\nThe browser is open and the form is filled in.")
            print("Check every field, then submit it yourself. Close the")
            print("window when you're done.")
            if sys.stdin.isatty():
                print("(Or press Enter here to close it.)")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
            else:
                # Launched without a terminal: wait for the window instead of
                # a keypress, so the form stays up while you work through it.
                while True:
                    try:
                        current = ctx.pages[-1] if ctx.pages else None
                        if current is None or current.is_closed():
                            break
                        current.wait_for_timeout(3000)
                    except Exception:
                        break
                print("Window closed.")
        close_browser(browser, ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
