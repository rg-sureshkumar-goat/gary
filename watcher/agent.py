"""Entry point: poll every configured career site, diff against what we've
already seen, and text the new corporate-finance / consulting internships.

    python3 -m watcher.agent run [--dry-run] [--seed] [--only NAME]
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import sys

from . import aging
from . import browser as browser_lane
from . import notifier
from . import reminders as reminder_lib
from .matcher import filter_jobs
from .sources import fetch_company

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state", "seen.json")
PRUNE_AFTER_DAYS = 120


def today():
    return datetime.date.today().isoformat()


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def load_config(path=CONFIG_PATH):
    with open(path) as fh:
        return json.load(fh)


def load_state(path=STATE_PATH):
    try:
        with open(path) as fh:
            state = json.load(fh)
    except (IOError, ValueError):
        state = {}
    state.setdefault("seen", {})       # job id -> {"f": first seen, "l": last seen}
    state.setdefault("broken", {})     # company -> last error reported
    state.setdefault("seeded_companies", [])  # companies whose backlog we've absorbed
    state.setdefault("reminders_sent", [])    # expiry warnings already delivered
    state.setdefault("recommended", {})       # job id -> date last recommended
    state.setdefault("reported", [])          # job ids actually texted to the user

    # "seen" is an observation log used to age postings; it is not proof the
    # user was ever told. Keeping them separate means a role absorbed under the
    # old silent-onboarding behaviour still gets reported.

    # Older state stored a bare date string. Treat it as both first and last
    # sighting so long-open detection still has something to work with.
    for job_id, value in list(state["seen"].items()):
        if not isinstance(value, dict):
            state["seen"][job_id] = {"f": value, "l": value}
    return state


def save_state(state, path=STATE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _last_seen(record):
    if isinstance(record, dict):
        return record.get("l") or record.get("f") or ""
    return record or ""


def prune(state):
    """Forget postings we haven't seen in a long time, so the file stays small."""
    cutoff = (datetime.date.today() -
              datetime.timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items()
                     if _last_seen(v) >= cutoff}
    state["recommended"] = {k: v for k, v in state.get("recommended", {}).items()
                            if k in state["seen"]}
    state["reported"] = sorted(set(state.get("reported", [])) & set(state["seen"]))


def select_shard(companies, spec):
    """Take slice i of N, splitting by a stable hash of the company name.

    Hashing the name rather than slicing the list means a company keeps its
    shard as the list grows, so newly harvested employers don't reshuffle
    everyone else and cause the same sites to be re-checked back to back.
    """
    try:
        index, total = (int(part) for part in str(spec).split("/", 1))
    except ValueError:
        raise SystemExit("--shard must look like 3/8, got %r" % spec)
    if total < 1 or not (0 <= index < total):
        raise SystemExit("--shard %r is out of range" % spec)
    picked = []
    for company in companies:
        digest = hashlib.sha1(company["name"].encode("utf-8")).hexdigest()
        if int(digest[:8], 16) % total == index:
            picked.append(company)
    return picked


def collect(companies, workers=8, headless=True):
    """Fetch every company. Returns (jobs, {company: error}).

    Plain-HTTP sites run in parallel. Browser-lane sites run sequentially in a
    single shared browser -- cheaper than a browser per site, and Playwright's
    sync API doesn't belong in a thread pool.
    """
    http_sites = [c for c in companies if c.get("ats") != "browser"]
    browser_sites = [c for c in companies if c.get("ats") == "browser"]

    jobs, errors = [], {}

    if http_sites:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_company, c): c for c in http_sites}
            for future in concurrent.futures.as_completed(futures):
                company = futures[future]
                try:
                    found, error = future.result()
                except Exception as exc:                  # pragma: no cover
                    found, error = [], "%s: %s" % (type(exc).__name__, exc)
                if error:
                    errors[company["name"]] = error
                    log("  %-28s FAILED (%s)" % (company["name"], error))
                else:
                    log("  %-28s %d postings" % (company["name"], len(found)))
                    jobs.extend(found)

    if browser_sites:
        log("Browser lane: %d site(s)" % len(browser_sites))
        results = browser_lane.fetch_all(browser_sites, headless=headless, log=log)
        for name, (found, error) in results.items():
            if error:
                errors[name] = error
            jobs.extend(found)

    return jobs, errors


def run(args):
    config = load_config(args.config)
    state = load_state(args.state)

    companies = [c for c in config["companies"] if c.get("enabled", True)]

    if args.tier != "all":
        companies = [c for c in companies
                     if c.get("tier", "core") == args.tier]

    if args.shard:
        companies = select_shard(companies, args.shard)

    if args.no_browser:
        companies = [c for c in companies if c.get("ats") != "browser"]
    if args.only_browser:
        companies = [c for c in companies if c.get("ats") == "browser"]
    if not companies:
        log("No companies selected; nothing to do.")
        return 0
    if args.only:
        wanted = args.only.lower()
        companies = [c for c in companies if wanted in c["name"].lower()]
        if not companies:
            log("No company matches %r" % args.only)
            return 1

    # Fail fast on a bad secret rather than after minutes of fetching.
    if not args.dry_run:
        problem = notifier.check_credentials(args.token, args.chat_id)
        if problem:
            log("Telegram is not configured correctly:")
            log("   %s" % problem)
            log("Set both secrets under Settings > Secrets and variables > "
                "Actions, then run this workflow again.")
            return 2
        log("Telegram credentials verified.")

    log("Checking %d career sites..." % len(companies))
    all_jobs, errors = collect(companies, config.get("workers", 8),
                               headless=not args.headed)
    log("Fetched %d postings total" % len(all_jobs))

    matches = filter_jobs(all_jobs, config["rules"])
    log("%d match the internship filters" % len(matches))

    seen = state["seen"]

    # A company we've never checked before arrives with a full backlog of open
    # roles. Those aren't news -- absorb them quietly and only report what the
    # company posts from here on. Without this, every expansion run would send
    # a flood.
    seeded = set(state["seeded_companies"])
    fresh_companies = sorted(c["name"] for c in companies if c["name"] not in seeded)

    # Every matching role Gary has not already reported, including the backlog
    # a newly watched employer arrives with. Those roles are open and they
    # match, so they get reported with their details like any other -- what
    # keeps a bulk onboarding manageable is the per-run cap below, not silence.
    reported = set(state["reported"])
    pending = [j for j in matches if j["id"] not in reported]

    cap = config["rules"].get("max_alerts_per_run", 40)
    new_jobs = pending[:cap] if cap else pending
    deferred = pending[len(new_jobs):]

    log("%d matching role(s) not yet reported" % len(pending))
    if deferred:
        log("   sending %d now, %d will follow on later runs"
            % (len(new_jobs), len(deferred)))
    if fresh_companies:
        log("%d newly watched company/companies" % len(fresh_companies))

    first_run = not seen
    if first_run and not args.seed:
        log("First run with an empty state file -- seeding instead of notifying.")

    # --- notify -------------------------------------------------------------
    if args.dry_run:
        for job in new_jobs:
            print("  NEW  %-30s %-60s %s" % (job["company"], job["title"], job["url"]))
        if not new_jobs:
            print("  (nothing new)")
    elif args.seed or first_run:
        token, chat = args.token, args.chat_id
        if token and chat:
            notifier.send(token, chat, (
                "✅ <b>Gary is live.</b>\n"
                "I'm watching %d career sites. %d matching US roles are open "
                "right now; I'll only text you about ones posted from here on."
                % (len(companies), len(matches))
            ))
    elif new_jobs or fresh_companies:
        token, chat = args.token, args.chat_id
        if not (token and chat):
            log("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set.")
            return 2
        if new_jobs:
            header = None
            if deferred:
                header = ("🔔 <b>%d new internship%s</b>\n<i>%d more queued; "
                          "they'll arrive on the next run.</i>"
                          % (len(new_jobs), "" if len(new_jobs) == 1 else "s",
                             len(deferred)))
            count = notifier.notify(token, chat, new_jobs, header=header)
            log("Sent %d Telegram message(s)." % count)
        if fresh_companies and args.announce_new_companies:
            names = ", ".join(notifier.esc(n) for n in fresh_companies[:12])
            more = "" if len(fresh_companies) <= 12 else \
                   " and %d more" % (len(fresh_companies) - 12)
            try:
                notifier.send(token, chat,
                              "🛰 <b>Gary is now watching:</b> %s%s."
                              % (names, more))
            except Exception as exc:
                log("Could not send the new-company notice: %s" % exc)

    # --- everything currently open, on request -------------------------------
    # The watch lanes only ever report roles Gary has not seen before, so a
    # role that was already posted when Gary started watching an employer is
    # absorbed and never mentioned. This is how you see those.
    if args.send_open:
        log("%d role(s) currently open and matching" % len(matches))
        if args.dry_run:
            for job in matches[:60]:
                print("  OPEN  %-26s %-56s %s" % (job["company"][:26],
                                                  job["title"][:54], job["url"][:60]))
        elif matches and args.token and args.chat_id:
            header = ("📋 <b>%d open role%s</b>\n<i>Everything matching right "
                      "now, including roles posted before Gary started "
                      "watching.</i>"
                      % (len(matches), "" if len(matches) == 1 else "s"))
            for message in notifier.build_messages(matches, header=header):
                notifier.send(args.token, args.chat_id, message)
            log("Sent the open-roles catalogue.")

    # --- long-open roles, still accepting applications -----------------------
    if args.recommend_aged:
        aged = aging.select_aged(matches, seen, min_days=args.min_age_days,
                                 recommended=state["recommended"])
        log("%d role(s) open %d+ days and still listed"
            % (len(aged), args.min_age_days))
        if args.dry_run:
            for job in aged[:40]:
                print("  AGED %4dd  %-26s %s" % (job["days_open"],
                                                 job["company"][:26],
                                                 job["title"][:56]))
        elif aged and args.token and args.chat_id:
            stamp = today()
            for message in notifier.build_aged_messages(aged, args.min_age_days):
                notifier.send(args.token, args.chat_id, message)
            for job in aged:
                state["recommended"][job["id"]] = stamp
            log("Sent the long-open digest.")

    # --- dated reminders (credentials that are about to lapse) ---------------
    sent_keys = set(state["reminders_sent"])
    pending = reminder_lib.due(config.get("reminders"), sent_keys)
    if pending and args.dry_run:
        for _key, text in pending:
            print("  REMIND  %s" % text.replace("\n", " ").replace("<b>", "")
                                      .replace("</b>", ""))
    elif pending and args.token and args.chat_id:
        for key, text in pending:
            try:
                notifier.send(args.token, args.chat_id, text)
                state["reminders_sent"].append(key)
            except Exception as exc:
                log("Could not send reminder %r: %s" % (key, exc))

    # --- flag newly-broken sources so failures aren't silent -----------------
    newly_broken = {c: e for c, e in errors.items() if state["broken"].get(c) != e}
    if newly_broken and not args.dry_run and args.token and args.chat_id and not first_run:
        lines = ["⚠️ <b>Career sites I couldn't read this run</b>"]
        lines += ["  • %s — <i>%s</i>" % (notifier.esc(c), notifier.esc(e))
                  for c, e in sorted(newly_broken.items())]
        lines.append("\nTheir config may need updating; other sites are unaffected.")
        try:
            notifier.send(args.token, args.chat_id, "\n".join(lines))
        except Exception as exc:
            log("Could not send the failure notice: %s" % exc)

    # --- persist ------------------------------------------------------------
    if not args.dry_run:
        stamp = today()
        # Every match updates the observation log, which is what dates a
        # posting for the long-open digest.
        for job in matches:
            record = seen.get(job["id"])
            if isinstance(record, dict):
                record["l"] = stamp
            else:
                # First sighting: anchor the age clock at the board's own
                # posted date when it gives one, so a role that was already
                # months old when Gary arrived isn't treated as brand new.
                posted = aging.parse_posted(job.get("posted_at"))
                first = stamp
                if posted and posted[1]:
                    first = (datetime.date.today()
                             - datetime.timedelta(days=posted[0])).isoformat()
                seen[job["id"]] = {"f": first, "l": stamp}
        # Only roles actually sent count as reported; deferred ones stay in
        # the queue and go out on a later run.
        if not (first_run or args.seed):
            reported |= {j["id"] for j in new_jobs}
        else:
            reported |= {j["id"] for j in matches}
        state["reported"] = sorted(reported)
        state["seeded_companies"] = sorted(seeded | {c["name"] for c in companies})
        state["broken"] = errors
        state["last_run"] = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        state["last_run_stats"] = {
            "sites": len(companies),
            "postings": len(all_jobs),
            "matching": len(matches),
            "new": 0 if (first_run or args.seed) else len(new_jobs),
            "failed": len(errors),
        }
        prune(state)
        save_state(state, args.state)
        log("State saved (%d ids tracked)." % len(state["seen"]))

    return 0


def build_parser():
    """Exposed so the workflow tests can check the commands CI actually runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run", choices=["run"])
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--state", default=STATE_PATH)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent; touch nothing")
    parser.add_argument("--seed", action="store_true",
                        help="mark everything currently open as already seen")
    parser.add_argument("--only", help="limit to companies whose name contains this")
    parser.add_argument("--tier", choices=["core", "wide", "all"], default="all",
                        help="core = the curated finance/consulting list; "
                             "wide = employers discovered by harvesting")
    parser.add_argument("--shard",
                        help="process one slice of the list, as i/N (e.g. 3/8). "
                             "Lets a large watch list be swept in rotation "
                             "without any single run running long.")
    parser.add_argument("--headed", action="store_true",
                        help="show the browser window (browser lane, debugging)")
    parser.add_argument("--no-browser", action="store_true",
                        help="skip browser-lane sites entirely")
    parser.add_argument("--only-browser", action="store_true",
                        help="run only the browser-lane sites")
    parser.add_argument("--send-open", action="store_true",
                        help="send every currently-open matching role, not "
                             "just ones Gary hasn't reported before")
    parser.add_argument("--recommend-aged", action="store_true",
                        help="send a digest of roles that have been open a "
                             "long time and are still listed")
    parser.add_argument("--min-age-days", type=int, default=60,
                        help="how long a role must have been open to be "
                             "recommended (default 60)")
    parser.add_argument("--quiet-new-companies", dest="announce_new_companies",
                        action="store_false", default=True,
                        help="don't announce newly watched employers")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    args.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
