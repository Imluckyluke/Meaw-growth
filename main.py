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
MEOWIE_BOT = "@MeowieQBot"  # username for entity resolution
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
    Parse leaderboard messages for میو میو and بازار ماهی types.
    Numbers may be wrapped in backticks.
    """
    groups = []
    if not text:
        return groups
    NUM = r"`?([\d,٬]+)`?"
    # Split by medal emoji lines
    blocks = re.split(r"
(?=[🥇🥈🥉🎖🏅])", text)
    for block in blocks:
        if not block.strip():
            continue
        g = {"type": lb_type, "timestamp": now_str()}

        first_line = block.strip().split("
")[0]
        g["group_raw"] = first_line.strip()

        m = re.search(r"میو میو ها\s*:\s*" + NUM, block)
        if m:
            g["meo_meo"] = parse_number(m.group(1))

        m = re.search(r"جمعیت\s*:\s*" + NUM, block)
        if m:
            g["population"] = parse_number(m.group(1))

        m = re.search(r"دارایی خزانه\s*:\s*" + NUM, block)
        if m:
            g["treasury"] = parse_number(m.group(1))

        m = re.search(r"ماهی ها\s*:\s*" + NUM, block)
        if m:
            g["fish"] = parse_number(m.group(1))

        m = re.search(r"رتبه گروه\s*:\s*" + NUM, block)
        if m:
            g["group_rank"] = parse_number(m.group(1))

        if any(k in g for k in ("meo_meo", "population", "treasury", "fish")):
            groups.append(g)
    return groups


def parse_city(text: str) -> dict:
    """Parse شهر میویی reply. Numbers may be wrapped in backticks."""
    d = {"timestamp": now_str()}
    # Match number with optional backtick wrapping
    NUM = r"`?([\d,٬]+)`?"

    m = re.search(r"میو میو ها\s*:\s*" + NUM, text)
    if m:
        d["meo_meo"] = parse_number(m.group(1))

    m = re.search(r"جمعیت\s*:\s*" + NUM, text)
    if m:
        d["population"] = parse_number(m.group(1))

    m = re.search(r"ماهی ها\s*:\s*" + NUM, text)
    if m:
        d["fish"] = parse_number(m.group(1))

    m = re.search(r"خزانه\s*:\s*" + NUM, text)
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

    # 1) Send "لیدربرد"
    sent = await client.send_message(MEOWIE_BOT, "لیدربرد")
    await asyncio.sleep(5)

    # 2) Get bot reply (most recent message in DM that isn't ours)
    me = await client.get_me()
    bot_reply = None
    async for msg in client.iter_messages(MEOWIE_BOT, limit=5):
        if msg.id != sent.id:
            bot_reply = msg
            break
    if not bot_reply:
        logger.error("No reply from bot after لیدربرد")
        return

    # Log all buttons on first reply
    def log_buttons(msg, label):
        if not msg.reply_markup:
            logger.info(f"[{label}] NO BUTTONS")
            return
        for ri, row in enumerate(msg.reply_markup.rows):
            for ci, btn in enumerate(row.buttons):
                logger.info(f"[{label}] row={ri} col={ci} text={getattr(btn, 'text', '?')!r}")

    log_buttons(bot_reply, "initial")

    # 3) Click لیدربرد گروهی (row=0, col=1 = right button)
    logger.info("Clicking لیدربرد گروهی (row=0, col=1)...")
    await bot_reply.click(0, 1)
    await asyncio.sleep(5)

    bot_reply = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    text = bot_reply.text or bot_reply.raw_text or ""
    logger.info(f"After گروهی — text: {text[:80]}")
    log_buttons(bot_reply, "after_gorouhi")

    all_lb_records = load_json(LEADERBOARD_FILE)

    # ── 4) Click میو میو ──────────────────────────────────────────────────────────
    logger.info("Clicking میو میو (row=0, col=0)...")
    await bot_reply.click(0, 0)
    await asyncio.sleep(6)

    meo_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    meo_text = meo_msg.text or meo_msg.raw_text or ""
    logger.info(f"میو میو text: {meo_text[:200]}")
    log_buttons(meo_msg, "after_meo")
    records = parse_leaderboard_meo(meo_text, "meo_meo")
    logger.info(f"  Parsed {len(records)} groups for میو میو")
    all_lb_records.extend(records)

    # Click back
    meo_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    log_buttons(meo_msg, "back_btn")
    if meo_msg.reply_markup:
        last_row = len(meo_msg.reply_markup.rows) - 1
        logger.info(f"Clicking back (row={last_row}, col=0)...")
        await meo_msg.click(last_row, 0)
        await asyncio.sleep(4)

    bot_reply = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    text = bot_reply.text or bot_reply.raw_text or ""
    logger.info(f"After back — text: {text[:80]}")
    log_buttons(bot_reply, "after_back")

    # ── 5) Click بازار ماهی ───────────────────────────────────────────────────────
    logger.info("Clicking بازار ماهی (row=2, col=0)...")
    await bot_reply.click(2, 0)
    await asyncio.sleep(6)

    fish_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    fish_text = fish_msg.text or fish_msg.raw_text or ""
    logger.info(f"بازار ماهی text: {fish_text[:200]}")
    log_buttons(fish_msg, "after_fish")
    records = parse_leaderboard_meo(fish_text, "fish_market")
    logger.info(f"  Parsed {len(records)} groups for بازار ماهی")
    all_lb_records.extend(records)

    # Click back (cleanup)
    fish_msg = await get_updated_message(client, MEOWIE_BOT, bot_reply.id)
    if fish_msg and fish_msg.reply_markup:
        last_row = len(fish_msg.reply_markup.rows) - 1
        await fish_msg.click(last_row, 0)
        await asyncio.sleep(3)

    save_json(LEADERBOARD_FILE, all_lb_records)
    logger.info("Leaderboard data saved.")


# ─── CITY FLOW ─────────────────────────────────────────────────────────────────
async def do_city(client):
    logger.info("Starting city cycle...")

    sent = await client.send_message(GROUP_CHAT_ID, "شهر میویی")
    await asyncio.sleep(8)

    found = False
    async for msg in client.iter_messages(GROUP_CHAT_ID, limit=20):
        if msg.reply_to_msg_id == sent.id:
            city_text = msg.text or msg.raw_text
            logger.info(f"City raw text: {city_text[:200] if city_text else chr(39)+'None'+chr(39)}")
            record = parse_city(city_text)
            logger.info(f"City data: {record}")
            all_city = load_json(CITY_FILE)
            all_city.append(record)
            save_json(CITY_FILE, all_city)
            found = True
            break

    if not found:
        logger.warning("No reply to chr(39)+'شهر میویی'+chr(39)+' found in group.")


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

    # Pre-resolve bot entity so numeric ID works later
    global MEOWIE_BOT
    try:
        bot_entity = await client.get_entity(MEOWIE_BOT)
        MEOWIE_BOT = bot_entity
        logger.info(f"Bot entity resolved: {bot_entity.id}")
    except Exception as e:
        logger.warning(f"Could not pre-resolve bot entity: {e}")

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
