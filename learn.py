#!/usr/bin/env python3
"""Watch you fill in one application, and remember your answers.

    .venv/bin/python learn.py "https://boards.greenhouse.io/acme/jobs/123"

Opens the form, waits while you fill it in by hand, then reads back what you
typed and saves it to profile.json. From then on `apply.py` can put those same
answers into any employer's form.

It learns *answers*, not clicks. A recorded sequence of clicks only works on
the form it was recorded against -- every employer lays their form out
differently -- whereas your name, university and graduation year are the same
everywhere. Employer-specific questions are stored against the question text,
so the identical wording is answered the same way elsewhere.

Password, SSN, card and bank fields are never read.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from watcher.browser import LAUNCH_ARGS, STEALTH, UA, _require_playwright  # noqa: E402
from watcher import formfill  # noqa: E402
from apply import form_frames, label_for, PROFILE  # noqa: E402


def harvest(frame):
    """Read back the labels and values on a form the user has filled in."""
    learned, custom, skipped = {}, {}, []

    for element in frame.query_selector_all("input, textarea, select"):
        try:
            if not element.is_visible():
                continue
            kind = (element.get_attribute("type") or "").lower()
            tag = element.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue
        if kind in ("hidden", "submit", "button", "checkbox", "radio"):
            continue

        label = formfill.normalise(label_for(frame, element))
        if not label:
            continue

        # Never read a credential back off the page.
        if kind == "password" or formfill.is_credential(label):
            skipped.append(label)
            continue
        if kind == "file":
            continue

        try:
            if tag == "select":
                value = element.evaluate(
                    "el => el.selectedOptions.length ? "
                    "el.selectedOptions[0].textContent.trim() : ''")
            else:
                value = element.input_value()
        except Exception:
            continue

        value = " ".join(str(value or "").split())
        if not value or value.lower() in ("select...", "select", "--", "choose"):
            continue

        key = formfill.key_for(label)
        if key:
            key = formfill.prior_degree_key(label, key)
            learned[key] = value
        else:
            custom[formfill.normalise(label).lower().rstrip("?").strip()] = value

    return learned, custom, skipped


def merge(profile, learned, custom):
    changed = []
    for key, value in sorted(learned.items()):
        if profile.get(key) != value:
            changed.append((key, profile.get(key), value))
            profile[key] = value
    answers = profile.setdefault("custom_answers", {})
    for question, value in sorted(custom.items()):
        if answers.get(question) != value:
            changed.append(("custom: " + question[:40], answers.get(question), value))
            answers[question] = value
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="an application form to learn from")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--wait-ms", type=int, default=5000)
    args = parser.parse_args(argv)

    profile = {}
    if os.path.exists(args.profile):
        with open(args.profile) as fh:
            profile = json.load(fh)

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

        print("\nFill the form in as you normally would. Don't submit it.")
        print("When you're done, come back here and press Enter.")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            browser.close()
            return 1

        frames = form_frames(page)
        if not frames:
            print("No form fields found on that page.")
            browser.close()
            return 1
        learned, custom, skipped = harvest(frames[0])
        browser.close()

    if not learned and not custom:
        print("Nothing to learn -- the form looked empty.")
        return 1

    changed = merge(profile, learned, custom)
    if not changed:
        print("Everything you entered already matches your profile.")
        return 0

    print("\n--- learned ---")
    for key, was, now in changed:
        if was in (None, ""):
            print("   %-34s %s" % (key[:34], str(now)[:44]))
        else:
            print("   %-34s %s  (was %s)" % (key[:34], str(now)[:32], str(was)[:20]))
    if skipped:
        print("\n--- not read (credential fields) ---")
        for label in skipped:
            print("   %s" % label[:60])

    print("\nSave these to %s? [y/N] " % os.path.basename(args.profile), end="")
    try:
        if not input().strip().lower().startswith("y"):
            print("Nothing saved.")
            return 0
    except (EOFError, KeyboardInterrupt):
        print("\nNothing saved.")
        return 0

    tmp = args.profile + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(profile, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, args.profile)
    print("Saved. apply.py will use these on the next form.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
