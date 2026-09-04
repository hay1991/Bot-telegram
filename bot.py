# -*- coding: utf-8 -*-
"""
بوت تلغرام لبيع أكواد الكورسات - Deeb Learning
=================================================
أربع طرق للدفع:
1) شام كاش — تأكيد يدوي:
   المستخدم يبعت صورة إثبات التحويل -> الأدمن يوافق يدوياً -> البوت يبعت الكود

2) USDT (شبكة TRC20) — تأكيد آلي بالكامل:
   المستخدم يحوّل لعنوان المحفظة -> يبعت رقم العملية (TxID) -> البوت يتحقق
   تلقائياً عبر API عام ومجاني من TronScan (بدون أي طرف ثالث غير رسمي) ->
   لو كل شي مطابق (العنوان، المبلغ، العملية غير مستخدمة قبل) يبعت الكود فوراً

3) USDT (شبكة BEP20 / BSC) — تأكيد آلي بالكامل:
   نفس فكرة TRC20 بالضبط، بس عبر BscScan API وعنوان عقد USDT الرسمي على BSC

4) حوالة الهرم — تأكيد يدوي:
   المستخدم يحوّل عبر فرع هرم -> يبعت رقم/كود الحوالة -> الأدمن يوافق يدوياً -> البوت يبعت الكود
"""
import os
import time
import logging
from collections import defaultdict

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

# عنوان محفظتك على شبكة BEP20 / BSC (اللي رح يحوّل عليه الزباين USDT عبر Binance Smart Chain)
BSC_WALLET_ADDRESS = os.environ.get("BSC_WALLET_ADDRESS", "")

# مفتاح BscScan — موصى فيه بشدة، بدونه حد الطلبات المجاني منخفض جداً وممكن يفشل التحقق بأوقات الضغط
BSCSCAN_API_KEY = os.environ.get("BSCSCAN_API_KEY", "")
BSCSCAN_URL = "https://api.bscscan.com/api"

# عنوان العقد الرسمي لـ USDT (Binance-Peg) على شبكة BEP20/BSC (ثابت، ما بيتغيّر)
# تأكد منه بنفسك عالموقع الرسمي (bscscan.com) قبل ما تفعّل الدفع فعلياً
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

# حد أدنى من التأكيدات على شبكة BSC قبل قبول العملية
BSC_MIN_CONFIRMATIONS = 3

# اسم المستلم الكامل لحوالات الهرم (نص ثابت لكل الكورسات)
HARAM_RECEIVER_NAME = os.environ.get("HARAM_RECEIVER_NAME", "")

# نسبة تسامح بسيطة بالمبلغ (عشان فروقات تقريب عشرية بسيطة، مو لتغطية نقص حقيقي بالمبلغ)
AMOUNT_TOLERANCE = 0.01

# عنوان العقد الرسمي لـ USDT على شبكة TRC20 (ثابت، ما بيتغيّر)
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# حد بسيط لمعدل الطلبات لكل مستخدم (صور إثبات + إرسال TxID)
RATE_LIMIT_MAX = int(os.environ.get("RATE_LIMIT_MAX", "8"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # ثانية

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_rate_hits: dict[int, list[float]] = defaultdict(list)

# ---------------------------------------------------------------------------
# أدوات مساعدة - عامة
# ---------------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def check_rate_limit(user_id: int) -> bool:
    """يرجع True إذا مسموح، False إذا تجاوز الحد."""
    now = time.time()
    hits = _rate_hits[user_id]
    _rate_hits[user_id] = [t for t in hits if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_hits[user_id]) >= RATE_LIMIT_MAX:
        return False
    _rate_hits[user_id].append(now)
    return True


def escape_md(text: str) -> str:
    """يهرب رموز Markdown الأساسية من نصوص المستخدم/قاعدة البيانات."""
    if not text:
        return ""
    for ch in ("\\", "`", "*", "_", "[", "]", "(", ")"):
        text = text.replace(ch, "\\" + ch)
    return text


get_active_courses = db.get_active_courses
get_course = db.get_course
available_codes_count = db.available_codes_count
pull_unused_code = db.pull_unused_code
mark_code_used = db.mark_code_used
claim_code = db.claim_code
create_order = db.create_order
get_order = db.get_order
set_order_status = db.set_order_status
set_order_code = db.set_order_code
get_pending_order = db.get_pending_order
is_tx_used = db.is_tx_used
mark_tx_used = db.mark_tx_used
try_reserve_tx = db.try_reserve_tx
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
        [InlineKeyboardButton("🪙 USDT (BEP20)", callback_data=f"pay_cryptobep_{course_id}")],
        [InlineKeyboardButton("🏦 حوالة الهرم", callback_data=f"pay_haram_{course_id}")],
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
    context.user_data.pop("awaiting_txid_network", None)
    context.user_data.pop("awaiting_haram", None)

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

    if method == "haram":
        if not HARAM_RECEIVER_NAME:
            await query.edit_message_text(
                "⚠️ طريقة حوالة الهرم غير مفعّلة حالياً (ما في اسم مستلم محدد).\n"
                "اختار طريقة دفع تانية أو تواصل معنا."
            )
            return
        context.user_data["awaiting_haram"] = course_id
        text = (
            f"📚 *{course['name']}*\n"
            f"💵 المبلغ المطلوب: {course['price']}\n\n"
            f"للاشتراك عبر حوالة الهرم:\n"
            f"1️⃣ روح لأقرب فرع هرم وحوّل المبلغ باسم:\n`{HARAM_RECEIVER_NAME}`\n"
            f"2️⃣ بعدين ابعت هون *رقم/كود الحوالة* يلي بياخده من الفرع (كنص)\n\n"
            f"بمجرد ما نتأكد من الدفع رح يوصلك كود التفعيل مباشرة ✅"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if method == "cryptobep":
        if not course["price_usdt"]:
            await query.edit_message_text(
                "الدفع بالكريبتو مو مفعّل لهاد الكورس بعد. اختار شام كاش أو تواصل معنا."
            )
            return
        if not BSC_WALLET_ADDRESS:
            await query.edit_message_text(
                "الدفع عبر BEP20 مو جاهز حالياً (ما في عنوان محفظة محدد). اختار طريقة تانية بدلاً عنه."
            )
            return
        context.user_data["awaiting_txid"] = course_id
        context.user_data["awaiting_txid_network"] = "bep20"
        text = (
            f"📚 *{course['name']}*\n"
            f"💵 المبلغ المطلوب: `{course['price_usdt']}` USDT\n"
            f"🌐 الشبكة: *BEP20 (BSC)* فقط (لا ترسل عبر أي شبكة تانية)\n\n"
            f"1️⃣ حوّل المبلغ بالضبط لهاد العنوان:\n`{BSC_WALLET_ADDRESS}`\n"
            f"2️⃣ بعدين ابعت هون *رقم العملية (Transaction Hash)* كنص\n\n"
            f"البوت رح يتحقق أوتوماتيكياً ويبعتلك الكود مباشرة إذا كل شي مطابق ⚡"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    # method == "crypto" (TRC20)
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
    context.user_data["awaiting_txid_network"] = "trc20"
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

    user = update.effective_user
    if not check_rate_limit(user.id):
        await update.message.reply_text(
            "⏳ أرسلت طلبات كثيرة خلال وقت قصير. استنى دقيقة وجرب مرة تانية."
        )
        return

    course = get_course(course_id)
    if not course:
        await update.message.reply_text("صار في خطأ، جرب /start من جديد.")
        return

    existing = get_pending_order(user.id, course_id)
    if existing:
        context.user_data.pop("pending_course", None)
        await update.message.reply_text(
            f"عندك طلب سابق (#{existing['id']}) لنفس الكورس لسا قيد المراجعة.\n"
            f"استنى رد الأدمن قبل ما تبعت طلب جديد. إذا في تأخير، تواصل معنا مباشرة 🙏"
        )
        return

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
                InlineKeyboardButton("✅ قبول وإرسال الكود", callback_data=f"askapprove_{order_id}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"askreject_{order_id}"),
            ]
        ]
    )
    photo = update.message.photo[-1].file_id if update.message.photo else None
    sent_refs = []
    for admin_id in ADMIN_IDS:
        try:
            if photo:
                msg = await context.bot.send_photo(
                    chat_id=admin_id, photo=photo, caption=caption, reply_markup=keyboard
                )
            else:
                msg = await context.bot.send_message(
                    chat_id=admin_id, text=caption, reply_markup=keyboard
                )
            sent_refs.append((admin_id, msg.message_id))
        except Exception:
            logger.exception("تعذر إرسال الطلب للأدمن %s", admin_id)

    register_admin_message_refs(context, order_id, sent_refs)
    context.user_data.pop("pending_course", None)
    await update.message.reply_text(
        "تم استلام إثبات الدفع ✅\nرح يتم التأكيد يدوياً وبتوصلك رسالة فيها الكود قريباً 🙏"
    )


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يمسك رسائل نصية عادية - رقم عملية كريبتو أو رقم حوالة هرم بانتظارها."""
    # --- حوالة الهرم ---
    haram_course_id = context.user_data.get("awaiting_haram")
    if haram_course_id:
        user = update.effective_user
        if not check_rate_limit(user.id):
            await update.message.reply_text(
                "⏳ أرسلت طلبات كثيرة خلال وقت قصير. استنى دقيقة وجرب مرة تانية."
            )
            return
        transfer_ref = (update.message.text or "").strip()
        if not transfer_ref:
            await update.message.reply_text("أرسل رقم/كود الحوالة كنص.")
            return
        course = get_course(haram_course_id)
        if not course:
            await update.message.reply_text("صار في خطأ، جرب /start من جديد.")
            context.user_data.pop("awaiting_haram", None)
            return
        existing = get_pending_order(user.id, haram_course_id)
        if existing:
            context.user_data.pop("awaiting_haram", None)
            await update.message.reply_text(
                f"عندك طلب سابق (#{existing['id']}) لنفس الكورس لسا قيد المراجعة.\n"
                f"استنى رد الأدمن قبل ما تبعت طلب جديد. إذا في تأخير، تواصل معنا مباشرة 🙏"
            )
            return
        order_id = create_order(
            user.id, user.username or "", user.full_name, haram_course_id, "haram", payment_ref=transfer_ref
        )
        caption = (
            f"🆕 طلب اشتراك جديد #{order_id} (حوالة الهرم)\n"
            f"👤 {user.full_name} (@{user.username or '—'})\n"
            f"🆔 {user.id}\n"
            f"📚 الكورس: {course['name']} ({course['price']})\n"
            f"🏦 رقم الحوالة: {transfer_ref}\n"
            f"📦 المتبقي بالمخزون: {available_codes_count(haram_course_id)} كود"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ قبول وإرسال الكود", callback_data=f"askapprove_{order_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"askreject_{order_id}"),
                ]
            ]
        )
        sent_refs = []
        for admin_id in ADMIN_IDS:
            try:
                msg = await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=keyboard)
                sent_refs.append((admin_id, msg.message_id))
            except Exception:
                logger.exception("تعذر إرسال الطلب للأدمن %s", admin_id)
        register_admin_message_refs(context, order_id, sent_refs)
        context.user_data.pop("awaiting_haram", None)
        await update.message.reply_text(
            "تم استلام رقم الحوالة ✅\nرح يتم التأكيد يدوياً وبتوصلك رسالة فيها الكود قريباً 🙏"
        )
        return

    # --- كريبتو (TxID) — TRC20 أو BEP20 ---
    course_id = context.user_data.get("awaiting_txid")
    if not course_id:
        return  # مش رقم عملية متوقع، تجاهل

    network = context.user_data.get("awaiting_txid_network", "trc20")

    user = update.effective_user
    if not check_rate_limit(user.id):
        await update.message.reply_text(
            "⏳ أرسلت طلبات كثيرة خلال وقت قصير. استنى دقيقة وجرب مرة تانية."
        )
        return

    tx_hash = (update.message.text or "").strip().lower()
    if not tx_hash or len(tx_hash) < 20:
        await update.message.reply_text(
            "رقم العملية غير صالح. انسخ Transaction Hash كاملاً من المحفظة."
        )
        return

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

    if network == "bep20":
        ok, message = await verify_bsc_tx(tx_hash, course["price_usdt"])
        payment_method_value = "crypto_bep20"
        network_label = "BEP20"
    else:
        ok, message = await verify_tron_tx(tx_hash, course["price_usdt"])
        payment_method_value = "crypto_trc20"
        network_label = "TRC20"

    if not ok:
        await update.message.reply_text(f"❌ {message}\nتأكد من رقم العملية وجرب تبعته من جديد.")
        return

    order_id = create_order(user.id, user.username or "", user.full_name, course_id, payment_method_value)

    if not try_reserve_tx(tx_hash, order_id):
        set_order_status(order_id, "rejected")
        await update.message.reply_text(
            "⚠️ رقم العملية هاد استُخدم للتو من طلب آخر. إذا فيك شك تواصل معنا مباشرة."
        )
        context.user_data.pop("awaiting_txid", None)
        context.user_data.pop("awaiting_txid_network", None)
        return

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
                    text=f"⚠️ طلب كريبتو ({network_label}) مؤكد #{order_id} بس ما في أكواد متبقية لكورس {course['name']}!",
                )
            except Exception:
                logger.exception("تعذر تنبيه الأدمن %s", admin_id)
        context.user_data.pop("awaiting_txid", None)
        context.user_data.pop("awaiting_txid_network", None)
        return

    set_order_code(order_id, code_row["id"])
    set_order_status(order_id, "approved")
    context.user_data.pop("awaiting_txid", None)
    context.user_data.pop("awaiting_txid_network", None)

    await update.message.reply_text(
        f"🎉 تم تأكيد الدفع تلقائياً عن طريق البلوكتشين ({network_label})!\n"
        f"📚 كورس: {escape_md(course['name'])}\n"
        f"🔑 كود التفعيل: `{code_row['code']}`\n\n"
        f"بالتوفيق! 🌟",
        parse_mode="Markdown",
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"✅ طلب كريبتو ({network_label}) #{order_id} تأكد آلياً وانبعت الكود\n"
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
    contract_address = transfer.get("contract_address", "")
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
    if contract_address and contract_address != USDT_TRC20_CONTRACT:
        return False, "العملية مو بعملة USDT الرسمية على شبكة TRC20 (عنوان العقد غير مطابق)."
    if amount + AMOUNT_TOLERANCE < expected_amount:
        return False, f"المبلغ المحوّل ({amount} USDT) أقل من المطلوب ({expected_amount} USDT)."

    return True, ""


async def verify_bsc_tx(tx_hash: str, expected_amount: float):
    """يتحقق من عملية USDT-BEP20 عبر API عام من BscScan (endpoint: account/tokentx).
    بيدور عن الـ tx_hash داخل آخر تحويلات USDT الواصلة لمحفظتنا، ويتأكد من:
    العنوان المستلم، عنوان العقد الرسمي، المبلغ، وعدد كافٍ من التأكيدات.
    يرجع (True, "") لو كل شي مطابق، أو (False, "سبب الرفض") لو في مشكلة."""
    if not BSCSCAN_API_KEY:
        return False, "التحقق من BEP20 مو جاهز حالياً (ناقص إعداد من طرفنا)."

    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": USDT_BEP20_CONTRACT,
        "address": BSC_WALLET_ADDRESS,
        "sort": "desc",
        "apikey": BSCSCAN_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(BSCSCAN_URL, params=params)
    except Exception:
        logger.exception("فشل الاتصال بـ BscScan")
        return False, "تعذر الاتصال بشبكة التحقق حالياً، جرب بعد شوي."

    if resp.status_code != 200:
        return False, "تعذر التحقق من العملية حالياً، جرب بعد شوي."

    data = resp.json()
    result = data.get("result")
    if data.get("status") != "1" or not isinstance(result, list):
        return False, "رقم العملية غير موجود أو غير صحيح."

    tx_hash_lower = tx_hash.lower()
    match = next((t for t in result if t.get("hash", "").lower() == tx_hash_lower), None)
    if not match:
        return False, "رقم العملية غير موجود أو غير صحيح."

    to_address = (match.get("to") or "").lower()
    contract_address = (match.get("contractAddress") or "").lower()

    if to_address != BSC_WALLET_ADDRESS.lower():
        return False, "العملية ما وصلت لعنواننا. تأكد إنك حولت للعنوان الصحيح."
    if contract_address != USDT_BEP20_CONTRACT.lower():
        return False, "العملية مو بعملة USDT الرسمية على شبكة BEP20."

    try:
        decimals = int(match.get("tokenDecimal", 18))
        amount = int(match.get("value", "0")) / (10 ** decimals)
    except (ValueError, TypeError):
        return False, "تعذر قراءة مبلغ العملية."

    try:
        confirmations = int(match.get("confirmations", "0") or "0")
    except (ValueError, TypeError):
        confirmations = 0

    if confirmations < BSC_MIN_CONFIRMATIONS:
        return False, "العملية لسا ما تأكدت كفاية على الشبكة، استنى شوي وجرب تبعت الرقم من جديد."
    if amount + AMOUNT_TOLERANCE < expected_amount:
        return False, f"المبلغ المحوّل ({amount} USDT) أقل من المطلوب ({expected_amount} USDT)."

    return True, ""


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_course", None)
    context.user_data.pop("awaiting_txid", None)
    context.user_data.pop("awaiting_txid_network", None)
    context.user_data.pop("awaiting_haram", None)
    await update.message.reply_text("تم إلغاء الطلب الحالي. اضغط /start للبدء من جديد.")


# ---------------------------------------------------------------------------
# رد الأدمن على طلبات شام كاش / حوالة الهرم (قبول / رفض)
# ---------------------------------------------------------------------------
def register_admin_message_refs(context: ContextTypes.DEFAULT_TYPE, order_id: int, refs: list):
    store = context.bot_data.setdefault("admin_msg_refs", {})
    store[order_id] = refs


async def clear_admin_message_buttons(context: ContextTypes.DEFAULT_TYPE, order_id: int):
    store = context.bot_data.get("admin_msg_refs", {})
    refs = store.get(order_id, [])
    for chat_id, message_id in refs:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
        except Exception:
            pass


async def _edit_admin_message(query, new_text: str):
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=new_text)
        else:
            await query.edit_message_text(text=new_text)
    except Exception:
        pass


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
        await _edit_admin_message(query, "⚠️ الطلب غير موجود.")
        return

    if action == "askapprove":
        if order["status"] != "pending":
            await _edit_admin_message(query, f"هاد الطلب سبق تعامل معه ({order['status']}).")
            return
        confirm_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔙 رجوع", callback_data=f"backconfirm_{order_id}"),
                    InlineKeyboardButton("✅ تأكيد", callback_data=f"confirmapprove_{order_id}"),
                ]
            ]
        )
        await context.bot.send_message(
            chat_id=user.id,
            text=f"❓ متأكد إنك بدك تقبل الطلب #{order_id} وترسل الكود؟",
            reply_markup=confirm_keyboard,
        )
        return

    if action == "askreject":
        if order["status"] != "pending":
            await _edit_admin_message(query, f"هاد الطلب سبق تعامل معه ({order['status']}).")
            return
        confirm_keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔙 رجوع", callback_data=f"backconfirm_{order_id}"),
                    InlineKeyboardButton("❌ تأكيد الرفض", callback_data=f"confirmreject_{order_id}"),
                ]
            ]
        )
        await context.bot.send_message(
            chat_id=user.id,
            text=f"❓ متأكد إنك بدك ترفض الطلب #{order_id}؟",
            reply_markup=confirm_keyboard,
        )
        return

    if action == "backconfirm":
        try:
            await query.edit_message_text("↩️ رجعنا، ما انعمل أي تغيير عالطلب.")
        except Exception:
            pass
        return

    if action == "confirmreject":
        if order["status"] != "pending":
            try:
                await query.edit_message_text(f"هاد الطلب سبق تعامل معه ({order['status']}).")
            except Exception:
                pass
            return
        set_order_status(order_id, "rejected")
        await context.bot.send_message(
            chat_id=order["user_id"],
            text="عذراً، ما قدرنا نأكد عملية الدفع. تواصل معنا إذا في استفسار 🙏",
        )
        try:
            await query.edit_message_text(f"❌ تم رفض الطلب #{order_id}.")
        except Exception:
            pass
        await clear_admin_message_buttons(context, order_id)
        return

    # action == "confirmapprove"
    if order["status"] != "pending":
        try:
            await query.edit_message_text(f"هاد الطلب سبق تعامل معه ({order['status']}).")
        except Exception:
            pass
        return

    code_row = claim_code(order["course_id"], order["user_id"])
    if not code_row:
        await query.answer("ما في أكواد متبقية لهاد الكورس! 🚫", show_alert=True)
        await context.bot.send_message(
            chat_id=user.id,
            text=f"⚠️ لا يوجد أكواد متبقية لكورس #{order['course_id']}, لازم تعبّي مخزون جديد بأمر /addcodes",
        )
        return

    set_order_code(order_id, code_row["id"])
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
    try:
        await query.edit_message_text(f"✅ تم قبول الطلب #{order_id} وإرسال الكود.")
    except Exception:
        pass
    await clear_admin_message_buttons(context, order_id)


# ---------------------------------------------------------------------------
# أوامر الأدمن لإدارة الكورسات والأكواد
# ---------------------------------------------------------------------------
async def admin_only_guard(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("هاد الأمر للأدمن بس.")
        return False
    return True


async def add_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            f"   💠 كريبتو: {crypto_price}"
        )
    await update.message.reply_text("\n".join(lines))


async def add_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"⏳ قيد الانتظار: {s['pending']}\n❌ مرفوض: {s['rejected']}\n"
        f"🪙 مدفوع بالكريبتو (الإجمالي): {s['crypto']}\n"
        f"   ↳ TRC20: {s['crypto_trc20']} — BEP20: {s['crypto_bep20']}"
    )


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        logger.warning("تنبيه: ما في TRON_WALLET_ADDRESS - الدفع بـ TRC20 مو مفعّل.")
    if not BSC_WALLET_ADDRESS:
        logger.warning("تنبيه: ما في BSC_WALLET_ADDRESS - الدفع بـ BEP20 مو مفعّل.")
    if not HARAM_RECEIVER_NAME:
        logger.warning("تنبيه: ما في HARAM_RECEIVER_NAME - الدفع بحوالة الهرم مو مفعّل.")

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
    app.add_handler(
        CallbackQueryHandler(
            payment_method_selected, pattern=r"^pay_(shamcash|crypto|cryptobep|haram)_\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            admin_decision,
            pattern=r"^(askapprove|confirmapprove|askreject|confirmreject|backconfirm)_\d+$",
        )
    )

    app.add_handler(MessageHandler(filters.PHOTO, receive_payment_proof))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    logger.info("البوت شغّال...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    run_bot()
