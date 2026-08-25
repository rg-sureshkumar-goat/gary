#!/usr/bin/env python3
"""One-time Telegram setup helper for Gary.

  1. In Telegram, message @BotFather -> /newbot -> copy the token it gives you.
  2. Open a chat with your new bot and send it any message (e.g. "hi").
  3. Run:  TELEGRAM_BOT_TOKEN=<token> python3 telegram_setup.py

It prints the chat id you need, then offers to send a test message.
"""
import os
import sys

from watcher.http import fetch_json
from watcher import notifier


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN first, e.g.\n"
              "  TELEGRAM_BOT_TOKEN=123456:ABC... python3 telegram_setup.py")
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
        print("No messages yet. Open Telegram, send your bot any message, then re-run this.")
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
