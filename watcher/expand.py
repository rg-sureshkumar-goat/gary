"""Grow the company list automatically.

Many employers haven't opened their internship applications yet, so a
hand-written roster goes stale. This walks `candidates.json`, works out which
employers expose a readable job board, and appends the ones that do to
config.json.

    python3 -m watcher.expand              # onboard whatever it can find
    python3 -m watcher.expand --dry-run    # report, change nothing
    python3 -m watcher.expand --retry-all  # re-probe candidates that failed before

Candidates that don't resolve are recorded with a timestamp and retried later
(default every 30 days), because companies migrate between platforms and a
board that didn't exist in September often exists in October.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import re
import sys
import urllib.parse

from . import notifier
from .http import fetch, fetch_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
CANDIDATES_PATH = os.path.join(ROOT, "candidates.json")
LEDGER_PATH = os.path.join(ROOT, "state", "expansion.json")

RETRY_AFTER_DAYS = 30

# A board with a handful of postings is nearly always the wrong one: a dormant
# board, a test tenant, or another company that happens to own the slug.
MIN_BOARD_SIZE = 5

# Dropped before comparing a board's declared name with the company's.
_NOISE_WORDS = {"the", "inc", "incorporated", "corp", "corporation", "co",
                "company", "group", "holdings", "plc", "llc", "ltd", "limited",
                "lp", "llp", "partners", "and", "of", "global", "international",
                "worldwide", "us", "usa", "america", "american", "na"}

WD_RE = re.compile(
    r"([a-z0-9\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[^/]+/)?"
    r"(?:([a-zA-Z\-]{2,5})/)?([A-Za-z0-9_\-]+)")

# Workday sites whose names tell us they carry student roles get priority.
CAMPUS_HINTS = ("campus", "student", "university", "graduate", "intern", "early")


def log(msg):
    print(msg, flush=True)


def _norm_name(text):
    words = re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()).split()
    kept = [w for w in words if w not in _NOISE_WORDS]
    return "".join(kept or words)


def names_agree(claimed, expected):
    """Does a board's own name plausibly belong to the company we wanted?

    Greenhouse hands out slugs first-come, so the token `disney` belongs to a
    board actually called "Sgt. Pepper's Lonely Hearts Club Band". Without this
    check the watcher would happily report that board's jobs as Disney's.
    """
    a, b = _norm_name(claimed), _norm_name(expected)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    # Fall back to first-word agreement, so "Kimberly Clark" matches
    # "Kimberly-Clark Corporation".
    return a[:6] == b[:6] and min(len(a), len(b)) >= 6


def board_identity(entry):
    """The name a board declares for itself, or None if it doesn't say."""
    ats, token = entry.get("ats"), entry.get("token")
    try:
        if ats == "greenhouse":
            d = fetch_json("https://boards-api.greenhouse.io/v1/boards/%s" % token,
                           timeout=12, retries=0)
            return d.get("name")
        if ats == "smartrecruiters":
            d = fetch_json(
                "https://api.smartrecruiters.com/v1/companies/%s/postings?limit=1"
                % token, timeout=12, retries=0)
            content = d.get("content") or []
            if content:
                return (content[0].get("company") or {}).get("name")
    except Exception:
        return None
    return None


def slugs_for(candidate):
    """Plausible board tokens for a company, most likely first."""
    name = candidate["name"].lower()
    domain = candidate.get("domain", "")
    base = re.sub(r"[^a-z0-9 ]", "", name).strip()
    root = domain.split(".")[0] if domain else ""

    out = []
    for value in (root, base.replace(" ", ""), base.replace(" ", "-"),
                  base.split(" ")[0]):
        value = re.sub(r"[^a-z0-9\-]", "", value or "")
        if value and value not in out and len(value) > 2:
            out.append(value)
    return out[:4]


# --------------------------------------------------------------------------- #
# Probes
# --------------------------------------------------------------------------- #
def _greenhouse(slug):
    d = fetch_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % slug,
                   timeout=12, retries=0)
    n = len(d.get("jobs", []))
    return ({"ats": "greenhouse", "token": slug}, n) if n else None


def _lever(slug):
    d = fetch_json("https://api.lever.co/v0/postings/%s?mode=json" % slug,
                   timeout=12, retries=0)
    return ({"ats": "lever", "token": slug}, len(d)) if isinstance(d, list) and d else None


def _ashby(slug):
    d = fetch_json("https://api.ashbyhq.com/posting-api/job-board/%s" % slug,
                   timeout=12, retries=0)
    n = len(d.get("jobs", []))
    return ({"ats": "ashby", "token": slug}, n) if n else None


def _smartrecruiters(slug):
    d = fetch_json(
        "https://api.smartrecruiters.com/v1/companies/%s/postings?limit=1" % slug,
        timeout=12, retries=0)
    n = d.get("totalFound") or 0
    return ({"ats": "smartrecruiters", "token": slug}, n) if n else None


TOKEN_PROBES = (_greenhouse, _lever, _ashby, _smartrecruiters)


def _workday_jobs(host, site, search=""):
    tenant = host.split(".")[0]
    d = fetch_json("https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site),
                   method="POST",
                   payload={"appliedFacets": {}, "limit": 1, "offset": 0,
                            "searchText": search},
                   headers={"Origin": "https://%s" % host,
                            "Referer": "https://%s/en-US/%s" % (host, site)},
                   timeout=14, retries=0)
    if "jobPostings" not in d:
        return None
    return d.get("total", 0)


def _workday_from_careers(candidate):
    """Follow a company's careers page and pick up a Workday host/site."""
    domain = candidate.get("domain")
    if not domain:
        return None
    seen = set()
    for url in ("https://careers.%s" % domain,
                "https://jobs.%s" % domain,
                "https://www.%s/careers" % domain):
        try:
            body = fetch(url, timeout=18, retries=0)
        except Exception:
            continue
        found = []
        for match in WD_RE.finditer(url + " " + body[:250000]):
            tenant, wd, _lang, site = match.groups()
            if site.lower() in ("en-us", "en", "wday", "cxs", "job", "jobs"):
                continue
            host = "%s.%s.myworkdayjobs.com" % (tenant, wd)
            if (host, site) in seen:
                continue
            seen.add((host, site))
            found.append((host, site))
        # Prefer a campus/student board when the company runs several.
        found.sort(key=lambda hs: 0 if any(h in hs[1].lower() for h in CAMPUS_HINTS) else 1)
        for host, site in found[:4]:
            try:
                total = _workday_jobs(host, site)
            except Exception:
                continue
            if total:
                return {"ats": "workday", "host": host, "site": site,
                        "searches": ["intern", "summer analyst"]}, total
    return None


BOARD_FIELDS = ("ats", "token", "host", "site", "searches", "max_results", "tier")


def _verify_known_board(candidate):
    """Check a board that was read off an apply URL rather than guessed.

    Harvested candidates already carry an exact token or host, so there is no
    slug ambiguity -- but the board still has to be real and non-trivial.
    """
    entry = {k: candidate[k] for k in BOARD_FIELDS if k in candidate}
    ats = entry.get("ats")
    if ats == "workday":
        try:
            total = _workday_jobs(entry["host"], entry["site"])
        except Exception:
            return None
        return (entry, total) if total and total >= MIN_BOARD_SIZE else None

    probes = {"greenhouse": _greenhouse, "lever": _lever,
              "ashby": _ashby, "smartrecruiters": _smartrecruiters}
    fn = probes.get(ats)
    if not fn or not entry.get("token"):
        return None
    try:
        hit = fn(entry["token"])
    except Exception:
        return None
    if not hit or hit[1] < MIN_BOARD_SIZE:
        return None
    claimed = board_identity(entry)
    if claimed is not None and not names_agree(claimed, candidate["name"]):
        return None
    return (entry, hit[1])


def probe(candidate):
    """Return (config_entry, board_size) or None.

    A token match alone is not proof of identity -- slugs are handed out
    first-come -- so a board must also be big enough to be real and, where the
    platform will tell us, must name the company we were looking for.
    """
    if candidate.get("ats"):
        return _verify_known_board(candidate)

    for slug in slugs_for(candidate):
        for probe_fn in TOKEN_PROBES:
            try:
                hit = probe_fn(slug)
            except Exception:
                hit = None
            if not hit:
                continue
            entry, size = hit
            if size < MIN_BOARD_SIZE:
                continue
            claimed = board_identity(entry)
            if claimed is not None and not names_agree(claimed, candidate["name"]):
                log("  - %-30s rejected: %r board is %r"
                    % (candidate["name"], entry["ats"], claimed))
                continue
            return hit
    try:
        return _workday_from_careers(candidate)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Ledger + config
# --------------------------------------------------------------------------- #
def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def already_have(config, candidate, entry=None):
    """Is this employer (or this exact board) already in the config?"""
    name = candidate["name"].lower()
    short = re.sub(r"[^a-z0-9]", "", name.split("(")[0])[:12]
    for existing in config["companies"]:
        current = re.sub(r"[^a-z0-9]", "", existing["name"].lower())
        if short and short in current:
            return True
        if entry:
            if entry.get("token") and existing.get("token") == entry["token"] \
                    and existing.get("ats") == entry.get("ats"):
                return True
            if entry.get("host") and existing.get("host") == entry["host"] \
                    and existing.get("site") == entry.get("site"):
                return True
    return False


def due(ledger, name, retry_all):
    if retry_all:
        return True
    record = ledger.get("tried", {}).get(name)
    if not record:
        return True
    if record.get("result") == "added":
        return False
    last = record.get("last", "")
    cutoff = (datetime.date.today() -
              datetime.timedelta(days=RETRY_AFTER_DAYS)).isoformat()
    return last < cutoff


def board_size(entry):
    """How many postings a board currently carries, or None if unreadable."""
    probes = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby,
              "smartrecruiters": _smartrecruiters}
    fn = probes.get(entry.get("ats"))
    if not fn or not entry.get("token"):
        return None
    try:
        hit = fn(entry["token"])
    except Exception:
        return 0
    return hit[1] if hit else 0


def _audit_one(company):
    """Return a reason string if this entry looks wrong, else None."""
    size = board_size(company)
    if size is not None and size < MIN_BOARD_SIZE:
        return "only %d posting(s) on the board" % size
    if company.get("ats") in ("greenhouse", "smartrecruiters"):
        claimed = board_identity(company)
        if claimed is None:
            return "board metadata unavailable"
        if not names_agree(claimed, company["name"]):
            return "board calls itself %r" % claimed
    return None


def audit(args):
    """Re-check every token-based company already in the config.

    Boards get renamed, retired, or reassigned to a different owner, so an entry
    that was right in September can be wrong in October.
    """
    config = load_json(args.config, None)
    if config is None:
        log("Could not read %s" % args.config)
        return 1

    suspect = []
    checkable = [c for c in config["companies"]
                 if c.get("ats") in ("greenhouse", "lever", "ashby", "smartrecruiters")]
    log("Auditing %d token-based board(s)..." % len(checkable))

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_audit_one, c): c for c in checkable}
        for future in concurrent.futures.as_completed(futures):
            company = futures[future]
            try:
                reason = future.result()
            except Exception as exc:
                reason = "audit failed: %s" % type(exc).__name__
            if reason:
                suspect.append((company, reason))

    if not suspect:
        log("Every audited board matches its company.")
        return 0

    for company, why in sorted(suspect, key=lambda s: s[0]["name"]):
        log("  ? %-30s %-14s %s" % (company["name"], company.get("ats"), why))

    if args.prune:
        drop = {(c["name"], c.get("token")) for c, _ in suspect}
        before = len(config["companies"])
        config["companies"] = [c for c in config["companies"]
                               if (c["name"], c.get("token")) not in drop]
        if not args.dry_run:
            save_json(args.config, config)
        log("Removed %d entr%s (%d -> %d)"
            % (before - len(config["companies"]),
               "y" if before - len(config["companies"]) == 1 else "ies",
               before, len(config["companies"])))
    else:
        log("\nRe-run with --prune to remove these.")
    return 0


def run(args):
    config = load_json(args.config, None)
    if config is None:
        log("Could not read %s" % args.config)
        return 1
    candidates = load_json(args.candidates, {}).get("candidates", [])
    ledger = load_json(args.ledger, {})
    ledger.setdefault("tried", {})

    todo = [c for c in candidates
            if due(ledger, c["name"], args.retry_all) and not already_have(config, c)]
    if args.limit:
        todo = todo[:args.limit]

    log("%d candidate(s) to probe (of %d seeded)" % (len(todo), len(candidates)))
    if not todo:
        return 0

    added, today = [], datetime.date.today().isoformat()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe, c): c for c in todo}
        for future in concurrent.futures.as_completed(futures):
            candidate = futures[future]
            name = candidate["name"]
            try:
                hit = future.result()
            except Exception:
                hit = None

            if not hit:
                ledger["tried"][name] = {"last": today, "result": "none"}
                continue

            entry_bits, size = hit
            if already_have(config, candidate, entry_bits):
                ledger["tried"][name] = {"last": today, "result": "duplicate"}
                continue

            entry = {"name": name, "category": candidate.get("category", "corporate")}
            if candidate.get("tier"):
                entry["tier"] = candidate["tier"]
            entry.update(entry_bits)
            added.append((entry, size))
            ledger["tried"][name] = {"last": today, "result": "added",
                                     "ats": entry_bits.get("ats")}
            log("  + %-32s %-16s %d postings" % (name, entry_bits["ats"], size))

    if not added:
        log("No new boards found this pass.")
    if added and not args.dry_run:
        config["companies"].extend(e for e, _ in added)
        save_json(args.config, config)
        log("Added %d company/companies to %s" % (len(added), args.config))

    if not args.dry_run:
        ledger["last_run"] = today
        save_json(args.ledger, ledger)

    # Tell the user which employers just joined the watch list.
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if added and token and chat and not args.dry_run:
        lines = ["🛰 <b>Gary is now watching %d more employer%s</b>"
                 % (len(added), "" if len(added) == 1 else "s")]
        for entry, size in sorted(added, key=lambda a: a[0]["name"]):
            lines.append("  • %s <i>(%s, %d roles on the board)</i>"
                         % (notifier.esc(entry["name"]),
                            notifier.esc(entry["ats"]), size))
        lines.append("\nAny US finance or consulting internship they post from "
                     "now on will reach you.")
        try:
            notifier.send(token, chat, "\n".join(lines))
        except Exception as exc:
            log("Could not send the expansion notice: %s" % exc)

    # Leave a machine-readable trace so the workflow can report it.
    if args.report:
        save_json(args.report, {"added": [e["name"] for e, _ in added]})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--candidates", default=CANDIDATES_PATH)
    parser.add_argument("--ledger", default=LEDGER_PATH)
    parser.add_argument("--report", help="write the list of added names here")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-all", action="store_true",
                        help="ignore the retry window and re-probe everything")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--audit", action="store_true",
                        help="re-verify the boards already in config.json")
    parser.add_argument("--prune", action="store_true",
                        help="with --audit, remove entries that fail")
    args = parser.parse_args(argv)
    return audit(args) if args.audit else run(args)


if __name__ == "__main__":
    sys.exit(main())
