"""Adapters for the applicant-tracking systems most large employers run their
career sites on. Each adapter hits the same JSON endpoint the career page's own
JavaScript calls, which is far more reliable than scraping rendered HTML.

Every adapter yields normalised dicts:
    {id, company, title, location, url, posted_at, source}
"""
import datetime
import html as html_lib
import re
import urllib.parse

from .http import fetch, fetch_json, HttpError


def _clean(text):
    return " ".join(str(text or "").split())


def _iso(value):
    """Best-effort normalisation of the many date shapes ATS platforms emit."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Epoch, in seconds or milliseconds.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.datetime.utcfromtimestamp(seconds).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return None
    text = str(value)
    if text.isdigit():
        return _iso(int(text))
    return text[:10]


# --------------------------------------------------------------------------- #
# Greenhouse
# --------------------------------------------------------------------------- #
def greenhouse(cfg):
    token = cfg["token"]
    url = "https://boards-api.greenhouse.io/v1/boards/%s/jobs" % token
    data = fetch_json(url)
    for job in data.get("jobs", []):
        loc = (job.get("location") or {}).get("name")
        yield {
            "id": "greenhouse:%s:%s" % (token, job.get("id")),
            "title": _clean(job.get("title")),
            "location": _clean(loc),
            "url": job.get("absolute_url"),
            "posted_at": _iso(job.get("first_published") or job.get("updated_at")),
        }


# --------------------------------------------------------------------------- #
# Lever
# --------------------------------------------------------------------------- #
def lever(cfg):
    token = cfg["token"]
    url = "https://api.lever.co/v0/postings/%s?mode=json" % token
    for job in fetch_json(url) or []:
        cats = job.get("categories") or {}
        yield {
            "id": "lever:%s:%s" % (token, job.get("id")),
            "title": _clean(job.get("text")),
            "location": _clean(cats.get("location")),
            "url": job.get("hostedUrl"),
            "posted_at": _iso(job.get("createdAt")),
        }


# --------------------------------------------------------------------------- #
# Ashby
# --------------------------------------------------------------------------- #
def ashby(cfg):
    token = cfg["token"]
    url = "https://api.ashbyhq.com/posting-api/job-board/%s" % token
    data = fetch_json(url)
    for job in data.get("jobs", []):
        yield {
            "id": "ashby:%s:%s" % (token, job.get("id")),
            "title": _clean(job.get("title")),
            "location": _clean(job.get("location")),
            "url": job.get("jobUrl"),
            "posted_at": _iso(job.get("publishedAt")),
        }


# --------------------------------------------------------------------------- #
# SmartRecruiters
# --------------------------------------------------------------------------- #
def smartrecruiters(cfg):
    company = cfg["token"]
    offset, page_size = 0, 100
    while True:
        url = (
            "https://api.smartrecruiters.com/v1/companies/%s/postings?limit=%d&offset=%d"
            % (company, page_size, offset)
        )
        data = fetch_json(url)
        content = data.get("content", [])
        for job in content:
            loc = job.get("location") or {}
            where = ", ".join(
                p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p
            )
            yield {
                "id": "smartrecruiters:%s:%s" % (company, job.get("id")),
                "title": _clean(job.get("name")),
                "location": _clean(where),
                "url": "https://jobs.smartrecruiters.com/%s/%s" % (company, job.get("id")),
                "posted_at": _iso(job.get("releasedDate")),
            }
        offset += page_size
        if len(content) < page_size or offset >= data.get("totalFound", 0):
            break


# --------------------------------------------------------------------------- #
# Workday  (the CXS endpoint behind every *.myworkdayjobs.com career site)
# --------------------------------------------------------------------------- #
def _workday_location(locations_text, external_path):
    """Workday says "2 Locations" when a role spans several offices, which tells
    us nothing. The job URL still carries the primary one:

        /job/Los-Angeles-CA-USA/Corporate-Development-Intern_R3354

    so fall back to that rather than throwing the location away -- otherwise a
    US role with two offices looks locationless and gets filtered out.
    """
    text = _clean(locations_text)
    if text and not re.match(r"^\d+\s+locations?$", text, re.I):
        return text
    parts = [p for p in (external_path or "").split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "job":
        slug = parts[1].replace("-", " ").strip()
        if slug and not slug.lower().startswith("xmlname"):
            derived = " ".join(slug.split())
            if text:
                return "%s (%s)" % (derived, text)
            return derived
    return text


def workday(cfg):
    host = cfg["host"]                     # e.g. "hl.wd1.myworkdayjobs.com"
    site = cfg["site"]                     # e.g. "Campus"
    tenant = cfg.get("tenant") or host.split(".")[0]
    lang = cfg.get("lang", "en-US")
    facets = cfg.get("facets", {})
    # Big boards are queried by keyword to stay within a sane request count;
    # small ones use "" to pull the whole board.
    searches = cfg.get("searches") or [cfg.get("search", "")]

    api = "https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site)
    headers = {"Origin": "https://%s" % host,
               "Referer": "https://%s/%s/%s" % (host, lang, site)}
    emitted = set()

    for term in searches:
        offset, page_size, total = 0, 20, None
        while True:
            body = {"appliedFacets": facets, "limit": page_size,
                    "offset": offset, "searchText": term}
            data = fetch_json(api, method="POST", payload=body, headers=headers)
            postings = data.get("jobPostings", [])
            if total is None:
                total = data.get("total", 0)
            for job in postings:
                path = job.get("externalPath") or ""
                key = "workday:%s:%s" % (tenant, path)
                if key in emitted:
                    continue
                emitted.add(key)
                yield {
                    "id": key,
                    "title": _clean(job.get("title")),
                    "location": _workday_location(job.get("locationsText"), path),
                    "url": "https://%s/%s/%s%s" % (host, lang, site, path),
                    # Workday sends "Posted Today" / "Posted 6 Days Ago";
                    # drop its prefix so the message doesn't read "posted Posted".
                    "posted_at": re.sub(r"^posted\s+", "", _clean(job.get("postedOn")),
                                        flags=re.I) or None,
                }
            offset += page_size
            if not postings or offset >= min(total or 0, cfg.get("max_results", 600)):
                break


# --------------------------------------------------------------------------- #
# Eightfold  (used by several large banks and corporates)
# --------------------------------------------------------------------------- #
def eightfold(cfg):
    host = cfg["host"]                     # e.g. "careers.company.com"
    domain = cfg.get("domain") or host
    start, page_size = 0, 100
    while True:
        params = urllib.parse.urlencode({
            "domain": domain,
            "start": start,
            "num": page_size,
            "query": cfg.get("search", ""),
        })
        url = "https://%s/api/apply/v2/jobs?%s" % (host, params)
        data = fetch_json(url)
        positions = data.get("positions", []) or []
        for job in positions:
            loc = job.get("location") or ", ".join(job.get("locations") or [])
            yield {
                "id": "eightfold:%s:%s" % (domain, job.get("id")),
                "title": _clean(job.get("name")),
                "location": _clean(loc),
                "url": job.get("canonicalPositionUrl")
                       or job.get("positionUrl")
                       or "https://%s/careers/job/%s" % (host, job.get("id")),
                "posted_at": _iso(job.get("t_create") or job.get("create_date")),
            }
        start += page_size
        if not positions or start >= min(data.get("count", 0), cfg.get("max_results", 1000)):
            break


# --------------------------------------------------------------------------- #
# Oracle Recruiting Cloud  (*.fa.oraclecloud.com -- e.g. JPMorgan Chase)
# --------------------------------------------------------------------------- #
def oracle(cfg):
    host = cfg["host"]                     # e.g. "jpmc.fa.oraclecloud.com"
    site = cfg.get("site", "CX_1001")      # siteNumber
    page_size = cfg.get("page_size", 200)
    cap = cfg.get("max_results", 1200)
    base = "https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitions" % host

    offset = 0
    while offset < cap:
        finder = ("findReqs;siteNumber=%s,limit=%d,offset=%d,sortBy=POSTING_DATES_DESC"
                  % (site, page_size, offset))
        url = "%s?onlyData=true&expand=requisitionList.secondaryLocations&finder=%s" % (
            base, urllib.parse.quote(finder, safe="=;,"))
        data = fetch_json(url)
        items = data.get("items") or []
        if not items:
            break
        reqs = items[0].get("requisitionList") or []
        for job in reqs:
            yield {
                "id": "oracle:%s:%s" % (host.split(".")[0], job.get("Id")),
                "title": _clean(job.get("Title")),
                "location": _clean(job.get("PrimaryLocation")),
                "url": "https://%s/hcmUI/CandidateExperience/en/sites/%s/job/%s" % (
                    host, site, job.get("Id")),
                "posted_at": _iso(job.get("PostedDate")),
            }
        total = items[0].get("TotalJobsCount") or 0
        offset += page_size
        if len(reqs) < page_size or offset >= total:
            break


# --------------------------------------------------------------------------- #
# Amazon (amazon.jobs)
# --------------------------------------------------------------------------- #
def amazon(cfg):
    page_size = 100
    for term in cfg.get("searches", ["finance internship", "intern"]):
        offset, total = 0, None
        while offset < cfg.get("max_results", 600):
            params = urllib.parse.urlencode({
                "base_query": term,
                "result_limit": page_size,
                "offset": offset,
                "sort": "recent",
            })
            data = fetch_json("https://www.amazon.jobs/en/search.json?%s" % params)
            jobs = data.get("jobs") or []
            if total is None:
                total = data.get("hits", 0)
            for job in jobs:
                path = job.get("job_path") or ""
                yield {
                    "id": "amazon:%s" % (job.get("id_icims") or path),
                    "title": _clean(job.get("title")),
                    "location": _clean(job.get("normalized_location") or job.get("location")),
                    "url": "https://www.amazon.jobs%s" % path,
                    "posted_at": _iso(job.get("posted_date")),
                }
            offset += page_size
            if not jobs or offset >= (total or 0):
                break


# --------------------------------------------------------------------------- #
# RSS / Atom job feeds
# --------------------------------------------------------------------------- #
_ITEM_RE = re.compile(r"<(?:item|entry)\b.*?</(?:item|entry)>", re.S | re.I)


def _tag(chunk, name):
    """Read one tag's text, unwrapping CDATA."""
    m = re.search(r"<%s\b[^>]*>(.*?)</%s>" % (name, name), chunk, re.S | re.I)
    if not m:
        # Atom often uses <link href="..."/>.
        m = re.search(r'<%s\b[^>]*href="([^"]+)"' % name, chunk, re.I)
        if not m:
            return ""
    text = m.group(1)
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean(text)


def rss(cfg):
    """Read an RSS/Atom job feed.

    Plenty of career platforms still publish one, which is far cheaper and more
    stable than driving a browser at the same site.
    """
    template = cfg.get("url_template")
    if template:
        step = cfg.get("page_step", 20)
        start = cfg.get("first_page", 0)
        urls = [template.replace("{offset}", str(start + i * step))
                for i in range(int(cfg.get("pages", 1)))]
    else:
        urls = cfg.get("urls") or [cfg["url"]]

    seen = set()
    for url in urls:
        try:
            body = fetch(url, timeout=cfg.get("timeout", 30))
        except HttpError:
            raise
        items = _ITEM_RE.findall(body)
        if not items:
            continue
        for chunk in items:
            link = _tag(chunk, "link") or _tag(chunk, "guid")
            title = _tag(chunk, "title")
            if not title or not link or link in seen:
                continue
            seen.add(link)
            yield {
                "id": "rss:%s:%s" % (cfg.get("token") or cfg["name"], link),
                "title": title,
                "location": _clean(_tag(chunk, "location")) or cfg.get("location_default", ""),
                "url": link,
                "posted_at": _iso_from_rfc822(_tag(chunk, "pubDate")
                                              or _tag(chunk, "updated")),
            }


def _iso_from_rfc822(value):
    """'Tue, 26 Aug 2025 00:00:00 +0000' -> '2025-08-26'."""
    if not value:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", value)
    if m:
        months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                  "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
        month = months.get(m.group(2).lower())
        if month:
            return "%s-%02d-%02d" % (m.group(3), month, int(m.group(1)))
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Server-rendered HTML job lists
# --------------------------------------------------------------------------- #
def html_links(cfg):
    """Pull job links out of a server-rendered search page over plain HTTP.

    Keys off the shape of the job-detail URL rather than CSS classes, so a
    restyle doesn't break it. Only works where the server renders the list --
    if the jobs arrive via JavaScript, use the browser lane instead.
    """
    pattern = re.compile(cfg["link_pattern"], re.I)
    anchor = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)

    template = cfg.get("url_template")
    if template:
        step = cfg.get("page_step", 10)
        start = cfg.get("first_page", 0)
        urls = [template.replace("{offset}", str(start + i * step))
                for i in range(int(cfg.get("pages", 1)))]
    else:
        urls = cfg.get("urls") or [cfg["url"]]

    seen = set()
    for url in urls:
        body = fetch(url, timeout=cfg.get("timeout", 30))
        found_here = 0
        for match in anchor.finditer(body):
            href, inner = match.group(1), match.group(2)
            if not pattern.search(href):
                continue
            title = _clean(html_lib.unescape(re.sub(r"<[^>]+>", " ", inner)))
            if len(title) < 4:
                continue
            full = urllib.parse.urljoin(url, html_lib.unescape(href))
            if full in seen:
                continue
            seen.add(full)
            found_here += 1
            location = cfg.get("location_default", "")
            if cfg.get("location_from_url"):
                m = re.search(cfg["location_from_url"], full, re.I)
                if m:
                    location = m.group(1).replace("-", " ").replace("_", " ").title()
            yield {
                "id": "html:%s:%s" % (cfg["name"], full),
                "title": title[:200],
                "location": location,
                "url": full,
                "posted_at": None,
            }
        if not found_here:
            break            # ran past the last page

ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "eightfold": eightfold,
    "oracle": oracle,
    "amazon": amazon,
    "rss": rss,
    "html": html_links,
}


def fetch_company(company):
    """Run the right adapter for one company. Returns (jobs, error_or_None)."""
    adapter = ADAPTERS.get(company.get("ats"))
    if adapter is None:
        return [], "unknown ats %r" % company.get("ats")
    try:
        jobs = []
        for job in adapter(company):
            if not job.get("title"):
                continue
            job["company"] = company["name"]
            job["source"] = company["ats"]
            jobs.append(job)
        return jobs, None
    except HttpError as exc:
        return [], "HTTP %s" % exc.status
    except Exception as exc:
        return [], "%s: %s" % (type(exc).__name__, exc)
