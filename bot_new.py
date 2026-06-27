import asyncio
import os
import sys
import re
import json
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

# ─── تنظیمات ──────────────────────────────────────────────────────────────────

LEADERBOARD_FILE = "leaderboard_stats.json"
CITY_FILE = "city_stats.json"
MEOWIE_BOT = "@MeowieQBot"

DEFAULT_MIU_INTERVAL   = 5  * 60
DEFAULT_MAHI_INTERVAL  = 46 * 60
DEFAULT_PISHI_INTERVAL = 3  * 60 * 60
STATS_INTERVAL         = 60 * 60


def get_env(name, required=True):
    val = os.getenv(name, "").strip()
    if required and not val:
        print(f"❌ متغیر '{name}' تنظیم نشده.")
        sys.exit(1)
    return val


API_ID         = int(get_env("API_ID"))
API_HASH       = get_env("API_HASH")
SESSION_STRING = get_env("SESSION_STRING")
GROUP_USERNAME = int(get_env("GROUP_USERNAME"))

# ─── حالت و فاصله‌های قابل تغییر ─────────────────────────────────────────────

is_running     = True
miu_interval   = DEFAULT_MIU_INTERVAL
mahi_interval  = DEFAULT_MAHI_INTERVAL
pishi_interval = DEFAULT_PISHI_INTERVAL


# ══════════════════════════════════════════════════════════════════════════════
# ابزارهای متنی
# ══════════════════════════════════════════════════════════════════════════════

def remove_emoji(text: str) -> str:
    pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002500-\U00002BEF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff"
        u"\u2640-\u2642\u2600-\u2B55"
        u"\u200d\u23cf\u23e9\u231a\ufe0f\u3030"
        "]+",
        flags=re.UNICODE,
    )
    text = pattern.sub("", text)
    text = re.sub(r"[┘─⋆₊˚]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def to_int(text: str):
    if not text:
        return None
    m = re.search(r"[\d,]+", str(text))
    return int(m.group().replace(",", "")) if m else None


def parse_shekam(text: str):
    if not text:
        return None
    for line in text.split("\n"):
        if "شکم" in line:
            return "hungry" if "من گشنمیووو" in line else "full"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# پارس لیدربرد
# ══════════════════════════════════════════════════════════════════════════════

def parse_leaderboard(text: str):
    medal_map = {"🥇": 1, "🥈": 2, "🥉": 3, "🎖": 4, "🏅": 5}

    group_rank = None
    m = re.search(r"رتبه گروه\s*[:`]?\s*`?([\d,]+)`?", text)
    if m:
        group_rank = to_int(m.group(1))

    groups = []
    for block in re.split(r"(?=🥇|🥈|🥉|🎖|🏅)", text):
        medal = next((num for em, num in medal_map.items() if block.startswith(em)), None)
        if medal is None:
            continue

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        first = lines[0] if lines else ""
        for em in medal_map:
            first = first.replace(em, "").strip()
        name_part = re.sub(r"^[^:]+:\s*", "", first).strip()
        name = remove_emoji(name_part if name_part else first)

        entry = {"rank": medal, "name": name,
                 "miu_count": None, "population": None, "treasury": None}
        for line in lines[1:]:
            if "میو میو" in line:
                entry["miu_count"] = to_int(line)
            elif "جمعیت" in line:
                entry["population"] = to_int(line)
            elif "خزانه" in line:
                entry["treasury"] = to_int(line)

        groups.append(entry)

    return groups, group_rank


# ══════════════════════════════════════════════════════════════════════════════
# پارس آمار شهر
# ══════════════════════════════════════════════════════════════════════════════

def parse_city_stats(text: str) -> dict:
    s = {}

    m = re.search(r"شهر پیشی\s+[`']?([^`'\n🏰⭐]+)", text)
    if m:
        s["city_name"] = remove_emoji(m.group(1)).strip()

    m = re.search(r"سطح شهر\s*[:`]\s*`?([^`\n]+)`?", text)
    if m:
        s["level"] = m.group(1).strip()

    for key, pattern in [
        ("miu_count",       r"میو میو ها\s*[:`]\s*`?([\d,]+)`?"),
        ("population",      r"جمعیت\s*[:`]\s*`?([\d,]+)`?"),
        ("fish",            r"ماهی ها\s*[:`]\s*`?([\d,]+)`?"),
        ("treasury",        r"خزانه\s*[:`]\s*`?([\d,]+)`?"),
    ]:
        m = re.search(pattern, text)
        if m:
            s[key] = to_int(m.group(1))

    for key, pattern in [
        ("miu_rank",        r"میو میو ها[^\n]*\n[^\n]*رتبه شهر[^\d]*([\d,]+)"),
        ("population_rank", r"جمعیت[^\n]*\n[^\n]*رتبه شهر[^\d]*([\d,]+)"),
        ("fish_rank",       r"ماهی ها[^\n]*\n[^\n]*رتبه شهر[^\d]*([\d,]+)"),
        ("treasury_rank",   r"خزانه[^\n]*\n[^\n]*رتبه شهر[^\d]*([\d,]+)"),
    ]:
        m = re.search(pattern, text)
        if m:
            s[key] = to_int(m.group(1))

    return s


# ══════════════════════════════════════════════════════════════════════════════
# ذخیره‌سازی
# ══════════════════════════════════════════════════════════════════════════════

def save_leaderboard(groups: list, timestamp: str):
    """
    ساختار: { "نام گروه": [ {timestamp, rank, miu_count, population, treasury}, ... ] }
    """
    data = {}
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    for g in groups:
        name = g.get("name", "")
        if not name:
            continue
        data.setdefault(name, []).append({
            "timestamp":  timestamp,
            "rank":       g["rank"],
            "miu_count":  g["miu_count"],
            "population": g["population"],
            "treasury":   g["treasury"],
        })

    with open(LEADERBOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_city_stats(stats: dict, timestamp: str):
    """
    ساختار: { "city_name": "...", "records": [ {timestamp, miu_count, ...}, ... ] }
    """
    data = {"city_name": stats.get("city_name", "نامشخص"), "records": []}
    if os.path.exists(CITY_FILE):
        try:
            with open(CITY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    data.setdefault("records", []).append({
        "timestamp":       timestamp,
        "level":           stats.get("level"),
        "miu_count":       stats.get("miu_count"),
        "miu_rank":        stats.get("miu_rank"),
        "population":      stats.get("population"),
        "population_rank": stats.get("population_rank"),
        "fish":            stats.get("fish"),
        "fish_rank":       stats.get("fish_rank"),
        "treasury":        stats.get("treasury"),
        "treasury_rank":   stats.get("treasury_rank"),
    })

    with open(CITY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# کلاینت اصلی
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    global is_running, miu_interval, mahi_interval, pishi_interval

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"[bot] logged in as {me.username or me.id}")

    pending      = {}   # msg_id → {type, shekam}
    gorbe_clicks = {}   # msg_id → click count
    gorbe_counter = 0

    # ── کلیک گربه ──────────────────────────────────────────────────────────────

    async def click_gorbe(msg_id):
        for i in range(3):
            try:
                msg = await client.get_messages(GROUP_USERNAME, ids=msg_id)
                if not msg or not msg.buttons:
                    break
                await msg.click(0)
                gorbe_clicks[msg_id] = i + 1
                print(f"[gorbe] click {i+1}")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[gorbe] error: {e}")
                await asyncio.sleep(0.5)

    # ── جمع‌آوری لیدربرد ────────────────────────────────────────────────────────

    async def collect_leaderboard():
        print("[leaderboard] start")
        try:
            meowie = await client.get_entity(MEOWIE_BOT)
            sent = await client.send_message(meowie, "لیدربرد")
            await asyncio.sleep(3)

            # ریپلای ربات با ۲ دکمه
            reply_msg = None
            async for m in client.iter_messages(meowie, limit=5):
                if m.id != sent.id and m.buttons:
                    reply_msg = m
                    break
            if not reply_msg:
                print("[leaderboard] no reply")
                return

            # دکمه دوم → منوی ۴تایی
            await reply_msg.click(1)
            await asyncio.sleep(3)
            menu_msg = await client.get_messages(meowie, ids=reply_msg.id)
            if not menu_msg or not menu_msg.buttons:
                print("[leaderboard] no 4-btn menu")
                return

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for i in range(4):
                try:
                    await menu_msg.click(i)
                    print(f"[leaderboard] clicked btn {i+1}")
                    await asyncio.sleep(3)

                    lb = await client.get_messages(meowie, ids=menu_msg.id)
                    if lb and lb.text:
                        groups, group_rank = parse_leaderboard(lb.text)
                        save_leaderboard(groups, timestamp)
                        print(f"[leaderboard] saved {len(groups)} groups, our_rank={group_rank}")

                    # بازگشت به منو
                    if i < 3 and lb and lb.buttons:
                        flat = [b for row in lb.buttons for b in row]
                        await lb.click(len(flat) - 1)
                        await asyncio.sleep(2)
                        menu_msg = await client.get_messages(meowie, ids=menu_msg.id)

                except Exception as e:
                    print(f"[leaderboard] btn {i+1} error: {e}")

            # بازگشت نهایی
            try:
                final = await client.get_messages(meowie, ids=menu_msg.id)
                if final and final.buttons:
                    flat = [b for row in final.buttons for b in row]
                    await final.click(len(flat) - 1)
            except Exception:
                pass

        except Exception as e:
            print(f"[leaderboard] fatal: {e}")

    # ── جمع‌آوری آمار شهر ───────────────────────────────────────────────────────

    async def collect_city():
        print("[city] start")
        try:
            sent = await client.send_message(GROUP_USERNAME, "شهر میویی")
            await asyncio.sleep(5)

            async for m in client.iter_messages(GROUP_USERNAME, limit=10):
                if m.reply_to and m.reply_to.reply_to_msg_id == sent.id and m.id != sent.id:
                    stats = parse_city_stats(m.text or "")
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_city_stats(stats, timestamp)
                    print(f"[city] saved miu={stats.get('miu_count')} pop={stats.get('population')}")
                    break
            else:
                print("[city] no reply found")

        except Exception as e:
            print(f"[city] error: {e}")

    # ── تسک یک‌ساعته ────────────────────────────────────────────────────────────

    async def hourly_stats():
        await asyncio.sleep(30)
        while True:
            if is_running:
                await asyncio.gather(collect_leaderboard(), collect_city())
            await asyncio.sleep(STATS_INTERVAL)

    # ── تسک میو ─────────────────────────────────────────────────────────────────

    async def send_miu():
        while True:
            if is_running:
                try:
                    await client.send_message(GROUP_USERNAME, "معو")
                    print("[miu] sent")
                except Exception as e:
                    print(f"[miu] error: {e}")
            await asyncio.sleep(miu_interval)

    # ── تسک ماهی ────────────────────────────────────────────────────────────────

    async def send_mahi():
        await asyncio.sleep(10)
        while True:
            if is_running:
                try:
                    check = await client.send_message(GROUP_USERNAME, "پیشی")
                    await asyncio.sleep(4)
                    shekam = None
                    async for r in client.iter_messages(GROUP_USERNAME, limit=15):
                        if r.reply_to and r.reply_to.reply_to_msg_id == check.id:
                            shekam = parse_shekam(r.text)
                            break
                    msg = await client.send_message(GROUP_USERNAME, "ماهی")
                    pending[msg.id] = {"type": "mahi", "shekam": shekam}
                    print(f"[mahi] sent shekam={shekam}")
                except Exception as e:
                    print(f"[mahi] error: {e}")
            await asyncio.sleep(mahi_interval)

    # ── تسک پیشی ────────────────────────────────────────────────────────────────

    async def send_pishi():
        await asyncio.sleep(5)
        while True:
            if is_running:
                try:
                    msg = await client.send_message(GROUP_USERNAME, "پیشی")
                    pending[msg.id] = {"type": "pishi"}
                    print("[pishi] sent")
                except Exception as e:
                    print(f"[pishi] error: {e}")
            await asyncio.sleep(pishi_interval)

    # ── هندلر پیام جدید ─────────────────────────────────────────────────────────

    @client.on(events.NewMessage(chats=GROUP_USERNAME))
    async def on_new_message(event):
        nonlocal gorbe_counter
        global is_running, miu_interval, mahi_interval, pishi_interval
        msg = event.message

        # پیام‌های خودمون
        if event.sender_id == me.id:
            text = msg.text.strip() if msg.text else ""

            if text.lower() == "stop":
                is_running = False
                await client.send_message(GROUP_USERNAME, "متوقف شد ⛔")
                return

            if text.lower() == "start":
                is_running = True
                await client.send_message(GROUP_USERNAME, "شروع شد ✅")
                return

            if text == "امار پیشی":
                sent_any = False
                for fpath, label in [(LEADERBOARD_FILE, "لیدربرد"), (CITY_FILE, "شهر")]:
                    if os.path.exists(fpath):
                        await client.send_file(
                            "me", fpath,
                            caption=f"📊 آمار {label} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        )
                        sent_any = True
                if sent_any:
                    await client.send_message(GROUP_USERNAME, "✅ فایل‌های آمار به سیو مسیج ارسال شد.")
                else:
                    await client.send_message(GROUP_USERNAME, "❌ هنوز آماری ذخیره نشده.")
                return

            if text.startswith("تنظیم میو "):
                parts = text.split()
                if parts[-1] == "دیفالت":
                    miu_interval = DEFAULT_MIU_INTERVAL
                    await client.send_message(GROUP_USERNAME, f"✅ میو دیفالت ({DEFAULT_MIU_INTERVAL//60} دقیقه)")
                else:
                    try:
                        miu_interval = int(parts[-1]) * 60
                        await client.send_message(GROUP_USERNAME, f"✅ میو هر {parts[-1]} دقیقه")
                    except ValueError:
                        await client.send_message(GROUP_USERNAME, "❌ مثال: تنظیم میو 10")
                return

            if text.startswith("تنظیم ماهی "):
                parts = text.split()
                if parts[-1] == "دیفالت":
                    mahi_interval = DEFAULT_MAHI_INTERVAL
                    await client.send_message(GROUP_USERNAME, f"✅ ماهی دیفالت ({DEFAULT_MAHI_INTERVAL//60} دقیقه)")
                else:
                    try:
                        mahi_interval = int(parts[-1]) * 60
                        await client.send_message(GROUP_USERNAME, f"✅ ماهی هر {parts[-1]} دقیقه")
                    except ValueError:
                        await client.send_message(GROUP_USERNAME, "❌ مثال: تنظیم ماهی 60")
                return

            if text.startswith("تنظیم پیشی "):
                parts = text.split()
                if parts[-1] == "دیفالت":
                    pishi_interval = DEFAULT_PISHI_INTERVAL
                    await client.send_message(GROUP_USERNAME, f"✅ پیشی دیفالت ({DEFAULT_PISHI_INTERVAL//60} دقیقه)")
                else:
                    try:
                        pishi_interval = int(parts[-1]) * 60
                        await client.send_message(GROUP_USERNAME, f"✅ پیشی هر {parts[-1]} دقیقه")
                    except ValueError:
                        await client.send_message(GROUP_USERNAME, "❌ مثال: تنظیم پیشی 180")
                return

        # گربه خیابونی
        if msg.text and "گربه خیابونی" in msg.text:
            gorbe_counter += 1
            if gorbe_counter % 3 == 0:
                asyncio.create_task(click_gorbe(msg.id))
            return

        # ریپلای ربات به پیام‌های pending
        if not msg.reply_to:
            return
        rid = msg.reply_to.reply_to_msg_id
        if rid not in pending or not msg.buttons:
            return
        task = pending[rid]
        try:
            if task["type"] == "pishi":
                pending.pop(rid)
                await msg.click(0)
                print("[pishi] clicked btn 1")
        except Exception as e:
            print(f"[pishi] error: {e}")

    # ── هندلر ادیت پیام ─────────────────────────────────────────────────────────

    @client.on(events.MessageEdited(chats=GROUP_USERNAME))
    async def on_message_edited(event):
        msg = event.message

        if msg.text and "گربه خیابونی" in msg.text:
            if gorbe_clicks.get(msg.id, 0) < 3:
                asyncio.create_task(click_gorbe(msg.id))
            return

        if not msg.reply_to:
            return
        rid = msg.reply_to.reply_to_msg_id
        if rid not in pending or not msg.buttons:
            return
        task = pending[rid]
        try:
            if task["type"] == "mahi":
                pending.pop(rid)
                idx = 1 if task.get("shekam") == "hungry" else 0
                await msg.click(idx)
                print(f"[mahi] clicked btn {idx+1}")
        except Exception as e:
            print(f"[mahi] error: {e}")

    # ── اجرا ────────────────────────────────────────────────────────────────────

    await asyncio.gather(
        send_miu(),
        send_mahi(),
        send_pishi(),
        hourly_stats(),
        client.run_until_disconnected(),
    )


if __name__ == "__main__":
    asyncio.run(main())
