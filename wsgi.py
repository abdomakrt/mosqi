#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نقطة دخول WSGI — تُستخدم على PythonAnywhere (الملف: /home/khateebs/mosqi/wsgi.py)
أو محلياً مع Gunicorn:

    gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app

ملاحظات مهمة:
- يقرأ متغيرات البيئة من ملف .env المجاور قبل استيراد التطبيق،
  لأن SECRET_KEY و ADMIN_PASSWORD تُقرأ عند وقت الاستيراد.
- ينفّذ الترحيل (idempotent) ويهيّئ مجلد instance في كل إقلاع.
"""

import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def _load_env_file(path):
    """تحميل متغيرات البيئة من ملف .env (بدون استبدال الموجود مسبقاً)"""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


_load_env_file(os.path.join(PROJECT_DIR, '.env'))

from app import app, db, create_directories, warn_dev_defaults
from migrate import run_migrations

warn_dev_defaults()

with app.app_context():
    run_migrations()
    create_directories()

# PythonAnywhere يتوقع المتغير باسم 'application' أو 'app'
application = app
__all__ = ['app', 'application']
