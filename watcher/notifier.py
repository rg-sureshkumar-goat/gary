"""Telegram delivery. Groups new roles by company and respects the 4096-char cap."""
import html
import json
import urllib.parse

from .http import fetch

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


def send(token, chat_id, text, disable_preview=True):
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_preview,
    }
    body = fetch(url, method="POST", payload=payload, retries=2)
    result = json.loads(body)
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message: %s" % result)
    return result


def notify(token, chat_id, jobs, header=None):
    sent = 0
    for message in build_messages(jobs, header):
        send(token, chat_id, message)
        sent += 1
    return sent
