#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نقطة دخول WSGI للاستخدام في الإنتاج (Gunicorn / uWSGI).

    gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app

يُستخدم فقط عند النشر؛ التشغيل المحلي يبقى: python3 app.py
"""

from app import app, db, create_directories, warn_dev_defaults
from migrate import run_migrations

warn_dev_defaults()

with app.app_context():
    run_migrations()
    create_directories()

__all__ = ['app']
