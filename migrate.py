#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكربت ترحيل بسيط وقابل للتكرار (Idempotent) لقاعدة بيانات SQLite.

الهدف:
- فحص بنية الجداول عبر PRAGMA table_info
- إضافة الأعمدة الناقصة فقط (بدون حذف أو إعادة تسمية)
- يمكن تشغيله أكثر من مرة بدون أي أثر جانبي

الاستخدام:
    python3 migrate.py
أو يُستدعى تلقائياً من app.py عند الإقلاع داخل app_context.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'instance', 'khutba_distribution.db')

# جداول يُنشأ إن لم تكن موجودة (إضافة فقط - لا حذف ولا إعادة تسمية)
CREATE_TABLES = [
    ("""CREATE TABLE IF NOT EXISTS app_setting (
            key TEXT NOT NULL,
            value TEXT,
            updated_at DATETIME,
            PRIMARY KEY (key)
        )""", 'app_setting'),
]

# الأعمدة المضافة: (اسم الجدول، [(اسم العمود, تعريف العمود), ...])
MIGRATIONS = {
    'khateb': [
        ('password_hash', 'TEXT'),
        ('profile_complete', 'INTEGER'),
        ('is_active', 'INTEGER DEFAULT 0'),
        ('pending_topic', 'VARCHAR(300)'),
        ('pending_topic_mode', 'VARCHAR(20)'),
        ('pending_topic_approved', 'INTEGER DEFAULT 0'),
        ('seasonal_topic', 'VARCHAR(300)'),
        ('seasonal_until', 'DATE'),
    ],
    'assignment': [
        ('replacement_of_id', 'INTEGER'),
    ],
}


def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cursor.fetchone() is not None


def _existing_columns(cursor, table_name):
    cursor.execute("PRAGMA table_info(%s)" % table_name)
    return [row[1] for row in cursor.fetchall()]


def run_migrations(db_path=DB_PATH, verbose=True):
    """تنفيذ الترحيل. يعيد قائمة الأعمدة التي تمت إضافتها فعلياً."""
    applied = []

    if not os.path.exists(db_path):
        if verbose:
            print("[migrate] قاعدة البيانات غير موجودة بعد: %s" % db_path)
        return applied

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # إنشاء الجداول الناقصة (إضافة فقط)
        for create_sql, table_name in CREATE_TABLES:
            if not _table_exists(cursor, table_name):
                cursor.execute(create_sql)
                applied.append('%s (table)' % table_name)
                if verbose:
                    print("[migrate] تم إنشاء الجدول %s" % table_name)

        for table_name, columns in MIGRATIONS.items():
            if not _table_exists(cursor, table_name):
                continue

            existing = _existing_columns(cursor, table_name)
            for column_name, column_def in columns:
                if column_name in existing:
                    continue
                cursor.execute(
                    "ALTER TABLE %s ADD COLUMN %s %s" % (table_name, column_name, column_def)
                )
                applied.append("%s.%s" % (table_name, column_name))
                if verbose:
                    print("[migrate] تمت إضافة العمود %s.%s" % (table_name, column_name))

        # ضمان قيمة افتراضية صحيحة للخطباء القدامى
        if _table_exists(cursor, 'khateb'):
            if 'is_active' in _existing_columns(cursor, 'khateb'):
                cursor.execute("UPDATE khateb SET is_active = 1 WHERE is_active IS NULL")
            # الخطباء المسجلون قبل هذا التحديث كانت بياناتهم جاهزة من المدير،
            # أما المنضمون الجدد فيُسجّلون بقيمة 0 صراحةً حتى يكملوا ملفهم.
            if 'profile_complete' in _existing_columns(cursor, 'khateb'):
                cursor.execute("UPDATE khateb SET profile_complete = 1 WHERE profile_complete IS NULL")
            if 'forbidden_mosques' in _existing_columns(cursor, 'khateb'):
                cursor.execute("UPDATE khateb SET forbidden_mosques = '[]' WHERE forbidden_mosques IS NULL")
            if 'mosques_visited' in _existing_columns(cursor, 'khateb'):
                cursor.execute("UPDATE khateb SET mosques_visited = '[]' WHERE mosques_visited IS NULL")

        conn.commit()
    finally:
        conn.close()

    if verbose:
        if applied:
            print("[migrate] اكتمل الترحيل، الأعمدة المضافة: %s" % ', '.join(applied))
        else:
            print("[migrate] لا حاجة لأي ترحيل - قاعدة البيانات محدّثة مسبقاً")

    return applied


if __name__ == '__main__':
    run_migrations()
