import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# توکن ربات
TOKEN = "8998126217:AAHmbAmXe3aLyrPYVKnpJTfPBWwhUgE3U10"

# آیدی عددی ادمین
ADMIN_ID = 6922701713

# یوزرنیم پشتیبانی
ADMIN_USERNAME = "Hobabadmin"

# یوزرنیم ربات چک مانده سرویس
BALANCE_BOT_USERNAME = "reportvolume_bot"

# شماره کارت برای پرداخت کارت‌به‌کارت
CARD_NUMBER = "5022-2913-3683-0904"
CARD_HOLDER = "علی باقری فرد"

PLANS = {
    "single": {
        "title": "🌀 تک کاربره",
        "subcats": {
            "m1": {
                "title": "✨ یک ماهه",
                "items": [
                    {"id": "s_m1_20", "label": "یکماه تک کاربر ۲۰ گیگ", "toman": 240},
                    {"id": "s_m1_40", "label": "یکماه تک کاربر ۴۰ گیگ", "toman": 420},
                    {"id": "s_m1_60", "label": "یکماه تک کاربر ۶۰ گیگ", "toman": 550},
                    {"id": "s_m1_100", "label": "یکماه تک کاربر ۱۰۰ گیگ", "toman": 690},
                ],
            },
            "m3": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "s_m3_100", "label": "سه ماه تک کاربر ۱۰۰ گیگ", "toman": 990},
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
                    {"id": "d_m1_40", "label": "یکماه دو کاربر ۴۰ گیگ", "toman": 540},
                    {"id": "d_m1_60", "label": "یکماه دو کاربر ۶۰ گیگ", "toman": 650},
                    {"id": "d_m1_80", "label": "یکماه دو کاربر ۸۰ گیگ", "toman": 750},
                    {"id": "d_m1_100", "label": "یکماه دو کاربر ۱۰۰ گیگ", "toman": 890},
                ],
            },
            "m3": {
                "title": "✨ سه ماهه",
                "items": [
                    {"id": "d_m3_100", "label": "سه ماه دو کاربر ۱۰۰ گیگ", "toman": 1190},
                    {"id": "d_m3_200", "label": "سه ماه دو کاربر ۲۰۰ گیگ", "toman": 1790},
                    {"id": "d_m3_360", "label": "سه ماه دو کاربر ۳۶۰ گیگ", "toman": 2090},
                ],
            },
        },
    },
}

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

def build_full_price_list_text() -> str:
    lines = ["💵 تعرفه‌های اشتراک‌های طرح پرو:", ""]
    for cat_key in ("single", "double"):
        cat = PLANS[cat_key]
        lines.append(f"{cat['title']}:")
        lines.append("")
        for sub_key in ("m1", "m3"):
            sub = cat["subcats"][sub_key]
            lines.append(f"{sub['title']}:")
            lines.append("")
            for item in sub["items"]:
                lines.append(f"{item['label']} {format_toman(item['toman'])}")
            lines.append("")
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

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 خرید اشتراک", callback_data="plans")],
        [InlineKeyboardButton("📦 سرویس‌های من", callback_data="my_services")],
        [InlineKeyboardButton("📊 چک کردن مانده سرویس", callback_data="check_balance")],
        [InlineKeyboardButton("🎧 پشتیبانی", callback_data="support")],
    ])

HOME_BUTTON_TEXT = "🏠 منوی اصلی"

PERSISTENT_KEYBOARD = ReplyKeyboardMarkup(
    [[HOME_BUTTON_TEXT]],
    resize_keyboard=True,
    is_persistent=True,
)

def plans_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌀 تک کاربره", callback_data="cat_single")],
        [InlineKeyboardButton("🌀 دو کاربره", callback_data="cat_double")],
        [InlineKeyboardButton("📋 لیست کلی قیمت‌ها", callback_data="all_prices")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")],
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
        text = f"{item['label']} — {format_toman(item['toman'])}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"buy_{item['id']}")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"cat_{cat_key}")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_plan", None)
    await update.message.reply_text(
        "سلام، جهت خرید یا تمدید سرور open connect در خدمتم😉",
        reply_markup=PERSISTENT_KEYBOARD,
    )
    await update.message.reply_text(
        "یکی از گزینه‌های زیر رو انتخاب کن:",
        reply_markup=main_menu_keyboard(),
    )

async def home_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_plan", None)
    await update.message.reply_text(
        "منوی اصلی:",
        reply_markup=main_menu_keyboard(),
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "plans":
        await query.edit_message_text(
            "💵 تعرفه اشتراک‌های طرح پرو:\n\nنوع اشتراک رو انتخاب کن، یا لیست کلی قیمت‌ها رو ببین:",
            reply_markup=plans_keyboard(),
        )

    elif data.startswith("cat_"):
        cat_key = data.split("_", 1)[1]
        await query.edit_message_text(
            f"{PLANS[cat_key]['title']}\n\nمدت اشتراک رو انتخاب کن:",
            reply_markup=category_keyboard(cat_key),
        )

    elif data.startswith("sub_"):
        _, cat_key, sub_key = data.split("_", 2)
        cat = PLANS[cat_key]
        sub = cat["subcats"][sub_key]
        await query.edit_message_text(
            f"{cat['title']} — {sub['title']}\n\nپلن مورد نظرت رو انتخاب کن:",
            reply_markup=subcat_keyboard(cat_key, sub_key),
        )

    elif data == "all_prices":
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="plans")]]
        await query.edit_message_text(
            build_full_price_list_text(),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("buy_"):
        plan_id = data.split("_", 1)[1]
        cat_key, sub_key, plan = find_plan(plan_id)
        if not plan:
            await query.edit_message_text("❌ این پلن پیدا نشد، دوباره تلاش کن.")
            return

        context.user_data["pending_plan"] = plan

        text = (
            f"✅ پلن انتخابی: {plan['label']}\n"
            f"💰 مبلغ: {format_toman(plan['toman'])}\n"
            f"💱 معادل این میشه: {format_rial(plan['toman'])}\n\n"
            f"لطفاً مبلغ رو به شماره کارت زیر واریز کن:\n\n"
            f"💳 {CARD_NUMBER}\n"
            f"👤 به نام: {CARD_HOLDER}\n\n"
            f"بعد از واریز، عکس رسید پرداخت رو همینجا برام بفرست تا سریع بررسی و تایید کنم."
        )
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data=f"sub_{cat_key}_{sub_key}")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "my_services":
        orders = get_user_orders(query.from_user.id, status="confirmed")
        if not orders:
            text = "📦 هنوز سرویس فعالی برای این حساب ثبت نشده."
        else:
            lines = ["📦 سرویس‌های فعال شما:\n"]
            for plan_label, price, created_at in orders:
                lines.append(f"✅ {plan_label} — {price}\n🗓 تاریخ خرید: {created_at}\n")
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "support":
        keyboard = [
            [InlineKeyboardButton("💬 ارتباط با پشتیبانی", url=f"https://t.me/{ADMIN_USERNAME}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")],
        ]
        await query.edit_message_text(
            "🎧 برای پشتیبانی، روی دکمه‌ی زیر بزن تا مستقیم چت باز بشه:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "check_balance":
        keyboard = [
            [InlineKeyboardButton("📊 چک کردن مانده", url=f"https://t.me/{BALANCE_BOT_USERNAME}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="back")],
        ]
        await query.edit_message_text(
            "📊 برای چک کردن مانده‌ی سرویست روی دکمه‌ی زیر بزن و ادامه‌ی کار رو با همون ربات انجام بده:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data == "back":
        await query.edit_message_text("منوی اصلی:", reply_markup=main_menu_keyboard())

    elif data.startswith("confirm_") or data.startswith("reject_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("این دکمه فقط برای ادمینه.", show_alert=True)
            return

        action, order_id_str = data.split("_", 1)
        order_id = int(order_id_str)
        order = get_order(order_id)

        if not order:
            await query.edit_message_caption(caption=(query.message.caption or "") + "\n\n⚠️ این سفارش پیدا نشد.")
            return

        if action == "confirm":
            set_order_status(order_id, "confirmed")
            await context.bot.send_message(
                chat_id=order["user_id"],
                text="✅ پرداخت شما تایید شد! سرویست تو بخش «📦 سرویس‌های من» قابل مشاهده‌ست.",
            )
            await query.edit_message_caption(caption=query.message.caption + "\n\n✅ تایید شد")
        else:
            set_order_status(order_id, "rejected")
            await context.bot.send_message(
                chat_id=order["user_id"],
                text="❌ رسید ارسالی تایید نشد. لطفاً با پشتیبانی در تماس باش یا رسید صحیح رو دوباره ارسال کن.",
            )
            await query.edit_message_caption(caption=query.message.caption + "\n\n❌ رد شد")

async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plan = context.user_data.get("pending_plan")

    if not plan:
        await update.message.reply_text(
            "برای ارسال رسید، اول باید یه پلن از بخش «🛒 خرید اشتراک» انتخاب کنی."
        )
        return

    user = update.effective_user
    photo_file_id = update.message.photo[-1].file_id

    price_text = format_toman(plan["toman"])
    order_id = create_order(user.id, plan["label"], price_text)

    caption = (
        f"🧾 رسید پرداخت جدید (سفارش #{order_id})\n\n"
        f"👤 کاربر: {user.full_name}\n"
        f"🆔 آیدی عددی: {user.id}\n"
        f"یوزرنیم: @{user.username if user.username else '---'}\n\n"
        f"📦 پلن انتخابی: {plan['label']}\n"
        f"💰 مبلغ: {price_text}\n"
        f"💱 معادل ریالی: {format_rial(plan['toman'])}"
    )

    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"confirm_{order_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{order_id}"),
        ]
    ])

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_file_id,
        caption=caption,
        reply_markup=admin_keyboard,
    )

    await update.message.reply_text(
        "✅ رسید شما دریافت شد و برای بررسی ارسال شد.\n"
        "به محض تایید، بهت اطلاع داده میشه. لطفاً کمی صبر کن 🙏"
    )

    context.user_data.pop("pending_plan", None)

async def post_init(application: Application):
    await application.bot.set_my_commands([("start", "شروع / منوی اصلی")])

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def main():
    init_db()
    
    threading.Thread(target=start_dummy_server, daemon=True).start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{HOME_BUTTON_TEXT}$"), home_button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, receipt_handler))

    print("ربات آنلاین شد...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
