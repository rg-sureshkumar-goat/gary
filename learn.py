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
from watcher import derive as derive_lib  # noqa: E402
from apply import (form_frames, label_for, section_for, identity_of,  # noqa: E402
                   controls, widget_value, looks_like_login, open_browser,
                   close_browser, PROFILE, ROOT)


def harvest(frame):
    """Read back every question on the page and exactly what you answered.

    Nothing is interpreted here. Earlier versions mapped each field onto a
    canonical key -- degree, gpa, university -- and two different questions
    mapping to the same key silently overwrote each other, which is how a
    profile holding two degrees ended up scrambled. The question text is the
    key, and your answer is stored as typed.
    """
    answers, skipped = {}, []
    seen_counts = {}

    for element in controls(frame):
        try:
            if not element.is_visible():
                continue
            kind = (element.get_attribute("type") or "").lower()
            tag = element.evaluate("el => el.tagName.toLowerCase()")
        except Exception:
            continue
        if kind in ("hidden", "submit", "checkbox", "radio"):
            continue
        if tag == "button" and not element.get_attribute("aria-haspopup"):
            continue

        label = formfill.normalise(label_for(frame, element))
        if not label:
            continue
        ident_raw = identity_of(frame, element)
        if formfill.is_page_furniture(label, ident_raw):
            continue
        if formfill.is_option_label(label):
            # The label is the option, not the question. On Workday the
            # question is often the section heading above it -- "Are you at
            # least 18 years of age?" with a control labelled only "Yes". Use
            # the heading as the question rather than discarding the answer.
            heading = formfill.normalise(section_for(frame, element))
            if formfill.is_reusable_question(heading):
                label = heading
            else:
                continue
        if kind == "password" or formfill.is_credential(label):
            skipped.append(label)
            continue
        if kind == "file":
            continue

        raw = str(widget_value(frame, element) or "")
        # Only trim the ends. A work-history description is reused verbatim on
        # every application, so its line breaks and bullets must survive.
        value = raw.strip()
        if not value or value.lower() in ("select...", "select", "select one",
                                          "--", "choose", "choose one"):
            continue

        # A dropdown's label picks up its own selection; strip it, or the key
        # changes with the answer and two entries stop matching.
        label = formfill.strip_value(label, value)
        section = formfill.normalise(section_for(frame, element))
        ident = ident_raw

        # Repeated blocks: an application carries two education entries and two
        # jobs whose fields are labelled identically. DOM order is visual
        # order, so the nth time a field recurs it belongs to the nth entry.
        # Count repeats on an id with its entry number removed, or
        # workExperience6/7 look like two different questions.
        base = formfill.answer_key(section, label,
                                   formfill.base_identity(ident))
        seen_counts[base] = seen_counts.get(base, 0) + 1
        block = formfill.block_of(section, ident, label)
        entry = seen_counts[base] if block in ("education", "work history") else 0
        key = formfill.answer_key(section, label, ident, entry)

        answers[key] = formfill.as_today_token(value)

    return answers, skipped


def merge(profile, recorded):
    """Store the recorded answers, reporting anything that changed."""
    answers = profile.setdefault("answers", {})
    changed = []
    for question, value in sorted(recorded.items()):
        if answers.get(question) != value:
            changed.append((question, answers.get(question), value))
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
    parser.add_argument("--reset", action="store_true",
                        help="discard previously learned answers first, so a "
                             "scrambled profile is replaced rather than merged "
                             "into. Contact details you typed by hand are kept.")
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--watch", action="store_true",
                        help="no terminal prompts: fill the form in the window, "
                             "then close it. Every page is read as you go, and "
                             "your answers are saved when the window closes.")
    parser.add_argument("--poll-seconds", type=int, default=4)
    args = parser.parse_args(argv)

    profile = {}
    if os.path.exists(args.profile):
        with open(args.profile) as fh:
            profile = json.load(fh)

    if args.reset:
        dropped = len(profile.get("answers") or {}) + len(profile.get("custom_answers") or {})
        # Canonical fields derived by earlier versions are what got scrambled;
        # clear those too so nothing stale survives.
        for key in ("answers", "custom_answers", "degree", "gpa", "university",
                    "major", "graduation", "undergrad_degree", "undergrad_gpa",
                    "undergrad_university", "undergrad_major",
                    "undergrad_graduation"):
            profile.pop(key, None)
        print("Cleared %d previously learned answer(s) and the degree fields."
              % dropped)

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser, ctx = open_browser(p, False, None if args.no_session
                                    else args.session)
        ctx.add_init_script(STEALTH)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("opening %s" % args.url)
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait_ms)

        recorded, skipped = {}, []
        pages_read = 0

        if args.watch:
            print("\nFill the form in the window as you normally would.")
            print("Every page is read as you go -- move through the whole")
            print("application, then CLOSE THE WINDOW to save. Don't submit.")
            print("(Watching; nothing is typed for you.)\n")
            last_signature = None
            while True:
                try:
                    current = ctx.pages[-1] if ctx.pages else None
                    if current is None or current.is_closed():
                        break
                    frames = form_frames(current)
                    if frames and not looks_like_login(frames[0]):
                        page_answers, page_skipped = harvest(frames[0])
                        if page_answers:
                            # Only report when the page actually changed.
                            signature = tuple(sorted(page_answers))
                            recorded.update(page_answers)
                            skipped.extend(page_skipped)
                            if signature != last_signature:
                                pages_read += 1
                                print("   read %d answer(s); %d recorded so far"
                                      % (len(page_answers), len(recorded)))
                                last_signature = signature
                    current.wait_for_timeout(args.poll_seconds * 1000)
                except KeyboardInterrupt:
                    break
                except Exception:
                    # The window was closed, which is how you finish.
                    break
            print("\nWindow closed.")
        else:
            print("\nFill the form in as you normally would. Don't submit it.")
            print("Workday spreads an application over several pages -- press Enter")
            print("here after each one, then move on. Type 'done' when finished.")
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
                if looks_like_login(frames[0]):
                    print("   that's a sign-in page -- nothing read from it")
                    continue
                page_answers, page_skipped = harvest(frames[0])
                recorded.update(page_answers)
                skipped.extend(page_skipped)
                pages_read += 1
                print("   recorded %d answer(s) from this page (%d in total)"
                      % (len(page_answers), len(recorded)))

        close_browser(browser, ctx)
        if not pages_read:
            print("Nothing read.")
            return 1

    if not recorded:
        print("Nothing recorded -- the form looked empty.")
        return 1

    changed = merge(profile, recorded)

    print("\n--- recorded %d answer(s), exactly as you entered them ---"
          % len(recorded))
    for question in sorted(recorded):
        marker = " "
        was = next((c[1] for c in changed if c[0] == question), None)
        if was not in (None, ""):
            marker = "*"
        print(" %s %-46s %s" % (marker, question[:46], str(recorded[question])[:40]))
    if any(c[1] not in (None, "") for c in changed):
        print("\n   * replaced an answer you had given before")

    if skipped:
        print("\n--- not read (credential fields) ---")
        for label in sorted(set(skipped)):
            print("   %s" % label[:60])

    if not changed:
        print("\nEverything already matches what was saved.")
        return 0

    if not args.watch:
        print("\nSave to %s? [y/N] " % os.path.basename(args.profile), end="")
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
    print("Saved %d answer(s)." % len(changed))

    # Recorded answers only match the wording they were recorded from. Distil
    # them into general facts so other employers' phrasings match too.
    derived = derive_lib.derive(profile)
    if derived:
        with open(tmp, "w") as fh:
            json.dump(profile, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, args.profile)
        print("\nAlso worked out %d general fact(s) so other employers' "
              "wordings match:" % len(derived))
        for key, value in derived:
            print("   %-24s %s" % (key, str(value)[:40]))
    print("\nReview everything with:  python3 profile.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
