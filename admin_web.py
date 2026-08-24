# -*- coding: utf-8 -*-
"""
لوحة تحكم ويب بسيطة لإدارة الكورسات والأكواد بدل التعديل المباشر بـ DB Browser
أو كتابة أوامر بالبوت. محمية بـ Basic Auth (اسم مستخدم + كلمة سر من متغيرات البيئة).
"""
import os
from functools import wraps

from flask import Flask, request, redirect, url_for, Response, render_template_string

import db

app = Flask(__name__)

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
  input, textarea { width:100%; padding:9px 10px; border-radius:8px; border:1px solid var(--line);
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
    return render_template_string(BASE, body=body_html, flash=flash)


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
      <div class="stat"><b>{s['crypto']}</b><span class="muted">مدفوع بالكريبتو</span></div>
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
        crypto_price = f"{c['price_usdt']} USDT" if c["price_usdt"] else "—"
        rows += f"""
        <tr>
          <td>#{c['id']}</td>
          <td>{c['name']}</td>
          <td>{c['price']}</td>
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
COURSE_FORM = """
<div class="card">
  <form method="post">
    <div class="row">
      <div>
        <label>اسم الكورس</label>
        <input name="name" value="{name}" required>
      </div>
      <div>
        <label>السعر (نصي - للعرض بشام كاش، مثلاً 10$)</label>
        <input name="price" value="{price}" required>
      </div>
    </div>
    <div class="row">
      <div>
        <label>رقم شام كاش</label>
        <input name="shamcash_number" value="{shamcash_number}" required>
      </div>
      <div>
        <label>سعر الكريبتو بالدولار (اختياري - اتركه فاضي لو ما بدك تفعّل الكريبتو لهاد الكورس)</label>
        <input name="price_usdt" value="{price_usdt}">
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
        name = request.form["name"].strip()
        price = request.form["price"].strip()
        shamcash = request.form["shamcash_number"].strip()
        price_usdt_raw = request.form.get("price_usdt", "").strip()
        course_id = db.create_course(name, price, shamcash)
        if price_usdt_raw:
            db.set_course_price_usdt(course_id, float(price_usdt_raw))
        return redirect(url_for("dashboard"))

    body = "<div class='card'><h3>إضافة كورس جديد</h3></div>" + COURSE_FORM.format(
        name="", price="", shamcash_number="", price_usdt="", extra=""
    )
    return render(body)


@app.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@require_auth
def edit_course(course_id):
    course = db.get_course(course_id)
    if not course:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form["name"].strip()
        price = request.form["price"].strip()
        shamcash = request.form["shamcash_number"].strip()
        price_usdt_raw = request.form.get("price_usdt", "").strip()
        price_usdt = float(price_usdt_raw) if price_usdt_raw else None
        db.update_course(course_id, name, price, shamcash, price_usdt)
        return redirect(url_for("dashboard"))

    toggle_label = "إيقاف الكورس" if course["active"] else "تفعيل الكورس"
    extra = f"""
    <a class="btn ghost" href="{url_for('toggle_course_web', course_id=course_id)}">{toggle_label}</a>
    """
    body = f"<div class='card'><h3>تعديل: {course['name']}</h3></div>" + COURSE_FORM.format(
        name=course["name"],
        price=course["price"],
        shamcash_number=course["shamcash_number"],
        price_usdt=course["price_usdt"] or "",
        extra=extra,
    )
    return render(body)


@app.route("/courses/<int:course_id>/toggle")
@require_auth
def toggle_course_web(course_id):
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
            badge = f'<span class="badge bad">مستخدم (زبون #{c["used_by"]})</span>'
            action = ""
        else:
            badge = '<span class="badge good">متاح</span>'
            action = f"""<a class="btn small danger"
                href="{url_for('delete_code', course_id=course_id, code_id=c['id'])}"
                onclick="return confirm('متأكد بدك تحذف هاد الكود؟')">حذف</a>"""
        rows += f"<tr><td>{c['code']}</td><td>{badge}</td><td>{action}</td></tr>"

    body = f"""
    <div class="card">
      <h3>أكواد كورس: {course['name']}</h3>
      <form method="post">
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


@app.route("/courses/<int:course_id>/codes/<int:code_id>/delete")
@require_auth
def delete_code(course_id, code_id):
    db.delete_unused_code(code_id)
    return redirect(url_for("course_codes", course_id=course_id))


# ---------------------------------------------------------------------------
# الطلبات
# ---------------------------------------------------------------------------
@app.route("/orders")
@require_auth
def orders_page():
    orders = db.get_recent_orders(100)
    status_badge = {
        "approved": '<span class="badge good">مقبول</span>',
        "pending": '<span class="badge warn">قيد الانتظار</span>',
        "rejected": '<span class="badge bad">مرفوض</span>',
        "no_stock": '<span class="badge bad">لا يوجد مخزون</span>',
    }
    rows = ""
    for o in orders:
        rows += f"""
        <tr>
          <td>#{o['id']}</td>
          <td>{o['full_name']} (@{o['username'] or '—'})</td>
          <td>{o['course_name']}</td>
          <td>{'🪙 كريبتو' if o['payment_method'] == 'crypto' else '💳 شام كاش'}</td>
          <td>{status_badge.get(o['status'], o['status'])}</td>
          <td class="muted">{o['created_at'][:16].replace('T',' ')}</td>
        </tr>
        """
    body = f"""
    <div class="card">
      <table>
        <tr><th>#</th><th>الزبون</th><th>الكورس</th><th>طريقة الدفع</th><th>الحالة</th><th>التاريخ</th></tr>
        {rows if orders else '<tr><td colspan="6" class="muted">ما في طلبات بعد.</td></tr>'}
      </table>
    </div>
    """
    return render(body)


def run_web():
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    db.init_db()
    run_web()
