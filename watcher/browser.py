"""Playwright lane: career sites that plain HTTP can't read.

Some employers -- most of the big consultancies and banks -- either render their
job list with JavaScript or sit behind bot protection that rejects a plain
request. A real browser gets past both.

Two extraction modes, chosen per company in config.json:

  "capture"  Watch the JSON the page fetches for itself and read the job list
             straight out of it. Preferred: structured data, no DOM guessing.
             Needs `capture` (a URL fragment) and `list_path` (dotted path).

  "links"    After the page renders, collect the anchors whose href looks like a
             job detail page. Needs `link_pattern` (a regex). Survives restyling,
             because it keys off URL shape rather than CSS classes.

Playwright is imported lazily, so the rest of the agent still runs -- and the
stdlib HTTP lane still works -- on a machine that doesn't have it installed.
"""
import re
import urllib.parse

STEALTH = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins',   {get: () => [1, 2, 3, 4, 5]});
    window.chrome = {runtime: {}};
"""

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class BrowserUnavailable(RuntimeError):
    pass


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable(
            "playwright is not installed -- run: pip install playwright "
            "&& python -m playwright install chromium")
    return sync_playwright


def _clean(text):
    return " ".join(str(text or "").split())


def _dig(obj, path):
    """Walk a dotted path, stepping into single-element lists as needed."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _field(record, spec):
    """Read one field. A list of keys means 'join whichever are present'."""
    if spec is None:
        return None
    if isinstance(spec, list):
        parts = [_clean(record.get(k)) for k in spec]
        return ", ".join(p for p in parts if p)
    return _clean(record.get(spec))


def _urls_for(cfg):
    """Build the list of URLs to visit for one company.

    `page_step` matters: some boards paginate by page number (1, 2, 3) and
    others by row offset (0, 25, 50). Getting this wrong silently re-fetches
    page one, which looks like it works but returns almost nothing new.
    """
    if cfg.get("urls"):
        return list(cfg["urls"])
    template, pages = cfg.get("url_template"), cfg.get("pages")
    if template and pages:
        start = cfg.get("first_page", 1)
        step = cfg.get("page_step", 1)
        return [template.replace("{page}", str(start + i * step))
                for i in range(int(pages))]
    return [cfg["url"]]


# --------------------------------------------------------------------------- #
# Per-page work
# --------------------------------------------------------------------------- #
def _settle(page, cfg):
    """Give the page time to render, ride out a bot-check, and load more rows."""
    page.wait_for_timeout(cfg.get("wait_ms", 8000))

    # Cloudflare and friends show an interstitial first; wait it out once.
    for _ in range(cfg.get("challenge_retries", 2)):
        title = (page.title() or "").lower()
        if "just a moment" not in title and "checking your browser" not in title:
            break
        page.wait_for_timeout(8000)

    for _ in range(cfg.get("scroll", 0)):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1200)

    selector = cfg.get("click_more")
    if selector:
        for _ in range(cfg.get("click_more_times", 3)):
            try:
                button = page.query_selector(selector)
                if not button or not button.is_visible():
                    break
                button.click()
                page.wait_for_timeout(cfg.get("click_wait_ms", 2500))
            except Exception:
                break


def _harvest_capture(captured, cfg, company):
    """Pull job records out of the JSON payloads the page fetched."""
    fields = cfg.get("fields", {})
    base = cfg.get("base_url", "")
    out = []
    for payload in captured:
        records = _dig(payload, cfg["list_path"])
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            title = _field(rec, fields.get("title", "title"))
            if not title:
                continue
            href = _field(rec, fields.get("url", "applyurl")) or ""
            if href and not href.startswith("http"):
                href = urllib.parse.urljoin(base or cfg.get("url", ""), href)
            ident = _field(rec, fields.get("id")) or href or title
            out.append({
                "id": "browser:%s:%s" % (company, ident),
                "title": title,
                "location": _field(rec, fields.get("location")) or "",
                "url": href,
                "posted_at": (_field(rec, fields.get("posted")) or None),
            })
    return out


# Pull each job link together with the text of the card it sits in, so we can
# recover a location that lives in a sibling element rather than the anchor.
_LINK_JS = """
els => els.map(a => {
  let card = a, hops = 0;
  // Climb to the nearest element that looks like a result card.
  while (card.parentElement && hops < 5) {
    const p = card.parentElement;
    const tag = p.tagName.toLowerCase();
    const cls = (p.className || '').toString().toLowerCase();
    if (tag === 'li' || tag === 'article' ||
        /card|result|job|posting|tile|row/.test(cls)) { card = p; break; }
    card = p; hops++;
  }
  return [a.getAttribute('href'),
          (a.innerText || a.textContent || '').trim(),
          (card.innerText || '').trim()];
})
"""

# Lines that are chrome rather than a location.
# "new" must be the whole line -- otherwise this eats New York, New Jersey,
# New Delhi and every other location that starts with the word.
_NOISE = re.compile(r"^(?:new|apply|save|view|share)$"
                    r"|^(?:save|apply|view|share|learn more|read more|posted|"
                    r"job id|req(?:uisition)?\s*id|full[- ]time|part[- ]time)\b", re.I)


def _guess_location(card_text, title, hint):
    """Find the location line inside a job card's text."""
    lines = [l.strip() for l in (card_text or "").splitlines() if l.strip()]
    if hint:
        for line in lines:
            if re.search(hint, line, re.I):
                return line[:120]
    title_head = title[:40].lower()
    for line in lines:
        low = line.lower()
        if low.startswith(title_head) or low == title.lower():
            continue
        if _NOISE.match(line) or len(line) > 90 or len(line) < 3:
            continue
        # A location almost always carries a comma or a known separator.
        if "," in line or re.search(r"\b(remote|hybrid|onsite)\b", low):
            return line[:120]
    return ""


def _harvest_links(page, cfg, company):
    """Collect anchors whose href looks like a job detail page."""
    pattern = re.compile(cfg["link_pattern"], re.I)
    hint = cfg.get("location_hint")
    rows = page.eval_on_selector_all("a[href]", _LINK_JS)

    seen, out = set(), []
    for href, text, card_text in rows:
        if not href or not pattern.search(href):
            continue
        lines = [l.strip() for l in _clean_lines(text)]
        if not lines:
            continue
        title = lines[0]
        if len(title) < 4:
            continue
        full = urllib.parse.urljoin(page.url, href)
        if full in seen:
            continue
        seen.add(full)
        location = lines[1] if len(lines) > 1 and "," in lines[1] else ""
        if not location:
            location = _guess_location(card_text, title, hint)
        if not location and cfg.get("location_from_url"):
            # Some boards put the city in the URL: /job/hong-kong/senior-...
            m = re.search(cfg["location_from_url"], full, re.I)
            if m:
                location = m.group(1).replace("-", " ").replace("_", " ").title()
        if not location and cfg.get("location_default"):
            # The search URL itself constrains the region (e.g. a US-only job
            # board), so a blank card location still tells us where the role is.
            location = cfg["location_default"]
        out.append({
            "id": "browser:%s:%s" % (company, full),
            "title": title[:200],
            "location": location,
            "url": full,
            "posted_at": None,
        })
    return out


def _clean_lines(text):
    return [l.strip() for l in str(text or "").splitlines() if l.strip()]


def _scrape_one(context, cfg):
    """Run every configured URL for one company and return its postings."""
    company = cfg["name"]
    mode = cfg.get("mode", "links")
    jobs, captured = [], []

    page = context.new_page()

    if mode == "capture":
        needle = cfg["capture"]

        def on_response(resp):
            if needle not in resp.url or resp.status >= 400:
                return
            try:
                if "json" not in (resp.headers or {}).get("content-type", "").lower():
                    return
                captured.append(resp.json())
            except Exception:
                pass

        page.on("response", on_response)

    try:
        for url in _urls_for(cfg):
            captured.clear()
            page.goto(url, wait_until="domcontentloaded",
                      timeout=cfg.get("timeout_ms", 45000))
            _settle(page, cfg)
            if mode == "capture":
                jobs.extend(_harvest_capture(captured, cfg, company))
            else:
                jobs.extend(_harvest_links(page, cfg, company))
    finally:
        page.close()

    # De-duplicate across pages.
    unique, seen = [], set()
    for job in jobs:
        if job["id"] in seen:
            continue
        seen.add(job["id"])
        job["company"] = company
        job["source"] = "browser"
        unique.append(job)
    return unique


# --------------------------------------------------------------------------- #
# Entry point used by the agent
# --------------------------------------------------------------------------- #
def fetch_all(companies, headless=True, log=None):
    """Scrape every browser-lane company, sharing one browser.

    Returns {company_name: (jobs, error_or_None)}.
    """
    results = {}
    if not companies:
        return results

    say = log or (lambda m: None)

    try:
        sync_playwright = _require_playwright()
    except BrowserUnavailable as exc:
        return {c["name"]: ([], str(exc)) for c in companies}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=LAUNCH_ARGS)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_init_script(STEALTH)
        # Images and fonts are pure cost here.
        context.route(re.compile(r"\.(png|jpe?g|gif|webp|svg|woff2?|ttf|mp4)(\?|$)"),
                      lambda route: route.abort())
        try:
            for cfg in companies:
                name = cfg["name"]
                try:
                    jobs = _scrape_one(context, cfg)
                    results[name] = (jobs, None if jobs else "no postings extracted")
                    say("  %-28s %d postings" % (name, len(jobs)))
                except Exception as exc:
                    results[name] = ([], "%s: %s" % (type(exc).__name__, str(exc)[:120]))
                    say("  %-28s FAILED (%s)" % (name, type(exc).__name__))
        finally:
            context.close()
            browser.close()
    return results
