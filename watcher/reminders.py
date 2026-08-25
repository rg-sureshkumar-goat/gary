"""Dated reminders Gary sends before something expires.

Credentials lapse quietly: a GitHub personal access token stops working on its
expiry date with no warning, and the first sign is usually a failed push at an
inconvenient moment. Each reminder names a date; Gary warns at a few thresholds
before it, then once on the day, then keeps nagging while it's overdue.

Warnings are keyed by expiry date as well as name, so replacing a credential
with a new date automatically re-arms every threshold.
"""
import datetime

DEFAULT_WARN_DAYS = [14, 7, 3, 1]


def _parse(value):
    try:
        return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _key(reminder, expires, threshold):
    return "%s|%s|%s" % (reminder.get("name", "?"), expires.isoformat(), threshold)


def due(reminders, already_sent, today=None):
    """Which reminders should fire now.

    Returns a list of (key, text). `already_sent` is the set of keys that have
    fired before, so each threshold is only ever sent once.
    """
    today = today or datetime.date.today()
    out = []

    for reminder in reminders or []:
        expires = _parse(reminder.get("expires"))
        if expires is None:
            continue
        days_left = (expires - today).days
        name = reminder.get("name", "A credential")
        detail = reminder.get("message", "")

        if days_left < 0:
            # Overdue: nag once a day rather than once ever.
            key = _key(reminder, expires, "overdue-%s" % today.isoformat())
            text = ("⚠️ <b>%s expired %d day%s ago.</b>"
                    % (name, -days_left, "" if days_left == -1 else "s"))
        else:
            # Ascending, so we pick the *tightest* threshold already crossed.
            # Taking the widest one would fire at 14 days and then stay silent
            # all the way to expiry, since every later day still satisfies it.
            thresholds = sorted(reminder.get("warn_days", DEFAULT_WARN_DAYS))
            hit = next((t for t in thresholds if days_left <= t), None)
            if hit is None:
                continue
            key = _key(reminder, expires, hit)
            when = ("<b>today</b>" if days_left == 0
                    else "in <b>%d day%s</b>" % (days_left, "" if days_left == 1 else "s"))
            text = "⏳ <b>%s</b> expires %s (%s)." % (name, when, expires.isoformat())

        if key in already_sent:
            continue
        if detail:
            text += "\n" + detail
        out.append((key, text))

    return out
