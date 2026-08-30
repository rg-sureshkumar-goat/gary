"""Where the candidate says he heard about a role.

His rule is the employer's own website, or LinkedIn if that is not offered.
Employers word their own site differently every time -- "Company Website",
"Career Website", "Sila Website", "Tencent Careers Page" -- and matching those
one at a time is a list that never ends.

Gary knows which employer it is filling for, so an option naming that employer
beside a word for a website is that employer's site. A careers page is one
too. A career fair is not.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher import lists
from watcher.formfill import is_referral_question

CASES = [
    # Every wording seen on a real application today.
    ("Tencent", ["Select One", "Tencent Careers Page", "Employee Referral",
                 "Job Board", "Other"], "Tencent Careers Page"),
    ("Ecolab", ["Select One", "Social Media - LinkedIn", "Career Website",
                "Referral"], "Career Website"),
    ("Berkeley Research Group", ["Select One", "Career Website", "LinkedIn",
                                 "Job Fair"], "Career Website"),
    ("Sila Nanotechnologies", ["Select One", "Sila Website", "Indeed"],
     "Sila Website"),
    ("Acme", ["Select One", "Company Website", "LinkedIn"], "Company Website"),
    # No site offered: LinkedIn, as he asked.
    ("Acme", ["Select One", "Career Fair", "LinkedIn"], "LinkedIn"),
    # Neither offered: his to answer.
    ("Acme", ["Select One", "Employee Referral", "Newspaper"], None),
]

failures = []

for company, options, wanted in CASES:
    got = lists.heard_about_us(options, company)
    if got != wanted:
        failures.append("%s: %r gave %r, wanted %r"
                        % (company, options[1:3], got, wanted))

for question in ("How Did You Hear About Us?", "How did you find this job?",
                 "Referral Source", "Where did you hear about this role?"):
    if not is_referral_question(question):
        failures.append("%r was not recognised as the question" % question)
for question in ("What is your major?", "Are you willing to relocate?"):
    if is_referral_question(question):
        failures.append("%r was mistaken for the question" % question)

total = len(CASES) + 4 + 2
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
