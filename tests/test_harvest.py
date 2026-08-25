"""Reading a job board off an apply URL.

This is what lets the watch list grow on its own: an apply link names the
employer's board exactly, so no slug has to be guessed. Getting a host or token
subtly wrong would add a company that silently returns nothing forever.

Run with:  python3 -m tests.test_harvest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.harvest import board_from_url, identity  # noqa: E402

failures = []


def check(url, expected):
    got = board_from_url(url)
    if expected is None:
        if got is not None:
            failures.append("expected no board for %r, got %r" % (url[:60], got))
        return
    if got is None:
        failures.append("no board found for %r" % url[:70])
        return
    for key, want in expected.items():
        if got.get(key) != want:
            failures.append("%s: %s was %r, expected %r"
                            % (url[:52], key, got.get(key), want))


# --- token boards ----------------------------------------------------------- #
check("https://boards.greenhouse.io/stripe/jobs/12345",
      {"ats": "greenhouse", "token": "stripe"})
check("https://job-boards.greenhouse.io/anthropic/jobs/999",
      {"ats": "greenhouse", "token": "anthropic"})
check("https://jobs.lever.co/voleon/abc-123",
      {"ats": "lever", "token": "voleon"})
check("https://jobs.ashbyhq.com/ramp/1a2b3c",
      {"ats": "ashby", "token": "ramp"})
check("https://jobs.smartrecruiters.com/RolandBerger/74400012",
      {"ats": "smartrecruiters", "token": "RolandBerger"})

# --- Workday: host and site both matter ------------------------------------- #
check("https://westernunion.wd5.myworkdayjobs.com/en-US/WesternUnionJobs/job/"
      "Denver/Software-Engineer-Intern_JR0128790",
      {"ats": "workday", "host": "westernunion.wd5.myworkdayjobs.com",
       "site": "WesternUnionJobs"})
# No language segment.
check("https://abbott.wd5.myworkdayjobs.com/abbottcareers/job/X/Analyst_123",
      {"ats": "workday", "host": "abbott.wd5.myworkdayjobs.com",
       "site": "abbottcareers"})
# Host casing must be normalised, or the same board is added twice.
check("https://ABBOTT.WD5.MyWorkdayJobs.com/en-US/abbottcareers/job/X/Y",
      {"host": "abbott.wd5.myworkdayjobs.com"})
# Workday entries need a keyword search, or the whole board is paged.
board = board_from_url("https://abbott.wd5.myworkdayjobs.com/en-US/abbottcareers/job/X/Y")
if not board.get("searches"):
    failures.append("Workday boards must carry a keyword search")
if not board.get("max_results"):
    failures.append("Workday boards must carry a page cap")

# --- things that are not boards --------------------------------------------- #
for url in ["https://simplify.jobs/c/Western-Union",
            "https://www.example.com/careers",
            "https://linkedin.com/jobs/view/123",
            "", None]:
    check(url, None)

# A hosting quirk must not become a company.
check("https://boards.greenhouse.io/embed/job_board?for=stripe",
      {"ats": "greenhouse", "token": "stripe"})

# --- de-duplication ---------------------------------------------------------- #
a = board_from_url("https://boards.greenhouse.io/stripe/jobs/1")
b = board_from_url("https://job-boards.greenhouse.io/stripe/jobs/2")
if identity(dict(a, name="Stripe")) != identity(dict(b, name="Stripe Inc")):
    failures.append("the same board reached by two URL shapes must de-duplicate")

w1 = board_from_url("https://abbott.wd5.myworkdayjobs.com/en-US/abbottcareers/job/A/B")
w2 = board_from_url("https://ABBOTT.wd5.myworkdayjobs.com/abbottcareers/job/C/D")
if identity(dict(w1, name="Abbott")) != identity(dict(w2, name="Abbott")):
    failures.append("Workday host casing must not defeat de-duplication")

# Different sites on one tenant are genuinely different boards.
w3 = board_from_url("https://abbott.wd5.myworkdayjobs.com/en-US/abbottcampus/job/A/B")
if identity(dict(w1, name="Abbott")) == identity(dict(w3, name="Abbott")):
    failures.append("different Workday sites must not collapse together")

total = 22
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
