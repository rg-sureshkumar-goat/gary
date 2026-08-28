"""Run the form logic against a saved page, with nothing live involved.

Working out why a field will not fill by editing the code, asking someone to
open a real application and describe what they saw, then guessing again, is
slow and burns their time -- and every remaining page costs another round.
apply.py saves the real markup of each page it meets; this replays one of
those files so the same fault reproduces here, against a test, as often as
needed.

    python3 replay.py snapshots/<file>.html            # what would be filled
    python3 replay.py snapshots/<file>.html --controls # every control seen

Nothing is submitted and no site is contacted: the page is loaded from disk.
"""

import argparse
import os
import re
import sys

import apply


def frames_in(path):
    """The saved frames, in the order they were captured."""
    with open(path, encoding="utf-8") as handle:
        blob = handle.read()
    parts = re.split(r"<!-- frame (\d+): (\S*) -->\n", blob)
    out = []
    for index in range(1, len(parts) - 1, 3):
        out.append((parts[index + 1], parts[index + 2]))
    if not out:                      # a file saved before frames were marked
        out.append(("", blob))
    return out


def replay(path, playwright, show_controls=False, profile_path="profile.json"):
    profile = apply.load_profile(profile_path)
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    written = []
    try:
        for number, (url, html) in enumerate(frames_in(path)):
            scratch = "%s.frame%d.html" % (path, number)
            with open(scratch, "w", encoding="utf-8") as handle:
                handle.write(html)
            written.append(scratch)
            page.goto("file://" + os.path.abspath(scratch))
            print("\n=== frame %d (%s) ===" % (number, url or "top"))
            if show_controls:
                for frame in apply.form_frames(page):
                    for element in apply.controls(frame):
                        try:
                            print("   %-34s %s" % (
                                apply.formfill.normalise(
                                    apply.label_for(frame, element))[:34],
                                apply.identity_of(frame, element)[:40]))
                        except Exception as exc:
                            print("   unreadable: %s" % exc)
                continue
            # dry_run so the saved page is only read, never typed into.
            filled, skipped, _ = apply.fill(page, profile, dry_run=True)
            for label, value in filled:
                print("   would fill  %-30s %s" % (label[:30], value))
            for label, why in skipped:
                print("   left        %-30s %s" % (label[:30], why))
    finally:
        browser.close()
        for scratch in written:
            try:
                os.remove(scratch)
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--controls", action="store_true",
                        help="list every control instead of filling")
    parser.add_argument("--profile", default="profile.json")
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        replay(args.snapshot, playwright, args.controls, args.profile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
