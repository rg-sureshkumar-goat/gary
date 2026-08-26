"""Degree-level filtering. Run with:  python3 -m tests.test_level"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.level import suits, levels_named  # noqa: E402

failures = []

# An MS Finance student: a graduate degree, but not an MBA.
KEEP = [
    "2027 Summer Intern, Finance & Accounting Leadership Accelerator",
    "Corporate Development Intern (Summer 2027)",
    "Investment Banking Summer Analyst",
    # Explicitly open to master's students.
    "Investment Banking Summer Analyst - Masters",
    "MS Finance Summer Analyst",
    "MFin Summer Associate",
    # Named alongside other levels -- still open to this student.
    "Summer Analyst - MBA or MS candidates",
    "Finance Intern - Undergraduate and Graduate Students",
    "MBA/MS Summer Associate",
    "Corporate Finance Intern - Graduate Level",
    # "MS" that isn't a degree must not be read as one either way.
    "Microsoft Office Specialist Intern",
    "Morgan Stanley MS Summer Analyst",
]
DROP = [
    "MBA Finance Leadership Development Program Intern",
    "2027 Finance Leader Accelerator Program Intern (MBA)",
    "2027 Accounting & Finance Development Program Intern (Undergraduate)",
    "Finance Intern - Bachelor's Degree Required",
    "Summer Analyst - Rising Senior",
    "PhD Quantitative Research Intern",
]

for title in KEEP:
    if not suits(title, "masters"):
        failures.append("dropped a role an MS student can take: %-56s %s"
                        % (title[:54], sorted(levels_named(title))))
for title in DROP:
    if suits(title, "masters"):
        failures.append("kept a role aimed elsewhere: %-56s %s"
                        % (title[:54], sorted(levels_named(title))))

# Other students see different results from the same postings.
if not suits("Finance Intern (Undergraduate)", "undergraduate"):
    failures.append("an undergraduate should match an undergraduate posting")
if suits("Finance Intern (Undergraduate)", "mba"):
    failures.append("an MBA student should not match an undergraduate posting")
if not suits("MBA Finance Leadership Program", "mba"):
    failures.append("an MBA student should match an MBA posting")

# --- accepting several levels at once --------------------------------------- #
BOTH = ["undergraduate", "masters"]
both_keep = [
    "2027 Accounting & Finance Development Program Intern (Undergraduate)",
    "Summer Analyst - Rising Senior",
    "Finance Intern - Bachelor's Degree Required",
    "Investment Banking Summer Analyst - Masters",
    "Summer Analyst - MBA or MS candidates",
    "Corporate Development Intern (Summer 2027)",
]
both_drop = [
    "MBA Finance Leadership Development Program Intern",
    "2027 Finance Leader Accelerator Program Intern (MBA)",
    "PhD Quantitative Research Intern",
]
for title in both_keep:
    if not suits(title, BOTH):
        failures.append("undergrad+masters should keep: %s" % title[:56])
for title in both_drop:
    if suits(title, BOTH):
        failures.append("undergrad+masters should drop: %s" % title[:56])

# A single level as a plain string must keep working.
if suits("Finance Intern (Undergraduate)", "masters"):
    failures.append("a lone string level should still filter")

# An empty list means no filtering, like "any".
if not suits("MBA Finance Leadership Program", []):
    failures.append("an empty level list should disengage the filter")

# Turning the filter off keeps everything.
for title in DROP:
    if not suits(title, "any") or not suits(title, None):
        failures.append("the filter should be disengaged by 'any'/None: %s" % title[:40])

total = len(KEEP) + len(DROP) + 3 + len(DROP) + len(both_keep) + len(both_drop) + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
