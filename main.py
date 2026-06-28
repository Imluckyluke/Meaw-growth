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
    blocks = re.split("\\n(?=[🥇🥈🥉🎖🏅])", text)
    for block in blocks:
        if not block.strip():
            continue
        g = {"type": lb_type, "timestamp": now_str()}

        first_line = block.strip().split("\n")[0]
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



# ─── COMPARE COMMAND ───────────────────────────────────────────────────────────
def calc_slope(values: list) -> float | None:
    """
    Linear regression slope.
    چون هر نمونه = 1 ساعت، slope = تغییر به ازای هر ساعت.
    """
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    return num / den if den else None


def hours_to_reach(current, target, my_slope, their_slope):
    gap = (target or 0) - (current or 0)
    if gap <= 0:
        return 0.0
    net = (my_slope or 0) - (their_slope or 0)
    if net <= 0:
        return float("inf")
    return gap / net


def fmt_eta(hours) -> str:
    if hours == 0:
        return "قبلاً رسیده! 🎉"
    if hours == float("inf") or hours is None:
        return "با شیب فعلی نمیرسه ❌"
    days = hours / 24
    if hours < 1:
        return f"{hours*60:.0f} دقیقه دیگه"
    if days < 1:
        return f"{hours:.1f} ساعت دیگه"
    if days < 30:
        return f"{days:.1f} روز دیگه ({hours:.0f} ساعت)"
    months = days / 30
    return f"{months:.1f} ماه دیگه ({days:.0f} روز)"



def fmt_num(n) -> str:
    if n is None:
        return "—"
    return f"{int(n):,}"



async def send_compare(client, chat_id):
    lb_data = load_json(LEADERBOARD_FILE)
    city_data = load_json(CITY_FILE)

    if not city_data:
        await client.send_message(chat_id, "❌ داده شهر کافی نیست.")
        return

    n_samples = len(city_data)
    n_hours = n_samples  # هر نمونه = 1 ساعت

    # ── محاسبه شیب شهر ──────────────────────────────────────────────────────────
    city_slopes = {}
    city_current = {}
    for key in ("meo_meo", "population", "fish", "treasury"):
        vals = [r[key] for r in city_data if key in r]
        city_slopes[key] = calc_slope(vals)
        city_current[key] = vals[-1] if vals else None

    lines = [
        f"📊 **تحلیل رشد** ({n_samples} نمونه = ~{n_hours} ساعت داده)\n",
        "━━━━━━━━━━━━━━━━━━━━",
        "🏰 **شهر پیشی — رشد هر ساعت**",
    ]

    param_meta = [
        ("meo_meo",    "🐾 میو میو"),
        ("population", "🐈 جمعیت"),
        ("fish",       "🎣 ماهی"),
        ("treasury",   "🏦 خزانه"),
    ]
    for key, label in param_meta:
        cur = city_current.get(key)
        sl = city_slopes.get(key)
        total_change = (sl * n_hours) if sl is not None and n_samples >= 2 else None
        sl_str = f"+{sl:,.1f}/h" if sl and sl >= 0 else (f"{sl:,.1f}/h" if sl is not None else "ناکافی")
        total_str = f"(+{total_change:,.0f} در {n_hours}h)" if total_change is not None else ""
        lines.append(f"  {label}: {fmt_num(cur)}  ←  {sl_str} {total_str}")

    # ── لیدربرد میو میو ──────────────────────────────────────────────────────────
    meo_records = [r for r in lb_data if r.get("type") == "meo_meo"]
    if meo_records:
        lines.append("\n━━━━━━━━━━━━━━━━━━━━")
        lines.append("🐾 **لیدربرد میو میو — رشد هر گروه**")

        # گروه‌بندی بر اساس رتبه (group_raw شامل 🥇🥈... هست)
        groups: dict = {}
        for r in meo_records:
            raw = r.get("group_raw", "")
            # کلید = بخش بعد از : (اسم گروه)
            key_name = raw.split(":")[-1].strip() if ":" in raw else raw.strip()
            key_name = key_name[:35]
            if key_name not in groups:
                groups[key_name] = {"meo_meo": [], "population": [], "treasury": []}
            for p in ("meo_meo", "population", "treasury"):
                if p in r:
                    groups[key_name][p].append(r[p])

        for gname, gvals in list(groups.items())[:5]:
            meo_vals = gvals["meo_meo"]
            meo_cur = meo_vals[-1] if meo_vals else None
            meo_sl = calc_slope(meo_vals)
            meo_sl_str = f"+{meo_sl:,.1f}/h" if meo_sl and meo_sl >= 0 else (f"{meo_sl:,.1f}/h" if meo_sl else "ناکافی")
            n_g = len(meo_vals)
            total_g = (meo_sl * n_g) if meo_sl and n_g >= 2 else None
            total_g_str = f"(+{total_g:,.0f} در {n_g}h)" if total_g else ""
            lines.append(f"  📌 {gname}")
            lines.append(f"    🐾 میو: {fmt_num(meo_cur)}  ←  {meo_sl_str} {total_g_str}")

        # ── مقایسه شهر با رتبه اول لیدربرد ─────────────────────────────────────
        first_group = list(groups.values())[0] if groups else None
        if first_group and city_current.get("meo_meo") is not None:
            fg_meo_vals = first_group["meo_meo"]
            fg_cur = fg_meo_vals[-1] if fg_meo_vals else None
            fg_sl = calc_slope(fg_meo_vals)
            my_cur = city_current["meo_meo"]
            my_sl = city_slopes["meo_meo"]
            eta = hours_to_reach(my_cur, fg_cur or 0, my_sl or 0, fg_sl or 0)
            lines.append("\n━━━━━━━━━━━━━━━━━━━━")
            lines.append("🏁 **شهر vs رتبه ۱ لیدربرد میو میو**")
            lines.append(f"  شهر:    {fmt_num(my_cur)} میو  ({'+' if (my_sl or 0) >= 0 else ''}{(my_sl or 0):,.1f}/h)")
            lines.append(f"  رتبه ۱: {fmt_num(fg_cur)} میو  ({'+' if (fg_sl or 0) >= 0 else ''}{(fg_sl or 0):,.1f}/h)")
            lines.append(f"  فاصله: {fmt_num((fg_cur or 0) - my_cur)} میو")
            lines.append(f"  ⏱ ETA: **{fmt_eta(eta)}**")

    # ── لیدربرد بازار ماهی ───────────────────────────────────────────────────────
    fish_records = [r for r in lb_data if r.get("type") == "fish_market"]
    if fish_records and city_current.get("fish") is not None:
        fish_groups: dict = {}
        for r in fish_records:
            raw = r.get("group_raw", "")
            key_name = raw.split(":")[-1].strip() if ":" in raw else raw.strip()
            key_name = key_name[:35]
            if key_name not in fish_groups:
                fish_groups[key_name] = {"fish": [], "meo_meo": [], "population": []}
            for p in ("fish", "meo_meo", "population"):
                if p in r:
                    fish_groups[key_name][p].append(r[p])

        first_fish = list(fish_groups.values())[0] if fish_groups else None
        if first_fish:
            ff_vals = first_fish["fish"]
            ff_cur = ff_vals[-1] if ff_vals else None
            ff_sl = calc_slope(ff_vals)
            my_cur = city_current["fish"]
            my_sl = city_slopes["fish"]
            eta = hours_to_reach(my_cur, ff_cur or 0, my_sl or 0, ff_sl or 0)
            lines.append("\n━━━━━━━━━━━━━━━━━━━━")
            lines.append("🏁 **شهر vs رتبه ۱ بازار ماهی**")
            lines.append(f"  شهر:    {fmt_num(my_cur)} ماهی  ({'+' if (my_sl or 0) >= 0 else ''}{(my_sl or 0):,.1f}/h)")
            lines.append(f"  رتبه ۱: {fmt_num(ff_cur)} ماهی  ({'+' if (ff_sl or 0) >= 0 else ''}{(ff_sl or 0):,.1f}/h)")
            lines.append(f"  فاصله: {fmt_num((ff_cur or 0) - my_cur)} ماهی")
            lines.append(f"  ⏱ ETA: **{fmt_eta(eta)}**")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:4000] + "\n\n..."
    await client.send_message(chat_id, msg, parse_mode="md")
    logger.info("Compare sent.")

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

    # "امار پیشی" — Saved Messages (خودم) + گروه هدف (همه)
    @client.on(events.NewMessage(pattern=r"(?i)امار پیشی"))
    async def stats_handler(event):
        chat_id = event.chat_id
        is_saved = event.is_private and hasattr(event.message.peer_id, "user_id") and event.message.peer_id.user_id == me.id
        is_group = chat_id == GROUP_CHAT_ID
        if is_saved or is_group:
            await send_stats(client, chat_id)

    # "مقایسه" — Saved Messages + گروه (همه)
    @client.on(events.NewMessage(pattern=r"(?i)مقایسه"))
    async def compare_handler(event):
        chat_id = event.chat_id
        is_saved = event.is_private and hasattr(event.message.peer_id, "user_id") and event.message.peer_id.user_id == me.id
        is_group = chat_id == GROUP_CHAT_ID
        if is_saved or is_group:
            await send_compare(client, chat_id)

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
