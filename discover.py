#!/usr/bin/env python3
"""Work out which applicant-tracking system a company uses, and print a config
block you can paste straight into config.json.

    python3 discover.py stripe                       # try the name as a token
    python3 discover.py https://careers.example.com  # follow a careers URL

Add anything it finds to the "companies" list in config.json.
"""
import json
import re
import sys
import urllib.parse

from watcher.http import fetch, fetch_json

WD_RE = re.compile(r"([a-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:([a-zA-Z\-]{2,5})/)?([A-Za-z0-9_\-]+)")


def _slug(text):
    text = re.sub(r"^https?://", "", text.strip().lower())
    text = re.sub(r"^(www|jobs|careers|apply)\.", "", text)
    text = re.split(r"[/.]", text)[0]
    return re.sub(r"[^a-z0-9\-]", "", text)


def try_greenhouse(token):
    d = fetch_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % token,
                   timeout=15, retries=0)
    n = len(d.get("jobs", []))
    return {"ats": "greenhouse", "token": token}, n if n else None


def try_lever(token):
    d = fetch_json("https://api.lever.co/v0/postings/%s?mode=json" % token,
                   timeout=15, retries=0)
    return {"ats": "lever", "token": token}, len(d) if isinstance(d, list) and d else None


def try_ashby(token):
    d = fetch_json("https://api.ashbyhq.com/posting-api/job-board/%s" % token,
                   timeout=15, retries=0)
    n = len(d.get("jobs", []))
    return {"ats": "ashby", "token": token}, n if n else None


def try_smartrecruiters(token):
    d = fetch_json("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=1" % token,
                   timeout=15, retries=0)
    n = d.get("totalFound") or 0
    return {"ats": "smartrecruiters", "token": token}, n if n else None


TOKEN_PROBES = [try_greenhouse, try_lever, try_ashby, try_smartrecruiters]


def probe_workday(host, site):
    tenant = host.split(".")[0]
    api = "https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site)
    d = fetch_json(api, method="POST",
                   payload={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                   headers={"Origin": "https://%s" % host,
                            "Referer": "https://%s/en-US/%s" % (host, site)},
                   timeout=15, retries=0)
    total = d.get("total", 0)
    if "jobPostings" in d and total:
        return {"ats": "workday", "host": host, "site": site}, total
    return None, None


def from_url(url):
    """Follow a careers URL and pull a Workday host/site out of it or its HTML."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        body = fetch(url, timeout=25, retries=1)
    except Exception as exc:
        print("  could not load %s (%s)" % (url, type(exc).__name__))
        body = ""
    for m in WD_RE.finditer(url + " " + body[:300000]):
        tenant, wd, _lang, site = m.groups()
        if site.lower() in ("en-us", "en", "wday", "cxs", "job"):
            continue
        host = "%s.%s.myworkdayjobs.com" % (tenant, wd)
        try:
            cfg, total = probe_workday(host, site)
        except Exception:
            continue
        if cfg:
            return cfg, total
    return None, None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    target = argv[1]
    name = argv[2] if len(argv) > 2 else None
    hits = []

    if target.startswith("http") or "/" in target:
        cfg, total = from_url(target)
        if cfg:
            hits.append((cfg, total))
        token = _slug(target)
    else:
        token = _slug(target)

    for probe in TOKEN_PROBES:
        try:
            cfg, total = probe(token)
            if total:
                hits.append((cfg, total))
        except Exception:
            pass

    if not hits:
        print("No public job API found for %r." % target)
        print("Open the careers page, then DevTools > Network > Fetch/XHR, and look for")
        print("the request that returns the job list -- that URL is what the agent needs.")
        return 1

    print("Found %d source(s) for %r:\n" % (len(hits), target))
    for cfg, total in sorted(hits, key=lambda h: -(h[1] or 0)):
        entry = {"name": name or token.title(), "category": "corporate"}
        entry.update(cfg)
        print("  # %d postings on the board" % total)
        print("  " + json.dumps(entry) + ",")
    print("\nPaste the one you want into the \"companies\" list in config.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
