#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكربت ترحيل بسيط وقابل للتكرار (Idempotent) لقاعدة بيانات SQLite.
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'instance', 'khutba_distribution.db')

CREATE_TABLES = [
    ("""CREATE TABLE IF NOT EXISTS app_setting (
            key TEXT NOT NULL,
            value TEXT,
            updated_at DATETIME,
            PRIMARY KEY (key)
        )""", 'app_setting'),
]

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


def _ensure_base_schema(verbose=True):
    """إنشاء الجداول الأساسية عبر SQLAlchemy إذا لم تكن قاعدة البيانات مهيأة بعد."""
    try:
        from app import app, db
        os.makedirs(app.instance_path, exist_ok=True)
        with app.app_context():
            db.create_all()
        if verbose:
            print("[migrate] تم إنشاء الجداول الأساسية لقاعدة البيانات")
    except Exception as e:
        if verbose:
            print("[migrate] تنبيه أثناء تهيئة الجداول الأساسية: %s" % e)


def run_migrations(db_path=DB_PATH, verbose=True):
    """تنفيذ الترحيل. يعيد قائمة الأعمدة التي تمت إضافتها فعلياً."""
    applied = []

    if not os.path.exists(db_path):
        if verbose:
            print("[migrate] قاعدة البيانات غير موجودة بعد، جارٍ إنشاؤها: %s" % db_path)
        _ensure_base_schema(verbose=verbose)
        if not os.path.exists(db_path):
            return applied

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if not _table_exists(cursor, 'mosque'):
            conn.close()
            _ensure_base_schema(verbose=verbose)
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

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

        if _table_exists(cursor, 'khateb'):
            existing_khateb_cols = _existing_columns(cursor, 'khateb')
            if 'is_active' in existing_khateb_cols:
                cursor.execute("UPDATE khateb SET is_active = 1 WHERE is_active IS NULL")
            if 'profile_complete' in existing_khateb_cols:
                cursor.execute("UPDATE khateb SET profile_complete = 1 WHERE profile_complete IS NULL")
            if 'forbidden_mosques' in existing_khateb_cols:
                cursor.execute("UPDATE khateb SET forbidden_mosques = '[]' WHERE forbidden_mosques IS NULL")
            if 'mosques_visited' in existing_khateb_cols:
                cursor.execute("UPDATE khateb SET mosques_visited = '[]' WHERE mosques_visited IS NULL")

        if _table_exists(cursor, 'assignment'):
            # معالجة أي تعيينات مكررة نشطة لنفس الخطيب في نفس الجمعة (إلغاء المكرر والإبقاء على التعيين الأول)
            cursor.execute("""
                UPDATE assignment 
                SET status = 'cancelled' 
                WHERE id IN (
                    SELECT a.id FROM assignment a
                    WHERE a.status != 'cancelled'
                    AND EXISTS (
                        SELECT 1 FROM assignment b
                        WHERE b.khateb_id = a.khateb_id
                        AND b.week_date = a.week_date
                        AND b.status != 'cancelled'
                        AND b.id < a.id
                    )
                )
            """)

            # معالجة أي تعيينات مكررة نشطة لنفس المسجد في نفس الجمعة
            cursor.execute("""
                UPDATE assignment 
                SET status = 'cancelled' 
                WHERE id IN (
                    SELECT a.id FROM assignment a
                    WHERE a.status != 'cancelled'
                    AND EXISTS (
                        SELECT 1 FROM assignment b
                        WHERE b.mosque_id = a.mosque_id
                        AND b.week_date = a.week_date
                        AND b.status != 'cancelled'
                        AND b.id < a.id
                    )
                )
            """)

            # إنشاء فهارس فريدة لمنع تكرار توزيع الخطيب أو المسجد في نفس الجمعة مستقبلاً
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_assignment_khateb_active_week 
                ON assignment (khateb_id, week_date) 
                WHERE status != 'cancelled'
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_assignment_mosque_active_week 
                ON assignment (mosque_id, week_date) 
                WHERE status != 'cancelled'
            """)

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
