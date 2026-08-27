# -*- coding: utf-8 -*-
"""
طبقة قاعدة البيانات المشتركة بين البوت ولوحة التحكم عبر الويب.
كل شي هون SQLite بسيط - نفس الملف بيستخدمه bot.py و admin_web.py.
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "bot_data.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price TEXT NOT NULL,
            shamcash_number TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            used_by INTEGER,
            used_at TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            full_name TEXT,
            course_id INTEGER NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'shamcash',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS used_tx (
            tx_hash TEXT PRIMARY KEY,
            order_id INTEGER,
            used_at TEXT NOT NULL
        );
        """
    )
    try:
        cur.execute("ALTER TABLE courses ADD COLUMN price_usdt REAL")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE orders ADD COLUMN payment_ref TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()

    cur.execute(
        """
        DELETE FROM codes
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY course_id, code
                           ORDER BY used DESC, id ASC
                       ) AS rn
                FROM codes
            )
            WHERE rn = 1
        )
        """
    )
    conn.commit()

    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_codes_unique ON codes(course_id, code)"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# كورسات
# ---------------------------------------------------------------------------
def get_active_courses():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM courses WHERE active = 1 ORDER BY id").fetchall()
    conn.close()
    return rows


def get_all_courses():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM courses ORDER BY id").fetchall()
    conn.close()
    return rows


def get_course(course_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    conn.close()
    return row


def create_course(name: str, price: str, shamcash_number: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO courses (name, price, shamcash_number) VALUES (?, ?, ?)",
        (name, price, shamcash_number),
    )
    conn.commit()
    course_id = cur.lastrowid
    conn.close()
    return course_id


def update_course(course_id: int, name: str, price: str, shamcash_number: str, price_usdt):
    conn = get_conn()
    conn.execute(
        "UPDATE courses SET name = ?, price = ?, shamcash_number = ?, price_usdt = ? WHERE id = ?",
        (name, price, shamcash_number, price_usdt, course_id),
    )
    conn.commit()
    conn.close()


def set_course_price_usdt(course_id: int, price):
    conn = get_conn()
    conn.execute("UPDATE courses SET price_usdt = ? WHERE id = ?", (price, course_id))
    conn.commit()
    conn.close()


def set_course_active(course_id: int, active: bool):
    conn = get_conn()
    conn.execute("UPDATE courses SET active = ? WHERE id = ?", (1 if active else 0, course_id))
    conn.commit()
    conn.close()


def toggle_course_active(course_id: int):
    course = get_course(course_id)
    if course:
        set_course_active(course_id, not course["active"])


# ---------------------------------------------------------------------------
# أكواد
# ---------------------------------------------------------------------------
def available_codes_count(course_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM codes WHERE course_id = ? AND used = 0", (course_id,)
    ).fetchone()
    conn.close()
    return row["c"]


def get_codes_for_course(course_id: int, only_unused: bool = False):
    conn = get_conn()
    if only_unused:
        rows = conn.execute(
            "SELECT * FROM codes WHERE course_id = ? AND used = 0 ORDER BY id", (course_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM codes WHERE course_id = ? ORDER BY id", (course_id,)
        ).fetchall()
    conn.close()
    return rows


def pull_unused_code(course_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM codes WHERE course_id = ? AND used = 0 ORDER BY id LIMIT 1",
        (course_id,),
    ).fetchone()
    conn.close()
    return row


def add_codes(course_id: int, codes: list) -> dict:
    """بيضيف الأكواد الجديدة بس بيتجاهل أي كود موجود مسبقاً لنفس الكورس (منع تكرار)."""
    conn = get_conn()
    added = 0
    skipped = 0
    for c in codes:
        cur = conn.execute(
            "INSERT OR IGNORE INTO codes (course_id, code) VALUES (?, ?)",
            (course_id, c),
        )
        if cur.rowcount:
            added += 1
        else:
            skipped += 1
    conn.commit()
    conn.close()
    return {"added": added, "skipped": skipped}

def delete_unused_code(code_id: int) -> bool:
    """يحذف كود بس إذا لسا غير مستخدم (حماية من حذف كود اتباع لزبون)."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM codes WHERE id = ? AND used = 0", (code_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted

def mark_code_used(code_id: int, user_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE codes SET used = 1, used_by = ?, used_at = ? WHERE id = ?",
        (user_id, datetime.utcnow().isoformat(), code_id),
    )
    conn.commit()
    conn.close()


def claim_code(course_id: int, user_id: int):
    """يحجز أول كود متاح لكورس معيّن ويعلّمه كمستخدم بعملية واحدة ذرية (atomic) —
    بتمنع إمكانية تسليم نفس الكود مرتين لو صار طلبين بنفس اللحظة تماماً."""
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM codes WHERE course_id = ? AND used = 0 ORDER BY id LIMIT 1",
            (course_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            conn.close()
            return None
        conn.execute(
            "UPDATE codes SET used = 1, used_by = ?, used_at = ? WHERE id = ? AND used = 0",
            (user_id, datetime.utcnow().isoformat(), row["id"]),
        )
        conn.commit()
        conn.close()
        return row
    except Exception:
        conn.rollback()
        conn.close()
        raise


# ---------------------------------------------------------------------------
# طلبات
# ---------------------------------------------------------------------------
def create_order(user_id, username, full_name, course_id, payment_method, payment_ref=None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO orders (user_id, username, full_name, course_id, payment_method, status, created_at, payment_ref) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
        (user_id, username, full_name, course_id, payment_method, datetime.utcnow().isoformat(), payment_ref),
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id


def get_order(order_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    return row


def get_recent_orders(limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT orders.*, courses.name AS course_name FROM orders "
        "JOIN courses ON courses.id = orders.course_id "
        "ORDER BY orders.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def set_order_status(order_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()


def get_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
    approved = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='approved'").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
    rejected = conn.execute("SELECT COUNT(*) c FROM orders WHERE status='rejected'").fetchone()["c"]
    crypto = conn.execute(
        "SELECT COUNT(*) c FROM orders WHERE payment_method='crypto' AND status='approved'"
    ).fetchone()["c"]
    conn.close()
    return {
        "total": total,
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
        "crypto": crypto,
    }


# ---------------------------------------------------------------------------
# عمليات كريبتو مستخدمة (منع تكرار استخدام نفس رقم العملية)
# ---------------------------------------------------------------------------
def is_tx_used(tx_hash: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM used_tx WHERE tx_hash = ?", (tx_hash,)).fetchone()
    conn.close()
    return row is not None


def mark_tx_used(tx_hash: str, order_id: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO used_tx (tx_hash, order_id, used_at) VALUES (?, ?, ?)",
        (tx_hash, order_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
