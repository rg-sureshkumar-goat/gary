# Gary

Gary is an agent that watches company career sites unprompted and texts you on
Telegram when a new **US corporate finance or consulting internship** is posted.

Three things Gary does without being asked:

- **Checks constantly.** Every 30 minutes for the sites plain HTTP can read;
  every 4 hours for the ones that need a real browser.
- **Grows its own watch list.** Twice a day Gary reads public internship feeds,
  pulls out employers it isn't watching, verifies each one has a real job board,
  and adds it. The list is not curated by hand and has no ceiling.
- **Only tells you about new things.** Gary remembers every posting it has seen,
  and a newly-onboarded company's existing backlog is absorbed silently.

## How it reads career sites

Rather than scraping rendered HTML, it calls the JSON APIs that career pages use
internally. Faster, and it doesn't break when a page gets restyled.

| Lane | What it handles | Cost |
|---|---|---|
| **HTTP** (`watcher/sources.py`) | Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Oracle Recruiting, Eightfold, Amazon, RSS feeds, server-rendered HTML | seconds, stdlib only |
| **Browser** (`watcher/browser.py`) | Sites behind bot protection or that render jobs with JavaScript | minutes, needs Playwright |

The HTTP lane needs no third-party packages at all, so a missing dependency can
never take the whole agent down. Playwright is imported lazily; without it, the
browser-lane companies report an error and every other company still runs.

```
watcher/
  http.py       stdlib HTTP with retries and gzip
  sources.py    one adapter per applicant-tracking system
  browser.py    Playwright lane: "capture" (intercept JSON) and "links" modes
  geo.py        the United States gate
  matcher.py    decides what counts as a finance/consulting internship
  notifier.py   Telegram formatting and delivery
  agent.py      fetch -> filter -> diff -> notify -> save
  expand.py     finds and onboards new employers
config.json     companies + matching rules
candidates.json employers the expander tries to onboard
state/          seen postings, and which candidates have been probed
```

## Setup

### 1. Telegram bot

Message [@BotFather](https://t.me/botfather) → `/newbot` → name it Gary → copy
the token. Send your new bot any message, then:

```bash
python3 telegram_setup.py
```

It asks for the token and hides it as you paste, so it never reaches your shell
history.

It prints your chat id and offers to send a test message.

### 2. Push to GitHub

The repo is already initialised, committed, and pointed at
`github.com/rg-sureshkumar-goat/gary`. Create that repo as an empty **public**
one (no README, no .gitignore), then:

```bash
git push -u origin main
```

Git asks for your username and a personal access token as the password. The
token needs both the `repo` and `workflow` scopes — without `workflow`, GitHub
refuses any push that touches `.github/workflows/`. macOS keychain stores it
after the first push.

Then add the two secrets under **Settings → Secrets and variables → Actions**:
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

**Public vs private matters here.** Actions minutes are unlimited on public
repos and capped at 2,000/month on private ones. At a 30-minute cadence this
uses roughly 3,000 minutes/month, so a private repo would run out. Either keep
the repo public — your Telegram credentials live in encrypted repo secrets, not
in the code — or widen the cron in `watch-fast.yml` to `0 */2 * * *`.

### 3. Seed it

Actions → **gary - watch (fast lane)** → Run workflow. The first run absorbs
everything currently open instead of texting you hundreds of roles. After that
it only reports genuinely new postings.

## The schedules

| Workflow | Cadence | What it does |
|---|---|---|
| `watch-fast.yml` | every 30 min | Every HTTP-readable career site |
| `watch-browser.yml` | every 4 hours | Playwright sites |
| `expand.yml` | daily 06:40 UTC | Looks for employers not yet watched |

All three share one concurrency group, so they can never corrupt the state file
by writing at once. Each commits its state back to the repo, which also keeps
GitHub from disabling the schedules for inactivity after 60 days.

## Running it yourself

```bash
python3 -m watcher.agent run --dry-run --no-browser
```

| Flag | What it does |
|---|---|
| `--dry-run` | Print what would be sent. Sends nothing, saves nothing. |
| `--no-browser` / `--only-browser` | Pick one lane. |
| `--seed` | Mark everything currently open as already seen. |
| `--only NAME` | One company — useful when adding a site. |
| `--headed` | Show the browser window, for debugging the browser lane. |

The browser lane needs `pip install -r requirements-browser.txt` and
`python -m playwright install chromium`.

Tests — no network, no Chromium:

```bash
for t in matcher geo browser expand seeding reminders; do python3 -m tests.test_$t; done
```

## The US filter

`watcher/geo.py` decides whether a posting is in America. Evidence is weighed in
a deliberate order, because the naive version of this is wrong in ways that are
easy to miss:

1. An explicit country marker — "United States", "USA".
2. A `City, ST` state code, or a spelled-out state name.
3. An explicit foreign marker.
4. Only then, a bare US metro name.

Step 3 has to come before step 4, or *San Jose, Costa Rica* reads as San Jose,
California. Two-letter codes are only honoured in a `City, ST` shape and only in
upper case, because `IN`, `OR`, `DE`, `OK`, `HI` and `ME` are ordinary English
words. And the **location field always outranks the title** — otherwise a role
called "(US Tax) Internship" based in Singapore looks American.

Two knobs in `config.json`:

- `us_only` — set `false` to watch worldwide.
- `keep_unknown_locations` — what to do when a posting doesn't say where it is.
  `false` (the default) is strict; `true` errs toward sending you more.

## Two tiers, and why

Harvesting turns up thousands of employers -- far more than can be read inside
one 30-minute window. So the watch list is split:

| Tier | Who's in it | Cadence |
|---|---|---|
| `core` | The curated banks, consultancies and finance-heavy corporates | every 30 min, all at once |
| `wide` | Everything harvesting has discovered | swept in 16 shards, one per run |

The core tier is small enough to check constantly, which is what you want for
the employers most likely to post a finance internship. The wide tier is swept
in rotation so no single run ever runs long.

Shards are chosen by a hash of the company name, not by list position. That
matters: newly harvested employers slot into a shard without reshuffling
everyone else, so adding a hundred companies doesn't cause the same sites to be
re-checked back to back while others go unread.

Wide-tier Workday boards are searched for `intern` only and paged less deeply
than core ones, which also search `summer analyst`. That idiom is a banking
one, and the banks are all in the core tier.

## Keeping the list growing

`candidates.json` holds employers to try. The expander derives likely board
tokens from each name and domain, probes Greenhouse/Lever/Ashby/SmartRecruiters,
then follows the company's careers page looking for a Workday board — preferring
a campus or student board when a company runs several.

```bash
python3 -m watcher.expand --dry-run      # report only
python3 -m watcher.expand                # onboard and write config.json
python3 -m watcher.expand --retry-all    # ignore the 30-day retry window
```

Candidates that resolve to nothing are recorded with a date and retried after 30
days, because a board that doesn't exist in September often exists in October.
When new employers are onboarded you get one Telegram message naming them.

To add an employer by hand:

```bash
python3 discover.py stripe
python3 discover.py https://careers.example.com "Example Corp"
```

For a site that needs a browser:

```bash
.venv/bin/python discover_browser.py https://careers.example.com/search "Example"
```

That one loads the page in Chromium, reports the JSON it fetched and the job-link
shapes it found, and prints a config block.

## Adapters

Set `ats` on a company to one of:

| `ats` | Use for |
|---|---|
| `greenhouse`, `lever`, `ashby`, `smartrecruiters` | Token-based boards. Just `token`. |
| `workday` | `host` + `site`. Add `searches` on big boards to query by keyword instead of paging everything. |
| `oracle` | Oracle Recruiting (`*.fa.oraclecloud.com`). |
| `eightfold`, `amazon` | Those platforms specifically. |
| `rss` | Any RSS/Atom job feed. |
| `html` | A server-rendered search page. Keys off `link_pattern` — the shape of the job-detail URL — so a restyle doesn't break it. |
| `browser` | Needs Playwright. Only when the list is JavaScript-rendered or bot-protected. |

`html` and `browser` both take `location_default` (when the search URL already
constrains the region) or `location_from_url` (when the city is in the job URL).
Prefer `location_from_url`: a blanket default will mislabel a foreign role as
American, and the US gate trusts what it's told.

## Tuning what gets sent

Under `rules` in `config.json`. A posting is sent when its title (1) reads as an
internship, (2) hits a `role_groups` term, (3) hits nothing in `exclude_terms`,
and (4) passes the US gate.

- **Too noisy?** Add to `exclude_terms`, or trim `role_groups` — `strategy`,
  `finance` and `investment` are deliberately broad.
- **Missing roles?** Add the phrase to `role_groups`, and check `exclude_terms`
  isn't catching it. `--dry-run --only <company>` prints why a posting was dropped.

Matching is whole-word, so `intern` never fires on *internal* or *international*.

## Expiry reminders

Credentials lapse quietly. `reminders` in `config.json` lists dated things Gary
should warn about:

```json
"reminders": [
  { "name": "GitHub personal access token",
    "expires": "2026-11-23",
    "warn_days": [14, 7, 3, 1],
    "message": "..." }
]
```

Gary texts you at each threshold, once on the day, then daily while overdue.
Warnings are keyed by expiry date as well as name, so putting a new date in
re-arms every threshold automatically — no state to clear by hand.

Worth being clear about what the GitHub token is for: **Gary's scheduled runs
don't use it.** The workflows authenticate with the `GITHUB_TOKEN` that GitHub
mints fresh for every run, which can't expire. The personal access token only
authenticates pushes from your own machine, so when it lapses Gary carries on
watching and committing state — it's your local `git push` that stops.

## Notes

- Scheduled runs are queued by GitHub, not guaranteed on the minute.
- If a career site starts failing you get one Telegram notice naming it; it
  won't repeat until the error changes, and other companies keep working.
- Postings unseen for 120 days are dropped from the state file.
- Some employers stay out of reach — a few large firms serve their job list only
  behind an interactive bot check. `discover_browser.py --headed` is the way to
  investigate one; if it can't be read, set a job alert on that firm's own site.
- Board tokens are handed out first-come, so a token match is not proof of
  identity: the Greenhouse slug `disney` belongs to a board actually named
  "Sgt. Pepper's Lonely Hearts Club Band". The expander checks a board's
  declared name against the company it was looking for, and rejects boards with
  only a handful of postings. `--audit --prune` re-runs those checks over the
  companies already in the config.
