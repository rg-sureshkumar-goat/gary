#!/usr/bin/env python3
"""Show what Gary knows about you, and what it still needs.

    python3 profile.py            # everything, grouped
    python3 profile.py --mask     # hide contact details, for sharing a screenshot

Fields are grouped so the two degrees stay distinct: a master's student is
asked about both, and answering an undergraduate question from graduate data is
how a form ends up misstating your record.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(ROOT, "profile.json")

GROUPS = [
    ("Who you are", [
        ("first_name", "First name (default)"),
        ("last_name", "Last name (default)"),
        ("legal_first_name", "Legal first name"),
        ("legal_last_name", "Legal last name"),
        ("preferred_first_name", "Preferred first name"),
        ("preferred_last_name", "Preferred last name"),
        ("preferred_name", "Preferred name (one box)"),
        ("full_name", "Full name"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("phone_type", "Phone device type"),
        ("linkedin", "LinkedIn"),
        ("website", "Website / portfolio"),
    ]),
    ("Where you live", [
        ("address", "Street address"),
        ("city", "City"),
        ("state", "State"),
        ("postal_code", "Postal code"),
        ("country", "Country"),
    ]),
    ("Your current degree", [
        ("university", "University"),
        ("degree", "Degree"),
        ("major", "Major"),
        ("graduation", "Graduation"),
        ("gpa", "GPA"),
    ]),
    ("Your previous degree", [
        ("undergrad_university", "University"),
        ("undergrad_degree", "Degree"),
        ("undergrad_major", "Major"),
        ("undergrad_graduation", "Graduation"),
        ("undergrad_gpa", "GPA"),
    ]),
    ("Eligibility and preferences", [
        ("work_authorization", "Authorised to work in the US"),
        ("sponsorship", "Requires sponsorship"),
        ("start_date", "Available from"),
        ("referral", "How you heard about the role"),
    ]),
    ("Documents", [
        ("resume", "Resume"),
        ("cover_letter", "Cover letter"),
    ]),
    ("Voluntary disclosures", [
        ("pronouns", "Pronouns"),
        ("gender", "Gender"),
        ("race", "Race / ethnicity"),
        ("veteran", "Veteran status"),
        ("disability", "Disability status"),
    ]),
]

SENSITIVE = {"phone", "email", "address", "postal_code", "linkedin"}


def show(value, key, mask):
    text = str(value)
    if mask and key in SENSITIVE:
        return text[:2] + "…" * 3 + text[-2:] if len(text) > 6 else "…" * 5
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--mask", action="store_true",
                        help="hide contact details in the output")
    parser.add_argument("--set", dest="assignments", action="append", default=[],
                        metavar="KEY=VALUE",
                        help="set a field, e.g. --set undergrad_degree='BS'. "
                             "Repeatable.")
    parser.add_argument("--clear", action="append", default=[], metavar="KEY",
                        help="empty a field. Repeatable.")
    parser.add_argument("--fallback", action="append", default=[],
                        metavar="KEY=A,B", dest="fallbacks",
                        help="what to try when a dropdown has no option "
                             "matching your answer, in order. e.g. "
                             "--fallback undergrad_major='Other,Art'")
    parser.add_argument("--derive", action="store_true",
                        help="work out general facts from recorded answers, so "
                             "other employers' wordings match")
    args = parser.parse_args(argv)

    if not os.path.exists(args.profile):
        print("No profile yet. Create one with:")
        print("   cp profile.example.json profile.json")
        print("   .venv/bin/python learn.py <an application url>")
        return 1

    with open(args.profile) as fh:
        profile = json.load(fh)

    valid = {f for _, fields in GROUPS for f, _ in fields}
    changes = []
    for pair in args.assignments:
        if "=" not in pair:
            print("--set needs KEY=VALUE, got %r" % pair)
            return 1
        key, value = pair.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in valid:
            print("Unknown field %r. Known fields:\n   %s"
                  % (key, ", ".join(sorted(valid))))
            return 1
        changes.append((key, profile.get(key), value))
        profile[key] = value
    for key in args.clear:
        key = key.strip()
        if key in profile:
            changes.append((key, profile.get(key), ""))
            profile[key] = ""

    for pair in args.fallbacks:
        if "=" not in pair:
            print("--fallback needs KEY=A,B, got %r" % pair)
            return 1
        key, listed = pair.split("=", 1)
        key = key.strip()
        values = [v.strip() for v in listed.split(",") if v.strip()]
        table = profile.setdefault("fallbacks", {})
        changes.append(("fallback %s" % key, table.get(key), values))
        if values:
            table[key] = values
        else:
            table.pop(key, None)

    if changes:
        for key, was, now in changes:
            print("   %-24s %r -> %r" % (key, was, now))
        tmp = args.profile + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(profile, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, args.profile)
        print("Saved %d change(s).\n" % len(changes))

    if args.derive:
        sys.path.insert(0, ROOT)
        from watcher.derive import derive as run_derive
        found = run_derive(profile)
        if found:
            tmp = args.profile + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(profile, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, args.profile)
            print("Worked out %d field(s) from your recorded answers:" % len(found))
            for key, value in found:
                print("   %-24s %s" % (key, str(value)[:40]))
            print()
        else:
            print("Nothing new to work out.\n")

    known = missing = 0
    for title, fields in GROUPS:
        print("\n%s" % title)
        print("  " + "-" * (len(title) + 2))
        for key, label in fields:
            value = profile.get(key)
            if value in (None, ""):
                missing += 1
                print("     %-30s  --  not set" % label)
            else:
                known += 1
                if key == "resume" and not os.path.exists(os.path.expanduser(str(value))):
                    print("     %-30s  %s   [file not found]"
                          % (label, show(value, key, args.mask)[:44]))
                else:
                    print("     %-30s  %s" % (label, show(value, key, args.mask)[:44]))

    answers = dict(profile.get("custom_answers") or {})
    answers.update(profile.get("answers") or {})
    print("\nAnswers recorded from forms, exactly as you entered them (%d)"
          % len(answers))
    print("  " + "-" * 58)
    if answers:
        for question in sorted(answers):
            shown = str(answers[question])
            print("     %-44s  %s" % (question[:44], shown[:30]))
    else:
        print("     none yet -- run learn.py on an application")

    table = profile.get("fallbacks") or {}
    if table:
        print("\nIf a dropdown has no option matching your answer, try")
        print("  " + "-" * 52)
        for key in sorted(table):
            print("     %-24s %s" % (key, " -> ".join(table[key])))

    extra = [k for k in profile
             if k not in {f for _, fields in GROUPS for f, _ in fields}
             and k not in ("custom_answers", "answers", "fallbacks")
             and not k.startswith("_")]
    if extra:
        print("\nOther keys in the file: %s" % ", ".join(sorted(extra)))

    print("\n%d field(s) set, %d still missing." % (known, missing))
    if missing:
        print("Fill them by editing profile.json, or by running learn.py on a")
        print("form that asks for them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
