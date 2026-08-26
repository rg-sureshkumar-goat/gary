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
    """The visible question text for a form control."""
    try:
        return page.evaluate("""el => {
            const byFor = el.id && document.querySelector(`label[for="${el.id}"]`);
            if (byFor) return byFor.innerText;
            const wrap = el.closest('label');
            if (wrap) return wrap.innerText;
            const aria = el.getAttribute('aria-label');
            if (aria) return aria;
            const labelled = el.getAttribute('aria-labelledby');
            if (labelled) {
                const t = document.getElementById(labelled);
                if (t) return t.innerText;
            }
            const group = el.closest('div,fieldset,section');
            if (group) {
                const lab = group.querySelector('label,legend');
                if (lab) return lab.innerText;
            }
            return el.getAttribute('placeholder') || el.getAttribute('name') || '';
        }""", element)
    except Exception:
        return ""


def fill(page, profile, dry_run=False):
    filled, skipped, credentials = [], [], []

    for element in page.query_selector_all("input, textarea, select"):
        try:
            if not element.is_visible() or not element.is_enabled():
                continue
            kind = (element.get_attribute("type") or "").lower()
            tag = element.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue

        if kind in ("hidden", "submit", "button", "checkbox", "radio"):
            continue

        label = formfill.normalise(label_for(page, element))

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
            choice = formfill.choose_option(label, options, profile)
            if choice:
                if not dry_run:
                    element.select_option(label=choice)
                filled.append((label, choice))
            else:
                skipped.append((label, "no confident match -- pick it yourself"))
            continue

        value = formfill.value_for(label, profile)
        if value:
            if not dry_run:
                element.fill(value)
            filled.append((label, value))
        elif label:
            skipped.append((label, "not in your profile"))

    return filled, skipped, credentials


def report(filled, skipped, credentials, page):
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

    buttons = []
    for el in page.query_selector_all("button, input[type=submit]"):
        try:
            text = (el.inner_text() or el.get_attribute("value") or "").strip()
        except Exception:
            continue
        if text and any(w in text.lower() for w in SUBMIT_WORDS):
            buttons.append(text)
    if buttons:
        print("\nSubmit control on this page: %r -- left for you to click."
              % buttons[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="the application page")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be filled, change nothing")
    parser.add_argument("--wait-ms", type=int, default=6000)
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    if profile is None:
        return 1

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=LAUNCH_ARGS)
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  viewport={"width": 1400, "height": 1000})
        ctx.add_init_script(STEALTH)
        page = ctx.new_page()
        print("opening %s" % args.url)
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait_ms)

        filled, skipped, credentials = fill(page, profile, args.dry_run)
        report(filled, skipped, credentials, page)

        print("\nThe browser is open. Check every field, then submit it yourself.")
        print("Press Enter here when you're done to close it.")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
