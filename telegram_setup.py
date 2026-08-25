#!/usr/bin/env python3
"""One-time Telegram setup helper for Gary.

  1. In Telegram, message @BotFather -> /newbot -> copy the token it gives you.
  2. Open a chat with your new bot and send it any message (e.g. "hi").
  3. Run:  python3 telegram_setup.py
     and paste the token when it asks. It is not echoed, and not stored.

It prints the chat id you need, then offers to send a test message.
"""
import getpass
import os
import sys

from watcher.http import fetch_json
from watcher import notifier


def main():
    # Prompt rather than read argv, so the token never lands in shell history.
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        if not sys.stdin.isatty():
            print("No token. Run this in a terminal, or set TELEGRAM_BOT_TOKEN.")
            return 1
        print("Paste the token BotFather gave you (it stays hidden), then press Enter.")
        try:
            token = getpass.getpass("Bot token: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return 1
    if not token:
        print("No token entered.")
        return 1
    if ":" not in token:
        print("That doesn't look like a bot token -- BotFather's tokens look "
              "like 123456789:AAE...  Copy the whole line he sent you.")
        return 1

    me = fetch_json("https://api.telegram.org/bot%s/getMe" % token)
    if not me.get("ok"):
        print("That token was rejected by Telegram: %s" % me)
        return 1
    print("Bot: @%s\n" % me["result"].get("username"))

    updates = fetch_json("https://api.telegram.org/bot%s/getUpdates" % token)
    chats = {}
    for upd in updates.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            who = chat.get("username") or chat.get("title") or chat.get("first_name") or "?"
            chats[chat["id"]] = "%s (%s)" % (who, chat.get("type"))

    if not chats:
        username = me["result"].get("username", "")
        print("Telegram has no message from you to this bot yet.\n")

        # A webhook silently swallows getUpdates, and is the one cause that
        # looks identical to "you didn't send anything".
        try:
            hook = fetch_json("https://api.telegram.org/bot%s/getWebhookInfo" % token)
            info = hook.get("result") or {}
            if info.get("url"):
                print("  A webhook is set (%s), which consumes updates before this\n"
                      "  script can see them. Clear it with:\n"
                      "    https://api.telegram.org/bot<token>/deleteWebhook\n"
                      % info["url"])
                return 1
            if info.get("pending_update_count"):
                print("  Telegram reports %d pending update(s) but returned none --\n"
                      "  try re-running in a few seconds.\n"
                      % info["pending_update_count"])
        except Exception:
            pass

        print("  Most likely: the message went to @BotFather rather than to your")
        print("  bot. They are different chats.\n")
        if username:
            print("  Open this link, press START, then re-run:")
            print("      https://t.me/%s\n" % username)
        else:
            print("  Search your bot by name in Telegram, press START, re-run.\n")
        print("  Pressing START counts as a message -- you don't have to type one.")
        return 1

    print("Chat ids found:")
    for cid, who in chats.items():
        print("   %-16s %s" % (cid, who))

    chat_id = str(list(chats)[0])
    print("\nUse TELEGRAM_CHAT_ID = %s" % chat_id)

    if sys.stdin.isatty():
        if input("\nSend a test message there now? [y/N] ").strip().lower().startswith("y"):
            notifier.send(token, chat_id,
                          "✅ <b>Gary</b> is wired up correctly. I'll text you here "
                          "when a new internship appears.")
            print("Sent -- check Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
