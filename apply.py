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
from watcher import formfill
from watcher import infer  # noqa: E402
from watcher import judge  # noqa: E402
from watcher import learning  # noqa: E402
from watcher import lists  # noqa: E402
from watcher import options as option_reading  # noqa: E402
from watcher import location as location_lib  # noqa: E402
from watcher import pay  # noqa: E402
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
            # No single action may block the pass. Workday hides controls
            # behind display elements that never become actionable, and the
            # default wait is thirty seconds each -- one such field stalled a
            # whole page for minutes and looked like Gary had died.
            ctx.set_default_timeout(4000)
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
    ctx.set_default_timeout(4000)
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
                    // React menus commit on mousedown; a click alone leaves
                    // them open with nothing chosen.
                    for (const kind of ['pointerdown', 'mousedown', 'mouseup',
                                        'click']) {
                        o.dispatchEvent(new MouseEvent(kind, {
                            bubbles: true, cancelable: true, view: window,
                            button: 0,
                        }));
                    }
                    return true;
                }
            }
            return false;
        }""", [element, wanted]))
    except Exception:
        return False


def gather_options(frame, element, queries, cap=60):
    """Everything the list will show, before deciding anything.

    A search box is a list you cannot see all of. Guessing at an answer and
    checking whether the search found it means a wrong guess looks exactly
    like an absent answer -- which is how a school spelled "University of
    Texas - Austin" went unanswered while the profile held the same school
    under a different spelling.

    So the options are collected first: what the list shows when opened, and
    what each query brings back. Deciding happens afterwards, over everything
    seen, and each option is remembered with the query that surfaced it so it
    can be found again when the time comes to click it.
    """
    seen = {}

    def collect(query):
        try:
            found = frame.evaluate("""el => {
                const id = el.getAttribute('aria-controls') ||
                           el.getAttribute('aria-owns');
                let root = id ? document.getElementById(id) : null;
                if (!root) {
                    const open = Array.from(document.querySelectorAll(
                        '[data-automation-id=activeListContainer],[role=listbox]'
                    )).filter(b => b.offsetParent !== null);
                    root = open.length ? open[open.length - 1] : null;
                }
                if (!root) return [];
                return Array.from(root.querySelectorAll(
                    '[role=option], [class*=option], li'))
                    .filter(o => o.offsetParent !== null)
                    .map(o => (o.innerText || '').trim())
                    .filter(Boolean);
            }""", element)
        except Exception:
            return
        for text in found or []:
            if text not in seen and len(seen) < cap:
                seen[text] = query

    # What it shows unprompted.
    try:
        element.click(timeout=2000)
        frame.wait_for_timeout(500)
    except Exception:
        pass
    collect(None)

    for query in queries:
        if not query:
            continue
        if not type_into(frame, element, query):
            continue
        frame.wait_for_timeout(700)
        collect(query)
        if len(seen) >= cap:
            break
    return seen


def shorter_queries(text):
    """Progressively less of a name, for a search that found nothing.

    A search matches the letters it is given. "The University of Texas at
    Austin" finds nothing on a list that spells it "University of Texas -
    Austin", and an empty list leaves nothing to choose between. Dropping the
    article, then the tail, puts the candidates on the table so something can
    be chosen at all.
    """
    words = [w for w in str(text or "").split() if w]
    if len(words) < 2:
        return []
    out = []
    if words[0].lower() in ("the", "a", "an"):
        out.append(" ".join(words[1:]))
    # The first distinctive words: enough to search on, short enough to match
    # a differently written tail.
    for keep in (3, 2):
        if len(words) > keep:
            trimmed = words[1:] if words[0].lower() in ("the", "a", "an") \
                else words
            candidate = " ".join(trimmed[:keep])
            if candidate and candidate not in out:
                out.append(candidate)
    return [q for q in out if q.lower() != str(text).lower()]


def choice_took(frame, element, chosen):
    """Did the page actually keep what was chosen?

    A widget that shows its selection as text rather than as an input value
    cannot be asked through the input, and a click it ignored leaves no trace
    there either. What settles it is whether the words appear anywhere in the
    block the control belongs to.
    """
    try:
        return bool(frame.evaluate("""([el, chosen]) => {
            const wanted = String(chosen).trim().toLowerCase();
            if (!wanted) return false;
            // A search box holds the query, not the answer, and the query is
            // usually the answer's own words -- so its value proves nothing.
            // Reading it as a commitment is how a school was confirmed while
            // the menu sat open and nothing had been chosen.
            const searching = el.getAttribute('role') === 'combobox' ||
                              el.getAttribute('aria-haspopup') ||
                              el.getAttribute('aria-autocomplete');
            if (!searching &&
                (el.value || '').trim().toLowerCase() === wanted) return true;
            let scope = el;
            for (let hop = 0; hop < 5 && scope; hop++) {
                scope = scope.parentElement;
                if (!scope) break;
                // An open menu contains the words too. Reading them back as a
                // committed choice is how a school was confirmed filled while
                // nothing had been chosen at all.
                const copy = scope.cloneNode(true);
                copy.querySelectorAll(
                    '[role=listbox], [role=option], [class*=menu]'
                ).forEach(n => n.remove());
                const shown = (copy.innerText || copy.textContent || '')
                    .trim().toLowerCase();
                if (shown.includes(wanted)) return true;
            }
            return false;
        }""", [element, chosen]))
    except Exception:
        return False


def type_into(frame, element, text):
    """Type into a control the way a person does.

    Setting a value and firing an input event is enough for a plain box, and
    nothing at all to a React widget: it keeps its own state, ignores the
    write, and never opens its menu. Greenhouse's location and school fields
    are these, and Gary typed into nothing, saw no list, and reported the
    text as filled -- a false success, which is worse than a blank.

    Keystrokes reach any control, because they are what a keyboard sends.
    """
    keyboard = getattr(frame, "keyboard", None)
    if keyboard is None:
        keyboard = frame.page.keyboard
    try:
        focused = frame.evaluate("""el => {
            el.focus();
            if ('value' in el) {
                el.select && el.select();
            }
            return document.activeElement === el;
        }""", element)
        if not focused:
            element.click(timeout=2000)
        keyboard.press("Meta+A")
        keyboard.press("Delete")
        keyboard.type(str(text), delay=30)
        return True
    except Exception:
        return False


def commit_typeahead(frame, element, wanted):
    """Settle a search box that is really a dropdown.

    Workday's Field of Study and School boxes accept typing, but the text is
    only a query: unless one of the offered options is clicked, the box empties
    the moment it loses focus. Typing the answer therefore looks like success
    and leaves the field blank. Returns the option actually chosen, or "".
    """
    global _LAST_OFFERED
    seen = []
    _LAST_OFFERED = seen
    try:
        frame.wait_for_timeout(700)
        first = _commit_once(frame, element, wanted, seen)
        if first:
            return first
        # A list still arriving is indistinguishable from no list at all, and
        # that is exactly when waiting helps -- returning early here meant the
        # retry could never fire for the case it was written for.
        frame.wait_for_timeout(900)
        second = _commit_once(frame, element, wanted, seen)
        if second:
            return second
        # "" only if a list was genuinely seen and held nothing matching.
        return "" if "" in (first, second) else None
    except Exception:
        return None


def _commit_once(frame, element, wanted, seen):
    """One attempt at committing, recording what was on offer."""
    try:
        result = frame.evaluate("""([el, wanted]) => {
            // Is this a search box at all? Asked first, because the searches
            // below reach several levels up and will happily find a list
            // belonging to another question. An ordinary text field handed
            // such a list decided its answer was not on offer and cleared
            // what it had just typed -- that emptied name and address.
            const searchable =
                el.getAttribute('role') === 'combobox' ||
                el.getAttribute('aria-haspopup') ||
                el.getAttribute('aria-autocomplete') ||
                el.getAttribute('aria-controls') ||
                el.getAttribute('aria-owns') ||
                el.closest('[data-uxi-widget-type=multiselect],' +
                           '[data-automation-id=multiSelectContainer],' +
                           '[data-automation-id*=multiselect],' +
                           '[data-automation-id*=promptSearch]');
            if (!searchable) return null;

            const id = el.getAttribute('aria-controls') ||
                       el.getAttribute('aria-owns');
            let root = id ? document.getElementById(id) : null;
            if (!root) {
                let scope = el;
                for (let hop = 0; hop < 3 && scope; hop++) {
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

            // Institutions and employers are written many ways: "The
            // University of Texas at Austin", "University of Texas - Austin",
            // "UT Austin". Comparing spellings fails on all but one of them,
            // so what is compared is the words that identify the thing --
            // articles, connectors and punctuation dropped.
            const NOISE = new Set(['the', 'of', 'at', 'in', 'and', 'a', 'an',
                                   'for', 'de', 'la']);
            const words = t => String(t).toLowerCase()
                .replace(/[^a-z0-9]+/g, ' ').split(' ')
                .filter(w => w && !NOISE.has(w));
            const wantWords = words(want);
            const covers = (a, b) => b.length > 0 &&
                b.every(w => a.includes(w));
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
            if (!pick && wantWords.length) {
                // Every identifying word present, however the option spells
                // it. Exactly one option may qualify -- two would mean the
                // words do not identify anything on this list.
                const alike = options.filter(
                    o => covers(words(text(o)), wantWords));
                if (alike.length === 1) pick = alike[0];
                else if (!alike.length) {
                    const inside = options.filter(
                        o => covers(wantWords, words(text(o))));
                    if (inside.length === 1) pick = inside[0];
                }
            }
            // Anything else on the list is a different answer, not this one.
            if (!pick) return {offered: options.map(text).slice(0, 40)};
            const chosen = text(pick);
            // React widgets commit on mousedown, not on click: a plain
            // .click() leaves the menu open and nothing chosen, which is how
            // a school was reported filled while the page stayed empty.
            for (const kind of ['pointerdown', 'mousedown', 'mouseup',
                                'click']) {
                pick.dispatchEvent(new MouseEvent(kind, {
                    bubbles: true, cancelable: true, view: window, button: 0,
                }));
            }
            return chosen;
        }""", [element, wanted])
    except Exception:
        return None
    if isinstance(result, dict):
        for option in result.get("offered") or []:
            if option not in seen:
                seen.append(option)
        return ""
    return result


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


def whole_date_group(frame, element):
    """The Month/Day/Year inputs this one belongs to, if it is a full date.

    Workday builds a date as three spin controls in one wrapper that advance
    focus as digits arrive. Filling them one at a time makes each entry push
    the next along, so a month of "5" ends up as a year of 2005. A full date
    has to be typed as one sequence, the way a person enters it.

    Only groups with a day are treated this way. The Month/Year pairs on
    education and work entries fill correctly one at a time, and are left as
    they are.
    """
    try:
        return frame.evaluate("""el => {
            // Only a date section belongs to a date. Workday wraps the whole
            // questionnaire in a role=group, so accepting any group made
            // every control on the page look like part of the date.
            const own = (el.getAttribute('data-automation-id') || '') + ' ' +
                        (el.getAttribute('aria-label') || '');
            if (!/dateSection|^\s*(Month|Day|Year)\s*$/i.test(own) &&
                !/^(Month|Day|Year)$/i.test(
                    (el.getAttribute('aria-label') || '').trim())) {
                return null;
            }
            const wrap = el.closest('[data-automation-id=dateInputWrapper]');
            if (!wrap) return null;
            const part = name => {
                const found = wrap.querySelector(
                    `[data-automation-id=dateSection${name}-input],` +
                    `input[aria-label="${name}"]`);
                return found ? found.id || '' : '';
            };
            const day = part('Day');
            if (!day) return null;   // month and year only: filled singly
            return {month: part('Month'), day: day, year: part('Year')};
        }""", element)
    except Exception:
        return None


def type_whole_date(frame, group, month, day, year):
    """Type a date into a Workday date group, section by section."""
    order = (("month", month), ("day", day), ("year", year))
    for name, value in order:
        if not value or not group.get(name):
            return False

    # These inputs carry tabindex="-1" and sit behind a display element, so
    # they never become "actionable": clicking or typing through the usual
    # path waits its full timeout on every one and the pass stalls for
    # minutes. Focus is set directly and the keys are sent to the page, which
    # is what typing into a focused field actually means.
    for name, value in order:
        digits = str(value)
        if name in ("month", "day"):
            digits = digits.zfill(2)
        focused = frame.evaluate("""id => {
            const el = document.getElementById(id);
            if (!el) return false;
            el.focus();
            return document.activeElement === el;
        }""", group[name])
        if not focused:
            return False
        # A Frame reaches its keyboard through the page; a Page has one.
        keyboard = getattr(frame, "keyboard", None)
        if keyboard is None:
            keyboard = frame.page.keyboard
        keyboard.type(digits, delay=40)
        frame.wait_for_timeout(100)
    return True


def pay_from_posting(ctx, url, profile):
    """Read the advertised pay from the posting in a tab of its own.

    Workday restores a part-finished application, so opening the job's address
    can land straight in the form with the description never shown -- and the
    salary question, several pages in, then has nothing to work from. A
    separate tab reads the posting without disturbing the window being filled.
    """
    if profile.get("desired_salary") or not url:
        return False
    aside = None
    try:
        aside = ctx.new_page()
        aside.goto(url, wait_until="domcontentloaded", timeout=30000)
        aside.wait_for_timeout(2000)
        return read_advertised_pay(aside, profile)
    except Exception:
        return False
    finally:
        if aside is not None:
            try:
                aside.close()
            except Exception:
                pass


def read_advertised_pay(page, profile):
    """Read the pay the posting advertises, expanding the description first.

    Workday collapses a job description behind "Read More", so the page's text
    holds none of it -- including the compensation line the salary question
    later needs. The description is also gone by the time that question is
    asked, several pages further in, so it is read while it is still there.
    """
    if profile.get("desired_salary"):
        return True
    try:
        page.evaluate("""() => {
            for (const b of document.querySelectorAll(
                    'button,[role=button],a[role=button]')) {
                const t = ((b.innerText || '') + ' ' +
                           (b.getAttribute('data-automation-id') || ''))
                          .toLowerCase();
                if (/read\s*more|show\s*more|see\s*more|expand/.test(t)) {
                    b.click();
                }
            }
        }""")
        page.wait_for_timeout(600)
        # innerText omits whatever is hidden, and a collapsed description is
        # hidden -- which is exactly where the compensation line was. The
        # underlying text is read too, and whichever names a rate is used.
        described = page.evaluate("""() => [
            document.body.innerText || '',
            document.body.textContent || ''
        ]""")
    except Exception:
        return False
    wanted, why = None, None
    for text in described or []:
        wanted, why = pay.desired(text)
        if wanted:
            break
    if not wanted:
        return False
    profile["desired_salary"] = wanted
    profile["desired_salary_reason"] = why
    print("   advertised pay: asking %s (%s)" % (wanted, why))
    return True


# What Gary put in each field, and what question it was answering. Read back
# on later passes: a value that differs is the candidate's, and worth keeping.
_WROTE = {}
# Which documents have been attached in this session. A file input never
# reports what it holds, so nothing on the page can be asked.
_ATTACHED = set()
# Marks are handed out from here, never from the page, so no two controls in a
# session can share one.
_NEXT_MARK = 0
PROFILE_PATH = None
COMPANY = ""


def note_written(mark, question, value):
    """Remember what Gary put somewhere, so the candidate's edit stands out."""
    if mark:
        _WROTE[mark] = {"question": question or "",
                        "gary": " ".join(str(value or "").split())}


def learn_from_candidate(frame, profile):
    """Keep what the candidate typed where Gary could not, or was wrong.

    Gary leaves a field alone when nothing settles it, and the candidate fills
    it in. That answer is worth keeping -- employers ask the same things in
    different words, and a question answered by hand once should not need
    answering again. A value differing from what Gary wrote is theirs; a value
    matching it teaches nothing.
    """
    learned = []
    for element in controls(frame):
        try:
            if not element.is_visible():
                continue
            mark = mark_of(frame, element)
            seen = _WROTE.get(mark)
            if not seen:
                continue
            now = (widget_value(frame, element) or "").strip()
            if not now or now == seen["gary"]:
                seen.pop("settling", None)
                continue
            # Wait for the typing to stop. Reading a field the moment it
            # changes catches the first keystroke -- "N" of "N/A" -- and
            # records a letter as the answer. A value is only the
            # candidate's answer once it has stopped changing.
            if seen.get("settling") != now:
                seen["settling"] = now
                continue
            question = seen["question"] or formfill.normalise(
                field_question(frame, element)) or formfill.normalise(
                label_for(frame, element))
            if formfill.is_credential(question):
                continue
            # Which entry a field belongs to cannot be read off the page
            # reliably enough to learn from -- asking the markup put a
            # question outside every entry inside one. The questions a form
            # repeats per entry are named instead, in learning.py.
            if learning.remember(profile, PROFILE_PATH, question, now,
                                 corrected=bool(seen["gary"]),
                                 company=COMPANY):
                learned.append((question, now, bool(seen["gary"])))
                seen["gary"] = now
        except Exception:
            continue
    for question, value, corrected in learned:
        print("   learned: %s = %r  (%s)"
              % (question[:52], value[:40],
                 "you corrected Gary" if corrected else "you filled it in"))
    return learned


def note_inference(label, profile, value, reasoned=None):
    """Say when an answer was worked out rather than read off.

    The candidate signs for the application, so anything derived has to be
    visible to them before they submit rather than after.
    """
    if reasoned and label in reasoned:
        return "%s   (worked out: %s)" % (value, reasoned[label])
    try:
        worked_out, why = infer.answer(label, profile)
    except Exception:
        return value
    if worked_out is None or str(worked_out).strip().lower() != \
            str(value).strip().lower():
        return value
    return "%s   (worked out: %s)" % (value, why)


def field_question(frame, element):
    """The question in the block of markup this control belongs to.

    Looking upward for a nearby heading finds whatever happens to be above,
    which on a page of questions is the previous question -- Gary was told a
    transcript upload was about relatives working at BRG, and sent a resume.
    The field's own container is unambiguous.
    """
    try:
        return frame.evaluate("""el => {
            const field = el.closest('[data-automation-id^=formField-]') ||
                          el.closest('fieldset');
            if (!field) return '';
            return (field.innerText || '').replace(/\s+/g, ' ').trim()
                   .slice(0, 300);
        }""", element) or ""
    except Exception:
        return ""


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
                    if (text && !GENERIC.test(text)) return text.slice(0, 300);
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
        # Nothing to learn from a blank page or a copy already on disk.
        if page.url.startswith(("about:", "file://", "data:")):
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

# What a search box last put on offer, for saying so when nothing matched.
_LAST_OFFERED = []

_RECENTLY_FILLED = {}
_UNREADABLE_FILLED = set()
_LISTED_PAGES = set()
_WRITES = {}
_GAVE_UP = set()
# Two attempts is enough for any field: one to answer it, one if the page
# rebuilt the control underneath. Beyond that something is wrong, and
# rewriting it forever churns the form under the user's hands.
MAX_WRITES = 2

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
    global _NEXT_MARK
    try:
        held = frame.evaluate(
            "el => el.getAttribute('data-gary-mark') || ''", element)
        if held:
            return held
        # Numbered from here rather than from the page, because a page counter
        # restarts on every load: the same mark then means one control on one
        # page and a different control on the next, and a field inherits
        # "already answered" from something it has nothing to do with.
        _NEXT_MARK += 1
        mark = "g%d" % _NEXT_MARK
        frame.evaluate("([el, mark]) => el.setAttribute('data-gary-mark', mark)",
                       [element, mark])
        return mark
    except Exception:
        return ""


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


# Answers that mean "tick this box".
_TICKED = ("yes", "true", "y", "on", "checked", "1")


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

    # A question answered by ticking one of several boxes. Asking each box
    # whether it should be ticked gets no answer, because the answer belongs
    # to the question -- "Asian" says nothing about a box labelled "White".
    # This is how race and ethnicity are asked, and nothing was ever ticked.
    groups = {}
    for element in frame.query_selector_all("input[type=checkbox]"):
        try:
            if not element.is_visible() or not element.is_enabled():
                continue
            box = frame.evaluate("""el => {
                const f = el.closest('[data-automation-id^=formField-]') ||
                          el.closest('fieldset');
                return f ? (f.getAttribute('data-automation-id') ||
                            f.getAttribute('id') || 'group') : '';
            }""", element)
        except Exception:
            continue
        if box:
            groups.setdefault(box, []).append(element)

    for members in groups.values():
        if len(members) < 2:
            continue
        try:
            if any(m.is_checked() for m in members):
                continue
        except Exception:
            continue
        labels = [formfill.normalise(label_for(frame, m)) for m in members]
        # An option carrying its own answer is ticked below, one box at a
        # time -- that is how "select all that apply" works. Only an answer
        # meaning "tick me" counts: every option of a disability question
        # contains the word disability, so each resolved to the answer for the
        # question as a whole, and the group was left to a path that could
        # only ever tick a box whose answer was yes.
        if any(str(formfill.value_for(text, profile, "", "", 0) or "")
               .strip().lower() in _TICKED for text in labels):
            continue
        question = formfill.normalise(field_question(frame, members[0]))
        for text in labels:
            question = question.replace(text, " ")
        question = " ".join(question.split())
        if not question:
            continue
        choice = formfill.choose_option(question, labels, profile,
                                        question, "", 0)
        if choice is None:
            skipped.append((question[:60], "no confident match among: " +
                            ", ".join(o[:24] for o in labels[:4])))
            continue
        for text, member in zip(labels, members):
            if text != choice:
                continue
            if not dry_run:
                member.check()
            filled.append((question[:60], choice))
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
            if str(wanted).strip().lower() not in _TICKED:
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
    reasoned = {}
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
        # The mark is numbered from one on every page load, so the same mark
        # on a later page is a different control. Keyed with the step it
        # belongs to, a field cannot inherit "already answered" from whatever
        # happened to be marked first somewhere else.
        field_key = "%s|%s" % (step, mark_of(frame, element)
                               or "%s|%s" % (label, _ident_early))
        if STATUS_TEXT.match(label or ""):
            # The widget described itself; look to its heading instead.
            label = formfill.normalise(section_for(frame, element)) or label
        if tag == "button":
            # "Degree M.S" is the question and the answer in one string. Keep
            # only the question, so the field keeps its identity once answered.
            state = button_state(frame, element)
            question = formfill.normalise((state or {}).get("question") or "")
            if question and not STATUS_TEXT.match(question):
                label = question
            elif STATUS_TEXT.match(label or ""):
                # Some dropdowns are called nothing but "Select One" -- the
                # whole of Workday's application-questions page is like this,
                # with the question sitting beside the control rather than
                # attached to it. Taking the placeholder as the question left
                # every one of them unanswerable.
                label = formfill.normalise(section_for(frame, element)) or label
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
            # What the employer asked for. A page may want a transcript or a
            # writing sample, and sending the resume because it is the file to
            # hand answers a question nobody asked.
            asked = "%s %s" % (label.lower(),
                               formfill.normalise(
                                   field_question(frame, element)
                                   or section_for(frame, element)).lower())
            if "transcript" in asked:
                which = "transcript"
            elif "cover" in asked:
                which = "cover_letter"
            elif "resume" in asked or "cv" in asked or "curriculum" in asked:
                which = "resume"
            elif "writing sample" in asked:
                which = "writing_sample"
            else:
                # Nothing in the wording says what this slot wants. Counting
                # slots does not settle it either: Greenhouse reveals its
                # cover-letter input only once Attach is clicked, so a later
                # pass sees a single file field again and calls it the first.
                # The resume goes in once and once only; a second unlabelled
                # slot is the candidate's to fill.
                which = "resume" if "resume" not in _ATTACHED else ""
            if not which:
                skipped.append((label or "attachment",
                                "a second attachment, and nothing says what it "
                                "should be -- attach it yourself"))
                continue
            path = os.path.expanduser(str(profile.get(which) or ""))
            if path and os.path.exists(path):
                if field_key in _UNREADABLE_FILLED:
                    continue
                if not dry_run:
                    element.set_input_files(path)
                    # A file input never reports its value back, so without
                    # this the resume is attached again every few seconds.
                    _UNREADABLE_FILLED.add(field_key)
                    _ATTACHED.add(which)
                filled.append((label or which, os.path.basename(path)))
            elif path:
                skipped.append((label or which, "file not found: %s" % path))
            else:
                skipped.append((label or which,
                                "no %s in your profile -- attach it yourself"
                                % which.replace("_", " ")))
            continue

        # A full date is typed as one sequence, or its sections push each
        # other along and the month lands in the year.
        group = whole_date_group(frame, element)
        if group:
            done_key = "date|%s" % group.get("year", "")
            if done_key in _UNREADABLE_FILLED:
                continue
            # Typing appends. A date already entered -- by an earlier pass, an
            # earlier session, or by hand -- becomes "20282028" if typed over.
            try:
                if frame.evaluate("""ids => ids.some(id => {
                        const el = id && document.getElementById(id);
                        return el && (el.value || '').trim() !== '';
                    })""", [group.get(n) for n in ("month", "day", "year")]):
                    _UNREADABLE_FILLED.add(done_key)
                    continue
            except Exception:
                pass
            asks = formfill.normalise(field_question(frame, element)) or section
            parts = {name: formfill.value_for(name.capitalize(), profile,
                                              asks, ident, entry)
                     for name in ("month", "day", "year")}
            if all(parts.values()):
                if _WRITES.get(done_key, 0) >= MAX_WRITES:
                    continue
                _WRITES[done_key] = _WRITES.get(done_key, 0) + 1
                if dry_run or type_whole_date(frame, group, parts["month"],
                                              parts["day"], parts["year"]):
                    filled.append((asks[:60] or label,
                        "%s/%s/%s" % (parts["month"], parts["day"],
                                      parts["year"])))
                    _UNREADABLE_FILLED.add(done_key)
                continue
            if not any(parts.values()):
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
        # Watch it even when nothing is written: a field Gary leaves alone is
        # exactly the one the candidate is about to answer by hand.
        note_written(field_key, label, "")
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
                # What you said about this particular question wins over the
                # general rule: the rule exists for offices you have not
                # spoken about, not to overrule the ones you have.
                stated = formfill.choose_option(label, options, profile,
                                                section, ident, entry)
                multiple = bool(element.evaluate("el => el.multiple"))
                picks = ([stated] if stated else
                         location_lib.answer(options, open_locations, company,
                                             hq_table, multiple,
                                             question=label))
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
            choice, working = lists.answer(options, profile)
            if choice is not None:
                reasoned[label] = working
            else:
                choice = formfill.choose_option(label, options, profile,
                                                section, ident, entry)
            if choice is None:
                choice, working = formfill.reasoned_option(label, options,
                                                           profile)
                if choice is not None:
                    reasoned[label] = working
            if choice is None:
                choice, working = judge.decide(label, options, profile)
                if choice is not None:
                    reasoned[label] = "%s (judged)" % (working or "judged from "
                                                       "your profile")
            if choice:
                if not dry_run:
                    _WRITES[field_key] = _WRITES.get(field_key, 0) + 1
                    _mark_answered(field_key)
                    element.select_option(label=choice)
                note_written(field_key, label, choice)
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

            # A search box shows what it can before anything is typed: nothing
            # at all for Greenhouse's "Location (City)", the first page of an
            # alphabet for its list of universities. Neither is the whole
            # list, so finding no match in what is shown means very little --
            # Gary left a school field blank while holding the school's name.
            shown = formfill.choose_option(label, options, profile, section,
                                           ident, entry) if options else None
            if shown is None and tag != "button":
                typed = names_lib.name_for(label, profile, all_labels,
                                           section, ident)
                if typed is None:
                    typed = formfill.value_for(label, profile, section, ident,
                                               entry)
                if typed and not dry_run:
                    try:
                        close_combobox(frame)
                        # Look before choosing. Collect what the list will
                        # show -- unprompted, then for the name in full, then
                        # for less of it -- and only then decide. Guessing and
                        # checking makes a wrong guess look like an absent
                        # answer, which is what left a school unanswered while
                        # the same school sat on the list under another
                        # spelling.
                        offered = gather_options(
                            frame, element,
                            [str(typed)] + shorter_queries(str(typed)))

                        chosen, query = None, None
                        if offered:
                            texts = list(offered)
                            picked, _fact = option_reading.best(texts, [str(typed)])
                            if picked is None:
                                picked = formfill.choose_option(
                                    label, texts, profile, section, ident, entry)
                            if picked is None:
                                picked, working = judge.decide(label, texts,
                                                               profile)
                                if picked is not None:
                                    reasoned[label] = "%s (judged)" % (
                                        working or "judged from your profile")
                            if picked is not None:
                                chosen, query = picked, offered.get(picked)

                        if chosen:
                            # Bring the list back to where that option was.
                            # An option seen before anything was typed is only
                            # there again once the box is empty, and the last
                            # query left it filtered to something else.
                            if query:
                                type_into(frame, element, query)
                            else:
                                type_into(frame, element, "")
                                try:
                                    element.click(timeout=2000)
                                except Exception:
                                    pass
                            frame.wait_for_timeout(700)
                            choose_from_combobox(frame, element, chosen)
                            frame.wait_for_timeout(400)

                        if chosen and choice_took(frame, element, chosen):
                            note_written(field_key, label, chosen)
                            filled.append((label, chosen))
                            _UNREADABLE_FILLED.add(field_key)
                            continue

                        # Nothing committed. Say so rather than claim it: what
                        # a search box holds is the query, not the answer.
                        settled = ""
                        try:
                            settled = (widget_value(frame, element) or "").strip()
                        except Exception:
                            pass
                        if settled and not choice_took(frame, element, settled):
                            settled = ""
                        if settled:
                            note_written(field_key, label, settled)
                            filled.append((label, settled))
                            continue
                        try:
                            element.fill("")
                        except Exception:
                            pass
                        close_combobox(frame)
                        skipped.append((label, "nothing on the list matched %r "
                                               "-- fill it yourself"
                                        % str(typed)[:30]))
                        continue
                    except Exception:
                        pass
            if location_lib.is_location_question(label):
                stated = formfill.choose_option(label, options, profile,
                                                section, ident, entry)
                picks = location_lib.answer(options, open_locations, company,
                                            hq_table, multiple=False,
                                            question=label)
                choice = stated or (picks[0] if picks else None)
                reason = "no location Gary can be sure of -- choose it yourself"
            else:
                # What the list is asking is settled by the options before the
                # wording is consulted. A list of racial categories wants the
                # race on file whether it is headed "Ethnicity", "Race", or
                # only "Select One" -- and answering it from a name that
                # happens to match is how it came to say "Hispanic or Latino".
                choice, working = lists.answer(options, profile)
                if choice is not None:
                    reasoned[label] = working
                else:
                    choice = formfill.choose_option(label, options, profile,
                                                    section, ident, entry)
                reason = "no confident match -- pick it yourself"
                if choice is None:
                    # The field names are Gary's and the wording is the
                    # employer's. Where they disagree, ask the list instead.
                    choice, working = formfill.reasoned_option(
                        label, options, profile)
                    if choice is not None:
                        reasoned[label] = working
                if choice is None:
                    # The rules have run out. Every employer writes at least
                    # one question nobody anticipated, and that is what this
                    # is for -- asked last, so it never overrides an answer
                    # the rules were sure of.
                    choice, working = judge.decide(label, options, profile)
                    if choice is not None:
                        reasoned[label] = "%s (judged)" % (working or "judged "
                                                           "from your profile")
            if choice and not dry_run and choose_from_combobox(frame, element, choice):
                print("   [dropdown] %s <- %r  from %d options: %s"
                      % (label[:34], choice, len(options),
                         ", ".join(str(o)[:22] for o in options[:6])))
                # Verify the control kept what was chosen. A dropdown holding
                # something else means the selection did not land where it was
                # aimed, and a wrong answer that reports as right is worse than
                # no answer at all.
                settled = ""
                try:
                    settled = (widget_value(frame, element) or "").strip()
                except Exception:
                    pass
                bare = re.sub(r"\s*\([^)]*\)\s*$", "", settled).strip().lower()
                aimed = re.sub(r"\s*\([^)]*\)\s*$", "", str(choice)).strip().lower()
                if settled and bare and aimed and bare != aimed:
                    skipped.append((label, "holds %r after choosing %r -- left "
                                           "for you to set" % (settled[:40],
                                                               str(choice)[:40])))
                    print("   [dropdown] MISMATCH %s: holds %r, chose %r"
                          % (label[:30], settled[:40], str(choice)[:40]))
                else:
                    note_written(field_key, label, choice)
                    filled.append((label,
                                   note_inference(label, profile, choice,
                                                  reasoned)))
                # If it still reads as empty, remember it as done.
                try:
                    if not (widget_value(frame, element) or "").strip():
                        _UNREADABLE_FILLED.add(field_key)
                except Exception:
                    _UNREADABLE_FILLED.add(field_key)
            elif choice and dry_run:
                filled.append((label,
                               note_inference(label, profile, choice, reasoned)))
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
        # A required box asking who the relative is, on a form where the
        # answer to the question above it is no. Only when the form insists:
        # an unnecessary "N/A" is noise on a page a person will read.
        if value is None and infer.name_of_relative(label):
            try:
                insists = bool(element.evaluate(
                    """el => el.required ||
                       el.getAttribute('aria-required') === 'true' ||
                       !!el.closest('[data-automation-id^=formField-]'
                       )?.querySelector('abbr[title=required], .required')"""))
            except Exception:
                insists = False
            if insists:
                value = "N/A"
                reasoned[label] = ("required, and you have no relative to "
                                   "name")

        # A box with nothing to choose from offers the rules nothing to match
        # against, so they reach it least often -- which makes it where
        # judgement earns its place. Asked last, so it never overrides an
        # answer the rules or the profile were sure of.
        if value is None and kind not in ("file",) and tag != "button":
            worked_out, working = judge.decide_text(label, profile)
            if worked_out:
                value = worked_out
                reasoned[label] = "%s (judged)" % (working or "judged from "
                                                   "your profile")

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
                            why = "offered no option matching %r" % value
                            if _LAST_OFFERED:
                                why += " | offered: " + ", ".join(
                                    str(o)[:28] for o in _LAST_OFFERED[:10])
                                if len(_LAST_OFFERED) > 10:
                                    why += ", ... (%d)" % len(_LAST_OFFERED)
                            else:
                                why += " | the list held nothing readable"
                            skipped.append((label, why))
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
                        filled.append((label,
                                       note_inference(label, profile, choice, reasoned)))
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
            note_written(field_key, label, value)
            filled.append((label, note_inference(label, profile, value, reasoned)))
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
        # Read the pay the posting advertises before the description is left
        # behind: the application asks for a salary expectation several pages
        # later, when this page is long gone.
        page.wait_for_timeout(1500)
        if not read_advertised_pay(page, profile):
            # Landed in a restored application rather than on the posting.
            pay_from_posting(ctx, args.url, profile)

        global PROFILE_PATH, COMPANY
        PROFILE_PATH = args.profile
        COMPANY = args.company or ""

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
                    # The description may still be rendering, or collapsed.
                    # Keep trying while the posting is on screen; once the
                    # application begins it is gone for good.
                    if not read_advertised_pay(current, profile):
                        pay_from_posting(ctx, args.url, profile)
                    frames = form_frames(current)
                    if frames and not looks_like_login(frames[0]):
                        learn_from_candidate(frames[0], profile)
                        # No ceiling on looking. A pass that fills nothing
                        # costs nothing, and counting those spent the
                        # whole budget while the page was still settling
                        # -- Gary went quiet on a page it had never
                        # filled. Repeated writing is bounded per field,
                        # where it belongs.
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
                    # A page mid-navigation is expected. A fault in Gary is
                    # not, and calling it "page busy" hid a crash that stopped
                    # a whole page from being filled -- it must be legible.
                    transient = any(word in text for word in (
                        "execution context", "navigat", "detach",
                        "not attached", "no node found", "timeout"))
                    if transient:
                        if mishaps == 1 or mishaps % 20 == 0:
                            print("   (page busy: %s -- still watching)"
                                  % type(exc).__name__)
                    else:
                        import traceback
                        print("\n   Gary hit a fault and skipped this pass:")
                        print("   %s: %s" % (type(exc).__name__, exc))
                        print("   " + traceback.format_exc().strip().replace(
                            "\n", "\n   ")[:1500])
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
