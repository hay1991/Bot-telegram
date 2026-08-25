# -*- coding: utf-8 -*-
"""
بوت تلغرام لبيع أكواد الكورسات - Deeb Learning
=================================================
طريقتين للدفع:

1) شام كاش — تأكيد يدوي:
   المستخدم يبعت صورة إثبات التحويل -> الأدمن يوافق يدوياً -> البوت يبعت الكود

2) USDT (شبكة TRC20) — تأكيد آلي بالكامل:
   المستخدم يحوّل لعنوان المحفظة -> يبعت رقم العملية (TxID) -> البوت يتحقق
   تلقائياً عبر API عام ومجاني من TronScan (بدون أي طرف ثالث غير رسمي) ->
   لو كل شي مطابق (العنوان، المبلغ، العملية غير مستخدمة قبل) يبعت الكود فوراً
"""

import os
import logging

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import db

# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# آي دي حسابات الأدمن (يفصل بينها بفاصلة إذا في أكثر من أدمن), مثال: "111111,222222"
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

# عنوان محفظتك على شبكة TRC20 (اللي رح يحوّل عليه الزباين USDT)
TRON_WALLET_ADDRESS = os.environ.get("TRON_WALLET_ADDRESS", "")
# مفتاح TronScan اختياري (بيرفع حد عدد الطلبات المسموحة بالدقيقة، مو إلزامي للتشغيل الأساسي)
TRONSCAN_API_KEY = os.environ.get("TRONSCAN_API_KEY", "")
TRONSCAN_URL = "https://apilist.tronscanapi.com/api/transaction-info"

# نسبة تسامح بسيطة بالمبلغ (عشان فروقات تقريب عشرية بسيطة، مو لتغطية نقص حقيقي بالمبلغ)
AMOUNT_TOLERANCE = 0.01

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# أدوات مساعدة - عامة
# (قاعدة البيانات نفسها صارت بملف db.py المشترك مع لوحة التحكم عبر الويب)
# ---------------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


get_active_courses = db.get_active_courses
get_course = db.get_course
available_codes_count = db.available_codes_count
pull_unused_code = db.pull_unused_code
mark_code_used = db.mark_code_used
create_order = db.create_order
get_order = db.get_order
set_order_status = db.set_order_status
is_tx_used = db.is_tx_used
mark_tx_used = db.mark_tx_used
set_course_price_usdt = db.set_course_price_usdt


# ---------------------------------------------------------------------------
# أوامر المستخدم العادي
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    courses = get_active_courses()
    if not courses:
        await update.message.reply_text("ما في كورسات متاحة حالياً، تابعنا قريباً 🌱")
        return

    keyboard = [
        [InlineKeyboardButton(f"{c['name']} - {c['price']}", callback_data=f"course_{c['id']}")]
        for c in courses
    ]
    await update.message.reply_text(
        "أهلاً فيك 👋\nاختار الكورس يلي حابب تشتركه:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def course_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بعد اختيار الكورس -> يعرض طريقة الدفع."""
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split("_")[1])
    course = get_course(course_id)
    if not course or not course["active"]:
        await query.edit_message_text("هاد الكورس مو متاح حالياً.")
        return

    keyboard = [
        [InlineKeyboardButton("💳 شام كاش", callback_data=f"pay_shamcash_{course_id}")],
        [InlineKeyboardButton("🪙 USDT (TRC20)", callback_data=f"pay_crypto_{course_id}")],
    ]
    await query.edit_message_text(
        f"📚 *{course['name']}*\nاختار طريقة الدفع المناسبة إلك:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def payment_method_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, method, course_id_str = query.data.split("_")
    course_id = int(course_id_str)
    course = get_course(course_id)
    if not course or not course["active"]:
        await query.edit_message_text("هاد الكورس مو متاح حالياً.")
        return

    # ننظف أي حالة سابقة عالقة بهاد المستخدم
    context.user_data.pop("pending_course", None)
    context.user_data.pop("awaiting_txid", None)

    if method == "shamcash":
        context.user_data["pending_course"] = course_id
        text = (
            f"📚 *{course['name']}*\n"
            f"💵 السعر: {course['price']}\n\n"
            f"للاشتراك:\n"
            f"1️⃣ حوّل المبلغ عبر شام كاش لهاد الرقم:\n`{course['shamcash_number']}`\n"
            f"2️⃣ بعدين ابعت هون *صورة إثبات التحويل* (سكرين شوت)\n\n"
            f"بمجرد ما نتأكد من الدفع رح يوصلك كود التفعيل مباشرة ✅"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    # method == "crypto"
    if not course["price_usdt"]:
        await query.edit_message_text(
            "الدفع بالكريبتو مو مفعّل لهاد الكورس بعد. اختار شام كاش أو تواصل معنا."
        )
        return
    if not TRON_WALLET_ADDRESS:
        await query.edit_message_text(
            "الدفع بالكريبتو مو جاهز حالياً (ما في عنوان محفظة محدد). اختار شام كاش بدلاً عنه."
        )
        return

    context.user_data["awaiting_txid"] = course_id
    text = (
        f"📚 *{course['name']}*\n"
        f"💵 المبلغ المطلوب: `{course['price_usdt']}` USDT\n"
        f"🌐 الشبكة: *TRC20* فقط (لا ترسل عبر أي شبكة تانية)\n\n"
        f"1️⃣ حوّل المبلغ بالضبط لهاد العنوان:\n`{TRON_WALLET_ADDRESS}`\n"
        f"2️⃣ بعدين ابعت هون *رقم العملية (Transaction Hash / TxID)* كنص\n\n"
        f"البوت رح يتحقق أوتوماتيكياً ويبعتلك الكود مباشرة إذا كل شي مطابق ⚡"
    )
    await query.edit_message_text(text, parse_mode="Markdown")


async def receive_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """صورة إثبات دفع شام كاش."""
    course_id = context.user_data.get("pending_course")
    if not course_id:
        await update.message.reply_text(
            "ما في طلب مفتوح حالياً. اضغط /start واختار كورس قبل ما تبعت صورة الدفع."
        )
        return

    course = get_course(course_id)
    if not course:
        await update.message.reply_text("صار في خطأ، جرب /start من جديد.")
        return

    user = update.effective_user
    order_id = create_order(user.id, user.username or "", user.full_name, course_id, "shamcash")

    caption = (
        f"🆕 طلب اشتراك جديد #{order_id} (شام كاش)\n"
        f"👤 {user.full_name} (@{user.username or '—'})\n"
        f"🆔 {user.id}\n"
        f"📚 الكورس: {course['name']} ({course['price']})\n"
        f"📦 المتبقي بالمخزون: {available_codes_count(course_id)} كود"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ قبول وإرسال الكود", callback_data=f"approve_{order_id}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"reject_{order_id}"),
            ]
        ]
    )

    photo = update.message.photo[-1].file_id if update.message.photo else None
    for admin_id in ADMIN_IDS:
        try:
            if photo:
                await context.bot.send_photo(
                    chat_id=admin_id, photo=photo, caption=caption, reply_markup=keyboard
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_id, text=caption, reply_markup=keyboard
                )
        except Exception:
            logger.exception("تعذر إرسال الطلب للأدمن %s", admin_id)

    context.user_data.pop("pending_course", None)
    await update.message.reply_text(
        "تم استلام إثبات الدفع ✅\nرح يتم التأكيد يدوياً وبتوصلك رسالة فيها الكود قريباً 🙏"
    )


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يمسك رسائل نصية عادية - نتحقق هل هي رقم عملية كريبتو بانتظارها."""
    course_id = context.user_data.get("awaiting_txid")
    if not course_id:
        return  # مش رقم عملية متوقع، تجاهل

    tx_hash = update.message.text.strip()
    course = get_course(course_id)
    if not course:
        await update.message.reply_text("صار في خطأ، جرب /start من جديد.")
        return

    if is_tx_used(tx_hash):
        await update.message.reply_text(
            "⚠️ رقم العملية هاد مستخدم قبل. إذا فيك شك تواصل معنا مباشرة."
        )
        return

    await update.message.reply_text("🔎 عم نتحقق من العملية على البلوكتشين، لحظات...")

    ok, message = await verify_tron_tx(tx_hash, course["price_usdt"])
    if not ok:
        await update.message.reply_text(f"❌ {message}\nتأكد من رقم العملية وجرب تبعته من جديد.")
        return

    user = update.effective_user
    order_id = create_order(user.id, user.username or "", user.full_name, course_id, "crypto")

    code_row = pull_unused_code(course_id)
    if not code_row:
        set_order_status(order_id, "no_stock")
        await update.message.reply_text(
            "✅ الدفع تأكد، بس للأسف نفد مخزون الأكواد حالياً. تواصل معنا وبنرسلك الكود يدوياً بأسرع وقت 🙏"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ طلب كريبتو مؤكد #{order_id} بس ما في أكواد متبقية لكورس {course['name']}!",
                )
            except Exception:
                logger.exception("تعذر تنبيه الأدمن %s", admin_id)
        context.user_data.pop("awaiting_txid", None)
        return

    mark_tx_used(tx_hash, order_id)
    mark_code_used(code_row["id"], user.id)
    set_order_status(order_id, "approved")
    context.user_data.pop("awaiting_txid", None)

    await update.message.reply_text(
        f"🎉 تم تأكيد الدفع تلقائياً عن طريق البلوكتشين!\n"
        f"📚 كورس: {course['name']}\n"
        f"🔑 كود التفعيل: `{code_row['code']}`\n\n"
        f"بالتوفيق! 🌟",
        parse_mode="Markdown",
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"✅ طلب كريبتو #{order_id} تأكد آلياً وانبعت الكود\n"
                    f"👤 {user.full_name} (@{user.username or '—'})\n"
                    f"📚 {course['name']} - {course['price_usdt']} USDT"
                ),
            )
        except Exception:
            logger.exception("تعذر تنبيه الأدمن %s", admin_id)


async def verify_tron_tx(tx_hash: str, expected_amount: float):
    """يتحقق من عملية USDT-TRC20 عبر API عام من TronScan.
    يرجع (True, "") لو كل شي مطابق، أو (False, "سبب الرفض") لو في مشكلة."""
    headers = {}
    if TRONSCAN_API_KEY:
        headers["TRON-PRO-API-KEY"] = TRONSCAN_API_KEY

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(TRONSCAN_URL, params={"hash": tx_hash}, headers=headers)
    except Exception:
        logger.exception("فشل الاتصال بـ TronScan")
        return False, "تعذر الاتصال بشبكة التحقق حالياً، جرب بعد شوي."

    if resp.status_code != 200:
        return False, "تعذر التحقق من العملية حالياً، جرب بعد شوي."

    data = resp.json()
    if not data or "hash" not in data:
        return False, "رقم العملية غير موجود أو غير صحيح."

    if data.get("confirmed") is False:
        return False, "العملية لسا ما تأكدت على الشبكة، استنى شوي وجرب تبعت الرقم من جديد."

    if data.get("contractRet") not in (None, "SUCCESS"):
        return False, "العملية فشلت على الشبكة (Failed)."

    transfer = data.get("tokenTransferInfo")
    if not transfer:
        return False, "هاي العملية مو تحويل USDT-TRC20."

    to_address = transfer.get("to_address", "")
    symbol = transfer.get("symbol", "")
    decimals = int(transfer.get("decimals", 6))
    amount_raw = transfer.get("amount_str") or transfer.get("amount") or "0"
    try:
        amount = int(amount_raw) / (10 ** decimals)
    except (ValueError, TypeError):
        return False, "تعذر قراءة مبلغ العملية."

    if to_address != TRON_WALLET_ADDRESS:
        return False, "العملية ما وصلت لعنواننا. تأكد إنك حولت للعنوان الصحيح."

    if symbol.upper() != "USDT":
        return False, "العملية مو بعملة USDT."

    if amount + AMOUNT_TOLERANCE < expected_amount:
        return False, f"المبلغ المحوّل ({amount} USDT) أقل من المطلوب ({expected_amount} USDT)."

    return True, ""


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_course", None)
    context.user_data.pop("awaiting_txid", None)
    await update.message.reply_text("تم إلغاء الطلب الحالي. اضغط /start للبدء من جديد.")


# ---------------------------------------------------------------------------
# رد الأدمن على طلبات شام كاش (قبول / رفض)
# ---------------------------------------------------------------------------
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    if not is_admin(user.id):
        await query.answer("هاد الإجراء للأدمن بس.", show_alert=True)
        return

    await query.answer()
    action, order_id_str = query.data.split("_")
    order_id = int(order_id_str)
    order = get_order(order_id)

    if not order:
        await query.edit_message_caption(caption="⚠️ الطلب غير موجود.")
        return
    if order["status"] != "pending":
        await query.edit_message_caption(caption=f"هاد الطلب سبق تعامل معه ({order['status']}).")
        return

    if action == "reject":
        set_order_status(order_id, "rejected")
        await context.bot.send_message(
            chat_id=order["user_id"],
            text="عذراً، ما قدرنا نأكد عملية الدفع. تواصل معنا إذا في استفسار 🙏",
        )
        cap = query.message.caption or query.message.text or ""
        await query.edit_message_caption(caption=cap + "\n\n❌ تم الرفض")
        return

    # action == "approve"
        code_row = claim_code(course_id, user.id)
    if not code_row:
        set_order_status(order_id, "no_stock")
        await update.message.reply_text(
            "✅ الدفع تأكد، بس للأسف نفد مخزون الأكواد حالياً. تواصل معنا وبنرسلك الكود يدوياً بأسرع وقت 🙏"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ طلب كريبتو مؤكد #{order_id} بس ما في أكواد متبقية لكورس {course['name']}!",
                )
            except Exception:
                logger.exception("تعذر تنبيه الأدمن %s", admin_id)
        context.user_data.pop("awaiting_txid", None)
        return

    mark_tx_used(tx_hash, order_id)
    set_order_status(order_id, "approved")

    course = get_course(order["course_id"])
    await context.bot.send_message(
        chat_id=order["user_id"],
        text=(
            f"🎉 تم تأكيد الدفع!\n"
            f"📚 كورس: {course['name']}\n"
            f"🔑 كود التفعيل: `{code_row['code']}`\n\n"
            f"بالتوفيق! 🌟"
        ),
        parse_mode="Markdown",
    )
    cap = query.message.caption or query.message.text or ""
    await query.edit_message_caption(caption=cap + "\n\n✅ تم القبول وإرسال الكود")


# ---------------------------------------------------------------------------
# أوامر الأدمن لإدارة الكورسات والأكواد
# ---------------------------------------------------------------------------
async def admin_only_guard(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("هاد الأمر للأدمن بس.")
        return False
    return True


async def add_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الاستخدام: /addcourse الاسم;السعر;رقم شام كاش
    مثال: /addcourse كورس اكسل;10$;0999999999
    """
    if not await admin_only_guard(update):
        return
    text = update.message.text.partition(" ")[2]
    parts = [p.strip() for p in text.split(";")]
    if len(parts) != 3:
        await update.message.reply_text(
            "الصيغة غلط. استخدم:\n/addcourse الاسم;السعر;رقم شام كاش\n"
            "مثال: /addcourse كورس اكسل;10$;0999999999"
        )
        return
    name, price, shamcash = parts
    course_id = db.create_course(name, price, shamcash)
    await update.message.reply_text(
        f"تمت إضافة الكورس #{course_id}: {name} ({price})\n"
        f"إذا بدك تفعّل الدفع بالكريبتو إله، استخدم:\n/setprice {course_id} السعر_بالدولار"
    )


async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الاستخدام: /setprice رقم_الكورس السعر_بالدولار
    مثال: /setprice 1 10
    """
    if not await admin_only_guard(update):
        return
    parts = update.message.text.split(" ")
    if len(parts) != 3:
        await update.message.reply_text("الصيغة: /setprice رقم_الكورس السعر_بالدولار\nمثال: /setprice 1 10")
        return
    try:
        course_id = int(parts[1])
        price = float(parts[2])
    except ValueError:
        await update.message.reply_text("رقم الكورس والسعر لازم يكونوا أرقام.")
        return
    course = get_course(course_id)
    if not course:
        await update.message.reply_text("رقم الكورس مو موجود.")
        return
    set_course_price_usdt(course_id, price)
    await update.message.reply_text(
        f"تم تحديد سعر كورس {course['name']} بالكريبتو: {price} USDT"
    )


async def list_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_guard(update):
        return
    rows = db.get_all_courses()
    if not rows:
        await update.message.reply_text("ما في كورسات مضافة بعد.")
        return
    lines = []
    for c in rows:
        n = available_codes_count(c["id"])
        state = "فعّال" if c["active"] else "متوقف"
        crypto_price = f"{c['price_usdt']} USDT" if c["price_usdt"] else "غير مفعّل"
        lines.append(
            f"#{c['id']} {c['name']} - {c['price']} - أكواد متبقية: {n} - ({state})\n"
            f"    💠 كريبتو: {crypto_price}"
        )
    await update.message.reply_text("\n".join(lines))


async def add_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الاستخدام: أرسل أمر /addcodes رقم_الكورس ثم بنفس الرسالة أو برسالة تالية
    اكتب الأكواد كل واحد بسطر لحاله.
    """
    if not await admin_only_guard(update):
        return
    lines = update.message.text.split("\n")
    first_line = lines[0]
    parts = first_line.split(" ")
    if len(parts) < 2 or not parts[1].isdigit():
        await update.message.reply_text(
            "الصيغة غلط. اكتب:\n/addcodes رقم_الكورس\nثم كل كود بسطر لحاله بنفس الرسالة."
        )
        return
    course_id = int(parts[1])
    course = get_course(course_id)
    if not course:
        await update.message.reply_text("رقم الكورس مو موجود. استخدم /listcourses للتأكد.")
        return

    codes = [l.strip() for l in lines[1:] if l.strip()]
    if not codes:
        await update.message.reply_text(
            "ما لقيت أي أكواد بالرسالة. لازم كل كود يكون بسطر منفصل بعد سطر الأمر."
        )
        return

    db.add_codes(course_id, codes)
    await update.message.reply_text(
        f"تمت إضافة {len(codes)} كود لكورس {course['name']}.\n"
        f"المجموع المتبقي الآن: {available_codes_count(course_id)}"
    )


async def toggle_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الاستخدام: /togglecourse رقم_الكورس"""
    if not await admin_only_guard(update):
        return
    parts = update.message.text.split(" ")
    if len(parts) != 2 or not parts[1].isdigit():
        await update.message.reply_text("الصيغة: /togglecourse رقم_الكورس")
        return
    course_id = int(parts[1])
    course = get_course(course_id)
    if not course:
        await update.message.reply_text("رقم الكورس مو موجود.")
        return
    new_state = 0 if course["active"] else 1
    db.set_course_active(course_id, bool(new_state))
    await update.message.reply_text(
        f"كورس {course['name']} أصبح {'فعّال ✅' if new_state else 'متوقف ⏸️'}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_guard(update):
        return
    s = db.get_stats()
    await update.message.reply_text(
        f"📊 إحصائيات:\nإجمالي الطلبات: {s['total']}\n✅ مقبول: {s['approved']}\n"
        f"⏳ قيد الانتظار: {s['pending']}\n❌ مرفوض: {s['rejected']}\n🪙 مدفوع بالكريبتو: {s['crypto']}"
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يرجع آيدي المستخدم - مفيد حتى تعرف آيدي أي حدا بدك تضيفه كأدمن."""
    user = update.effective_user
    await update.message.reply_text(f"آيدي حسابك: {user.id}")


async def help_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only_guard(update):
        return
    await update.message.reply_text(
        "أوامر الأدمن:\n"
        "/addcourse الاسم;السعر;رقم شام كاش\n"
        "/setprice رقم_الكورس السعر_بالدولار (لتفعيل الدفع بالكريبتو)\n"
        "/listcourses\n"
        "/togglecourse رقم_الكورس\n"
        "/addcodes رقم_الكورس (ثم أكواد، كل وحد بسطر)\n"
        "/stats\n"
        "/whoami (يعرض آيديك)"
    )


# ---------------------------------------------------------------------------
# التشغيل
# ---------------------------------------------------------------------------
def run_bot():
    if not BOT_TOKEN:
        raise SystemExit("لازم تحط BOT_TOKEN بمتغيرات البيئة (environment variables)")
    if not ADMIN_IDS:
        logger.warning("تنبيه: ما في ADMIN_IDS محددين - ما رح توصلك طلبات الدفع!")
    if not TRON_WALLET_ADDRESS:
        logger.warning("تنبيه: ما في TRON_WALLET_ADDRESS - الدفع بالكريبتو مو مفعّل.")

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("addcourse", add_course))
    app.add_handler(CommandHandler("setprice", set_price))
    app.add_handler(CommandHandler("listcourses", list_courses))
    app.add_handler(CommandHandler("togglecourse", toggle_course))
    app.add_handler(CommandHandler("addcodes", add_codes))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("adminhelp", help_admin))

    app.add_handler(CallbackQueryHandler(course_selected, pattern=r"^course_\d+$"))
    app.add_handler(CallbackQueryHandler(payment_method_selected, pattern=r"^pay_(shamcash|crypto)_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_decision, pattern=r"^(approve|reject)_\d+$"))

    app.add_handler(MessageHandler(filters.PHOTO, receive_payment_proof))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    logger.info("البوت شغّال...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()
