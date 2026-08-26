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
from apply import (form_frames, label_for, controls, widget_value,  # noqa: E402
                   open_browser, close_browser, PROFILE, ROOT)


def harvest(frame):
    """Read back the labels and values on a form the user has filled in."""
    learned, custom, skipped = {}, {}, []

    for element in controls(frame):
        try:
            if not element.is_visible():
                continue
            kind = (element.get_attribute("type") or "").lower()
            tag = element.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue
        # A custom dropdown is a <button>; a real submit button is not.
        if kind in ("hidden", "submit", "checkbox", "radio"):
            continue
        if tag == "button" and not element.get_attribute("aria-haspopup"):
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

        value = " ".join(str(widget_value(frame, element) or "").split())
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
    parser.add_argument("--session", default=os.path.join(ROOT, ".browser-session"),
                        help="browser profile directory, so a Workday sign-in "
                             "survives between runs")
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--wait-ms", type=int, default=5000)
    args = parser.parse_args(argv)

    profile = {}
    if os.path.exists(args.profile):
        with open(args.profile) as fh:
            profile = json.load(fh)

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser, ctx = open_browser(p, False, None if args.no_session
                                    else args.session)
        ctx.add_init_script(STEALTH)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("opening %s" % args.url)
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait_ms)

        print("\nFill the form in as you normally would. Don't submit it.")
        print("Workday spreads an application over several pages -- press Enter")
        print("here after each one, then move on. Type 'done' when finished.")

        learned, custom, skipped = {}, {}, []
        pages_read = 0
        while True:
            try:
                answer = input("\n[Enter] read this page, or 'done': ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "done"
            if answer.startswith("d") or answer.startswith("q"):
                break

            current = ctx.pages[-1] if ctx.pages else page
            frames = form_frames(current)
            if not frames:
                print("   no form fields visible on this page")
                continue
            page_learned, page_custom, page_skipped = harvest(frames[0])
            learned.update(page_learned)
            custom.update(page_custom)
            skipped.extend(page_skipped)
            pages_read += 1
            print("   read %d answer(s) from this page (%d in total)"
                  % (len(page_learned) + len(page_custom),
                     len(learned) + len(custom)))

        close_browser(browser, ctx)
        if not pages_read:
            print("Nothing read.")
            return 1

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
