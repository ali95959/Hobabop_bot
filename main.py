import os
import re
import html
import logging
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import (
    Application,
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
TOKEN = "8998126217:AAHmbAmXe3aLyrPYVKnpJTfPBWwhUgE3U10"

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
    prefix = "🔥 " if item.get("recommended") else ""
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

DB_FILE = "orders.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_label TEXT NOT NULL,
            price TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

def create_order(user_id: int, plan_label: str, price: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.execute(
        "INSERT INTO orders (user_id, plan_label, price, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (user_id, plan_label, price, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id

def get_order(order_id: int):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT id, user_id, plan_label, price, status, created_at FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "plan_label": row[2],
        "price": row[3],
        "status": row[4],
        "created_at": row[5],
    }

def set_order_status(order_id: int, status: str):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def get_user_orders(user_id: int, status: str = "confirmed"):
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT plan_label, price, created_at FROM orders WHERE user_id = ? AND status = ? ORDER BY id DESC",
        (user_id, status),
    ).fetchall()
    conn.close()
    return rows

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
        [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")],
        [InlineKeyboardButton("📊 چک کردن مانده سرویس", callback_data="check_balance")],
        [InlineKeyboardButton("🎧 پشتیبانی", callback_data="support")],
    ])

BUY_BUTTON_TEXT = "🛒 خرید اشتراک"
RENEW_BUTTON_TEXT = "🔄 تمدید سرور"
MY_SERVICES_BUTTON_TEXT = "📦 سرویس‌های من"
CHECK_BALANCE_BUTTON_TEXT = "📊 چک کردن مانده سرویس"
SUPPORT_BUTTON_TEXT = "🎧 پشتیبانی"
HOME_BUTTON_TEXT = "🏠 منوی اصلی"

# حذف is_persistent جهت جلوگیری از گیر کردن دکمه بازگشت گوشی
# تمام آیتم‌های منوی اصلی در کنار «منوی اصلی» به صورت کیبورد ثابت نمایش داده می‌شوند
PERSISTENT_KEYBOARD = ReplyKeyboardMarkup(
    [
        [BUY_BUTTON_TEXT, RENEW_BUTTON_TEXT],
        [MY_SERVICES_BUTTON_TEXT, CHECK_BALANCE_BUTTON_TEXT],
        [SUPPORT_BUTTON_TEXT, HOME_BUTTON_TEXT],
    ],
    resize_keyboard=True,
)

def plans_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 پلن‌های پیشنهادی (پرفروش‌ترین‌ها)", callback_data="recommended")],
        [InlineKeyboardButton("🌀 تک کاربره", callback_data="cat_single")],
        [InlineKeyboardButton("🌀 دو کاربره", callback_data="cat_double")],
        [InlineKeyboardButton("📋 لیست کلی قیمت‌ها", callback_data="all_prices")],
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

def reset_transient_state(context: ContextTypes.DEFAULT_TYPE):
    """هرگونه حالت موقتِ در انتظار پاسخ (پلن در انتظار پرداخت، در انتظار نام کاربری) را پاک می‌کند."""
    context.user_data.pop("pending_plan", None)
    context.user_data.pop("awaiting_username", None)
    context.user_data.pop("username_attempts", None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_transient_state(context)
    await update.message.reply_text(
        "سلام! به ربات حباب خوش آمدید 😉\nجهت خرید یا تمدید سرور OpenConnect در خدمتیم.",
        reply_markup=PERSISTENT_KEYBOARD,
    )
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=main_menu_keyboard(),
    )

async def home_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_transient_state(context)
    await update.message.reply_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_keyboard(),
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    had_active_flow = (
        context.user_data.get("pending_plan") is not None
        or context.user_data.get("awaiting_username") is True
    )
    reset_transient_state(context)
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
    reset_transient_state(context)
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
    reset_transient_state(context)
    await update.message.reply_text(
        "🛒 **بخش خرید اشتراک**\n\nلطفاً نوع اشتراک مورد نظر خود را انتخاب کنید یا لیست کلی قیمت‌ها را ببینید:",
        parse_mode="Markdown",
        reply_markup=plans_keyboard(),
    )

async def renew_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_renewal_flow(update, context, via_callback=False)

async def my_services_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_transient_state(context)
    orders = get_user_orders(update.effective_user.id, status="confirmed")
    await update.message.reply_text(build_my_services_text(orders), parse_mode="Markdown")

async def check_balance_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_transient_state(context)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 چک کردن مانده", url=f"https://t.me/{BALANCE_BOT_USERNAME}")],
    ])
    await update.message.reply_text(
        "📊 برای بررسی مانده سرویس خود، روی دکمه زیر کلیک کرده و ادامه مراحل را در ربات استعلام انجام دهید:",
        reply_markup=keyboard,
    )

async def support_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_transient_state(context)
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
        buttons.append([InlineKeyboardButton("📋 لیست کلی قیمت‌ها", callback_data="all_prices")])
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
        # دکمه‌ی «خرید سرور» که کاربر را مستقیم به انتخاب تک‌کاربره/دو‌کاربره برمی‌گرداند
        keyboard = [
            [InlineKeyboardButton("🛒 خرید سرور", callback_data="plans")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back")],
        ]
        await query.edit_message_text(
            build_full_price_list_text(),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("buy_"):
        plan_id = data.split("_", 1)[1]
        cat_key, sub_key, plan = find_plan(plan_id)
        if not plan:
            await query.edit_message_text("❌ این پلن پیدا نشد، دوباره تلاش کن.")
            return

        context.user_data["pending_plan"] = plan

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
        orders = get_user_orders(query.from_user.id, status="confirmed")
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
        reset_transient_state(context)
        await query.edit_message_text("🏠 منوی اصلی:", reply_markup=main_menu_keyboard())

    elif data.startswith("confirm_") or data.startswith("reject_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("این دکمه فقط برای ادمین است.", show_alert=True)
            return

        action, order_id_str = data.split("_", 1)
        order_id = int(order_id_str)
        order = get_order(order_id)
        # caption_html: قالب‌بندی اصلی حفظ می‌شود و نام/یوزرنیم کاربر دوباره پارس نمی‌شود
        old_caption = query.message.caption_html or ""

        if not order:
            await query.edit_message_caption(
                caption=old_caption + "\n\n⚠️ این سفارش پیدا نشد.", parse_mode="HTML"
            )
            return

        if action == "confirm":
            set_order_status(order_id, "confirmed")
            user_text = "✅ پرداخت شما تایید شد! سرویس شما فعال گردید و در بخش «📦 سرویس‌های من» قابل مشاهده است."
            suffix = "\n\n✅ <b>تایید شد</b>"
        else:
            set_order_status(order_id, "rejected")
            user_text = "❌ رسید ارسالی تایید نشد. لطفاً با پشتیبانی در تماس باشید یا رسید صحیح را مجدداً ارسال کنید."
            suffix = "\n\n❌ <b>رد شد</b>"

        try:
            await context.bot.send_message(chat_id=order["user_id"], text=user_text)
        except TelegramError:
            logger.exception("Could not notify user %s about order %s", order["user_id"], order_id)
            suffix += "\n⚠️ پیام به کاربر ارسال نشد (احتمالاً ربات را بلاک کرده)."

        await query.edit_message_caption(caption=old_caption + suffix, parse_mode="HTML")

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

    if plan:
        price_text = format_toman(plan["toman"])
        order_id = create_order(user.id, plan["label"], price_text)
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
    else:
        # پلنی در حافظه نیست (مثلاً ربات ری‌استارت شده). رسید را از دست نمی‌دهیم و برای ادمین می‌فرستیم.
        caption = (
            "🧾 <b>رسید پرداخت (بدون پلن انتخاب‌شده)</b>\n\n"
            f"{user_block}"
            f"{renewal_line}"
            "⚠️ ربات پلن انتخابی این کاربر را ندارد (احتمالاً ری‌استارت شده). لطفاً مستقیم با کاربر هماهنگ کنید."
        )
        admin_keyboard = None

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
    init_db()
    
    server_thread = threading.Thread(target=start_dummy_server, daemon=True)
    server_thread.start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))

    # دکمه‌های کیبورد ثابت (باید قبل از هندلر عمومی متن ثبت شوند)
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(HOME_BUTTON_TEXT)}$"), home_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(BUY_BUTTON_TEXT)}$"), buy_button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{re.escape(RENEW_BUTTON_TEXT)}$"), renew_button_handler))
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
