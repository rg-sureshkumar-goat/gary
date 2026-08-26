"""Credential checks and secret redaction.

Gary's logs are public (the repo is public so anyone can read Actions output),
and Telegram puts the bot token in the request URL. An unredacted error message
therefore leaks the token to the world.

Run with:  python3 -m tests.test_notifier
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from watcher.http import redact                      # noqa: E402
from watcher.notifier import check_credentials, _explain  # noqa: E402

failures = []
TOKEN = "8123456789:AAEabcdefghijklmnopqrstuvwxyz012345"

# --- redaction -------------------------------------------------------------- #
leaky = "HTTP 400 for https://api.telegram.org/bot%s/sendMessage" % TOKEN
cleaned = redact(leaky)
if TOKEN in cleaned:
    failures.append("token survived redaction: %r" % cleaned)
if "<REDACTED>" not in cleaned:
    failures.append("redaction produced no marker: %r" % cleaned)
if "api.telegram.org" not in cleaned:
    failures.append("redaction destroyed useful context: %r" % cleaned)

for text in ("https://x.com/a?api_key=supersecretvalue1234&b=1",
             "https://x.com/a?access_token=supersecretvalue1234"):
    if "supersecretvalue1234" in redact(text):
        failures.append("query secret survived: %r" % redact(text))

# Ordinary text must pass through untouched.
plain = "HTTP 404 for https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
if redact(plain) != plain:
    failures.append("redaction mangled a harmless URL: %r" % redact(plain))

# --- credential checks (all offline: they return before any network call) ---- #
cases = [
    (("", ""),                    "both"),
    ((TOKEN, ""),                 "CHAT_ID"),
    (("", "123"),                 "BOT_TOKEN"),
    (("no-colon-here", "123"),    "bot token"),
    ((TOKEN, "not-a-number"),     "should be a number"),
    ((TOKEN, '"123456"'),         "should be a number"),
    # The mix-up that actually happened in setup: values entered the wrong way
    # round. A chat id has no colon, so this otherwise reads as a bad token.
    (("123456789", TOKEN),        "swapped"),
    (("123456789", "987654321"),  "swapped"),
]
for (tok, chat), needle in cases:
    msg = check_credentials(tok, chat)
    if not msg:
        failures.append("check_credentials(%r, %r) accepted bad input" % (tok[:12], chat))
    elif needle.lower() not in msg.lower():
        failures.append("check_credentials(%r, %r) -> %r, expected mention of %r"
                        % (tok[:12], chat, msg, needle))

# A negative chat id (groups/channels) is legitimate and must not be rejected
# by the shape check -- it can only fail later, on the network call.
msg = check_credentials(TOKEN, "-1001234567890")
if msg and "should be a number" in msg:
    failures.append("rejected a valid negative (group) chat id")

# --- Telegram error wording maps to actionable advice ----------------------- #
for description, needle in [
    ("Bad Request: chat not found", "TELEGRAM_CHAT_ID"),
    ("Unauthorized", "TELEGRAM_BOT_TOKEN"),
    ("Forbidden: bot was blocked by the user", "blocked"),
    ("Bad Request: can't parse entities", "bug in Gary"),
]:
    hint = _explain(description)
    if not hint or needle.lower() not in hint.lower():
        failures.append("no useful hint for %r -> %r" % (description, hint))

if _explain("some unrecognised problem") is not None:
    failures.append("invented a hint for an unknown error")

# --- message packing -------------------------------------------------------- #
from watcher.notifier import build_messages, build_aged_messages, TELEGRAM_LIMIT  # noqa: E402

def job(i, company="Acme Capital Partners International"):
    return {"company": company,
            "title": "2027 Investment Banking Summer Analyst, Group %d" % i,
            "location": "New York, NY", "cycle": "Summer 2027",
            "posted_at": "2026-08-20",
            "url": "https://careers.example.com/en-US/board/job/"
                   "New-York-NY-United-States/Investment-Banking-Summer-"
                   "Analyst-Group-%d_R-%06d" % (i, i)}

# One employer posting far more roles than fit in a single message. Splitting
# only between companies would emit one oversized message, which Telegram
# rejects outright.
many = [job(i) for i in range(120)]
msgs = build_messages(many)

if any(len(m) > TELEGRAM_LIMIT for m in msgs):
    failures.append("a message exceeded Telegram's %d-char limit: %r"
                    % (TELEGRAM_LIMIT, [len(m) for m in msgs]))
if len(msgs) < 2:
    failures.append("120 roles from one company should span several messages")

joined = "".join(msgs)
for i in range(120):
    if ("Group %d<" % i) not in joined and ("Group %d," % i) not in joined:
        failures.append("role %d was dropped while packing" % i)
        break

# Every message carrying entries must name the employer, or a continuation
# message arrives with roles and no company against them.
for n, m in enumerate(msgs):
    if "•" in m and "Acme Capital Partners" not in m:
        failures.append("message %d lists roles without naming the company" % n)

# Each entry must carry a working application link.
if joined.count('<a href="https://careers.example.com') != 120:
    failures.append("not every entry carried its application link")

# Several employers still group under their own headings.
mixed = build_messages([job(1, "Alpha Bank"), job(2, "Beta Advisors")])
if "<b>Alpha Bank</b>" not in mixed[0] or "<b>Beta Advisors</b>" not in mixed[0]:
    failures.append("companies should each get a heading")

# The long-open digest uses the same packing and reports how long roles sat.
aged = [dict(job(i), days_open=90 + i) for i in range(60)]
amsgs = build_aged_messages(aged, 60)
if any(len(m) > TELEGRAM_LIMIT for m in amsgs):
    failures.append("an aged-digest message exceeded the limit")
if "open 90 days" not in "".join(amsgs):
    failures.append("the digest should say how long a role has been open")

total = 6 + len(cases) + 1 + 5 + 7
if failures:
    print("FAILED %d of %d checks:" % (len(failures), total))
    for f in failures:
        print("   " + f)
    sys.exit(1)
print("All %d checks passed." % total)
