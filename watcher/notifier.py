"""Telegram delivery. Groups new roles by company and respects the 4096-char cap."""
import html
import json
import urllib.parse

from .http import fetch, redact, HttpError

TELEGRAM_LIMIT = 4096


def esc(text):
    return html.escape(str(text or ""), quote=False)


def build_messages(jobs, header=None):
    """Render new roles into one or more HTML messages, grouped by company."""
    by_company = {}
    for job in jobs:
        by_company.setdefault(job["company"], []).append(job)

    blocks = []
    for company in sorted(by_company):
        lines = ["<b>%s</b>" % esc(company)]
        for job in sorted(by_company[company], key=lambda j: j["title"]):
            bits = ['  • <a href="%s">%s</a>' % (esc(job["url"]), esc(job["title"]))]
            if job.get("location"):
                bits.append("\n     <i>%s</i>" % esc(job["location"]))
            if job.get("posted_at"):
                bits.append(" <i>· posted %s</i>" % esc(job["posted_at"]))
            lines.append("".join(bits))
        blocks.append("\n".join(lines))

    if not blocks:
        return []

    intro = header or "🔔 <b>%d new internship%s</b>" % (
        len(jobs), "" if len(jobs) == 1 else "s"
    )

    messages, current = [], intro
    for block in blocks:
        candidate = current + "\n\n" + block
        if len(candidate) > TELEGRAM_LIMIT - 32:
            messages.append(current)
            current = block
        else:
            current = candidate
    messages.append(current)
    return messages


# Telegram's own wording is terse; say which setting is actually wrong.
_HINTS = (
    ("chat not found",
     "TELEGRAM_CHAT_ID doesn't match a chat this bot can reach. Re-run "
     "telegram_setup.py to read the id, and make sure you've sent the bot a "
     "message from that account."),
    ("unauthorized",
     "TELEGRAM_BOT_TOKEN is wrong or the bot was deleted. Copy the token from "
     "BotFather again."),
    ("bot was blocked",
     "You've blocked the bot in Telegram. Unblock it and try again."),
    ("can't parse entities",
     "A job title broke the HTML formatting. This is a bug in Gary, not your "
     "configuration."),
    ("chat_id is empty",
     "TELEGRAM_CHAT_ID is empty -- check the repository secret exists and has "
     "a value."),
)


def _explain(description):
    low = (description or "").lower()
    for needle, hint in _HINTS:
        if needle in low:
            return hint
    return None


def send(token, chat_id, text, disable_preview=True):
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    try:
        body = fetch(url, method="POST", payload=payload, retries=2)
    except HttpError as exc:
        # Telegram puts the real reason in the body, not the status line.
        description = ""
        try:
            description = (json.loads(exc.body) or {}).get("description", "")
        except Exception:
            description = redact(exc.body)[:200]
        hint = _explain(description)
        raise RuntimeError(
            "Telegram refused the message (HTTP %s): %s%s"
            % (exc.status, description or "no reason given",
               "\n  -> " + hint if hint else ""))

    result = json.loads(body)
    if not result.get("ok"):
        description = result.get("description", "")
        hint = _explain(description)
        raise RuntimeError(
            "Telegram rejected the message: %s%s"
            % (description or redact(result),
               "\n  -> " + hint if hint else ""))
    return result


def notify(token, chat_id, jobs, header=None):
    sent = 0
    for message in build_messages(jobs, header):
        send(token, chat_id, message)
        sent += 1
    return sent


def check_credentials(token, chat_id):
    """Validate the Telegram settings before doing any real work.

    Reading 80 career sites takes minutes; discovering afterwards that a secret
    is mistyped wastes all of it and buries the reason at the end of the log.
    """
    if not token and not chat_id:
        return "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are both unset."
    if not token:
        return "TELEGRAM_BOT_TOKEN is unset or empty."
    if not chat_id:
        return "TELEGRAM_CHAT_ID is unset or empty."
    if ":" not in token:
        return ("TELEGRAM_BOT_TOKEN doesn't look like a bot token (expected "
                "digits, a colon, then letters). Check for a truncated paste.")
    if not str(chat_id).lstrip("-").isdigit():
        return ("TELEGRAM_CHAT_ID should be a number like 123456789, but is "
                "%r. Check for quotes or stray whitespace in the secret."
                % str(chat_id)[:40])
    try:
        me = json.loads(fetch("https://api.telegram.org/bot%s/getMe" % token,
                              timeout=20, retries=1))
    except HttpError as exc:
        if exc.status == 401:
            return ("Telegram rejected TELEGRAM_BOT_TOKEN. Copy it from "
                    "BotFather again -- it may be truncated or revoked.")
        return "Could not reach Telegram to verify the token: %s" % exc
    except Exception as exc:
        return "Could not reach Telegram to verify the token: %s" % redact(exc)
    if not me.get("ok"):
        return "Telegram rejected TELEGRAM_BOT_TOKEN: %s" % me.get("description")
    return None
