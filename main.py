import asyncio
import json
import os
import re
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import KeyboardButtonCallback

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── ENV ───────────────────────────────────────────────────────────────────────
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
GROUP_CHAT_ID = int(os.environ["GROUP_CHAT_ID"])   # گروهی که "شهر میویی" می‌فرستیم
MEOWIE_BOT = "@MeowieeQ"
INTERVAL_HOURS = float(os.environ.get("INTERVAL_HOURS", "1"))

DATA_DIR = "data"
LEADERBOARD_FILE = os.path.join(DATA_DIR, "leaderboard.json")
CITY_FILE = os.path.join(DATA_DIR, "city.json")

os.makedirs(DATA_DIR, exist_ok=True)


# ─── HELPERS ───────────────────────────────────────────────────────────────────
def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved → {path}")


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_number(s: str) -> int | None:
    """'76,089' → 76089"""
    try:
        return int(s.replace(",", "").replace("٬", "").strip())
    except Exception:
        return None


# ─── PARSERS ───────────────────────────────────────────────────────────────────
def parse_leaderboard_meo(text: str, lb_type: str) -> list[dict]:
    """
    Parse leaderboard messages for 'میو میو' and 'بازار ماهی' types.
    Returns list of group dicts.
    """
    groups = []
    # Split by medal lines (🥇 🥈 🥉 🎖 🏅)
    blocks = re.split(r"\n(?=[🥇🥈🥉🎖🏅])", text)
    for block in blocks:
        if not block.strip():
            continue
        g = {"type": lb_type, "timestamp": now_str()}

        # Group name: first line after medal emoji
        first_line = block.strip().split("\n")[0]
        g["group_raw"] = first_line.strip()

        # میو میو
        m = re.search(r"میو میو ها\s*:\s*([\d,٬]+)", block)
        if m:
            g["meo_meo"] = parse_number(m.group(1))

        # جمعیت
        m = re.search(r"جمعیت\s*:\s*([\d,٬]+)", block)
        if m:
            g["population"] = parse_number(m.group(1))

        # خزانه
        m = re.search(r"دارایی خزانه\s*:\s*([\d,٬]+)", block)
        if m:
            g["treasury"] = parse_number(m.group(1))

        # ماهی
        m = re.search(r"ماهی ها\s*:\s*([\d,٬]+)", block)
        if m:
            g["fish"] = parse_number(m.group(1))

        # رتبه گروه
        m = re.search(r"رتبه گروه\s*:\s*([\d,٬]+)", block)
        if m:
            g["group_rank"] = parse_number(m.group(1))

        if any(k in g for k in ("meo_meo", "population", "treasury", "fish")):
            groups.append(g)
    return groups


def parse_city(text: str) -> dict:
    """Parse شهر میویی reply."""
    d = {"timestamp": now_str()}

    m = re.search(r"میو میو ها\s*:\s*([\d,٬]+)", text)
    if m:
        d["meo_meo"] = parse_number(m.group(1))

    m = re.search(r"جمعیت\s*:\s*([\d,٬]+)", text)
    if m:
        d["population"] = parse_number(m.group(1))

    m = re.search(r"ماهی ها\s*:\s*([\d,٬]+)", text)
    if m:
        d["fish"] = parse_number(m.group(1))

    m = re.search(r"خزانه\s*:\s*([\d,٬]+)", text)
    if m:
        d["treasury"] = parse_number(m.group(1))

    return d


# ─── BUTTON CLICKER ────────────────────────────────────────────────────────────
async def click_button(client, message, row: int, col: int):
    """Click an inline button by row/col (0-indexed). Waits for edit."""
    markup = message.reply_markup
    if not markup:
        raise RuntimeError("No reply markup found")
    button = markup.rows[row].buttons[col]
    if not isinstance(button, KeyboardButtonCallback):
        raise RuntimeError(f"Button at ({row},{col}) is not a callback button")
    await message.click(row, col)
    await asyncio.sleep(3)   # wait for bot to edit the message


async def get_updated_message(client, chat, msg_id):
    """Re-fetch the message to get latest markup/text after edit."""
    async for m in client.iter_messages(chat, ids=msg_id):
        return m
    return None


# ─── LEADERBOARD FLOW ──────────────────────────────────────────────────────────
async def do_leaderboard(client):
    logger.info("Starting leaderboard cycle...")

    # 1) Send "لیدربرد" to @MeowieeQ
    sent = await client.send_message(MEOWIE_BOT, "لیدربرد")
    await asyncio.sleep(4)

    # 2) Get bot reply
    async for msg in client.iter_messages(MEOWIE_BOT, limit=5):
        if msg.reply_to_msg_id == sent.id or (msg.id != sent.id and msg.from_id != (await client.get_me()).id):
            bot_reply = msg
            break
    else:
        logger.error("No reply from bot after 'لیدربرد'")
        return

    # Refresh
    bot_reply = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)

    # 3) Click second button (row 0, col 0 = right button = لیدربرد گروهی)
    #    In RTL: visually right = first in array index? Let's click index 1 first
    #    From screenshot: two buttons, right one = لیدربرد گروهی (col 1 in row 0)
    logger.info("Clicking 'لیدربرد گروهی' (row=0, col=1)...")
    await bot_reply.click(0, 1)
    await asyncio.sleep(4)
    bot_reply = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)

    # Now we have 5 buttons:
    # Row 0: میو میو  (single)
    # Row 1: خزانه | جمعیت
    # Row 2: بازار ماهی (single)
    # Row 3: بازگشت (red)

    all_lb_records = load_json(LEADERBOARD_FILE)

    # ── 4) Click میو میو (row=0, col=0) ────────────────────────────────────────
    logger.info("Clicking 'میو میو' (row=0, col=0)...")
    await bot_reply.click(0, 0)
    await asyncio.sleep(4)
    meo_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)

    records = parse_leaderboard_meo(meo_msg.text or meo_msg.raw_text, "meo_meo")
    logger.info(f"  Parsed {len(records)} groups for میو میو")
    all_lb_records.extend(records)

    # Click back button
    back_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    # Back button is last row
    back_markup = back_msg.reply_markup
    if back_markup:
        last_row = len(back_markup.rows) - 1
        logger.info("Clicking back...")
        await back_msg.click(last_row, 0)
        await asyncio.sleep(3)
        bot_reply = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)

    # ── 5) Click بازار ماهی (row=2, col=0) ─────────────────────────────────────
    logger.info("Clicking 'بازار ماهی' (row=2, col=0)...")
    await bot_reply.click(2, 0)
    await asyncio.sleep(4)
    fish_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)

    records = parse_leaderboard_meo(fish_msg.text or fish_msg.raw_text, "fish_market")
    logger.info(f"  Parsed {len(records)} groups for بازار ماهی")
    all_lb_records.extend(records)

    # Click back
    back_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    if back_msg and back_msg.reply_markup:
        last_row = len(back_msg.reply_markup.rows) - 1
        await back_msg.click(last_row, 0)
        await asyncio.sleep(3)

    save_json(LEADERBOARD_FILE, all_lb_records)
    logger.info("Leaderboard data saved.")


# ─── CITY FLOW ─────────────────────────────────────────────────────────────────
async def do_city(client):
    logger.info("Starting city cycle...")

    sent = await client.send_message(GROUP_CHAT_ID, "شهر میویی")
    await asyncio.sleep(5)

    # Get reply in the group
    async for msg in client.iter_messages(GROUP_CHAT_ID, limit=10):
        if msg.reply_to_msg_id == sent.id:
            city_text = msg.text or msg.raw_text
            record = parse_city(city_text)
            logger.info(f"City data: {record}")

            all_city = load_json(CITY_FILE)
            all_city.append(record)
            save_json(CITY_FILE, all_city)
            break
    else:
        logger.warning("No reply to 'شهر میویی' found in group.")


# ─── STATS COMMAND ─────────────────────────────────────────────────────────────
async def send_stats(client, chat_id):
    files = []
    if os.path.exists(LEADERBOARD_FILE):
        files.append(LEADERBOARD_FILE)
    if os.path.exists(CITY_FILE):
        files.append(CITY_FILE)

    if not files:
        await client.send_message(chat_id, "هنوز داده‌ای ذخیره نشده.")
        return

    for f in files:
        await client.send_file(chat_id, f, caption=os.path.basename(f))
        await asyncio.sleep(1)

    logger.info(f"Sent {len(files)} files to {chat_id}")


# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────
async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as: {me.username or me.id}")

    # Listen for "امار پیشی" in Saved Messages
    @client.on(events.NewMessage(from_users="me", pattern=r"(?i)امار پیشی"))
    async def stats_handler(event):
        if event.is_private and event.message.peer_id.user_id == me.id:
            await send_stats(client, me.id)

    async def cycle():
        while True:
            try:
                await do_leaderboard(client)
            except Exception as e:
                logger.error(f"Leaderboard error: {e}", exc_info=True)

            try:
                await do_city(client)
            except Exception as e:
                logger.error(f"City error: {e}", exc_info=True)

            logger.info(f"Cycle done. Sleeping {INTERVAL_HOURS}h...")
            await asyncio.sleep(INTERVAL_HOURS * 3600)

    await asyncio.gather(
        cycle(),
        client.run_until_disconnected(),
    )


if __name__ == "__main__":
    asyncio.run(main())
