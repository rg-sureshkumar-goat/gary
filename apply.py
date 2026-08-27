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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from watcher.browser import LAUNCH_ARGS, STEALTH, UA, _require_playwright  # noqa: E402
from watcher import formfill  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(ROOT, "profile.json")

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
        ctx = playwright.chromium.launch_persistent_context(
            session_dir, headless=headless, args=LAUNCH_ARGS, user_agent=UA,
            locale="en-US", viewport={"width": 1400, "height": 1000})
        return None, ctx
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
        return element.input_value()
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

    Gary never authenticates anywhere. If a form carries a password field, or
    reads like a sign-in, nothing on it is filled -- not the email, not the
    name, nothing. Signing in is yours to do by hand.
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
    try:
        heading = frame.evaluate(
            "() => Array.from(document.querySelectorAll('h1,h2,h3,button'))"
            ".slice(0, 40).map(e => e.innerText).join(' | ')")
    except Exception:
        heading = ""
    return formfill.is_auth_form(labels + [heading])


def fill(page, profile, dry_run=False):
    filled, skipped, credentials = [], [], []
    frames = form_frames(page)
    if not frames:
        return filled, skipped, credentials

    frame = frames[0]
    seen_counts = {}
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
        base = formfill.answer_key(section, label, ident)
        seen_counts[base] = seen_counts.get(base, 0) + 1
        block = formfill.block_of(section, ident, label)
        entry = seen_counts[base] if block in ("education", "work history") else 0

        # A password field is never filled, whatever it is labelled.
        if kind == "password" or formfill.is_credential(label):
            credentials.append(label or "(unlabelled password field)")
            continue

        if kind == "file":
            which = "cover_letter" if "cover" in label.lower() else "resume"
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
            choice = formfill.choose_option(label, options, profile, section,
                                            ident, entry)
            if choice:
                if not dry_run:
                    element.select_option(label=choice)
                filled.append((label, choice))
            else:
                skipped.append((label, "no confident match -- pick it yourself"))
            continue

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
        filled, skipped, credentials = fill(page, profile, args.dry_run)
        report(filled, skipped, credentials, page,
               frames[0] if frames else None)

        if not headless:
            print("\nThe browser is open. Check every field, then submit it "
                  "yourself.")
            print("Press Enter here when you're done to close it.")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
        close_browser(browser, ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
