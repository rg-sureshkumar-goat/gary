"""Find employers Gary isn't watching yet.

`candidates.json` started as a hand-written list, which caps how far the watch
list can ever grow -- it can only ever onboard employers somebody thought to
name. This pulls fresh company names from public internship feeds instead.

The valuable part isn't the job listings (those are mostly software roles Gary
would filter out anyway); it's the **apply URLs**. Those point straight at each
employer's job board, so the exact Greenhouse token or Workday host/site can be
read off rather than guessed. A board resolved this way is far more reliable
than one found by slug-guessing a company name.

Harvested candidates still go through the expander's verification -- board size
and declared identity -- before Gary watches them.

    python3 -m watcher.harvest            # merge new candidates
    python3 -m watcher.harvest --dry-run  # report only
"""
import argparse
import json
import os
import re
import sys
import urllib.parse

from .http import fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
CANDIDATES_PATH = os.path.join(ROOT, "candidates.json")

# Public, machine-readable internship feeds. Each is a JSON array of postings
# with a company name and an apply URL.
FEEDS = [
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/vanshb03/Summer2026-Internships/dev/.github/scripts/listings.json",
]

BOARD_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)),
]

WORKDAY = re.compile(
    r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:([a-zA-Z-]{2,5})/)?([A-Za-z0-9_-]+)",
    re.I)

# Slugs that belong to a hosting quirk rather than a company.
BAD_TOKENS = {"embed", "job_board", "jobs", "careers", "en-us", "job", "search"}


def log(msg):
    print(msg, flush=True)


def board_from_url(url):
    """Read an employer's job board straight off an apply link."""
    if not url:
        return None

    m = WORKDAY.search(url)
    if m:
        host, _lang, site = m.groups()
        if site.lower() not in BAD_TOKENS:
            # One keyword and shallow paging: the wide tier is swept in
            # shards on a schedule, and a board that pages 300 results twice
            # over costs ~30 requests, which does not scale to thousands.
            return {"ats": "workday", "host": host.lower(), "site": site,
                    "searches": ["intern"], "max_results": 100}

    for ats, pattern in BOARD_PATTERNS:
        m = pattern.search(url)
        if m:
            token = m.group(1)
            if token.lower() in BAD_TOKENS or len(token) < 3:
                continue
            return {"ats": ats, "token": token}
    return None


def identity(entry):
    """A stable key for de-duplication, independent of company name."""
    if entry.get("token"):
        return (entry["ats"], entry["token"].lower())
    return (entry["ats"], entry.get("host", "").lower(), entry.get("site", "").lower())


def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def harvest_feed(url):
    """Return {identity: candidate} for one feed."""
    found = {}
    try:
        listings = json.loads(fetch(url, timeout=60))
    except Exception as exc:
        log("  could not read %s (%s)" % (url.split("/")[4], type(exc).__name__))
        return found

    considered = 0
    for item in listings:
        if not isinstance(item, dict):
            continue
        # Dead listings still name a real employer whose board is worth watching.
        if item.get("is_visible") is False:
            continue
        name = (item.get("company_name") or "").strip()
        if not name:
            continue
        board = board_from_url(item.get("url") or "")
        if not board:
            continue
        considered += 1
        entry = {"name": name, "category": "corporate", "source": "harvested",
                 "tier": "wide"}
        entry.update(board)
        found.setdefault(identity(entry), entry)

    log("  %-26s %5d listings -> %4d distinct boards"
        % (url.split("/")[4][:26], considered, len(found)))
    return found


def run(args):
    config = load_json(args.config, {"companies": []})
    doc = load_json(args.candidates, {"candidates": []})
    candidates = doc.setdefault("candidates", [])

    known = set()
    for company in config.get("companies", []):
        if company.get("ats") and (company.get("token") or company.get("host")):
            known.add(identity(company))
    for cand in candidates:
        if cand.get("ats") and (cand.get("token") or cand.get("host")):
            known.add(identity(cand))
    known_names = {re.sub(r"[^a-z0-9]", "", c["name"].lower())
                   for c in config.get("companies", [])}

    log("Reading %d public feed(s)..." % len(FEEDS))
    discovered = {}
    for url in FEEDS:
        discovered.update(harvest_feed(url))

    fresh = []
    for key, entry in discovered.items():
        if key in known:
            continue
        if re.sub(r"[^a-z0-9]", "", entry["name"].lower()) in known_names:
            continue
        fresh.append(entry)

    fresh.sort(key=lambda e: e["name"].lower())
    log("\n%d board(s) Gary isn't watching yet" % len(fresh))
    for entry in fresh[:15]:
        label = entry.get("token") or "%s/%s" % (entry.get("host"), entry.get("site"))
        log("   + %-32s %-16s %s" % (entry["name"][:32], entry["ats"], label[:44]))
    if len(fresh) > 15:
        log("   ... and %d more" % (len(fresh) - 15))

    if args.limit:
        fresh = fresh[:args.limit]

    if fresh and not args.dry_run:
        candidates.extend(fresh)
        save_json(args.candidates, doc)
        log("\nAdded %d candidate(s) to %s" % (len(fresh), os.path.basename(args.candidates)))
        log("The expander verifies each one before Gary watches it.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--candidates", default=CANDIDATES_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="cap how many new candidates to add in one pass")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
