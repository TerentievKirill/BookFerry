#!/usr/bin/env python3
"""One-off Telegram announcement for BookFerry users.

Usage:
    python scripts/send_donate_message.py                # preview only
    python scripts/send_donate_message.py --test-id 123   # send to yourself
    python scripts/send_donate_message.py --send          # broadcast
"""
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description="BookFerry donation announcement")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test-id", type=int, help="Send only to this Telegram chat ID")
    mode.add_argument("--send", action="store_true", help="Broadcast to Telegram users")
    args = parser.parse_args()

    load_dotenv()
    db_path = Path(os.getenv("DB_NAME", "bookferry.db"))
    if not db_path.is_file():
        parser.error(f"Database not found: {db_path}")

    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT external_id FROM users "
                "WHERE client_type = 'telegram' AND external_id IS NOT NULL"
            )
            if str(row[0]).isdigit()
        ]

    print(f"Telegram recipients: {len(ids)}")
    if not args.send and args.test_id is None:
        print("Preview only. Use --test-id YOUR_ID or --send.")
        return

    number = os.getenv("DONATE_PHONE")
    bank = os.getenv("DONATE_BANK")
    if not number or not bank:
        parser.error("Set DONATE_PHONE and DONATE_BANK in the environment")

    token = os.getenv("BOT_TOKEN")
    if not token:
        parser.error("BOT_TOKEN is missing")

    message = (
        "📚 Небольшое объявление от автора BookFerry\n\n"
        "Для начала прошу прощения за массовую рассылку. 😁\n\n"
        "Ноябрь наступил как-то неожиданно, а вместе с ним пришло время "
        "оплачивать инфраструктуру BookFerry на следующий год — домен, "
        "почту и прочие радости жизни.\n\n"
        "И я, признаться, немного прораздолбайничал этот момент, "
        "поэтому в этом месяце расходы оказались несколько некстати. ))\n\n"
        "Так что, если вы когда-нибудь задумывались, как поддержать "
        "проект донатом, — кажется, этот момент настал!\n\n"
        f"💳 Донат по СБП: {number}\nБанк: {bank}\n\n"
        "Разумеется, всё исключительно добровольно. BookFerry как "
        "работал бесплатно, так и продолжит.\n\n"
        "А если вдруг хочется что-нибудь сказать лично — к этому же "
        "номеру привязаны Telegram и WhatsApp. Можно написать, "
        "предложить идею или просто поздороваться. ))\n\n"
        "Спасибо всем, кто пользуется BookFerry! ❤️\n\n"
        "P.S. Я ведь даже лучше Википедии — денег прошу только раз в год! 😁"
    )

    recipients = [args.test_id] if args.test_id is not None else ids
    # A local log prevents duplicates if broadcasting is restarted.
    log_path = Path("donate_sent_ids.txt")
    sent = set()
    if args.send and log_path.exists():
        sent = {
            int(line) for line in log_path.read_text().splitlines()
            if line.strip().isdigit()
        }

    success = failures = 0
    for chat_id in recipients:
        if chat_id in sent:
            continue
        payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
        request = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(4):
            try:
                with urlopen(request, timeout=20) as response:
                    result = json.load(response)
                if not result.get("ok"):
                    raise RuntimeError(str(result))
                success += 1
                print(f"OK {chat_id}")
                if args.send:
                    with log_path.open("a") as log:
                        log.write(f"{chat_id}\n")
                break
            except HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code == 429 and attempt < 3:
                    try:
                        delay = json.loads(body)["parameters"]["retry_after"]
                    except (KeyError, ValueError, TypeError):
                        delay = 5
                    time.sleep(max(1, min(int(delay), 120)))
                    continue
                print(f"FAILED {chat_id}: HTTP {error.code} {body[:180]}")
                failures += 1
                break
            except (URLError, OSError, RuntimeError) as error:
                print(f"FAILED {chat_id}: {error}")
                failures += 1
                break
        time.sleep(0.15)

    print(f"Sent: {success}; failed: {failures}")


if __name__ == "__main__":
    main()
