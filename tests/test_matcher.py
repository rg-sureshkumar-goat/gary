"""Run with:  python3 -m tests.test_matcher"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.matcher import classify           # noqa: E402
from watcher.notifier import build_messages    # noqa: E402

RULES = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config.json")))["rules"]

SHOULD_MATCH = [
    "2027 Commercial & Investment Bank - Global Investment Banking Program - Summer Analyst",
    "Corporate Development Intern (Summer 2027)",
    "Off-Cycle Intern, Financial Restructuring - Singapore",
    "OLIVER WYMAN - INTERN CONSULTANT - 2026 - NETHERLANDS",
    "Associate Consultant Intern, Strategy & Transformation, Internship Program 2027",
    "2027 Financial Analyst Intern",
    "Finance Intern",
    "2027 Point72 Academy Investment Analyst Summer Internship Program",
    "Summer Analyst, Corporate Finance",
    "FP&A Co-op Student",
    "Management Consulting Summer Associate",
    "Treasury Internship - Summer 2027",
    "Spring Week - Investment Banking",
]

SHOULD_NOT_MATCH = [
    # Right function, but not an internship.
    ("Assistant Vice President - International Finance (Riyadh)", "international != intern"),
    ("Corporate Finance Manager", "no internship signal"),
    ("Internal Audit Director", "internal != intern"),
    # Internship, but the wrong function.
    ("Summer 2027 Intern - Software Engineer", "engineering"),
    ("Sales Intern - Dutch Speaker", "no finance/consulting term"),
    ("2026 Warsaw MI Data - Web Scraping Internship", "no finance/consulting term"),
    ("Clinical Research Intern", "clinical"),
    ("Talent Acquisition Intern, Finance Team", "recruiting"),
    ("Data Scientist Intern, Strategy", "data scientist"),
    # Wrong degree level for an MS Finance student.
    ("MBA Finance Leadership Development Program Intern", "MBA-only"),
    ("2027 MBA Finance Leadership Development Program (FLDP) Internship",
     "MBA-only"),
    ("Finance Development Program Intern (Undergraduate)", "undergraduate-only"),
]


def main():
    failures = []

    for title in SHOULD_MATCH:
        ok, why = classify({"title": title, "location": "New York"}, RULES)
        if not ok:
            failures.append("MISSED   %-70s (%s)" % (title[:68], why.get("why")))

    for title, note in SHOULD_NOT_MATCH:
        ok, why = classify({"title": title, "location": "New York"}, RULES)
        if ok:
            failures.append("FALSE +  %-70s (expected drop: %s)" % (title[:68], note))

    # Explicit allow-list, with the US gate switched off.
    gated = dict(RULES, us_only=False, locations_allow=["new york", "london"])
    ok, _ = classify({"title": "Finance Intern", "location": "Tokyo, Japan"}, gated)
    if ok:
        failures.append("location allow-list did not filter Tokyo")
    ok, _ = classify({"title": "Finance Intern", "location": "London, UK"}, gated)
    if not ok:
        failures.append("location allow-list wrongly filtered London")

    # The US gate, as shipped: keep US roles, drop everything else.
    us_rules = dict(RULES, us_only=True, keep_unknown_locations=False,
                    locations_allow=[])
    keep_us = [
        ("2027 Investment Banking Summer Analyst", "New York, NY, United States"),
        ("Corporate Finance Intern", "Charlotte, NC"),
        ("Management Consulting Summer Associate", "Chicago"),
    ]
    drop_abroad = [
        ("2027 Global Investment Banking Program - Summer Analyst", "Tokyo, Japan"),
        ("Off-Cycle Intern, Financial Restructuring", "Singapore, Singapore"),
        ("Associate Consultant Intern, Strategy", "San Jose, Costa Rica"),
        ("Oliver Wyman - Consultant Intern", "Munich, Germany"),
    ]
    for title, loc in keep_us:
        ok, why = classify({"title": title, "location": loc}, us_rules)
        if not ok:
            failures.append("US gate dropped a US role: %-46s (%s)" % (title[:44], why.get("why")))
    for title, loc in drop_abroad:
        ok, _ = classify({"title": title, "location": loc}, us_rules)
        if ok:
            failures.append("US gate kept a non-US role: %-40s %s" % (title[:38], loc))

    # Telegram messages must stay under the 4096-char cap.
    many = [{"company": "Company %02d" % i, "title": "Corporate Finance Summer Analyst %d" % i,
             "location": "New York, NY", "url": "https://example.com/job/%d" % i,
             "posted_at": "2026-08-25"} for i in range(120)]
    msgs = build_messages(many)
    if not msgs or any(len(m) > 4096 for m in msgs):
        failures.append("build_messages produced a chunk over Telegram's 4096 limit")
    if sum(m.count("Corporate Finance Summer Analyst") for m in msgs) != 120:
        failures.append("build_messages dropped jobs while chunking")

    # HTML escaping, so a title with & or < can't break the message.
    msg = build_messages([{"company": "A & B <Ltd>", "title": "M&A Intern",
                           "location": "NY", "url": "https://x.com/?a=1&b=2",
                           "posted_at": None}])[0]
    if "&amp;" not in msg or "<Ltd>" in msg:
        failures.append("build_messages did not escape HTML")

    total = len(SHOULD_MATCH) + len(SHOULD_NOT_MATCH) + 5 + 7
    if failures:
        print("FAILED %d of %d checks:" % (len(failures), total))
        for f in failures:
            print("   " + f)
        return 1
    print("All %d checks passed." % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
