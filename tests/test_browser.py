"""Unit tests for the browser lane's pure helpers (no network, no Chromium).

Run with:  python3 -m tests.test_browser
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.browser import (  # noqa: E402
    _dig, _field, _guess_location, _urls_for, _harvest_capture,
)

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%-42s got %r, want %r" % (label, got, want))


# --- _dig: dotted paths, stepping through single-element lists -------------- #
payload = {"targetedJobs": {"data": {"jobs": [{"title": "A"}, {"title": "B"}]}}}
check("_dig nested", _dig(payload, "targetedJobs.data.jobs"), [{"title": "A"}, {"title": "B"}])
check("_dig missing", _dig(payload, "targetedJobs.nope.jobs"), None)
check("_dig through list", _dig({"items": [{"reqs": [1, 2]}]}, "items.reqs"), [1, 2])

# --- _field: single key, joined keys, missing ------------------------------- #
rec = {"city": "London", "country": "UK", "title": "  Summer   Analyst ", "empty": ""}
check("_field single", _field(rec, "title"), "Summer Analyst")
check("_field joined", _field(rec, ["city", "country"]), "London, UK")
check("_field skips blanks", _field(rec, ["empty", "city"]), "London")
check("_field none", _field(rec, None), None)

# --- _urls_for: explicit list, template + pages, single ---------------------- #
check("_urls_for list", _urls_for({"urls": ["a", "b"]}), ["a", "b"])
check("_urls_for single", _urls_for({"url": "a"}), ["a"])
check("_urls_for template",
      _urls_for({"url_template": "x?p={page}", "pages": 3}),
      ["x?p=1", "x?p=2", "x?p=3"])
check("_urls_for zero-based",
      _urls_for({"url_template": "x?f={page}", "pages": 2, "first_page": 0}),
      ["x?f=0", "x?f=1"])

# --- _guess_location: pick the location line out of a card ------------------ #
card = "Summer Analyst, Markets\nNew York, NY\nSave job\nPosted 3 days ago"
check("_guess_location basic", _guess_location(card, "Summer Analyst, Markets", None),
      "New York, NY")
check("_guess_location skips noise",
      _guess_location("Finance Intern\nSave\nApply now", "Finance Intern", None), "")
check("_guess_location hint",
      _guess_location("Finance Intern\nRemote - Global\nSave", "Finance Intern", "remote"),
      "Remote - Global")

# --- _harvest_capture: JSON payload -> normalised jobs ---------------------- #
cfg = {
    "list_path": "targetedJobs.data.jobs",
    "base_url": "https://careers.example.com/",
    "fields": {"id": "jobid", "title": "title", "url": "applyurl",
               "location": ["city", "country"], "posted": "datecreated"},
}
captured = [{"targetedJobs": {"data": {"jobs": [
    {"jobid": "77", "title": "Consulting Intern", "applyurl": "/global/en/job/77",
     "city": "Milan", "country": "Italy", "datecreated": "2026-08-20"},
    {"jobid": "78", "title": "", "applyurl": "/global/en/job/78"},          # no title
]}}}]
jobs = _harvest_capture(captured, cfg, "BCG")
check("_harvest_capture count", len(jobs), 1)
check("_harvest_capture title", jobs[0]["title"], "Consulting Intern")
check("_harvest_capture location", jobs[0]["location"], "Milan, Italy")
check("_harvest_capture absolute url", jobs[0]["url"],
      "https://careers.example.com/global/en/job/77")
check("_harvest_capture id", jobs[0]["id"], "browser:BCG:77")
check("_harvest_capture posted", jobs[0]["posted_at"], "2026-08-20")
check("_harvest_capture bad path",
      _harvest_capture(captured, dict(cfg, list_path="no.such.path"), "BCG"), [])

total = 22
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
