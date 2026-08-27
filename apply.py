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
    "input, textarea, select, "
    "button[aria-haspopup='listbox'], [role=combobox], "
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
            const id = el.getAttribute('aria-controls') ||
                       el.getAttribute('aria-owns');
            let root = id ? document.getElementById(id) : null;
            if (!root) {
                // Prefer a listbox near this control; a page-wide search finds
                // whichever dropdown was opened last.
                let scope = el;
                for (let hop = 0; hop < 6 && scope; hop++) {
                    scope = scope.parentElement;
                    if (!scope) break;
                    const near = Array.from(scope.querySelectorAll('[role=listbox]'))
                        .filter(b => b.offsetParent !== null);
                    if (near.length) { root = near[0]; break; }
                }
            }
            if (!root) {
                const boxes = Array.from(
                    document.querySelectorAll('[role=listbox]'))
                    .filter(b => b.offsetParent !== null);
                root = boxes.length ? boxes[boxes.length - 1] : null;
            }
            if (!root) return [];
            const seen = new Set();
            return Array.from(root.querySelectorAll(
                    '[role=option], [class*=option], [id*=option], li'))
                .map(o => (o.innerText || '').trim())
                .filter(t => t && !seen.has(t) && seen.add(t))
                .slice(0, 400);
        }""", element)
        return [o for o in options if o]
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
            if (!root) {
                const boxes = Array.from(
                    document.querySelectorAll('[role=listbox]'))
                    .filter(b => b.offsetParent !== null);
                root = boxes.length ? boxes[boxes.length - 1] : null;
            }
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


def widget_value(frame, element):
    """What a control currently holds, native or custom."""
    try:
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            return element.evaluate(
                "el => el.selectedOptions.length ? "
                "el.selectedOptions[0].textContent.trim() : ''")
        if tag == "button":
            # A Workday dropdown shows its selection as the button's text.
            text = (element.inner_text() or "").strip()
            return "" if text.lower() in ("select one", "select", "") else text

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


def add_buttons(frame, block):
    """The "Add" controls belonging to a section, e.g. Work Experience.

    Workday builds these sections empty: until Add is pressed there are no
    fields at all, which is why a page can look unfillable.

    The buttons carry data-automation-id="add-button" and are labelled only
    "Add", so which section each belongs to has to come from the surrounding
    text. Looking for a heading element does not work -- Workday renders those
    section titles as plain divs.
    """
    words = {"work history": r"work\s*experience|employment|work\s*history",
             "education": r"education|school|degree|university"}.get(block, block)
    try:
        return frame.evaluate("""([words]) => {
            const re = new RegExp(words, 'i');
            const all = Array.from(document.querySelectorAll(
                'button,[role=button],a[role=button]'));
            const out = [];
            all.forEach((b, i) => {
                const id = b.getAttribute('data-automation-id') || '';
                const text = ((b.innerText || '') + ' ' +
                              (b.getAttribute('aria-label') || '')).trim();
                const isAdd = /add-button/i.test(id) || /^\s*add\b/i.test(text);
                if (!isAdd) return;
                if (re.test(text)) { out.push(i); return; }
                // Climb, reading the whole container's text rather than
                // looking for a heading tag.
                let node = b;
                for (let hop = 0; hop < 7 && node; hop++) {
                    node = node.parentElement;
                    if (!node) break;
                    const t = (node.innerText || '').slice(0, 400);
                    if (re.test(t)) { out.push(i); return; }
                }
            });
            return out;
        }""", [words])
    except Exception:
        return []


def open_entry_sections(frame, profile, dry_run=False, log=None):
    """Press Add until each repeated section has room for what we know.

    Clicking Add creates a blank entry; it never submits anything.
    """
    created = []
    for block in ("work history", "education"):
        wanted = entries_wanted(profile, block)
        if not wanted:
            continue
        for attempt in range(wanted):
            # Re-read each time: pressing Add changes the page.
            present = len({formfill.answer_key(
                formfill.normalise(section_for(frame, el)),
                formfill.normalise(label_for(frame, el)),
                formfill.base_identity(identity_of(frame, el)))
                for el in controls(frame)
                if formfill.block_of(
                    formfill.normalise(section_for(frame, el)),
                    identity_of(frame, el),
                    formfill.normalise(label_for(frame, el))) == block})
            if present >= wanted:
                break
            indexes = add_buttons(frame, block)
            if not indexes:
                break
            if dry_run:
                created.append((block, "would press Add"))
                break
            try:
                frame.evaluate("""([i]) => {
                    const b = document.querySelectorAll(
                        'button, [role=button], a[role=button]')[i];
                    if (b) b.click();
                }""", [indexes[0]])
                frame.wait_for_timeout(1200)
                created.append((block, "pressed Add"))
            except Exception:
                break
    if created and log:
        for block, what in created:
            log("   %s: %s" % (block, what))
    return created


_RECENTLY_FILLED = {}


def _too_soon(key, seconds=25):
    """Was this field answered a moment ago?

    Some controls cannot be read back reliably, and without this they are
    re-answered on every pass -- which reopens dropdowns under the user.
    """
    import time
    now = time.time()
    last = _RECENTLY_FILLED.get(key, 0)
    if now - last < seconds:
        return True
    _RECENTLY_FILLED[key] = now
    return False


def fill(page, profile, dry_run=False, open_locations=None, company="",
         hq_table=None):
    filled, skipped, credentials = [], [], []
    frames = form_frames(page)
    if not frames:
        return filled, skipped, credentials

    frame = frames[0]
    seen_counts = {}
    file_slots = 0

    # Workday's repeated sections start empty. Press Add first, or there are
    # no fields on the page to fill.
    opened = open_entry_sections(frame, profile, dry_run)
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
            if not element.is_visible() or not element.is_enabled():
                continue
            kind = (element.get_attribute("type") or "").lower()
            tag = element.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue

        if kind in ("hidden", "submit", "button", "checkbox", "radio"):
            continue

        label = formfill.normalise(label_for(frame, element))
        section = formfill.normalise(section_for(frame, element))
        ident = identity_of(frame, element)
        if formfill.is_page_furniture(label, ident):
            continue
        # Count repeats on an id with its entry number removed, or
        # workExperience6/7 look like two different questions.
        base = formfill.answer_key(section, label,
                                   formfill.base_identity(ident))
        seen_counts[base] = seen_counts.get(base, 0) + 1
        block = formfill.block_of(section, ident, label)
        entry = seen_counts[base] if block in ("education", "work history") else 0

        # A password field is never filled, whatever it is labelled.
        if kind == "password" or formfill.is_credential(label):
            credentials.append(label or "(unlabelled password field)")
            continue

        if kind == "file":
            file_slots += 1
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
                if not dry_run:
                    element.set_input_files(path)
                filled.append((label or which, os.path.basename(path)))
            elif path:
                skipped.append((label or which, "file not found: %s" % path))
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
                    element.select_option(label=choice)
                filled.append((label, choice))
            else:
                skipped.append((label, "no confident match -- pick it yourself"))
            continue

        # A typeahead combobox: options only exist once it is opened.
        is_combo = (element.get_attribute("role") == "combobox"
                    or element.get_attribute("aria-haspopup") in ("true", "listbox"))
        if is_combo and tag != "select":
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
            elif choice and dry_run:
                filled.append((label, choice))
            else:
                close_combobox(frame)
                skipped.append((label, reason))
            continue

        # Names follow their own rule, decided by the whole form.
        # On a second pass over the same page -- Workday reveals State only
        # once Country is set -- fill the blanks and leave everything else.
        try:
            if (widget_value(frame, element) or "").strip():
                continue
        except Exception:
            pass
        if _too_soon("%s|%s|%s" % (page.url, label, ident)):
            continue

        value = names_lib.name_for(label, profile, all_labels, section, ident)
        if value is None:
            value = formfill.value_for(label, profile, section, ident, entry)
        if value:
            if not dry_run:
                element.fill(value)
            filled.append((label, value))
        elif label:
            skipped.append((label, "not in your profile"))

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
            reported_buttons = set()
            while True:
                try:
                    current = ctx.pages[-1] if ctx.pages else None
                    if current is None or current.is_closed():
                        break
                    frames = form_frames(current)
                    if frames and not looks_like_login(frames[0]):
                        # Fill on every pass. Only empty fields are touched, so
                        # this never overwrites anything -- and keying off the
                        # page's labels instead would mark a page done forever,
                        # so a field you cleared would never be refilled.
                        f, sk, cr = fill(current, profile, args.dry_run,
                                         open_locations, args.company,
                                         hq_table)
                        if not f:
                            # Nothing to fill usually means the section is
                            # still collapsed behind an Add control. Report
                            # what buttons exist so the right one can be
                            # matched.
                            # Workday keeps one URL for the whole
                            # application, so keying this on the URL reports
                            # the job advert once and never the pages that
                            # follow. Key it on what is actually on screen.
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
                                    print("   tabs open : %d" % len(ctx.pages))
                                    print("   url       : %s" % current.url[:100])
                                    try:
                                        print("   headings  : %s" % frames[0].evaluate(
                                            "() => Array.from(document.querySelectorAll("
                                            "'h1,h2,h3')).slice(0,6)"
                                            ".map(h => (h.innerText||'').trim())"
                                            ".filter(Boolean).join(' | ')")[:150])
                                    except Exception:
                                        pass
                                    print("   frames    : %d" % len(current.frames))
                                    for fr in current.frames:
                                        try:
                                            n = len(fr.query_selector_all(CONTROL_SELECTOR))
                                            vis = len([e for e in
                                                       fr.query_selector_all(CONTROL_SELECTOR)
                                                       if e.is_visible()])
                                        except Exception:
                                            n, vis = -1, -1
                                        print("     frame %-58s controls=%-4s visible=%s"
                                              % ((fr.url or "(main)")[:58], n, vis))
                                    print("   chosen frame controls: %d"
                                          % len(controls(frames[0])))
                                    for b in buttons:
                                        print("   button: %s" % b[:90])
                                except Exception as exc:
                                    print("   (could not list buttons: %s)" % type(exc).__name__)
                        if f:
                            print("--- filled %d ---" % len(f))
                            for lab, val in f:
                                print("   %-36s %s" % (lab[:36], str(val)[:36]))
                            left = [x for x in sk if x[0] not in
                                    {y[0] for y in f}]
                            for lab, why in left[:6]:
                                print("   %-36s (left: %s)" % (lab[:36], why[:26]))
                    current.wait_for_timeout(args.poll_seconds * 1000)
                except Exception:
                    break
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
