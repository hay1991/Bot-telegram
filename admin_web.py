# -*- coding: utf-8 -*-
"""
لوحة تحكم ويب بسيطة لإدارة الكورسات والأكواد بدل التعديل المباشر بـ DB Browser
أو كتابة أوامر بالبوت. محمية بـ Basic Auth + CSRF + HTML escape.
"""
import os
import csv
import io
import secrets
import html
from functools import wraps

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    Response,
    render_template_string,
    session,
    abort,
)

import db

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

ADMIN_WEB_USER = os.environ.get("ADMIN_WEB_USER", "admin")
ADMIN_WEB_PASS = os.environ.get("ADMIN_WEB_PASS", "")


def check_auth(username, password):
    return username == ADMIN_WEB_USER and password and password == ADMIN_WEB_PASS


def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not ADMIN_WEB_PASS:
            return Response(
                "لوحة التحكم مو مفعّلة: لازم تحط ADMIN_WEB_PASS بمتغيرات البيئة أولاً.",
                500,
            )
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "لازم تسجل دخول.",
                401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'},
            )
        return f(*args, **kwargs)

    return wrapped


def _get_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def _validate_csrf():
    expected = session.get("csrf_token")
    got = request.form.get("csrf_token", "")
    if not expected or not got or not secrets.compare_digest(expected, got):
        abort(400, description="CSRF token invalid or missing")


def e(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


BASE = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>لوحة تحكم Deeb Learning</title>
<style>
:root { --bg:#0f1115; --card:#171a21; --line:#262b36; --text:#e8eaed; --muted:#9aa3b2;
        --accent:#4f8cff; --good:#22c55e; --bad:#ef4444; --warn:#f59e0b; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font-family:'Segoe UI', Tahoma, Arial, sans-serif; }
header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex;
         justify-content:space-between; align-items:center; }
header h1 { font-size:18px; margin:0; }
nav a { color:var(--muted); text-decoration:none; margin-inline-start:16px; font-size:14px; }
nav a:hover { color:var(--text); }
main { max-width:960px; margin:0 auto; padding:24px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:18px; margin-bottom:18px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th, td { text-align:right; padding:10px 8px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; }
.badge { padding:2px 8px; border-radius:999px; font-size:12px; }
.badge.good { background:rgba(34,197,94,.15); color:var(--good); }
.badge.bad { background:rgba(239,68,68,.15); color:var(--bad); }
.badge.warn { background:rgba(245,158,11,.15); color:var(--warn); }
.btn { display:inline-block; background:var(--accent); color:#fff; border:none;
       padding:8px 14px; border-radius:8px; cursor:pointer; font-size:14px;
       text-decoration:none; }
.btn.small { padding:4px 10px; font-size:12px; }
.btn.danger { background:var(--bad); }
.btn.ghost { background:transparent; border:1px solid var(--line); color:var(--text); }
input, textarea, select { width:100%; padding:9px 10px; border-radius:8px; border:1px solid var(--line);
       background:#10131a; color:var(--text); font-size:14px; margin-bottom:10px; }
label { font-size:13px; color:var(--muted); display:block; margin-bottom:4px; }
.row { display:flex; gap:10px; flex-wrap:wrap; }
.row > div { flex:1; min-width:160px; }
.muted { color:var(--muted); font-size:13px; }
.stats { display:flex; gap:14px; flex-wrap:wrap; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:12px;
        padding:14px 18px; min-width:120px; }
.stat b { font-size:22px; display:block; }
.flash { background:rgba(79,140,255,.12); border:1px solid var(--accent); color:var(--text);
         padding:10px 14px; border-radius:8px; margin-bottom:16px; font-size:14px; }
</style>
</head>
<body>
<header>
  <h1>🎓 Deeb Learning — لوحة التحكم</h1>
  <nav>
    <a href="{{ url_for('dashboard') }}">الرئيسية</a>
    <a href="{{ url_for('orders_page') }}">الطلبات</a>
    <a href="{{ url_for('new_course') }}">+ كورس جديد</a>
  </nav>
</header>
<main>
{% if flash %}<div class="flash">{{ flash }}</div>{% endif %}
{{ body|safe }}
</main>
</body>
</html>
"""


def render(body_html, flash=None):
    safe_flash = e(flash) if flash else None
    return render_template_string(BASE, body=body_html, flash=safe_flash)


def csrf_field():
    return f'<input type="hidden" name="csrf_token" value="{e(_get_csrf_token())}">'


# ---------------------------------------------------------------------------
# الرئيسية: قائمة الكورسات + إحصائيات سريعة
# ---------------------------------------------------------------------------
@app.route("/")
@require_auth
def dashboard():
    s = db.get_stats()
    courses = db.get_all_courses()
    stats_html = f"""
    <div class="stats">
      <div class="stat"><b>{s['total']}</b><span class="muted">إجمالي الطلبات</span></div>
      <div class="stat"><b>{s['approved']}</b><span class="muted">مقبول</span></div>
      <div class="stat"><b>{s['pending']}</b><span class="muted">قيد الانتظار</span></div>
      <div class="stat"><b>{s['rejected']}</b><span class="muted">مرفوض</span></div>
      <div class="stat"><b>{s['crypto']}</b><span class="muted">مدفوع بالكريبتو (إجمالي)</span></div>
      <div class="stat"><b>{s['crypto_trc20']}</b><span class="muted">كريبتو - TRC20</span></div>
      <div class="stat"><b>{s['crypto_bep20']}</b><span class="muted">كريبتو - BEP20</span></div>
    </div>
    """

    rows = ""
    for c in courses:
        remaining = db.available_codes_count(c["id"])
        state_badge = (
            '<span class="badge good">فعّال</span>'
            if c["active"]
            else '<span class="badge bad">متوقف</span>'
        )
        low_stock = '<span class="badge warn">مخزون منخفض</span>' if remaining <= 3 else ""
        crypto_price = f"{e(c['price_usdt'])} USDT" if c["price_usdt"] else "—"
        rows += f"""
        <tr>
          <td>#{c['id']}</td>
          <td>{e(c['name'])}</td>
          <td>{e(c['price'])}</td>
          <td>{crypto_price}</td>
          <td>{remaining} {low_stock}</td>
          <td>{state_badge}</td>
          <td>
            <a class="btn small ghost" href="{url_for('edit_course', course_id=c['id'])}">تعديل</a>
            <a class="btn small ghost" href="{url_for('course_codes', course_id=c['id'])}">الأكواد</a>
          </td>
        </tr>
        """

    body = f"""
    {stats_html}
    <div class="card">
      <table>
        <tr><th>#</th><th>الاسم</th><th>السعر</th><th>سعر الكريبتو</th>
            <th>أكواد متبقية</th><th>الحالة</th><th></th></tr>
        {rows if courses else '<tr><td colspan="7" class="muted">ما في كورسات بعد. أضف واحد من زر "+ كورس جديد" فوق.</td></tr>'}
      </table>
    </div>
    """
    return render(body)


# ---------------------------------------------------------------------------
# إضافة / تعديل كورس
# ---------------------------------------------------------------------------
def course_form_html(name="", price="", shamcash_number="", price_usdt="", extra=""):
    return f"""
    <div class="card">
      <form method="post">
        {csrf_field()}
        <div class="row">
          <div>
            <label>اسم الكورس</label>
            <input name="name" value="{e(name)}" required>
          </div>
          <div>
            <label>السعر (نصي - للعرض بشام كاش، مثلاً 10$)</label>
            <input name="price" value="{e(price)}" required>
          </div>
        </div>
        <div class="row">
          <div>
            <label>رقم شام كاش</label>
            <input name="shamcash_number" value="{e(shamcash_number)}" required>
          </div>
          <div>
            <label>سعر الكريبتو بالدولار (اختياري - اتركه فاضي لو ما بدك تفعّل الكريبتو لهاد الكورس)</label>
            <input name="price_usdt" value="{e(price_usdt)}">
          </div>
        </div>
        <button class="btn" type="submit">حفظ</button>
        {extra}
      </form>
    </div>
    """


@app.route("/courses/new", methods=["GET", "POST"])
@require_auth
def new_course():
    if request.method == "POST":
        _validate_csrf()
        name = request.form["name"].strip()
        price = request.form["price"].strip()
        shamcash = request.form["shamcash_number"].strip()
        price_usdt_raw = request.form.get("price_usdt", "").strip()
        course_id = db.create_course(name, price, shamcash)
        if price_usdt_raw:
            try:
                db.set_course_price_usdt(course_id, float(price_usdt_raw))
            except ValueError:
                pass
        return redirect(url_for("dashboard"))
    body = "<div class='card'><h3>إضافة كورس جديد</h3></div>" + course_form_html()
    return render(body)


@app.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@require_auth
def edit_course(course_id):
    course = db.get_course(course_id)
    if not course:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        _validate_csrf()
        name = request.form["name"].strip()
        price = request.form["price"].strip()
        shamcash = request.form["shamcash_number"].strip()
        price_usdt_raw = request.form.get("price_usdt", "").strip()
        price_usdt = None
        if price_usdt_raw:
            try:
                price_usdt = float(price_usdt_raw)
            except ValueError:
                price_usdt = None
        db.update_course(course_id, name, price, shamcash, price_usdt)
        return redirect(url_for("dashboard"))

    toggle_label = "إيقاف الكورس" if course["active"] else "تفعيل الكورس"
    extra = f"""
    <form method="post" action="{url_for('toggle_course_web', course_id=course_id)}"
          onsubmit="return confirm('متأكد بدك {e(toggle_label)}؟')">
      {csrf_field()}
      <button class="btn ghost" type="submit">{toggle_label}</button>
    </form>
    """
    body = f"<div class='card'><h3>تعديل: {e(course['name'])}</h3></div>" + course_form_html(
        name=course["name"],
        price=course["price"],
        shamcash_number=course["shamcash_number"],
        price_usdt=course["price_usdt"] or "",
        extra=extra,
    )
    return render(body)


@app.route("/courses/<int:course_id>/toggle", methods=["POST"])
@require_auth
def toggle_course_web(course_id):
    _validate_csrf()
    db.toggle_course_active(course_id)
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# إدارة أكواد كورس معيّن
# ---------------------------------------------------------------------------
@app.route("/courses/<int:course_id>/codes", methods=["GET", "POST"])
@require_auth
def course_codes(course_id):
    course = db.get_course(course_id)
    if not course:
        return redirect(url_for("dashboard"))

    flash = None
    if request.method == "POST":
        _validate_csrf()
        raw = request.form.get("codes", "")
        codes = [line.strip() for line in raw.splitlines() if line.strip()]
        if codes:
            result = db.add_codes(course_id, codes)
            flash = f"تمت إضافة {result['added']} كود."
            if result["skipped"]:
                flash += f" — تم تجاهل {result['skipped']} كود لأنه كان موجود مسبقاً بنفس الكورس."

    codes = db.get_codes_for_course(course_id)
    rows = ""
    for c in codes:
        if c["used"]:
            badge = f'<span class="badge bad">مستخدم (زبون #{e(c["used_by"])})</span>'
            action = ""
        else:
            badge = '<span class="badge good">متاح</span>'
            action = f"""<form method="post" action="{url_for('delete_code', course_id=course_id, code_id=c['id'])}"
                  onsubmit="return confirm('متأكد بدك تحذف هاد الكود؟')" style="display:inline">
                  {csrf_field()}
                  <button class="btn small danger" type="submit">حذف</button>
                  </form>"""
        rows += f"<tr><td>{e(c['code'])}</td><td>{badge}</td><td>{action}</td></tr>"

    body = f"""
    <div class="card">
      <h3>أكواد كورس: {e(course['name'])}</h3>
      <form method="post">
        {csrf_field()}
        <label>ألصق الأكواد الجديدة هون، كل كود بسطر لحاله</label>
        <textarea name="codes" rows="6" placeholder="ABC123&#10;DEF456&#10;GHI789"></textarea>
        <button class="btn" type="submit">إضافة الأكواد</button>
      </form>
    </div>
    <div class="card">
      <table>
        <tr><th>الكود</th><th>الحالة</th><th></th></tr>
        {rows if codes else '<tr><td colspan="3" class="muted">ما في أكواد مضافة بعد.</td></tr>'}
      </table>
    </div>
    """
    return render(body, flash=flash)


@app.route("/courses/<int:course_id>/codes/<int:code_id>/delete", methods=["POST"])
@require_auth
def delete_code(course_id, code_id):
    _validate_csrf()
    db.delete_unused_code(code_id)
    return redirect(url_for("course_codes", course_id=course_id))


# ---------------------------------------------------------------------------
# الطلبات — سجل كامل مع فلترة، ترقيم صفحات، وتصدير CSV
# ---------------------------------------------------------------------------
ORDER_STATUSES = [
    ("pending", "قيد الانتظار"),
    ("approved", "مقبول"),
    ("rejected", "مرفوض"),
    ("no_stock", "لا يوجد مخزون"),
]

ORDER_PAYMENT_METHODS = [
    ("shamcash", "شام كاش"),
    ("crypto_trc20", "USDT (TRC20)"),
    ("crypto_bep20", "USDT (BEP20)"),
    ("haram", "حوالة الهرم"),
]

PAGE_SIZE = 50


def _order_filters_from_request():
    return {
        "status": request.args.get("status") or None,
        "payment_method": request.args.get("payment_method") or None,
        "search": request.args.get("search") or None,
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
    }


def status_badge_html(status):
    badges = {
        "approved": '<span class="badge good">مقبول</span>',
        "pending": '<span class="badge warn">قيد الانتظار</span>',
        "rejected": '<span class="badge bad">مرفوض</span>',
        "no_stock": '<span class="badge bad">لا يوجد مخزون</span>',
    }
    return badges.get(status, e(status))


def payment_label(o):
    method = o["payment_method"]
    ref = o["payment_ref"] if "payment_ref" in o.keys() else None
    if method in ("crypto", "crypto_trc20"):
        return "🪙 USDT (TRC20)"
    if method == "crypto_bep20":
        return "🪙 USDT (BEP20)"
    if method == "haram":
        ref_part = f" — رقم: {e(ref)}" if ref else ""
        return f"🏦 حوالة الهرم{ref_part}"
    return "💳 شام كاش"


@app.route("/orders")
@require_auth
def orders_page():
    filters = _order_filters_from_request()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    offset = (page - 1) * PAGE_SIZE

    orders, total = db.get_orders(
        status=filters["status"],
        payment_method=filters["payment_method"],
        search=filters["search"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
        limit=PAGE_SIZE,
        offset=offset,
    )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    def option(value, label, current):
        selected = "selected" if current == value else ""
        return f'<option value="{e(value)}" {selected}>{e(label)}</option>'

    status_options = '<option value="">كل الحالات</option>' + "".join(
        option(v, label, filters["status"] or "") for v, label in ORDER_STATUSES
    )
    method_options = '<option value="">كل طرق الدفع</option>' + "".join(
        option(v, label, filters["payment_method"] or "") for v, label in ORDER_PAYMENT_METHODS
    )

    export_qs = "&".join(f"{k}={e(v)}" for k, v in filters.items() if v)

    filter_form = f"""
    <div class="card">
      <form method="get">
        <div class="row">
          <div>
            <label>الحالة</label>
            <select name="status">{status_options}</select>
          </div>
          <div>
            <label>طريقة الدفع</label>
            <select name="payment_method">{method_options}</select>
          </div>
        </div>
        <div class="row">
          <div>
            <label>بحث (اسم / يوزرنيم / آيدي)</label>
            <input name="search" value="{e(filters['search'] or '')}">
          </div>
          <div>
            <label>من تاريخ</label>
            <input type="date" name="date_from" value="{e(filters['date_from'] or '')}">
          </div>
          <div>
            <label>لتاريخ</label>
            <input type="date" name="date_to" value="{e(filters['date_to'] or '')}">
          </div>
        </div>
        <button class="btn" type="submit">فلترة</button>
        <a class="btn ghost" href="{url_for('orders_page')}">إلغاء الفلترة</a>
        <a class="btn ghost" href="{url_for('orders_export')}?{export_qs}">⬇️ تصدير CSV (حسب الفلترة الحالية)</a>
      </form>
    </div>
    """

    rows = ""
    for o in orders:
        uname = e(o["username"]) if o["username"] else "—"
        rows += f"""
        <tr>
          <td>#{o['id']}</td>
          <td>{e(o['full_name'])} (@{uname})</td>
          <td>{e(o['course_name'])}</td>
          <td>{payment_label(o)}</td>
          <td>{status_badge_html(o['status'])}</td>
          <td>{e(o['delivered_code']) if o['delivered_code'] else '—'}</td>
          <td class="muted">{e(str(o['created_at'])[:16].replace('T',' '))}</td>
        </tr>
        """

    if total_pages > 1:
        base_qs = "&".join(f"{k}={e(v)}" for k, v in filters.items() if v)
        prev_qs = f"page={page-1}" + (("&" + base_qs) if base_qs else "")
        next_qs = f"page={page+1}" + (("&" + base_qs) if base_qs else "")
        prev_btn = f'<a class="btn small ghost" href="?{prev_qs}">◀ السابق</a>' if page > 1 else ""
        next_btn = (
            f'<a class="btn small ghost" href="?{next_qs}">التالي ▶</a>' if page < total_pages else ""
        )
        pagination = (
            f'<div class="row" style="align-items:center;justify-content:space-between">'
            f'<span class="muted">صفحة {page} من {total_pages} — إجمالي {total} طلب</span>'
            f"<div>{prev_btn} {next_btn}</div></div>"
        )
    else:
        pagination = f'<div class="muted">إجمالي {total} طلب</div>'

    body = f"""
    {filter_form}
    <div class="card">
      {pagination}
      <table>
        <tr><th>#</th><th>الزبون</th><th>الكورس</th><th>طريقة الدفع</th><th>الحالة</th><th>الكود المسلَّم</th><th>التاريخ</th></tr>
        {rows if orders else '<tr><td colspan="7" class="muted">ما في طلبات مطابقة.</td></tr>'}
      </table>
    </div>
    """
    return render(body)


@app.route("/orders/export")
@require_auth
def orders_export():
    filters = _order_filters_from_request()
    orders, _total = db.get_orders(
        status=filters["status"],
        payment_method=filters["payment_method"],
        search=filters["search"],
        date_from=filters["date_from"],
        date_to=filters["date_to"],
        limit=1_000_000,
        offset=0,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["#", "الاسم", "يوزرنيم", "آيدي", "الكورس", "طريقة الدفع", "الحالة", "الكود المسلَّم", "التاريخ"]
    )
    for o in orders:
        writer.writerow(
            [
                o["id"],
                o["full_name"],
                o["username"] or "",
                o["user_id"],
                o["course_name"],
                o["payment_method"],
                o["status"],
                o["delivered_code"] or "",
                o["created_at"],
            ]
        )

    csv_data = "\ufeff" + buf.getvalue()  # BOM حتى إكسل يفتحه صح مع الحروف العربية
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


def run_web():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    db.init_db()
    run_web()
