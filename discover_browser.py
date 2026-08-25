#!/usr/bin/env python3
"""Work out how to read a career site that needs a real browser.

    .venv/bin/python discover_browser.py https://careers.example.com/search "Example"

Loads the page in Chromium and reports two things:

  * capture candidates - JSON the page fetched that contains a job list, with
    the dotted path to reach it and the field names on each record.
  * links candidates   - the href shapes that look like job detail pages.

Then it prints a config block for the "companies" list in config.json.
Pass --headed to watch it work.
"""
import collections
import json
import re
import sys
import urllib.parse

sys.path.insert(0, ".")
from watcher.browser import LAUNCH_ARGS, STEALTH, UA, _require_playwright  # noqa: E402

TITLE_KEYS = {"title", "jobtitle", "name", "positiontitle", "displayjobtitle"}
LOCATION_KEYS = {"location", "city", "country", "state", "locationstext", "region"}
URL_KEYS = {"applyurl", "url", "joburl", "canonicalpositionurl", "absolute_url", "link"}
ID_KEYS = {"jobid", "id", "jobseqno", "reqid", "requisitionid"}


def find_job_lists(obj):
    """Every (path, count, keys) where the list items look like job records."""
    out = []

    def walk(node, path):
        if isinstance(node, list):
            if node and isinstance(node[0], dict):
                keys = set()
                for item in node[:3]:
                    keys |= {k.lower() for k in item.keys()}
                if keys & TITLE_KEYS and len(keys) >= 4:
                    out.append((path or "$", len(node), sorted(keys)))
            for item in node[:2]:
                walk(item, path + "[]")
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + "." + key if path else key)

    walk(obj, "")
    return out


def pick(keys, candidates, default=None):
    for key in candidates:
        if key in keys:
            return key
    return default


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    url = args[0] if args[0].startswith("http") else "https://" + args[0]
    name = args[1] if len(args) > 1 else urllib.parse.urlparse(url).netloc
    headed = "--headed" in argv

    sync_playwright = _require_playwright()
    captures, link_counts, examples = [], collections.Counter(), {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=LAUNCH_ARGS)
        ctx = browser.new_context(user_agent=UA, locale="en-US",
                                  viewport={"width": 1440, "height": 1000})
        ctx.add_init_script(STEALTH)

        def on_response(resp):
            try:
                if "json" not in (resp.headers or {}).get("content-type", "").lower():
                    return
                if resp.status >= 400:
                    return
                body = resp.json()
            except Exception:
                return
            for path, count, keys in find_job_lists(body):
                captures.append((resp.url, path, count, keys))

        ctx.on("response", on_response)
        page = ctx.new_page()
        print("loading %s ..." % url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(9000)
            if "just a moment" in (page.title() or "").lower():
                print("   bot check detected, waiting it out...")
                page.wait_for_timeout(12000)
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(2500)
            print("   final url: %s" % page.url[:110])
            print("   title    : %s" % (page.title() or "")[:90])

            hrefs = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))")
            for href in hrefs:
                if not href:
                    continue
                # Generalise the path: /job/hong-kong/analyst/123 -> /job/*/*/*
                path = urllib.parse.urlparse(href).path
                parts = [p for p in path.split("/") if p]
                if not parts:
                    continue
                for depth in (1, 2):
                    if len(parts) > depth:
                        shape = "/" + "/".join(parts[:depth])
                        if re.search(r"job|career|vacan|position|opening|req",
                                     shape, re.I):
                            link_counts[shape] += 1
                            examples.setdefault(shape, href)
        except Exception as exc:
            print("   ERROR: %s: %s" % (type(exc).__name__, str(exc)[:140]))
        finally:
            browser.close()

    print("\n--- capture candidates ---")
    if not captures:
        print("   none (the page probably renders its jobs server-side)")
    best_capture = None
    seen = set()
    for resp_url, path, count, keys in sorted(captures, key=lambda c: -c[2]):
        key = (resp_url.split("?")[0], path)
        if key in seen:
            continue
        seen.add(key)
        print("   %s\n      path=%s  n=%d\n      keys=%s" % (
            resp_url[:120], path, count, keys[:14]))
        if best_capture is None and count >= 3:
            best_capture = (resp_url, path, keys)

    print("\n--- links candidates ---")
    for shape, count in link_counts.most_common(6):
        print("   %-34s %3d links   e.g. %s" % (shape, count, examples[shape][:70]))

    print("\n--- config block ---")
    if best_capture:
        resp_url, path, keys = best_capture
        keyset = set(keys)
        entry = {
            "name": name, "category": "consulting", "ats": "browser",
            "mode": "capture", "url": url,
            "capture": urllib.parse.urlparse(resp_url).path or resp_url,
            "list_path": path,
            "fields": {
                "id": pick(keyset, ID_KEYS),
                "title": pick(keyset, TITLE_KEYS, "title"),
                "url": pick(keyset, URL_KEYS),
                "location": [k for k in ("city", "state", "country") if k in keyset]
                            or pick(keyset, LOCATION_KEYS),
            },
            "wait_ms": 9000,
        }
    elif link_counts:
        shape = link_counts.most_common(1)[0][0]
        entry = {
            "name": name, "category": "consulting", "ats": "browser",
            "mode": "links", "url": url,
            "link_pattern": re.escape(shape) + "/",
            "wait_ms": 9000, "scroll": 2,
        }
    else:
        print("   Nothing found. Try --headed to watch what the page does.")
        return 1

    print("  " + json.dumps(entry) + ",")
    print("\nAdd `url_template` with a {page} placeholder plus `pages` to page through.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
