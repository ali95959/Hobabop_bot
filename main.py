import os
import re
import html
import time
import math
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone

import psycopg
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommandScopeChat,
)
from telegram.error import TelegramError, Forbidden, BadRequest, RetryAfter
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    TypeHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # جلوگیری از لاگ شدن توکن در URLها
logger = logging.getLogger("hobab-bot")

# توکن ربات
# اگر متغیر محیطی BOT_TOKEN تنظیم شده باشد همان استفاده می‌شود؛ در غیر این صورت مقدار پیش‌فرض زیر.
TOKEN = os.environ.get("BOT_TOKEN") or "8998126217:AAF91fQE3VRIIfhCLx9HwBviwXdxIG6X0DA"

# آیدی عددی ادمین
ADMIN_ID = 6922701713

# یوزرنیم پشتیبانی
ADMIN_USERNAME = "Hobabadmin"

# یوزرنیم ربات چک مانده سرویس
BALANCE_BOT_USERNAME = "reportvolume_bot"

# الگوی نام کاربری معتبر سرور جهت تمدید: provpn + عدد انگلیسی (مثال: provpn27)
RENEWAL_USERNAME_PATTERN = re.compile(r"^provpn[0-9]+$")
CARD_NUMBER = "5022 2913 3683 0904"
CARD_HOLDER = "علی باقری فرد"

PLANS = {
    "single": {
        "title": "🌀 تک کاربره",
        "subcats": {
            "m1": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "s_m1_20", "label": "یکماه تک کاربر ۲۰ گیگ", "toman": 260},
                    {"id": "s_m1_40", "label": "یکماه تک کاربر ۴۰ گیگ", "toman": 420, "recommended": True},
                    {"id": "s_m1_60", "label": "یکماه تک کاربر ۶۰ گیگ", "toman": 550},
                    {"id": "s_m1_100", "label": "یکماه تک کاربر ۱۰۰ گیگ", "toman": 690},
                ],
            },
            "m3": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "s_m3_100", "label": "سه ماه تک کاربر ۱۰۰ گیگ", "toman": 1190, "recommended": True},
                    {"id": "s_m3_150", "label": "سه ماه تک کاربر ۱۵۰ گیگ", "toman": 1390},
                    {"id": "s_m3_180", "label": "سه ماه تک کاربر ۱۸۰ گیگ", "toman": 1590},
                ],
            },
        },
    },
    "double": {
        "title": "🌀 دو کاربره",
        "subcats": {
            "m1": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "d_m1_40", "label": "یکماه دو کاربر ۴۰ گیگ", "toman": 590},
                    {"id": "d_m1_60", "label": "یکماه دو کاربر ۶۰ گیگ", "toman": 740},
                    {"id": "d_m1_80", "label": "یکماه دو کاربر ۸۰ گیگ", "toman": 840, "recommended": True},
                    {"id": "d_m1_100", "label": "یکماه دو کاربر ۱۰۰ گیگ", "toman": 930},
                ],
            },
            "m3": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "d_m3_100", "label": "سه ماه دو کاربر ۱۰۰ گیگ", "toman": 1490},
                    {"id": "d_m3_200", "label": "سه ماه دو کاربر ۲۰۰ گیگ", "toman": 1990},
                    {"id": "d_m3_360", "label": "سه ماه دو کاربر ۳۶۰ گیگ", "toman": 2390, "recommended": True},
                ],
            },
        },
    },
}

CHANNEL_USERNAME = "HobabServices"

def to_persian_digits(text: str) -> str:
    return text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

def format_toman(amount: int) -> str:
    return f"{to_persian_digits(f'{amount:,}')} تومن"

def format_rial(amount_toman: int) -> str:
    rial = amount_toman * 10_000
    return f"{to_persian_digits(f'{rial:,}')} ریال"

def find_plan(plan_id: str):
    for cat_key, category in PLANS.items():
        for sub_key, sub in category["subcats"].items():
            for item in sub["items"]:
                if item["id"] == plan_id:
                    return cat_key, sub_key, item
    return None, None, None

def plan_button_text(item: dict) -> str:
    prefix = "🔥 (پیشنهادی) " if item.get("recommended") else ""
    return f"{prefix}{item['label']} — {format_toman(item['toman'])}"

def get_recommended_plans():
    result = []
    for cat_key, category in PLANS.items():
        for sub_key, sub in category["subcats"].items():
            for item in sub["items"]:
                if item.get("recommended"):
                    result.append((cat_key, sub_key, item))
    return result

def build_full_price_list_text() -> str:
    lines = [
        "💎 **لیست کلی تعرفه‌های اشتراک طرح پرو** 💎",
        "🔥 = پلن پیشنهادی ما",
        "────────────────────",
        "",
    ]
    for cat_key in ("single", "double"):
        cat = PLANS[cat_key]
        lines.append(f"📌 **{cat['title']}**")
        lines.append("")
        for sub_key in ("m1", "m3"):
            sub = cat["subcats"][sub_key]
            lines.append(f"  🔹 {sub['title']}:")
            for item in sub["items"]:
                mark = "  🔥 (پیشنهادی)" if item.get("recommended") else ""
                lines.append(f"     • {item['label']} ── 💰 **{format_toman(item['toman'])}**{mark}")
            lines.append("")
        lines.append("────────────────────")
        lines.append("")
    lines.append(f"📢 کانال ما: @{CHANNEL_USERNAME}")
    return "\n".join(lines).strip()

DATABASE_URL = os.environ.get("DATABASE_URL")

def _db_execute(query: str, params: tuple = (), fetch: str = None):
    """اجرای یک کوئری روی Postgres (Neon). یک بار تلاش مجدد برای زمانی که دیتابیس تازه از خواب بیدار می‌شود."""
    if not DATABASE_URL:
        raise RuntimeError("متغیر محیطی DATABASE_URL تنظیم نشده است.")
    last_exc = None
    for _attempt in range(2):
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    if fetch == "one":
                        return cur.fetchone()
                    if fetch == "all":
                        return cur.fetchall()
                    return None
        except psycopg.OperationalError as exc:
            last_exc = exc
            logger.warning("DB connection problem, retrying: %s", exc)
            time.sleep(1)
    raise last_exc

def init_db():
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            plan_label TEXT NOT NULL,
            price TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS user_state (
            user_id BIGINT PRIMARY KEY,
            pending_plan_id TEXT,
            renewal_username TEXT,
            updated_at TEXT
        )
        """
    )
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            first_seen TEXT,
            blocked BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    _db_execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    _db_execute(
        """
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS duration_days INTEGER,
            ADD COLUMN IF NOT EXISTS amount_toman INTEGER,
            ADD COLUMN IF NOT EXISTS created_ts TIMESTAMP,
            ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS renewal_username TEXT,
            ADD COLUMN IF NOT EXISTS receipt_file_id TEXT,
            ADD COLUMN IF NOT EXISTS receipt_is_photo BOOLEAN,
            ADD COLUMN IF NOT EXISTS expiry_reminded BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS admin_reminded BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    backfill_orders()
    apply_saved_settings()

# ---------- زمان و ابزارهای کمکی ----------
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
PERSIAN_TO_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DURATION_DAYS = {"m1": 30, "m3": 90}   # مدت هر پلن (کلید زیرمجموعه در PLANS)
REMINDER_DAYS_BEFORE = 3               # چند روز قبل از پایان سرویس یادآوری برود
PENDING_REMIND_MINUTES = 30            # بعد از چند دقیقه رسید بی‌جواب به ادمین یادآوری شود
BACKGROUND_INTERVAL = 3600             # فاصله‌ی اجرای کارهای پس‌زمینه (ثانیه)

def now_dt() -> datetime:
    """زمان فعلی به وقت تهران (بدون tzinfo)؛ مستقل از ساعت سرور."""
    return datetime.now(TEHRAN_TZ).replace(tzinfo=None)

def _now() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")

def parse_int(text: str) -> int:
    digits = re.sub(r"\D", "", (text or "").translate(PERSIAN_TO_EN))
    return int(digits) if digits else 0

def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd

def backfill_orders():
    """سفارش‌های قدیمی (قبل از این نسخه) را با فیلدهای جدید کامل می‌کند؛ فقط یک بار برای هر سفارش اجرا می‌شود."""
    rows = _db_execute(
        "SELECT id, created_at, status, plan_label, price FROM orders WHERE created_ts IS NULL",
        (), "all",
    ) or []
    for oid, created_at, status, label, price in rows:
        try:
            ts = datetime.strptime(created_at, "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            ts = now_dt()
        days = 90 if "سه ماه" in (label or "") else 30
        confirmed = status == "confirmed"
        _db_execute(
            "UPDATE orders SET created_ts = %s, duration_days = %s, amount_toman = %s, "
            "confirmed_at = %s, expires_at = %s WHERE id = %s",
            (ts, days, parse_int(price), ts if confirmed else None,
             ts + timedelta(days=days) if confirmed else None, oid),
        )
    # کاربران قدیمی را هم وارد جدول users می‌کنیم تا پیام همگانی به آن‌ها برسد
    _db_execute(
        "INSERT INTO users (user_id, first_seen) SELECT user_id, MIN(created_at) FROM orders "
        "GROUP BY user_id ON CONFLICT (user_id) DO NOTHING"
    )
    _db_execute(
        "INSERT INTO users (user_id, first_seen) SELECT user_id, MIN(updated_at) FROM user_state "
        "GROUP BY user_id ON CONFLICT (user_id) DO NOTHING"
    )

def apply_saved_settings():
    """قیمت‌ها، شماره کارت و نام صاحب کارت ذخیره‌شده در دیتابیس را روی تنظیمات برنامه اعمال می‌کند."""
    global CARD_NUMBER, CARD_HOLDER
    rows = _db_execute("SELECT key, value FROM settings", (), "all") or []
    for key, value in rows:
        if key == "card_number":
            CARD_NUMBER = value
        elif key == "card_holder":
            CARD_HOLDER = value
        elif key.startswith("price_"):
            _, _, item = find_plan(key[len("price_"):])
            if item:
                try:
                    item["toman"] = int(value)
                except ValueError:
                    pass

async def set_setting(key: str, value: str):
    await asyncio.to_thread(
        _db_execute,
        "INSERT INTO settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )

# ---------- سفارش‌ها ----------
async def create_order(
    user_id: int, plan_label: str, price: str, amount_toman: int, duration_days: int,
    renewal_username, receipt_file_id, receipt_is_photo: bool,
) -> int:
    row = await asyncio.to_thread(
        _db_execute,
        "INSERT INTO orders (user_id, plan_label, price, status, created_at, created_ts, amount_toman, "
        "duration_days, renewal_username, receipt_file_id, receipt_is_photo) "
        "VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, plan_label, price, _now(), now_dt(), amount_toman, duration_days,
         renewal_username, receipt_file_id, receipt_is_photo),
        "one",
    )
    return row[0]

async def get_order(order_id: int):
    row = await asyncio.to_thread(
        _db_execute,
        "SELECT id, user_id, plan_label, price, status, created_at, duration_days FROM orders WHERE id = %s",
        (order_id,),
        "one",
    )
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "plan_label": row[2],
        "price": row[3],
        "status": row[4],
        "created_at": row[5],
        "duration_days": row[6],
    }

async def set_order_status(order_id: int, status: str):
    await asyncio.to_thread(
        _db_execute, "UPDATE orders SET status = %s WHERE id = %s", (status, order_id)
    )

async def finalize_order(order_id: int, status: str, duration_days=None) -> bool:
    """وضعیت سفارش را فقط در صورتی که هنوز pending باشد تغییر می‌دهد (جلوگیری از تایید/رد دوباره).
    در صورت تایید، تاریخ تایید و تاریخ پایان سرویس هم ثبت می‌شود."""
    now = now_dt()
    confirmed = status == "confirmed"
    expires = now + timedelta(days=duration_days or 30) if confirmed else None
    row = await asyncio.to_thread(
        _db_execute,
        "UPDATE orders SET status = %s, confirmed_at = %s, expires_at = %s "
        "WHERE id = %s AND status = 'pending' RETURNING id",
        (status, now if confirmed else None, expires, order_id),
        "one",
    )
    return row is not None

async def get_user_orders(user_id: int, status: str = "confirmed"):
    return await asyncio.to_thread(
        _db_execute,
        "SELECT plan_label, price, created_at FROM orders WHERE user_id = %s AND status = %s ORDER BY id DESC",
        (user_id, status),
        "all",
    )

# ---------- حالت موقت کاربر (پلن در انتظار پرداخت / نام کاربری تمدید) ----------
# این توابع هیچ‌وقت خطا پرتاب نمی‌کنند تا مشکل دیتابیس باعث از کار افتادن منوها نشود.
async def save_pending_plan(user_id: int, plan_id: str):
    try:
        await asyncio.to_thread(
            _db_execute,
            "INSERT INTO user_state (user_id, pending_plan_id, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET pending_plan_id = EXCLUDED.pending_plan_id, "
            "updated_at = EXCLUDED.updated_at",
            (user_id, plan_id, _now()),
        )
    except Exception:
        logger.exception("save_pending_plan failed for user %s", user_id)

async def save_renewal_username(user_id: int, username: str):
    try:
        await asyncio.to_thread(
            _db_execute,
            "INSERT INTO user_state (user_id, renewal_username, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET renewal_username = EXCLUDED.renewal_username, "
            "updated_at = EXCLUDED.updated_at",
            (user_id, username, _now()),
        )
    except Exception:
        logger.exception("save_renewal_username failed for user %s", user_id)

async def clear_pending_plan(user_id: int):
    try:
        await asyncio.to_thread(
            _db_execute,
            "UPDATE user_state SET pending_plan_id = NULL, updated_at = %s WHERE user_id = %s",
            (_now(), user_id),
        )
    except Exception:
        logger.exception("clear_pending_plan failed for user %s", user_id)

async def get_user_state(user_id: int):
    """(pending_plan_id, renewal_username) را برمی‌گرداند."""
    try:
        row = await asyncio.to_thread(
            _db_execute,
            "SELECT pending_plan_id, renewal_username FROM user_state WHERE user_id = %s",
            (user_id,),
            "one",
        )
        return (row[0], row[1]) if row else (None, None)
    except Exception:
        logger.exception("get_user_state failed for user %s", user_id)
        return (None, None)

async def delete_user_state(user_id: int):
    try:
        await asyncio.to_thread(_db_execute, "DELETE FROM user_state WHERE user_id = %s", (user_id,))
    except Exception:
        logger.exception("delete_user_state failed for user %s", user_id)

def build_my_services_text(orders) -> str:
    if not orders:
        return "📦 هنوز سرویس فعالی برای این حساب ثبت نشده است."
    lines = ["📦 **سرویس‌های فعال شما:**\n"]
    for plan_label, price, created_at in orders:
        lines.append(f"✅ **{plan_label}** — {price}\n🗓 تاریخ خرید: {created_at}\n")
    return "\n".join(lines)

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="plans")],
        [InlineKeyboardButton("🔄 تمدید سرور", callback_data="renew")],
        [InlineKeyboardButton("📋 لیست قیمت‌ها", callback_data="all_prices")],
        [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")],
        [InlineKeyboardButton("📊 چک کردن مانده سرویس", callback_data="check_balance")],
        [InlineKeyboardButton("🎧 پشتیبانی", callback_data="support")],
    ])

BUY_BUTTON_TEXT = "🛒 خرید اشتراک"
RENEW_BUTTON_TEXT = "🔄 تمدید سرور"
PRICE_LIST_BUTTON_TEXT = "📋 لیست قیمت‌ها"
MY_SERVICES_BUTTON_TEXT = "📦 سرویس‌های من"
CHECK_BALANCE_BUTTON_TEXT = "📊 چک کردن مانده سرویس"
SUPPORT_BUTTON_TEXT = "🎧 پشتیبانی"
HOME_BUTTON_TEXT = "🏠 منوی اصلی"

# حذف is_persistent جهت جلوگیری از گیر کردن دکمه بازگشت گوشی
# تمام آیتم‌های منوی اصلی در کنار «منوی اصلی» به صورت کیبورد ثابت نمایش داده می‌شوند
PERSISTENT_KEYBOARD = ReplyKeyboardMarkup(
    [
        [BUY_BUTTON_TEXT, RENEW_BUTTON_TEXT],
        [PRICE_LIST_BUTTON_TEXT, MY_SERVICES_BUTTON_TEXT],
        [CHECK_BALANCE_BUTTON_TEXT, SUPPORT_BUTTON_TEXT],
        [HOME_BUTTON_TEXT],
    ],
    resize_keyboard=True,
)

def plans_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 پلن‌های پیشنهادی (پرفروش‌ترین‌ها)", callback_data="recommended")],
        [InlineKeyboardButton("🌀 تک کاربره", callback_data="cat_single")],
        [InlineKeyboardButton("🌀 دو کاربره", callback_data="cat_double")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")],
    ])

def price_list_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="plans")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")],
    ])

def category_keyboard(cat_key: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ یک ماهه", callback_data=f"sub_{cat_key}_m1")],
        [InlineKeyboardButton("✨ سه ماهه", callback_data=f"sub_{cat_key}_m3")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="plans")],
    ])

def subcat_keyboard(cat_key: str, sub_key: str):
    buttons = []
    for item in PLANS[cat_key]["subcats"][sub_key]["items"]:
        buttons.append([InlineKeyboardButton(plan_button_text(item), callback_data=f"buy_{item['id']}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"cat_{cat_key}")])
    return InlineKeyboardMarkup(buttons)

async def reset_transient_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هرگونه حالت موقتِ در انتظار پاسخ (پلن در انتظار پرداخت، در انتظار نام کاربری) را پاک می‌کند."""
    context.user_data.pop("pending_plan", None)
    context.user_data.pop("awaiting_username", None)
    context.user_data.pop("username_attempts", None)
    if update.effective_user:
        await clear_pending_plan(update.effective_user.id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    await update.message.reply_text(
        "سلام! به ربات حباب خوش آمدید 😉\nجهت خرید یا تمدید سرور OpenConnect در خدمتیم.",
        reply_markup=PERSISTENT_KEYBOARD,
    )
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=main_menu_keyboard(),
    )

async def home_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    await update.message.reply_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_keyboard(),
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    had_active_flow = (
        context.user_data.get("pending_plan") is not None
        or context.user_data.get("awaiting_username") is True
    )
    await reset_transient_state(update, context)
    text = (
        "❌ فرآیند جاری لغو شد و از آن خارج شدید."
        if had_active_flow
        else "چیزی برای لغو کردن وجود نداشت."
    )
    await update.message.reply_text(text, reply_markup=PERSISTENT_KEYBOARD)
    await update.message.reply_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_keyboard(),
    )

async def start_renewal_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, via_callback: bool):
    await reset_transient_state(update, context)
    context.user_data["awaiting_username"] = True
    context.user_data["username_attempts"] = 0

    text = (
        "🔄 **تمدید سرور**\n\n"
        "لطفاً نام کاربری سرور OpenConnect خود را همینجا ارسال کنید.\n\n"
        "📌 فرمت صحیح: کلمه‌ی `provpn` به همراه یک عدد انگلیسی، مثلاً:\n"
        "`provpn27` ✅\n\n"
        "برای انصراف از این مرحله می‌توانید دستور /cancel را ارسال کنید."
    )

    if via_callback:
        query = update.callback_query
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=PERSISTENT_KEYBOARD)

async def buy_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    await update.message.reply_text(
        "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر خود را انتخاب کنید یا لیست کلی قیمت‌ها را ببینید:",
        parse_mode="Markdown",
        reply_markup=plans_keyboard(),
    )

async def price_list_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    await update.message.reply_text(
        build_full_price_list_text(),
        parse_mode="Markdown",
        reply_markup=price_list_keyboard(),
    )

async def renew_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_renewal_flow(update, context, via_callback=False)

async def my_services_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    orders = await get_user_orders(update.effective_user.id, status="confirmed")
    await update.message.reply_text(build_my_services_text(orders), parse_mode="Markdown")

async def check_balance_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 چک کردن مانده", url=f"https://t.me/{BALANCE_BOT_USERNAME}")],
    ])
    await update.message.reply_text(
        "📊 برای بررسی مانده سرویس خود، روی دکمه زیر کلیک کرده و ادامه مراحل را در ربات استعلام انجام دهید:",
        reply_markup=keyboard,
    )

async def support_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_transient_state(update, context)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 ارتباط با پشتیبانی", url=f"https://t.me/{ADMIN_USERNAME}")],
    ])
    await update.message.reply_text(
        "🎧 برای دریافت پشتیبانی روی دکمه زیر کلیک کنید تا مستقیم چت باز شود:",
        reply_markup=keyboard,
    )

async def renewal_username_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیام‌های متنی را در زمانی که ربات منتظر دریافت نام کاربری تمدید سرور است، بررسی می‌کند."""
    if not context.user_data.get("awaiting_username"):
        return

    username = (update.message.text or "").strip()

    if RENEWAL_USERNAME_PATTERN.match(username):
        context.user_data["awaiting_username"] = False
        context.user_data["username_attempts"] = 0
        context.user_data["renewal_username"] = username
        await save_renewal_username(update.effective_user.id, username)
        await update.message.reply_text(
            f"✅ نام کاربری شما با موفقیت تایید شد! (`{username}`)",
            parse_mode="Markdown",
        )
        await update.message.reply_text(
            "لطفاً نوع اشتراک مورد نظر خود جهت تمدید را انتخاب کنید:",
            reply_markup=plans_keyboard(),
        )
        return

    attempts = context.user_data.get("username_attempts", 0) + 1
    context.user_data["username_attempts"] = attempts

    base_text = (
        "❌ نام کاربری شما اشتباه است!\n\n"
        "لطفاً دوباره با فرمت صحیح ارسال کنید، مثلاً:\n"
        "`provpn27`"
    )

    if attempts >= 2:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 ارتباط با پشتیبانی", url=f"https://t.me/{ADMIN_USERNAME}")],
        ])
        await update.message.reply_text(
            base_text + "\n\nاگر در تایید نام کاربری مشکلی برایتان پیش آمده، لطفاً به پشتیبانی پیام دهید.",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(base_text, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "plans":
        await query.edit_message_text(
            "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر خود را انتخاب کنید یا لیست کلی قیمت‌ها را ببینید:",
            parse_mode="Markdown",
            reply_markup=plans_keyboard(),
        )

    elif data == "renew":
        await start_renewal_flow(update, context, via_callback=True)

    elif data == "recommended":
        buttons = [
            [InlineKeyboardButton(plan_button_text(item), callback_data=f"buy_{item['id']}")]
            for _cat, _sub, item in get_recommended_plans()
        ]
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="plans")])
        await query.edit_message_text(
            "🔥 **پلن‌های پیشنهادی ما**\n\n"
            "منتخب پلن‌ها برای هر دسته؛ انتخاب اول بیشتر کاربرها.\n"
            "یکی را انتخاب کنید تا مستقیم به مرحله‌ی پرداخت بروید 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data.startswith("cat_"):
        cat_key = data.split("_", 1)[1]
        await query.edit_message_text(
            f"✨ **{PLANS[cat_key]['title']}**\n\nلطفاً مدت زمان اشتراک را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=category_keyboard(cat_key),
        )

    elif data.startswith("sub_"):
        _, cat_key, sub_key = data.split("_", 2)
        cat = PLANS[cat_key]
        sub = cat["subcats"][sub_key]
        await query.edit_message_text(
            f"⚡️ **{cat['title']} — {sub['title']}**\n\nپلن مورد نظر خود را جهت خرید انتخاب کنید:\n🔥 = پلن پیشنهادی ما",
            parse_mode="Markdown",
            reply_markup=subcat_keyboard(cat_key, sub_key),
        )

    elif data == "all_prices":
        await query.edit_message_text(
            build_full_price_list_text(),
            parse_mode="Markdown",
            reply_markup=price_list_keyboard(),
        )

    elif data.startswith("buy_"):
        plan_id = data.split("_", 1)[1]
        cat_key, sub_key, plan = find_plan(plan_id)
        if not plan:
            await query.edit_message_text("❌ این پلن پیدا نشد، دوباره تلاش کن.")
            return

        context.user_data["pending_plan"] = plan
        await save_pending_plan(query.from_user.id, plan_id)

        renewal_username = context.user_data.get("renewal_username")
        renewal_note = (
            f"🔄 **نام کاربری جهت تمدید:** `{renewal_username}`\n\n" if renewal_username else ""
        )

        recommended_note = "🔥 **انتخاب عالی! این یکی از پلن‌های پیشنهادی ماست.**\n\n" if plan.get("recommended") else ""

        text = (
            f"{renewal_note}"
            f"{recommended_note}"
            f"✅ **پلن انتخابی:** {plan['label']}\n"
            f"💰 **مبلغ:** {format_toman(plan['toman'])}\n"
            f"💱 **معادل ریالی:** {format_rial(plan['toman'])}\n\n"
            f"────────────────────\n"
            f"💳 **شماره کارت جهت واریز:**\n"
            f"`{CARD_NUMBER}`\n"
            f"_(روی شماره کارت بزنید تا کپی شود)_\n"
            f"👤 **به نام:** {CARD_HOLDER}\n"
            f"────────────────────\n\n"
            f"📸 لطفاً بعد از واریز، **عکس رسید پرداخت** را همینجا ارسال کنید تا سریعاً بررسی و تایید شود."
        )
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"sub_{cat_key}_{sub_key}")]]
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "my_services":
        orders = await get_user_orders(query.from_user.id, status="confirmed")
        text = build_my_services_text(orders)
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back")]]
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "support":
        keyboard = [
            [InlineKeyboardButton("💬 ارتباط با پشتیبانی", url=f"https://t.me/{ADMIN_USERNAME}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")],
        ]
        await query.edit_message_text(
            "🎧 برای دریافت پشتیبانی روی دکمه زیر کلیک کنید تا مستقیم چت باز شود:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "check_balance":
        keyboard = [
            [InlineKeyboardButton("📊 چک کردن مانده", url=f"https://t.me/{BALANCE_BOT_USERNAME}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")],
        ]
        await query.edit_message_text(
            "📊 برای بررسی مانده سرویس خود، روی دکمه زیر کلیک کرده و ادامه مراحل را در ربات استعلام انجام دهید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "back":
        await reset_transient_state(update, context)
        await query.edit_message_text("🏠 منوی اصلی:", reply_markup=main_menu_keyboard())

    elif data.startswith("confirm_") or data.startswith("reject_"):
        if query.from_user.id != ADMIN_ID:
            return

        action, order_id_str = data.split("_", 1)
        order_id = int(order_id_str)
        order = await get_order(order_id)

        if not order:
            await append_to_admin_message(query, "\n\n⚠️ این سفارش پیدا نشد.")
            return

        new_status = "confirmed" if action == "confirm" else "rejected"
        changed = await finalize_order(order_id, new_status, order.get("duration_days"))
        if not changed:
            status_fa = {"confirmed": "تایید", "rejected": "رد"}.get(order["status"], order["status"])
            await append_to_admin_message(query, f"\n\n⚠️ این سفارش قبلاً {status_fa} شده است.")
            return

        if action == "confirm":
            user_text = "✅ پرداخت شما تایید شد! سرویس شما فعال گردید و در بخش «📦 سرویس‌های من» قابل مشاهده است."
            suffix = "\n\n✅ <b>تایید شد</b>"
        else:
            user_text = "❌ رسید ارسالی تایید نشد. لطفاً با پشتیبانی در تماس باشید یا رسید صحیح را مجدداً ارسال کنید."
            suffix = "\n\n❌ <b>رد شد</b>"

        try:
            await context.bot.send_message(chat_id=order["user_id"], text=user_text)
        except TelegramError:
            logger.exception("Could not notify user %s about order %s", order["user_id"], order_id)
            suffix += "\n⚠️ پیام به کاربر ارسال نشد (احتمالاً ربات را بلاک کرده)."

        await append_to_admin_message(query, suffix)

async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user

    # رسید می‌تواند عکس معمولی، عکس ارسال‌شده «به‌صورت فایل» یا PDF باشد
    if message.photo:
        file_id, is_photo = message.photo[-1].file_id, True
    elif message.document:
        file_id, is_photo = message.document.file_id, False
    else:
        return

    logger.info("Receipt received from user %s (photo=%s)", user.id, is_photo)

    plan = context.user_data.get("pending_plan")
    renewal_username = context.user_data.get("renewal_username")

    # بعد از ری‌استارت سرور حافظه‌ی RAM خالی است؛ پلن و نام کاربری را از دیتابیس بازیابی می‌کنیم
    if plan is None or renewal_username is None:
        db_plan_id, db_renewal = await get_user_state(user.id)
        if plan is None and db_plan_id:
            _, _, plan = find_plan(db_plan_id)
        if renewal_username is None:
            renewal_username = db_renewal

    # تمام متن‌های وارد‌شده توسط کاربر escape می‌شوند تا پارس HTML خطا ندهد
    safe_name = html.escape(user.full_name or "---")
    safe_username = html.escape(user.username) if user.username else "---"
    renewal_line = (
        f"🔄 نام کاربری سرور جهت تمدید: <code>{html.escape(renewal_username)}</code>\n\n"
        if renewal_username else ""
    )
    user_block = (
        f"👤 کاربر: {safe_name}\n"
        f"🆔 آیدی عددی: <code>{user.id}</code>\n"
        f"یوزرنیم: @{safe_username}\n\n"
    )

    order_id = None
    db_failed = False
    if plan:
        price_text = format_toman(plan["toman"])
        try:
            _, plan_sub_key, _ = find_plan(plan["id"])
            order_id = await create_order(
                user.id, plan["label"], price_text, plan["toman"],
                DURATION_DAYS.get(plan_sub_key, 30), renewal_username, file_id, is_photo,
            )
        except Exception:
            logger.exception("create_order failed for user %s", user.id)
            db_failed = True

    admin_keyboard = None
    if plan and order_id is not None:
        caption = (
            f"🧾 <b>رسید پرداخت جدید (سفارش #{order_id})</b>\n\n"
            f"{user_block}"
            f"{renewal_line}"
            f"📦 پلن انتخابی: <b>{html.escape(plan['label'])}</b>\n"
            f"💰 مبلغ: <b>{price_text}</b>\n"
            f"💱 معادل ریالی: <b>{format_rial(plan['toman'])}</b>"
        )
        admin_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تایید", callback_data=f"confirm_{order_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{order_id}"),
            ]
        ])
    elif plan and db_failed:
        # دیتابیس خطا داد؛ رسید را از دست نمی‌دهیم و بدون دکمه‌ی تایید برای ادمین می‌فرستیم
        caption = (
            "🧾 <b>رسید پرداخت (خطای دیتابیس)</b>\n\n"
            f"{user_block}"
            f"{renewal_line}"
            f"📦 پلن انتخابی: <b>{html.escape(plan['label'])}</b>\n"
            f"💰 مبلغ: <b>{price_text}</b>\n\n"
            "⚠️ ثبت سفارش در دیتابیس انجام نشد، لطفاً دستی پیگیری کنید."
        )
    else:
        caption = (
            "🧾 <b>رسید پرداخت (بدون پلن انتخاب‌شده)</b>\n\n"
            f"{user_block}"
            f"{renewal_line}"
            "⚠️ پلن انتخابی این کاربر پیدا نشد. لطفاً مستقیم با کاربر هماهنگ کنید."
        )

    try:
        if is_photo:
            await context.bot.send_photo(
                chat_id=ADMIN_ID, photo=file_id, caption=caption,
                parse_mode="HTML", reply_markup=admin_keyboard,
            )
        else:
            await context.bot.send_document(
                chat_id=ADMIN_ID, document=file_id, caption=caption,
                parse_mode="HTML", reply_markup=admin_keyboard,
            )
    except TelegramError:
        logger.exception("Failed to forward receipt from user %s to admin", user.id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 ارتباط با پشتیبانی", url=f"https://t.me/{ADMIN_USERNAME}")],
        ])
        await message.reply_text(
            "⚠️ ارسال رسید به ادمین با مشکل مواجه شد. لطفاً دوباره تلاش کنید یا رسید را به پشتیبانی بفرستید.",
            reply_markup=keyboard,
        )
        return

    await message.reply_text(
        "✅ رسید شما با موفقیت دریافت شد و برای ادمین ارسال گردید.\n"
        "به محض تایید، به شما اطلاع داده خواهد شد. لطفاً کمی شکیبا باشید 🙏"
    )

    context.user_data.pop("pending_plan", None)
    context.user_data.pop("renewal_username", None)
    await delete_user_state(user.id)

    if order_id is not None:
        # یادآوری به ادمین اگر تا ۳۰ دقیقه‌ی دیگر رسید بررسی نشد
        context.application.create_task(delayed_pending_reminder(context.bot))

# =====================================================================
# ثبت کاربر و عضویت اجباری در کانال
# =====================================================================
async def register_user(user, context: ContextTypes.DEFAULT_TYPE):
    """کاربر را (یک بار در هر اجرای برنامه) در جدول users ثبت/به‌روز می‌کند؛ برای پیام همگانی لازم است."""
    seen = context.bot_data.setdefault("seen_users", set())
    if user.id in seen:
        return
    try:
        await asyncio.to_thread(
            _db_execute,
            "INSERT INTO users (user_id, full_name, username, first_seen, blocked) "
            "VALUES (%s, %s, %s, %s, FALSE) "
            "ON CONFLICT (user_id) DO UPDATE SET full_name = EXCLUDED.full_name, "
            "username = EXCLUDED.username, blocked = FALSE",
            (user.id, user.full_name, user.username, _now()),
        )
        seen.add(user.id)
    except Exception:
        logger.exception("register_user failed for user %s", user.id)

async def is_channel_member(context: ContextTypes.DEFAULT_TYPE, user_id: int, use_cache: bool = True) -> bool:
    cache = context.bot_data.setdefault("member_cache", {})
    if use_cache and cache.get(user_id, 0) > time.time():
        return True
    try:
        member = await context.bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
    except TelegramError as exc:
        # اگر ربات در کانال ادمین نباشد نمی‌تواند عضویت را بررسی کند؛ برای اینکه مشتری‌ها قفل نشوند اجازه می‌دهیم.
        logger.warning("Channel membership check failed: %s", exc)
        if not context.bot_data.get("join_check_warned"):
            context.bot_data["join_check_warned"] = True
            try:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"⚠️ بررسی عضویت در @{CHANNEL_USERNAME} ممکن نیست ({exc}).\n"
                    "ربات را در کانال «ادمین» کنید. تا آن موقع عضویت اجباری اعمال نمی‌شود.",
                )
            except TelegramError:
                pass
        return True
    ok = member.status in ("member", "administrator", "creator") or (
        member.status == "restricted" and getattr(member, "is_member", False)
    )
    if ok:
        cache[user_id] = time.time() + 600  # ده دقیقه نتیجه را نگه می‌داریم
    return ok

def join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")],
    ])

async def membership_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if user is None or user.is_bot or chat is None or chat.type != "private":
        return

    await register_user(user, context)

    if user.id == ADMIN_ID:
        return
    query = update.callback_query
    if query and query.data == "check_join":
        return
    if await is_channel_member(context, user.id):
        return

    text = (
        "🔒 برای استفاده از ربات ابتدا باید در کانال ما عضو شوید:\n"
        f"📢 @{CHANNEL_USERNAME}\n\n"
        "بعد از عضویت روی «✅ عضو شدم» بزنید."
    )
    if query:
        await query.answer("ابتدا باید در کانال عضو شوید.", show_alert=True)
        await context.bot.send_message(chat.id, text, reply_markup=join_keyboard())
    elif update.message:
        await update.message.reply_text(text, reply_markup=join_keyboard())
    raise ApplicationHandlerStop

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if await is_channel_member(context, query.from_user.id, use_cache=False):
        await query.answer("✅ عضویت شما تایید شد")
        try:
            await query.edit_message_text("✅ عضویت شما تایید شد! به ربات حباب خوش آمدید 😉")
        except TelegramError:
            pass
        chat_id = query.message.chat_id
        await context.bot.send_message(
            chat_id,
            "جهت خرید یا تمدید سرور OpenConnect در خدمتیم.",
            reply_markup=PERSISTENT_KEYBOARD,
        )
        await context.bot.send_message(
            chat_id,
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer("❌ هنوز عضو کانال نشده‌اید.", show_alert=True)

# =====================================================================
# ابزارهای ادمین
# =====================================================================
async def append_to_admin_message(query, suffix: str):
    """متنی را به انتهای پیام ادمین (رسید عکس/فایل یا پیام متنی) اضافه می‌کند و دکمه‌ها را برمی‌دارد."""
    msg = query.message
    if msg.photo or msg.document:
        await query.edit_message_caption(caption=(msg.caption_html or "") + suffix, parse_mode="HTML")
    else:
        await query.edit_message_text(text=(msg.text_html or "") + suffix, parse_mode="HTML")

def build_pending_caption(order_id, user_id, plan_label, price, created_at, renewal_username) -> str:
    renewal_line = (
        f"🔄 نام کاربری سرور جهت تمدید: <code>{html.escape(renewal_username)}</code>\n"
        if renewal_username else ""
    )
    return (
        f"🧾 <b>رسید در انتظار بررسی (سفارش #{order_id})</b>\n\n"
        f"🆔 آیدی کاربر: <code>{user_id}</code>\n"
        f"{renewal_line}"
        f"📦 پلن: <b>{html.escape(plan_label)}</b>\n"
        f"💰 مبلغ: <b>{html.escape(price)}</b>\n"
        f"🗓 ثبت: {html.escape(created_at or '---')}"
    )

def order_action_keyboard(order_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"confirm_{order_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{order_id}"),
        ]
    ])

async def admin_help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 دستورهای ادمین\n\n"
        "/pending — رسیدهای بررسی‌نشده (با دکمه‌ی تایید/رد)\n"
        "/stats — آمار فروش امروز، این ماه و کل\n"
        "/user <آیدی عددی یا @یوزرنیم> — اطلاعات و سفارش‌های یک کاربر\n"
        "/broadcast <متن> — پیام همگانی (یا روی یک پیام ریپلای کنید و /broadcast بزنید)\n"
        "/prices — لیست پلن‌ها با آیدی و قیمت فعلی\n"
        "/setprice <آیدی پلن> <قیمت> — تغییر قیمت. مثال: /setprice s_m1_40 450\n"
        "/setcard <شماره کارت ۱۶ رقمی> — تغییر شماره کارت\n"
        "/setholder <نام> — تغییر نام صاحب کارت"
    )

async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await asyncio.to_thread(
        _db_execute,
        "SELECT id, user_id, plan_label, price, created_at, renewal_username, receipt_file_id, receipt_is_photo "
        "FROM orders WHERE status = 'pending' ORDER BY id LIMIT 20",
        (), "all",
    )
    if not rows:
        await update.message.reply_text("✅ هیچ رسید بررسی‌نشده‌ای وجود ندارد.")
        return
    await update.message.reply_text(
        f"🧾 {to_persian_digits(str(len(rows)))} رسید در انتظار بررسی (حداکثر ۲۰ مورد نمایش داده می‌شود):"
    )
    for oid, uid, label, price, created_at, renewal, file_id, is_photo in rows:
        caption = build_pending_caption(oid, uid, label, price, created_at, renewal)
        kb = order_action_keyboard(oid)
        try:
            if file_id and is_photo:
                await context.bot.send_photo(ADMIN_ID, file_id, caption=caption, parse_mode="HTML", reply_markup=kb)
            elif file_id:
                await context.bot.send_document(ADMIN_ID, file_id, caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                await context.bot.send_message(
                    ADMIN_ID,
                    caption + "\n\n⚠️ فایل رسید برای این سفارش ذخیره نشده (سفارش قدیمی)؛ رسید را در چت بالاتر پیدا کنید.",
                    parse_mode="HTML", reply_markup=kb,
                )
        except TelegramError:
            logger.exception("pending_cmd: could not send order %s", oid)
        await asyncio.sleep(0.05)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = now_dt()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    _, _, jalali_day = gregorian_to_jalali(now.year, now.month, now.day)
    month_start = day_start - timedelta(days=jalali_day - 1)

    sales_q = (
        "SELECT COUNT(*), COALESCE(SUM(amount_toman), 0) FROM orders "
        "WHERE status = 'confirmed' AND confirmed_at >= %s"
    )
    today = await asyncio.to_thread(_db_execute, sales_q, (day_start,), "one")
    month = await asyncio.to_thread(_db_execute, sales_q, (month_start,), "one")
    total = await asyncio.to_thread(
        _db_execute,
        "SELECT COUNT(*), COALESCE(SUM(amount_toman), 0) FROM orders WHERE status = 'confirmed'",
        (), "one",
    )
    pending = await asyncio.to_thread(
        _db_execute, "SELECT COUNT(*) FROM orders WHERE status = 'pending'", (), "one"
    )
    users = await asyncio.to_thread(
        _db_execute, "SELECT COUNT(*), COUNT(*) FILTER (WHERE blocked) FROM users", (), "one"
    )

    def fmt(row):
        return f"{to_persian_digits(str(row[0]))} سفارش — {format_toman(int(row[1]))}"

    await update.message.reply_text(
        "📊 آمار فروش\n\n"
        f"📅 امروز: {fmt(today)}\n"
        f"🗓 این ماه (از اول ماه شمسی): {fmt(month)}\n"
        f"💰 کل: {fmt(total)}\n\n"
        f"⏳ رسید در انتظار بررسی: {to_persian_digits(str(pending[0]))}\n"
        f"👥 کاربران ربات: {to_persian_digits(str(users[0]))} "
        f"({to_persian_digits(str(users[1]))} نفر ربات را بلاک کرده‌اند)"
    )

async def user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استفاده: /user <آیدی عددی یا @یوزرنیم>")
        return
    arg = context.args[0].strip().lstrip("@").translate(PERSIAN_TO_EN)
    if arg.isdigit():
        uid = int(arg)
    else:
        row = await asyncio.to_thread(
            _db_execute,
            "SELECT user_id FROM users WHERE LOWER(username) = LOWER(%s) LIMIT 1",
            (arg,), "one",
        )
        if not row:
            await update.message.reply_text(
                "کاربری با این یوزرنیم پیدا نشد (فقط کاربرانی که با ربات تعامل داشته‌اند ذخیره شده‌اند)."
            )
            return
        uid = row[0]

    info = await asyncio.to_thread(
        _db_execute,
        "SELECT full_name, username, first_seen, blocked FROM users WHERE user_id = %s",
        (uid,), "one",
    )
    orders = await asyncio.to_thread(
        _db_execute,
        "SELECT id, plan_label, price, status, created_at, expires_at, renewal_username "
        "FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 15",
        (uid,), "all",
    )
    summary = await asyncio.to_thread(
        _db_execute,
        "SELECT COUNT(*) FILTER (WHERE status = 'confirmed'), "
        "COALESCE(SUM(amount_toman) FILTER (WHERE status = 'confirmed'), 0) "
        "FROM orders WHERE user_id = %s",
        (uid,), "one",
    )
    if not info and not orders:
        await update.message.reply_text("اطلاعاتی برای این آیدی پیدا نشد.")
        return

    lines = []
    if info:
        full_name, username, first_seen, blocked = info
        lines.append(f"👤 <b>{html.escape(full_name or '---')}</b>")
        lines.append(f"🆔 <code>{uid}</code>")
        lines.append(f"یوزرنیم: @{html.escape(username) if username else '---'}")
        lines.append(f"🗓 اولین تعامل: {html.escape(first_seen or '---')}")
        if blocked:
            lines.append("🚫 این کاربر ربات را بلاک کرده است.")
    else:
        lines.append(f"🆔 <code>{uid}</code>")
    lines.append("")
    lines.append(
        f"🧾 سفارش‌ها (تایید شده: {to_persian_digits(str(summary[0]))} — "
        f"جمع: {format_toman(int(summary[1]))})"
    )
    status_icon = {"pending": "⏳", "confirmed": "✅", "rejected": "❌"}
    for oid, label, price, status, created_at, expires_at, renewal in orders:
        line = f"{status_icon.get(status, '•')} #{oid} — {html.escape(label)} — {html.escape(price)} — {html.escape(created_at or '')}"
        if status == "confirmed" and expires_at:
            line += f" (پایان: {expires_at.strftime('%Y-%m-%d')})"
        if renewal:
            line += f" 🔄 <code>{html.escape(renewal)}</code>"
        lines.append(line)
    if not orders:
        lines.append("سفارشی ثبت نشده است.")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

# ---------- تغییر قیمت و اطلاعات کارت از داخل تلگرام ----------
async def prices_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["💰 پلن‌ها (آیدی — عنوان — قیمت فعلی)\n"]
    for category in PLANS.values():
        for sub in category["subcats"].values():
            for item in sub["items"]:
                lines.append(
                    f"<code>{item['id']}</code> — {html.escape(item['label'])} — {format_toman(item['toman'])}"
                )
    lines.append("\nتغییر قیمت: /setprice <آیدی پلن> <قیمت>")
    lines.append(f"💳 کارت فعلی: <code>{html.escape(CARD_NUMBER)}</code> — {html.escape(CARD_HOLDER)}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def setprice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("استفاده: /setprice <آیدی پلن> <قیمت>\nمثال: /setprice s_m1_40 450\nآیدی‌ها: /prices")
        return
    plan_id = context.args[0]
    amount = parse_int(context.args[1])
    _, _, item = find_plan(plan_id)
    if not item:
        await update.message.reply_text("❌ آیدی پلن پیدا نشد. لیست آیدی‌ها: /prices")
        return
    if amount <= 0:
        await update.message.reply_text("❌ قیمت باید یک عدد مثبت باشد.")
        return
    old = item["toman"]
    item["toman"] = amount
    await set_setting(f"price_{plan_id}", str(amount))
    await update.message.reply_text(
        f"✅ قیمت «{item['label']}» از {format_toman(old)} به {format_toman(amount)} تغییر کرد."
    )

async def setcard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CARD_NUMBER
    digits = re.sub(r"\D", "", " ".join(context.args).translate(PERSIAN_TO_EN))
    if len(digits) != 16:
        await update.message.reply_text("استفاده: /setcard <شماره کارت ۱۶ رقمی>\nمثال: /setcard 6037 9911 2233 4455")
        return
    CARD_NUMBER = " ".join(digits[i:i + 4] for i in range(0, 16, 4))
    await set_setting("card_number", CARD_NUMBER)
    await update.message.reply_text(f"✅ شماره کارت تغییر کرد:\n{CARD_NUMBER}")

async def setholder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CARD_HOLDER
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("استفاده: /setholder <نام صاحب کارت>")
        return
    CARD_HOLDER = name
    await set_setting("card_holder", name)
    await update.message.reply_text(f"✅ نام صاحب کارت تغییر کرد: {name}")

# =====================================================================
# پیام همگانی
# =====================================================================
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    reply = msg.reply_to_message
    parts = re.split(r"\s+", msg.text or "", maxsplit=1)
    text = parts[1].strip() if len(parts) > 1 else ""

    if reply:
        payload = {"mode": "copy", "chat_id": msg.chat_id, "message_id": reply.message_id}
    elif text:
        payload = {"mode": "text", "text": text}
    else:
        await update.message.reply_text(
            "استفاده:\n/broadcast <متن پیام>\n\n"
            "یا روی هر پیامی (متن، عکس، ...) ریپلای کنید و فقط /broadcast بفرستید."
        )
        return

    row = await asyncio.to_thread(
        _db_execute,
        "SELECT COUNT(*) FROM users WHERE blocked = FALSE AND user_id <> %s",
        (ADMIN_ID,), "one",
    )
    count = row[0] if row else 0
    context.bot_data["broadcast_payload"] = payload

    # پیش‌نمایش همان پیامی که برای کاربران می‌رود
    if payload["mode"] == "copy":
        await context.bot.copy_message(ADMIN_ID, payload["chat_id"], payload["message_id"])
    else:
        await context.bot.send_message(ADMIN_ID, payload["text"])

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ارسال", callback_data="bc_send"),
        InlineKeyboardButton("❌ لغو", callback_data="bc_cancel"),
    ]])
    await update.message.reply_text(
        f"📣 پیام بالا برای {to_persian_digits(str(count))} کاربر ارسال می‌شود. تایید می‌کنید؟",
        reply_markup=keyboard,
    )

async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("این دکمه فقط برای ادمین است.", show_alert=True)
        return
    await query.answer()

    if query.data == "bc_cancel":
        context.bot_data.pop("broadcast_payload", None)
        await query.edit_message_text("❌ ارسال پیام همگانی لغو شد.")
        return

    payload = context.bot_data.pop("broadcast_payload", None)
    if not payload:
        await query.edit_message_text("⚠️ پیامی برای ارسال پیدا نشد (احتمالاً قبلاً ارسال شده یا ربات ری‌استارت شده). دوباره /broadcast بزنید.")
        return
    await query.edit_message_text("⏳ ارسال شروع شد؛ بعد از پایان گزارش می‌فرستم.")
    context.application.create_task(
        run_broadcast(context.bot, payload, context.bot_data.setdefault("seen_users", set()))
    )

def _retry_seconds(exc: RetryAfter) -> float:
    delay = exc.retry_after
    return delay.total_seconds() if hasattr(delay, "total_seconds") else float(delay)

async def run_broadcast(bot, payload: dict, seen_users: set):
    try:
        rows = await asyncio.to_thread(
            _db_execute,
            "SELECT user_id FROM users WHERE blocked = FALSE AND user_id <> %s",
            (ADMIN_ID,), "all",
        )
        ids = [r[0] for r in rows or []]
        sent = failed = 0
        blocked = []
        for uid in ids:
            for _attempt in range(2):
                try:
                    if payload["mode"] == "copy":
                        await bot.copy_message(uid, payload["chat_id"], payload["message_id"])
                    else:
                        await bot.send_message(uid, payload["text"])
                    sent += 1
                    break
                except RetryAfter as exc:
                    await asyncio.sleep(_retry_seconds(exc) + 1)
                except Forbidden:
                    blocked.append(uid)
                    seen_users.discard(uid)
                    break
                except TelegramError:
                    failed += 1
                    break
            else:
                failed += 1
            await asyncio.sleep(0.05)  # حدود ۲۰ پیام در ثانیه، زیر محدودیت تلگرام

        if blocked:
            await asyncio.to_thread(
                _db_execute, "UPDATE users SET blocked = TRUE WHERE user_id = ANY(%s)", (blocked,)
            )
        await bot.send_message(
            ADMIN_ID,
            "📣 گزارش پیام همگانی\n\n"
            f"✅ ارسال‌شده: {to_persian_digits(str(sent))}\n"
            f"🚫 بلاک‌کرده‌ها: {to_persian_digits(str(len(blocked)))}\n"
            f"⚠️ ناموفق: {to_persian_digits(str(failed))}",
        )
    except Exception:
        logger.exception("run_broadcast failed")
        try:
            await bot.send_message(ADMIN_ID, "⚠️ ارسال پیام همگانی با خطا مواجه شد؛ لاگ سرور را ببینید.")
        except TelegramError:
            pass

# =====================================================================
# یادآوری‌ها (تمدید برای کاربر، رسید بی‌جواب برای ادمین)
# =====================================================================
async def send_expiry_reminders(bot):
    now = now_dt()
    rows = await asyncio.to_thread(
        _db_execute,
        "SELECT o.id, o.user_id, o.plan_label, o.expires_at FROM orders o "
        "WHERE o.status = 'confirmed' AND o.expiry_reminded = FALSE "
        "AND o.expires_at IS NOT NULL AND o.expires_at > %s AND o.expires_at <= %s "
        "AND NOT EXISTS (SELECT 1 FROM orders n WHERE n.user_id = o.user_id "
        "AND n.status = 'confirmed' AND n.expires_at > o.expires_at)",
        (now, now + timedelta(days=REMINDER_DAYS_BEFORE)), "all",
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تمدید سرور", callback_data="renew")]])
    for oid, uid, label, expires_at in rows or []:
        days_left = max(1, math.ceil((expires_at - now).total_seconds() / 86400))
        text = (
            "⏰ یادآوری تمدید\n\n"
            f"سرویس «{label}» شما حدود {to_persian_digits(str(days_left))} روز دیگر به پایان می‌رسد.\n"
            "برای اینکه اتصال شما قطع نشود، همین حالا تمدید کنید 👇"
        )
        mark_done = False
        try:
            await bot.send_message(uid, text, reply_markup=keyboard)
            mark_done = True
        except Forbidden:
            mark_done = True
            await asyncio.to_thread(_db_execute, "UPDATE users SET blocked = TRUE WHERE user_id = %s", (uid,))
        except BadRequest:
            mark_done = True
        except TelegramError:
            logger.exception("expiry reminder failed for order %s (will retry)", oid)
        if mark_done:
            await asyncio.to_thread(
                _db_execute, "UPDATE orders SET expiry_reminded = TRUE WHERE id = %s", (oid,)
            )
        await asyncio.sleep(0.1)

async def remind_admin_pending(bot):
    cutoff = now_dt() - timedelta(minutes=PENDING_REMIND_MINUTES)
    rows = await asyncio.to_thread(
        _db_execute,
        "SELECT id, plan_label, price, created_at FROM orders "
        "WHERE status = 'pending' AND admin_reminded = FALSE "
        "AND created_ts IS NOT NULL AND created_ts <= %s ORDER BY id",
        (cutoff,), "all",
    )
    if not rows:
        return
    lines = [f"⏰ <b>رسیدهای بررسی‌نشده (بیش از {to_persian_digits(str(PENDING_REMIND_MINUTES))} دقیقه)</b>\n"]
    for oid, label, price, created_at in rows:
        lines.append(f"• سفارش #{oid} — {html.escape(label)} — {html.escape(price)} — {html.escape(created_at or '')}")
    lines.append("\nبرای دیدن رسیدها و تایید/رد: /pending")
    await bot.send_message(ADMIN_ID, "\n".join(lines), parse_mode="HTML")
    await asyncio.to_thread(
        _db_execute,
        "UPDATE orders SET admin_reminded = TRUE WHERE id = ANY(%s)",
        ([r[0] for r in rows],),
    )

async def delayed_pending_reminder(bot):
    await asyncio.sleep(PENDING_REMIND_MINUTES * 60 + 5)
    try:
        await remind_admin_pending(bot)
    except Exception:
        logger.exception("delayed pending reminder failed")

async def background_loop(application: Application):
    """هر ساعت: یادآوری تمدید برای کاربرها + جاروی رسیدهای بی‌جواب (برای زمانی که ربات ری‌استارت شده)."""
    await asyncio.sleep(15)
    while True:
        try:
            await send_expiry_reminders(application.bot)
        except Exception:
            logger.exception("expiry reminder job failed")
        try:
            await remind_admin_pending(application.bot)
        except Exception:
            logger.exception("pending reminder job failed")
        await asyncio.sleep(BACKGROUND_INTERVAL)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception while processing update: %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ مشکلی پیش آمد. لطفاً دوباره تلاش کنید یا به پشتیبانی پیام دهید."
            )
        except TelegramError:
            pass

async def post_init(application: Application):
    await application.bot.set_my_commands([
        ("start", "شروع / منوی اصلی"),
        ("cancel", "لغو عملیات جاری و خروج"),
    ])
    try:
        await application.bot.set_my_commands(
            [
                ("start", "شروع / منوی اصلی"),
                ("admin", "راهنمای دستورهای ادمین"),
                ("pending", "رسیدهای در انتظار بررسی"),
                ("stats", "آمار فروش"),
                ("user", "اطلاعات و سفارش‌های یک کاربر"),
                ("broadcast", "ارسال پیام همگانی"),
                ("prices", "لیست پلن‌ها و قیمت‌ها"),
                ("setprice", "تغییر قیمت یک پلن"),
                ("setcard", "تغییر شماره کارت"),
                ("setholder", "تغییر نام صاحب کارت"),
            ],
            scope=BotCommandScopeChat(ADMIN_ID),
        )
    except TelegramError:
        logger.warning("Could not set admin commands menu (has the admin started the bot?)")
    application.bot_data["bg_task"] = asyncio.create_task(background_loop(application))

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        pass

def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Dummy server running on port {port}...")
    server.serve_forever()

def main():
    if not TOKEN:
        raise SystemExit("متغیر محیطی BOT_TOKEN تنظیم نشده است.")
    init_db()
    
    server_thread = threading.Thread(target=start_dummy_server, daemon=True)
    server_thread.start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # دروازه‌ی عضویت اجباری + ثبت کاربر؛ قبل از همه‌ی هندلرها اجرا می‌شود
    app.add_handler(TypeHandler(Update, membership_gate), group=-1)

    # دستورهای ادمین
    admin_only = filters.User(user_id=ADMIN_ID)
    app.add_handler(CommandHandler("admin", admin_help_cmd, filters=admin_only))
    app.add_handler(CommandHandler("pending", pending_cmd, filters=admin_only))
    app.add_handler(CommandHandler("stats", stats_cmd, filters=admin_only))
    app.add_handler(CommandHandler("user", user_cmd, filters=admin_only))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd, filters=admin_only))
    app.add_handler(CommandHandler("prices", prices_cmd, filters=admin_only))
    app.add_handler(CommandHandler("setprice", setprice_cmd, filters=admin_only))
    app.add_handler(CommandHandler("setcard", setcard_cmd, filters=admin_only))
    app.add_handler(CommandHandler("setholder", setholder_cmd, filters=admin_only))

    # این دو باید قبل از button_handler عمومی ثبت شوند
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern=r"^check_join$"))
    app.add_handler(CallbackQueryHandler(broadcast_callback, pattern=r"^bc_(send|cancel)$"))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))

    # دکمه‌های کیبورد ثابت (باید قبل از هندلر عمومی متن ثبت شوند)
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(HOME_BUTTON_TEXT)}$"), home_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BUY_BUTTON_TEXT)}$"), buy_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(RENEW_BUTTON_TEXT)}$"), renew_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(PRICE_LIST_BUTTON_TEXT)}$"), price_list_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(MY_SERVICES_BUTTON_TEXT)}$"), my_services_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(CHECK_BALANCE_BUTTON_TEXT)}$"), check_balance_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(SUPPORT_BUTTON_TEXT)}$"), support_button_handler))

    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.IMAGE | filters.Document.MimeType("application/pdf"),
        receipt_handler,
    ))

    # هندلر عمومی متن، برای دریافت نام کاربری تمدید سرور (کمترین اولویت)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, renewal_username_router))

    app.add_error_handler(error_handler)

    print("ربات آنلاین شد...")
    # drop_pending_updates=False: پیام‌هایی که در زمان خاموشی/خوابِ سرور آمده‌اند از بین نروند
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
