#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام توزيع الخطباء على المساجد
作者: MiniMax Agent
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import inspect as sa_inspect
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Dict, Optional
from urllib.parse import quote

# مسار مجلد المشروع (لاستيراد migrate)
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

app = Flask(__name__)

# ============================================
# الإعدادات ومفاتيح التشغيل
# ============================================
# المفاتيح تُقرأ من متغيرات البيئة. القيم الافتراضية للتطوير فقط.
DEV_SECRET_KEY = 'خطبة_توزيع_مفاتيح_سرية_2025'
DEV_ADMIN_PASSWORD = 'admin123'

SECRET_KEY = os.environ.get('SECRET_KEY') or DEV_SECRET_KEY
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or DEV_ADMIN_PASSWORD

app.secret_key = SECRET_KEY
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///khutba_distribution.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
# أمان الجلسة
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
app.config['PERMANENT_SESSION_LIFETIME'] = 12 * 3600

db = SQLAlchemy(app)


def warn_dev_defaults():
    """تحذير في السجل عند استخدام القيم الافتراضية للتطوير"""
    if not os.environ.get('SECRET_KEY'):
        print('[تحذير] متغير البيئة SECRET_KEY غير مضبوط - يُستخدم مفتاح تطوير افتراضي. غيّره قبل النشر!')
    if not os.environ.get('ADMIN_PASSWORD'):
        print('[تحذير] متغير البيئة ADMIN_PASSWORD غير مضبوط - تُستخدم كلمة مرور تطوير افتراضية. غيّرها قبل النشر!')

# ============================================
# المصادقة والصلاحيات (دوران فقط: مدير / خطيب)
# ============================================

def normalize_phone(phone):
    """توحيد صيغة رقم الجوال (مثال: 0501234567 أو +966501234567 -> 966501234567)"""
    if not phone:
        return ''
    digits = re.sub(r'\D', '', str(phone))
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('966'):
        return digits
    if digits.startswith('0'):
        return '966' + digits[1:]
    if len(digits) == 9 and digits.startswith('5'):
        return '966' + digits
    return digits


def whatsapp_link(phone, name, message=None):
    """رابط واتساب جاهز (بدون أي API) لطلب موضوع جديد"""
    number = normalize_phone(phone)
    if not number:
        return ''
    if not message:
        message = (
            'السلام عليكم الشيخ %s،\n'
            'لقد انتهيت من جميع المساجد بالموضوع الحالي، '
            'فيرجى إرسال موضوع خطبة جديد للاعتماد. شكراً لك.\n'
            'نظام توزيع الخطباء' % name
        )
    return 'https://wa.me/%s?text=%s' % (number, quote(message))


ADMIN_PASSWORD_KEY = 'admin_password_hash'

# أوضاع طلب الموضوع الجديد من الخطيب
TOPIC_MODE_RESET = 'reset'              # إعادة التعيين على جميع المساجد من جديد
TOPIC_MODE_AFTER_CURRENT = 'after_current'  # الموضوع القادم بعد إنهاء المساجد الحالية

# مناسبات إسلامية مقترحة للموضوع الموسمي (يمكن للخطيب كتابة غيرها)
SEASONAL_OCCASIONS = [
    'رأس السنة الهجرية',
    'هجرة النبي ﷺ',
    'يوم عرفة',
    'العشر من ذي الحجة',
    'عاشوراء',
    'المولد النبوي',
    'ليلة القدر',
    'الأيام العشر من رمضان',
    'عيد الفطر',
    'عيد الأضحى',
]


def khateb_upcoming_sermon_dates(khateb):
    """تواريخ خطب الخطيب القادمة (تعيناته غير الملغاة من اليوم فصاعداً)"""
    assignments = Assignment.query.filter(
        Assignment.khateb_id == khateb.id,
        Assignment.week_date >= date.today(),
        Assignment.status != 'cancelled'
    ).order_by(Assignment.week_date.asc()).all()
    return [a.week_date for a in assignments]


def seasonal_window(khateb, weeks):
    """حساب نافذة الموضوع الموسمي: (البداية، النهاية)

    النهاية = تاريخ آخر خطبة مشمولة (خطبة واحدة أو خطبتان من خطب الخطيب القادمة).
    إن لم تكن له تعيينات بعد، تُحسب على أساس الجمعة التي يوزّع عليها النظام افتراضياً.
    """
    try:
        count = int(weeks)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(2, count))

    engine = DistributionEngine()
    default_friday = engine.get_next_friday(engine.get_current_friday())
    upcoming = khateb_upcoming_sermon_dates(khateb)

    if len(upcoming) >= count:
        end = upcoming[count - 1]
    elif upcoming:
        end = max(upcoming[-1], default_friday + timedelta(days=7 * (count - 1)))
    else:
        end = default_friday + timedelta(days=7 * (count - 1))

    start = upcoming[0] if upcoming else default_friday
    return start, end


def apply_seasonal_to_assignments(khateb, topic, first_friday, last_friday):
    """تحديث موضوع التعيينات المستقبلية للخطيب ضمن نافذة الموسم فقط"""
    assignments = Assignment.query.filter(
        Assignment.khateb_id == khateb.id,
        Assignment.week_date >= first_friday,
        Assignment.week_date <= last_friday,
        Assignment.status != 'cancelled'
    ).all()

    for assignment in assignments:
        assignment.khutba_topic = topic
        db.session.add(assignment)
    return len(assignments)


def activate_new_topic(khateb, topic):
    """تفعيل موضوع جديد للخطيب: تعيين الموضوع + تصفير المساجد المزارة"""
    khateb.current_topic = topic
    khateb.pending_topic = None
    khateb.pending_topic_mode = None
    khateb.pending_topic_approved = 0
    khateb.mosques_visited = json.dumps([])
    khateb.last_topic_change = datetime.utcnow()
    # الموضوع الجديد هو البداية الجديدة => يُلغى أي موضوع موسمي قائم
    khateb.seasonal_topic = None
    khateb.seasonal_until = None
    db.session.add(khateb)
    return khateb


def maybe_activate_queued_topic(khateb):
    """إذا كان هناك موضوع معتمد مجدول (بعد_current) وتم إنهاء جميع المساجد => يُفعَّل تلقائياً"""
    if not khateb.pending_topic:
        return False
    if khateb.pending_topic_mode != TOPIC_MODE_AFTER_CURRENT:
        return False
    if not khateb.pending_topic_approved:
        return False

    all_mosques = set(m.id for m in Mosque.query.all())
    if not all_mosques:
        return False
    forbidden = set(khateb.get_forbidden_mosques_list())
    allowed = all_mosques - forbidden
    if not allowed:
        return False
    visited = set(khateb.get_visited_mosques_list())
    if not allowed.issubset(visited):
        return False

    activate_new_topic(khateb, khateb.pending_topic)
    db.session.commit()
    return True


def verify_admin_password(password):
    """التحقق من كلمة مرور المدير.

    - إذا كانت هناك كلمة مرور مخزّنة في قاعدة البيانات (غيّرها من الإعدادات) فهي المعتمدة
    - وإلا تُستخدم كلمة المرور من متغير البيئة ADMIN_PASSWORD
    """
    if not password:
        return False

    stored = None
    try:
        stored = AppSetting.get(ADMIN_PASSWORD_KEY)
    except Exception:
        stored = None

    if stored:
        try:
            return check_password_hash(stored, password)
        except Exception:
            return False

    return password == ADMIN_PASSWORD


def admin_password_source():
    """مصدر كلمة مرور المدير الحالية: 'database' أو 'environment'"""
    try:
        return 'database' if AppSetting.get(ADMIN_PASSWORD_KEY) else 'environment'
    except Exception:
        return 'environment'


# ---------- إدارة الجلسة ----------

def is_logged_in():
    return bool(session.get('role'))


def current_role():
    return session.get('role')


def is_admin():
    return session.get('role') == 'admin'


def current_khateb():
    """الخطيب الذي سجّل دخوله حالياً (إن كان معروفاً)"""
    if session.get('role') != 'khateb':
        return None
    return Khateb.query.get(session.get('khateb_id'))


def login_admin():
    session.clear()
    session['role'] = 'admin'


def login_khateb(khateb_id):
    session.clear()
    session['role'] = 'khateb'
    session['khateb_id'] = khateb_id


def logout_session():
    session.clear()


# ---------- الـ Decorators ----------

def _wants_json():
    return request.path.startswith('/api/') or request.is_json


def login_required(f):
    """يتطلب تسجيل دخول (مدير أو خطيب)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_logged_in():
            if _wants_json():
                return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
            flash('يرجى تسجيل الدخول للمتابعة', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """يتطلب صلاحية المدير"""
    @wraps(f)
    def decorated(*args, **kwargs):
        role = session.get('role')
        if not role:
            if _wants_json():
                return jsonify({'success': False, 'message': 'يجب تسجيل الدخول أولاً'}), 401
            flash('يرجى تسجيل الدخول للمتابعة', 'error')
            return redirect(url_for('login'))
        if role != 'admin':
            if _wants_json():
                return jsonify({'success': False, 'message': 'هذه الصفحة متاحة للمدير فقط'}), 403
            flash('هذه الصفحة متاحة للمدير فقط', 'error')
            return redirect(url_for('my'))
        return f(*args, **kwargs)
    return decorated


# ============================================
# نماذج قاعدة البيانات
# ============================================

class Mosque(db.Model):
    """نموذج المسجد"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    capacity = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignments = db.relationship('Assignment', backref='mosque', lazy=True)

    def __repr__(self):
        return f'<Mosque {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
                'capacity': self.capacity,
                'created_at': self.created_at
        }



@app.route('/assignment/<int:assignment_id>/confirm', methods=['POST'])
@admin_required
def api_confirm_assignment(assignment_id):
    """خمسة: تأكيد التعيين من قبل الخطيب"""
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'success': False, 'message': 'التعيين غير موجود'}), 404

    # التحقق من عدم وجود تعيين نشط آخر لنفس الخطيب في نفس الجمعة
    dup = Assignment.query.filter(
        Assignment.khateb_id == assignment.khateb_id,
        Assignment.week_date == assignment.week_date,
        Assignment.status != 'cancelled',
        Assignment.id != assignment.id
    ).first()
    if dup:
        return jsonify({'success': False, 'message': 'الخطيب لديه تعيين نشط آخر في نفس هذا الأسبوع بالفعل'}), 400

    # Mark as confirmed and update visited mosques for khateb
    assignment.status = 'confirmed'
    db.session.add(assignment)

    # تحديث قائمة المساجد المزارة للخطيب
    khateb = Khateb.query.get(assignment.khateb_id)
    visited = khateb.get_visited_mosques_list()
    if assignment.mosque_id not in visited:
        visited.append(assignment.mosque_id)
        khateb.mosques_visited = json.dumps(visited)
        db.session.add(khateb)

    db.session.commit()
    return jsonify({'success': True, 'message': 'تم تأكيد التعيين'})


class Khateb(db.Model):
    """نموذج الخطيب"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    current_topic = db.Column(db.String(300), default="موضوع افتراضي")
    last_topic_change = db.Column(db.DateTime, default=datetime.utcnow)
    mosques_visited = db.Column(db.Text)  # JSON array of mosque IDs
    rest_weeks = db.Column(db.Integer, default=0)  # أسابيع الراحة
    availability_mode = db.Column(db.String(20), default='always')  # always / alternate
    alternate_offset = db.Column(db.Integer, default=0)
    forbidden_mosques = db.Column(db.Text, default='[]')  # JSON array of mosque IDs
    password_hash = db.Column(db.String(255))  # كلمة مرور الخطيب المشفّرة
    # بلا default عمداً: الأسطر القديمة تبقى NULL (ملفهم جاهز) والجديد يُضبط على 0 صراحةً
    profile_complete = db.Column(db.Integer)
    is_active = db.Column(db.Integer, default=0)  # 1 = مفعّل، 0 = في انتظار موافقة المدير
    pending_topic = db.Column(db.String(300), nullable=True)  # موضوع مقترح بانتظار اعتماد المدير
    pending_topic_mode = db.Column(db.String(20), nullable=True)  # reset = من جديد / after_current = بعد إنهاء المساجد
    pending_topic_approved = db.Column(db.Integer, default=0)  # 1 = معتمد ومجدول للتفعيل بعد إنهاء المساجد
    seasonal_topic = db.Column(db.String(300), nullable=True)  # موضوع موسمي مؤقت (يعلو على الموضوع الأساسي)
    seasonal_until = db.Column(db.Date, nullable=True)  # آخر جمعة يُطبَّق فيها الموضوع الموسمي
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignments = db.relationship('Assignment', backref='khateb', lazy=True)

    def __repr__(self):
        return f'<Khateb {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'current_topic': self.current_topic,
            'rest_weeks': self.rest_weeks,
            'availability_mode': self.availability_mode or 'always',
            'forbidden_mosques': json.loads(self.forbidden_mosques or '[]'),
            'mosques_visited': json.loads(self.mosques_visited or '[]')
        }

    def get_visited_mosques_list(self):
        """إرجاع قائمة المساجد المزارة"""
        return json.loads(self.mosques_visited or '[]')

    def has_profile(self):
        """هل أكمل الخطيب ملفه؟ (موضوع الخطبة + المساجد المستثناة + نظام التوفر)

        الخطباء المسجلون قبل هذه الميزة ملفهم جاهز تلقائياً
        (قيمة profile_complete = NULL تُعامل كمكتمل).
        """
        if self.profile_complete is None:
            return True
        return bool(self.profile_complete)

    def is_seasonal_active(self):
        """هل يوجد موضوع موسمي ساري الآن؟"""
        if not self.seasonal_topic or not self.seasonal_until:
            return False
        return date.today() <= self.seasonal_until

    def get_effective_topic(self):
        """الموضوع المعروض للخطيب: الموضوع الموسمي إن كان سارياً، وإلا الموضوع الأساسي"""
        if self.is_seasonal_active():
            return self.seasonal_topic
        return self.current_topic

    def get_forbidden_mosques_list(self):
        """إرجاع قائمة المساجد المستثناة"""
        return json.loads(self.forbidden_mosques or '[]')


class Assignment(db.Model):
    """نموذج التعيين الأسبوعي"""
    __table_args__ = (
        db.Index(
            'idx_assignment_khateb_active_week',
            'khateb_id', 'week_date',
            unique=True,
            sqlite_where=db.text("status != 'cancelled'")
        ),
        db.Index(
            'idx_assignment_mosque_active_week',
            'mosque_id', 'week_date',
            unique=True,
            sqlite_where=db.text("status != 'cancelled'")
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    khateb_id = db.Column(db.Integer, db.ForeignKey('khateb.id'), nullable=False)
    mosque_id = db.Column(db.Integer, db.ForeignKey('mosque.id'), nullable=False)
    week_date = db.Column(db.Date, nullable=False)  # تاريخ الجمعة
    khutba_topic = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='confirmed')  # pending, confirmed, completed, cancelled
    replacement_of_id = db.Column(db.Integer, nullable=True)  # التعيين الأصلي الذي حُلّ محلّه هذا التعيين
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Assignment {self.khateb_id} -> {self.mosque_id} on {self.week_date}>'

    def to_dict(self):
        return {
            'id': self.id,
            'khateb_name': self.khateb.name if self.khateb else 'غير محدد',
            'mosque_name': self.mosque.name if self.mosque else 'غير محدد',
            'week_date': self.week_date.strftime('%Y-%m-%d'),
            'khutba_topic': self.khutba_topic,
            'status': self.status
        }


class WeeklySchedule(db.Model):
    """نموذج الجدول الأسبوعي"""
    id = db.Column(db.Integer, primary_key=True)
    week_date = db.Column(db.Date, nullable=False, unique=True)
    khateb_ids = db.Column(db.Text)  # JSON array of khateb IDs for this week
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<WeeklySchedule {self.week_date}>'

    def to_dict(self):
        return {
            'id': self.id,
            'week_date': self.week_date.strftime('%Y-%m-%d'),
            'khateb_count': len(json.loads(self.khateb_ids or '[]'))
        }


class AppSetting(db.Model):
    """إعدادات التطبيق (مفتاح / قيمة) - مثل كلمة مرور المدير"""
    __tablename__ = 'app_setting'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AppSetting {self.key}>'

    @staticmethod
    def get(key, default=None):
        row = AppSetting.query.get(key)
        return row.value if row is not None else default

    @staticmethod
    def set(key, value):
        row = AppSetting.query.get(key)
        if row is None:
            row = AppSetting(key=key)
        row.value = value
        row.updated_at = datetime.utcnow()
        db.session.add(row)
        db.session.commit()
        return row

    @staticmethod
    def delete(key):
        row = AppSetting.query.get(key)
        if row is not None:
            db.session.delete(row)
            db.session.commit()
            return True
        return False


# ============================================
# خوارزمية التوزيع الذكية
# ============================================

class DistributionEngine:
    """محرك التوزيع الذكي للخطباء على المساجد"""

    def __init__(self):
        self.rest_cycle_weeks = 3  # كل 3 أسابيع أسبوع راحة

    def get_current_friday(self):
        """الحصول على تاريخ الجمعة الحالية"""
        today = date.today()
        days_ahead = 4 - today.weekday()  # Friday = 4
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        # return a date object for the upcoming Friday
        return today + timedelta(days=days_ahead)

    def get_next_friday(self, friday_date):
        """الحصول على الجمعة التالية"""
        return friday_date + timedelta(days=7)

    def get_available_khutbas(self, target_friday=None):
        """الحصول على قائمة الخطباء المتاحين للتوزيع

        يُستبعد:
        - الخطباء غير المعتمدين من المدير (is_active = 0)
        - الخطباء الذين لم يكملوا ملفهم (موضوع الخطبة + المساجد المزارة + نظام التوفر)
        - الخطباء الذين أنهوا جميع المساجد وبانتظار موضوع جديد للدورة القادمة
        """
        # حسب طلب المستخدم: تجاهل نظام الراحة عند التوزيع الأولي
        khutbas = Khateb.query.all()
        available = []
        week_index = None
        if target_friday:
            # استخدام رقم الأسبوع لتحديد دورية "أسبوع متاح / أسبوع غير متاح"
            week_index = target_friday.isocalendar()[1] + target_friday.year * 100
        for khateb in khutbas:
            # معتمد من المدير فقط
            if khateb.is_active not in (1, True):
                continue
            # يجب أن يكون قد أكمل ملفه (الخطباء القدامى ملفهم جاهز)
            if not khateb.has_profile():
                continue

            # تفعيل أي موضوع مجدول تلقائياً إذا كان الخطيب قد أنهى جميع مساجده
            maybe_activate_queued_topic(khateb)

            # إذا أنهى جميع المساجد المتاحة له ولم يحدد موضوعاً جديداً => لا يدخل التوزيع حتى يغير الموضوع
            if self.should_change_topic(khateb.id):
                continue

            mode = khateb.availability_mode or 'always'
            if mode == 'alternate' and week_index is not None:
                offset = khateb.alternate_offset or 0
                if ((week_index + offset) % 2) == 1:
                    continue
            available.append(khateb)
        return available

    def update_rest_weeks(self):
        """تحديث أسابيع الراحة للخطباء"""
        all_khutbas = Khateb.query.all()
        for khateb in all_khutbas:
            # العثور على آخر مرة تم تعيين الخطيب
            last_assignment = Assignment.query.filter_by(khateb_id=khateb.id)\
                .order_by(Assignment.week_date.desc()).first()
            
            if last_assignment:
                # حساب عدد الأسابيع منذ آخر تعيين
                weeks_since = (datetime.now().date() - last_assignment.week_date).days // 7
                
                # إذا مر أكثر من فترة الراحة، أضف أسبوع راحة
                if weeks_since >= self.rest_cycle_weeks:
                    khateb.rest_weeks = 1
                elif weeks_since < self.rest_cycle_weeks - 1:
                    khateb.rest_weeks = 0
        db.session.commit()

    def get_unvisited_mosques(self, khateb_id):
        """الحصول على المساجد غير المزارة للخطيب"""
        khateb = Khateb.query.get(khateb_id)
        visited_mosques = set(khateb.get_visited_mosques_list())
        all_mosques = set([m.id for m in Mosque.query.all()])
        unvisited = all_mosques - visited_mosques
        return list(unvisited)

    def distribute_for_week(self, target_friday):
        """توزيع الخطباء على المساجد لجمعة معينة"""
        # السماح بإعادة التوزيع تلقائياً (حذف التعيينات والجدول السابق لهذا الأسبوع)
        existing_assignments = Assignment.query.filter_by(week_date=target_friday).all()
        if existing_assignments:
            for a in existing_assignments:
                db.session.delete(a)
            db.session.flush()
        existing_schedule = WeeklySchedule.query.filter_by(week_date=target_friday).first()
        if existing_schedule:
            db.session.delete(existing_schedule)
            db.session.flush()

        # تحديث أسابيع الراحة
        self.update_rest_weeks()

        # الحصول على الخطباء المتاحين
        available_khutbas = self.get_available_khutbas(target_friday)
        mosques = Mosque.query.all()

        if len(available_khutbas) == 0:
            waiting = [k for k in Khateb.query.all() if k.is_active in (1, True) and k.has_profile() and self.should_change_topic(k.id)]
            if waiting:
                return False, f"لا يوجد خطباء متاحون: ({', '.join(k.name for k in waiting)}) أنهوا جميع المساجد ويجب تحديد موضوع جديد لبدء الدورة التالية"
            return False, "لا يوجد خطباء متاحون حالياً"

        if len(mosques) == 0:
            return False, "لا يوجد مساجد مسجلة"

        assignments = []
        
        # توزيع الذكي: كل خطيب يذهب لمسجد لم يزره من قبل
        used_mosques = set()
        
        for khateb in available_khutbas:
            unvisited = self.get_unvisited_mosques(khateb.id)
            forbidden = set(khateb.get_forbidden_mosques_list())
            
            # تصفية المساجد المستخدمة بالفعل هذا الأسبوع والمساجد المستثناة
            available_mosques = [m_id for m_id in unvisited if m_id not in used_mosques and m_id not in forbidden]
            
            if available_mosques:
                # اختيار مسجد عشوائي من المتاحة
                import random
                chosen_mosque_id = random.choice(available_mosques)
                used_mosques.add(chosen_mosque_id)
                
                # إنشاء التعيين
                assignment = Assignment(
                    khateb_id=khateb.id,
                    mosque_id=chosen_mosque_id,
                    week_date=target_friday,
                    khutba_topic=khateb.get_effective_topic()
                )
                assignments.append(assignment)
        
        # إذا لم تُوزع جميع المساجد، وزّع الخطباء الذين لم يُعيّنوا بعد
        remaining_mosques = [m for m in mosques if m.id not in used_mosques]
        assigned_khatebs = set(a.khateb_id for a in assignments)
        unassigned_khatebs = [k for k in available_khutbas if k.id not in assigned_khatebs]

        if remaining_mosques and unassigned_khatebs:
            for mosque, khateb in zip(remaining_mosques, unassigned_khatebs):
                forbidden = set(khateb.get_forbidden_mosques_list())
                if mosque.id in forbidden:
                    continue
                assignment = Assignment(
                    khateb_id=khateb.id,
                    mosque_id=mosque.id,
                    week_date=target_friday,
                    khutba_topic=khateb.get_effective_topic()
                )
                assignments.append(assignment)
                used_mosques.add(mosque.id)

        # حفظ التعيينات
        db.session.add_all(assignments)
        
        # حفظ الجدول الأسبوعي
        week_schedule = WeeklySchedule(
            week_date=target_friday,
            khateb_ids=json.dumps([a.khateb_id for a in assignments])
        )
        db.session.add(week_schedule)
        
        db.session.commit()

        return True, f"تم إنشاء {len(assignments)} تعيين بنجاح"

    def update_khateb_mosques_visited(self, khateb_id, mosque_id):
        """تحديث قائمة المساجد المزارة للخطيب"""
        khateb = Khateb.query.get(khateb_id)
        visited = khateb.get_visited_mosques_list()
        
        if mosque_id not in visited:
            visited.append(mosque_id)
            khateb.mosques_visited = json.dumps(visited)
            db.session.commit()
            
            # فحص إذا انتهى من جميع المساجد
            if len(visited) >= len(Mosque.query.all()):
                return True, "انتهى من جميع المساجد - يحتاج تغيير الموضوع"
        
        return False, "تم التحديث بنجاح"

    def should_change_topic(self, khateb_id):
        """فحص إذا كان يجب على الخطيب تغيير الموضوع (أنهى دورة كاملة على جميع المساجد المتاحة له)"""
        khateb = Khateb.query.get(khateb_id)
        if not khateb:
            return False
        all_mosques = set(m.id for m in Mosque.query.all())
        forbidden = set(khateb.get_forbidden_mosques_list())
        allowed_mosques = all_mosques - forbidden

        if not allowed_mosques:
            return False
        visited = set(khateb.get_visited_mosques_list())
        return allowed_mosques.issubset(visited)

    def reset_khateb_mosques(self, khateb_id):
        """إعادة تعيين قائمة المساجد للخطيب"""
        khateb = Khateb.query.get(khateb_id)
        khateb.mosques_visited = json.dumps([])
        khateb.last_topic_change = datetime.utcnow()
        db.session.commit()
        return True, "تم إعادة تعيين قائمة المساجد"


# ============================================
# إضافة البيانات الأولية
# ============================================

def init_sample_data():
    """إضافة بيانات عينة للاختبار"""
    # مساجد العينة
    mosques_data = [
        {"name": "مسجد النور", "address": "شارع الرياض، حي النور", "capacity": 300},
        {"name": "مسجد الهدى", "address": "شارع الأمان، حي السلام", "capacity": 250},
        {"name": "مسجد الفرقان", "address": "شارع الإيمان، حي التوبة", "capacity": 400},
        {"name": "مسجد التقوى", "address": "شارع الخشوع، حي الورع", "capacity": 200},
        {"name": "مسجد القرآن", "address": "شارع الذكر، حي الختم", "capacity": 350},
        {"name": "مسجد السنة", "address": "شارع السلف، حي التقليد", "capacity": 280},
    ]

    # خطباء العينة
    khutbas_data = [
        {"name": "الشيخ أحمد محمد", "phone": "0501234567", "topic": "أهمية الصبر في الحياة"},
        {"name": "الشيخ فاطمة علي", "phone": "0502345678", "topic": "الإحسان في التعامل"},
        {"name": "الشيخ محمد سعد", "phone": "0503456789", "topic": "التوبة والأوبة"},
        {"name": "الشيخ علي حسن", "phone": "0504567890", "topic": "الشكر والامتنان"},
        {"name": "الشيخ سارة أحمد", "phone": "0505678901", "topic": "الحجاب والحشمة"},
        {"name": "الشيخ خالد Yusuf", "phone": "0506789012", "topic": "الجهاد في سبيل الله"},
        {"name": "الشيخ عبدالله محمد", "phone": "0507890123", "topic": "العدل والقسط"},
        {"name": "الشيخ رنا سالم", "phone": "0508901234", "topic": "البر بالوالدين"},
    ]

    # إضافة المساجد
    for mosque_data in mosques_data:
        if not Mosque.query.filter_by(name=mosque_data["name"]).first():
            mosque = Mosque(**mosque_data)
            db.session.add(mosque)

    # إضافة الخطباء
    for khateb_data in khutbas_data:
        if not Khateb.query.filter_by(name=khateb_data["name"]).first():
            khateb = Khateb(
                name=khateb_data["name"],
                phone=khateb_data["phone"],
                current_topic=khateb_data["topic"],
                mosques_visited=json.dumps([]),
                profile_complete=1,
                is_active=1
            )
            db.session.add(khateb)

    db.session.commit()


# ============================================
# Routes - صفحات الويب
# ============================================

@app.route('/')
@admin_required
def index():
    """الصفحة الرئيسية"""
    total_mosques = Mosque.query.count()
    total_khutbas = Khateb.query.count()
    total_assignments = Assignment.query.count()
    this_week_assignments = Assignment.query.filter_by(
        week_date=DistributionEngine().get_current_friday()
    ).count()
    
    stats = {
        'total_mosques': total_mosques,
        'total_khutbas': total_khutbas,
        'total_assignments': total_assignments,
        'this_week_assignments': this_week_assignments
    }
    
    return render_template('index.html', stats=stats)


@app.route('/mosques')
@admin_required
def mosques():
    """صفحة إدارة المساجد"""
    mosques = Mosque.query.all()
    # Convert SQLAlchemy models to dictionaries for JSON serialization
    mosque_list = [mosque.to_dict() for mosque in mosques]
    # إجمالي الطاقة الاستيعابية (تجاهل المساجد بدون سعة مسجلة)
    total_capacity = sum(m.capacity or 0 for m in mosques)
    return render_template('mosques.html', mosques=mosque_list, total_capacity=total_capacity)


@app.route('/mosque/add', methods=['POST'])
@admin_required
def add_mosque():
    """إضافة مسجد جديد"""
    name = request.form.get('name')
    address = request.form.get('address')
    capacity = request.form.get('capacity', type=int)
    
    if not name:
        flash('اسم المسجد مطلوب', 'error')
        return redirect(url_for('mosques'))
    
    mosque = Mosque(name=name, address=address, capacity=capacity)
    db.session.add(mosque)
    db.session.commit()
    
    flash('تم إضافة المسجد بنجاح', 'success')
    return redirect(url_for('mosques'))


@app.route('/khutbas')
@admin_required
def khutbas():
    """صفحة إدارة الخطباء"""
    khutbas = Khateb.query.all()
    mosques = Mosque.query.all()
    current_friday = DistributionEngine().get_current_friday()
    return render_template('khutbas.html', khutbas=khutbas, mosques=mosques, current_friday=current_friday)


@app.route('/khateb/add', methods=['POST'])
@admin_required
def add_khateb():
    """إضافة خطيب جديد"""
    name = request.form.get('name')
    phone = request.form.get('phone')
    topic = request.form.get('topic', 'موضوع افتراضي')
    visited_mosques = request.form.getlist('visited_mosques')
    availability_mode = request.form.get('availability_mode', 'always')
    alternate_offset = request.form.get('alternate_offset', 0, type=int)
    forbidden_mosques = request.form.getlist('forbidden_mosques')
    
    if not name:
        flash('اسم الخطيب مطلوب', 'error')
        return redirect(url_for('khutbas'))
    
    khateb = Khateb(
        name=name,
        phone=phone,
        current_topic=topic,
        mosques_visited=json.dumps([int(m) for m in visited_mosques]),
        availability_mode=availability_mode,
        alternate_offset=alternate_offset,
        forbidden_mosques=json.dumps([int(m) for m in forbidden_mosques]),
        profile_complete=1,
        is_active=1,
    )
    db.session.add(khateb)
    db.session.commit()
    
    flash('تم إضافة الخطيب %s بنجاح. سيظهر في التوزيع تلقائياً.' % name, 'success')
    return redirect(url_for('khutbas'))


@app.route('/distribution')
@admin_required
def distribution():
    """صفحة التوزيع الأسبوعي"""
    engine = DistributionEngine()
    current_friday = engine.get_current_friday()
    
    # الحصول على التعيينات لهذا الأسبوع
    assignments = Assignment.query.filter_by(week_date=current_friday)\
        .order_by(Assignment.mosque_id).all()
    
    # تحويل التعيينات إلى قواميس
    assignment_dicts = [assignment.to_dict() for assignment in assignments]
    
    # إحصائيات
    total_mosques = Mosque.query.count()
    assigned_mosques = len(set(a.mosque_id for a in assignments))
    remaining_mosques = total_mosques - assigned_mosques
    
    distribution_stats = {
        'current_friday': current_friday,
        'total_assignments': len(assignments),
        'assigned_mosques': assigned_mosques,
        'remaining_mosques': remaining_mosques,
        'total_mosques': total_mosques
    }
    
    return render_template('distribution.html', 
                         assignments=assignment_dicts, 
                         stats=distribution_stats)


@app.route('/distribution/create', methods=['POST'])
@admin_required
def create_distribution():
    """إنشاء توزيع جديد للجمعة القادمة"""
    engine = DistributionEngine()
    target_date_str = request.form.get('target_date')
    
    if target_date_str:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    else:
        target_date = engine.get_next_friday(engine.get_current_friday())
    
    success, message = engine.distribute_for_week(target_date)
    
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')
    
    return jsonify({'success': success, 'message': message})


@app.route('/khateb/<int:khateb_id>/change_topic', methods=['POST'])
@admin_required
def change_khateb_topic(khateb_id):
    """تغيير موضوع الخطيب وإعادة تعيين المساجد"""
    new_topic = request.form.get('new_topic')
    
    if not new_topic:
        flash('الموضوع الجديد مطلوب', 'error')
        return redirect(url_for('khutbas'))
    
    engine = DistributionEngine()
    success, message = engine.reset_khateb_mosques(khateb_id)
    
    if success:
        khateb = Khateb.query.get(khateb_id)
        khateb.current_topic = new_topic
        db.session.commit()
        flash('تم تغيير الموضوع وإعادة تعيين المساجد بنجاح', 'success')
    else:
        flash('حدث خطأ', 'error')
    
    return redirect(url_for('khutbas'))


@app.route('/khateb/<int:khateb_id>/status')
@admin_required
def get_khateb_status(khateb_id):
    """API للحصول على حالة الخطيب"""
    engine = DistributionEngine()
    khateb = Khateb.query.get(khateb_id)
    
    if not khateb:
        return jsonify({'error': 'الخطيب غير موجود'}), 404
    
    visited_mosques = khateb.get_visited_mosques_list()
    total_mosques = Mosque.query.count()
    should_change = engine.should_change_topic(khateb_id)
    
    status = {
        'khateb_id': khateb_id,
        'name': khateb.name,
        'current_topic': khateb.current_topic,
        'visited_count': len(visited_mosques),
        'total_mosques': total_mosques,
        'progress_percentage': (len(visited_mosques) / total_mosques * 100) if total_mosques else 0.0,
        'should_change_topic': should_change,
        'visited_mosques': visited_mosques
    }
    
    return jsonify(status)


@app.route('/api/khutbas/status')
@admin_required
def api_all_khutbas_status():
    """API للحصول على حالة جميع الخطباء"""
    engine = DistributionEngine()
    khutbas = Khateb.query.all()
    total_mosques = Mosque.query.count()
    
    statuses = []
    for khateb in khutbas:
        visited_mosques = khateb.get_visited_mosques_list()
        should_change = engine.should_change_topic(khateb.id)
        
        status = {
            'id': khateb.id,
            'name': khateb.name,
            'current_topic': khateb.current_topic,
            'visited_count': len(visited_mosques),
            'total_mosques': total_mosques,
            'progress_percentage': (len(visited_mosques) / total_mosques * 100) if total_mosques else 0.0,
            'should_change_topic': should_change,
            'rest_weeks': khateb.rest_weeks
        }
        statuses.append(status)
    
    return jsonify(statuses)


# إنشاء المجلدات المطلوبة
import os

def create_directories():
    """إنشاء المجلدات المطلوبة"""
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # إنشاء قاعدة البيانات وإضافة البيانات العينة (للقاعدة الجديدة فقط)
    is_new_database = 'khateb' not in sa_inspect(db.engine).get_table_names()
    db.create_all()
    if is_new_database:
        init_sample_data()

    # الاحتفاظ بأحدث نسختين احتياطيتين فقط على الخادم
    try:
        prune_local_backups()
    except Exception:
        pass


# ============================================
# النسخ الاحتياطي والاستعادة
# ============================================

BACKUP_DIR_NAME = 'instance'
# عدد النسخ الاحتياطية المحفوظة على الخادم (تُحذف الأقدم تلقائياً)
MAX_LOCAL_BACKUPS = 2
REQUIRED_TABLES = ('mosque', 'khateb', 'assignment', 'weekly_schedule')


def get_db_path():
    """المسار المطلق لملف قاعدة البيانات"""
    return os.path.join(app.instance_path, 'khutba_distribution.db')


def _is_backup_file(name):
    """هل هذا الملف نسخة احتياطية معروفة (مع استثناء ملف قاعدة البيانات نفسه)"""
    if not name.endswith('.db'):
        return False
    if name == os.path.basename(get_db_path()):
        return False
    return name.startswith('khutba_backup_') or name.startswith('backup_')


def create_local_backup(prefix='khutba_backup_'):
    """إنشاء نسخة احتياطية محلية متناسقة (عبر sqlite backup API)"""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return None

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = '%s%s.db' % (prefix, stamp)
    dest_path = os.path.join(app.instance_path, name)

    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.Error:
        return None
    finally:
        src.close()

    prune_local_backups()
    return name


def prune_local_backups(keep=MAX_LOCAL_BACKUPS):
    """حذف النسخ القديمة من الخادم مع الإبقاء على الأحدث فقط"""
    try:
        names = [f for f in os.listdir(app.instance_path) if _is_backup_file(f)]
    except OSError:
        return

    # الترتيب من الأحدث إلى الأقدم
    def _key(name):
        try:
            mtime = os.stat(os.path.join(app.instance_path, name)).st_mtime
        except OSError:
            mtime = 0
        return (mtime, name)

    names.sort(key=_key, reverse=True)

    for name in names[keep:]:
        try:
            os.remove(os.path.join(app.instance_path, name))
        except OSError:
            pass


def list_local_backups():
    """قائمة النسخ الاحتياطية المحفوظة في مجلد الخادم (الأحدث أولاً)"""
    items = []
    try:
        names = os.listdir(app.instance_path)
    except OSError:
        return items

    for f in names:
        if not _is_backup_file(f):
            continue
        path = os.path.join(app.instance_path, f)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
            size_kb = max(1, round(st.st_size / 1024.0, 1))
            mtime = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')
            ts = st.st_mtime
        except OSError:
            continue
        items.append({'name': f, 'size_kb': size_kb, 'mtime': mtime, '_ts': ts})

    items.sort(key=lambda x: (x['_ts'], x['name']), reverse=True)
    for item in items:
        item.pop('_ts', None)

    return items[:MAX_LOCAL_BACKUPS]


def safe_backup_path(name):
    """التحقق من أن اسم الملف ضمن مجلد الخادم ومنع الخروج منه"""
    if not name or not re.match(r'^[A-Za-z0-9_\-\.]+\.db$', name):
        return None
    path = os.path.abspath(os.path.join(app.instance_path, name))
    if os.path.dirname(path) != os.path.abspath(app.instance_path):
        return None
    if os.path.basename(path) == os.path.basename(get_db_path()):
        return None
    return path


def validate_backup_file(path):
    """التحقق من صلاحية الملف كقاعدة بيانات SQLite تحتوي الجداول المتوقعة"""
    try:
        conn = sqlite3.connect(path)
        try:
            tables = set(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"))
        finally:
            conn.close()
    except sqlite3.Error:
        return False, 'الملف ليس قاعدة بيانات SQLite صالحة'

    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        return False, 'الملف لا يحتوي على الجداول المتوقعة: ' + '، '.join(missing)

    return True, ''


def restore_database(source_path):
    """استعادة قاعدة البيانات من ملف نسخة احتياطية (مع حفظ نسخة أمان أولاً)"""
    db_path = get_db_path()

    # نسخة مؤقتة من الملف المصدر قبل أي حذف تلقائي للنسخ القديمة
    tmp_src_dir = tempfile.mkdtemp(prefix='khutba_restore_src_')
    tmp_src = os.path.join(tmp_src_dir, 'source.db')
    try:
        shutil.copyfile(source_path, tmp_src)

        # نسخة أمان من الوضع الحالي قبل الاستبدال
        safety = create_local_backup('khutba_backup_before_restore_')

        # استبدال الملف بشكل آمن
        tmp_path = db_path + '.restoring'
        shutil.copyfile(tmp_src, tmp_path)
        os.replace(tmp_path, db_path)
    finally:
        shutil.rmtree(tmp_src_dir, ignore_errors=True)

    # إعادة فتح الاتصالات على الملف الجديد
    db.session.remove()
    db.engine.dispose()

    # ترحيل بسيط إن كانت النسخة أقدم من المخطط الحالي
    try:
        from migrate import run_migrations
        run_migrations(db_path, verbose=False)
    except Exception:
        pass

    return safety


@app.route('/settings/backup/download')
@admin_required
def settings_backup_download():
    """تنزيل نسخة احتياطية من قاعدة البيانات"""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        flash('لا يوجد ملف قاعدة بيانات لتنزيله', 'error')
        return redirect(url_for('settings'))

    tmp_dir = tempfile.mkdtemp(prefix='khutba_dl_')
    tmp_path = os.path.join(tmp_dir, 'khutba_distribution.db')

    # نسخة متناسقة حتى لو كانت قاعدة البيانات قيد الكتابة
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(tmp_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    filename = 'khutba_distribution_%s.db' % datetime.now().strftime('%Y%m%d_%H%M%S')
    response = send_file(tmp_path, as_attachment=True, download_name=filename,
                         mimetype='application/x-sqlite3')

    @response.call_on_close
    def _cleanup():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return response


@app.route('/settings/backup/download/<name>')
@admin_required
def settings_backup_download_local(name):
    """تنزيل نسخة احتياطية محفوظة على الخادم"""
    path = safe_backup_path(name)
    if not path or not os.path.isfile(path):
        flash('ملف النسخة الاحتياطية غير موجود', 'error')
        return redirect(url_for('settings'))
    return send_file(path, as_attachment=True, download_name=os.path.basename(path),
                     mimetype='application/x-sqlite3')


@app.route('/settings/backup/restore', methods=['POST'])
@admin_required
def settings_backup_restore():
    """استعادة قاعدة البيانات من ملف مرفوع"""
    uploaded = request.files.get('backup_file')
    if not uploaded or not uploaded.filename:
        flash('يرجى اختيار ملف النسخة الاحتياطية أولاً', 'error')
        return redirect(url_for('settings'))

    if not uploaded.filename.lower().endswith('.db'):
        flash('يجب أن يكون الملف بامتداد .db', 'error')
        return redirect(url_for('settings'))

    tmp_dir = tempfile.mkdtemp(prefix='khutba_restore_')
    tmp_path = os.path.join(tmp_dir, 'restore.db')
    try:
        uploaded.save(tmp_path)
        ok, message = validate_backup_file(tmp_path)
        if not ok:
            flash('تعذرت الاستعادة: ' + message, 'error')
            return redirect(url_for('settings'))

        safety = restore_database(tmp_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    extra = ' (نسخة أمان محفوظة باسم %s)' % safety if safety else ''
    flash('تمت استعادة قاعدة البيانات بنجاح' + extra, 'success')
    return redirect(url_for('settings'))


@app.route('/settings/backup/restore/<name>', methods=['POST'])
@admin_required
def settings_backup_restore_local(name):
    """استعادة قاعدة البيانات من نسخة محفوظة على الخادم"""
    path = safe_backup_path(name)
    if not path or not os.path.isfile(path):
        flash('ملف النسخة الاحتياطية غير موجود', 'error')
        return redirect(url_for('settings'))

    ok, message = validate_backup_file(path)
    if not ok:
        flash('تعذرت الاستعادة: ' + message, 'error')
        return redirect(url_for('settings'))

    safety = restore_database(path)
    extra = ' (نسخة أمان محفوظة باسم %s)' % safety if safety else ''
    flash('تمت استعادة قاعدة البيانات بنجاح' + extra, 'success')
    return redirect(url_for('settings'))


@app.route('/settings/admin/password', methods=['POST'])
@admin_required
def settings_change_admin_password():
    """تغيير كلمة مرور المدير"""
    new_password = request.form.get('new_password', '') or ''
    confirm_password = request.form.get('confirm_password', '') or ''
    current_password = request.form.get('current_password', '') or ''

    if len(new_password) < 6:
        flash('كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل', 'error')
        return redirect(url_for('settings'))

    if new_password != confirm_password:
        flash('كلمة المرور الجديدة وتأكيدها غير متطابقين', 'error')
        return redirect(url_for('settings'))

    # التحقق من كلمة المرور الحالية (إ 추가ً إلى تسجيل الدخول الحالي)
    if current_password and not verify_admin_password(current_password):
        flash('كلمة المرور الحالية غير صحيحة', 'error')
        return redirect(url_for('settings'))

    AppSetting.set(ADMIN_PASSWORD_KEY, generate_password_hash(new_password))
    flash('تم تغيير كلمة مرور المدير بنجاح', 'success')
    return redirect(url_for('settings'))


@app.route('/settings/admin/password/reset', methods=['POST'])
@admin_required
def settings_reset_admin_password():
    """الرجوع إلى كلمة المرور من متغير البيئة ADMIN_PASSWORD"""
    current_password = request.form.get('current_password', '') or ''
    if not verify_admin_password(current_password):
        flash('كلمة المرور الحالية غير صحيحة', 'error')
        return redirect(url_for('settings'))

    AppSetting.delete(ADMIN_PASSWORD_KEY)
    flash('تمت إعادة كلمة مرور المدير إلى القيمة الأساسية (متغير البيئة ADMIN_PASSWORD)', 'success')
    return redirect(url_for('settings'))


@app.route('/settings')
@admin_required
def settings():
    """صفحة الإعدادات"""
    engine = DistributionEngine()
    mosques = Mosque.query.all()
    khutbas = Khateb.query.all()
    assignments = Assignment.query.order_by(Assignment.week_date.desc(), Assignment.id.asc()).all()
    schedules = WeeklySchedule.query.order_by(WeeklySchedule.week_date.desc()).limit(50).all()
    
    # قائمة الأسابيع المتاحة
    week_dates = sorted(set([a.week_date for a in assignments]), reverse=True)
    
    total_mosques = len(mosques)
    for khateb in khutbas:
        visited = khateb.get_visited_mosques_list()
        khateb._progress = round((len(visited) / total_mosques * 100), 1) if total_mosques else 0
        khateb._should_change = engine.should_change_topic(khateb.id)
        khateb._visited_count = len(visited)
        khateb._forbidden = khateb.get_forbidden_mosques_list()
        # معلومات إضافية للوحة "خطباء يحتاجون موضوعاً جديداً" والدخول
        khateb._need_new_topic = bool(total_mosques) and khateb._visited_count >= total_mosques
        khateb._has_password = bool(khateb.password_hash)
        khateb._wa_link = whatsapp_link(khateb.phone, khateb.name)
        khateb._seasonal_active = khateb.is_seasonal_active()

    # الخطباء الذين لديهم موضوع موسمي ساري الآن
    seasonal_khutbas = [k for k in khutbas if k.is_seasonal_active()]

    return render_template('settings.html',
                         mosques=mosques,
                         khutbas=khutbas,
                         assignments=assignments,
                         schedules=schedules,
                         week_dates=week_dates,
                         total_mosques=total_mosques,
                         backups=list_local_backups(),
                         seasonal_khutbas=seasonal_khutbas,
                         admin_password_source=admin_password_source())


@app.route('/settings/reset/distributions', methods=['POST'])
@admin_required
def settings_reset_distributions():
    """تصفير التوزيعات فقط"""
    try:
        Assignment.query.delete()
        WeeklySchedule.query.delete()
        db.session.commit()
        flash('تم تصفير جميع التعيينات والجداول الأسبوعية بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء التصفير: {str(e)}', 'error')
    return redirect(url_for('settings'))


@app.route('/settings/reset/khatibs_progress', methods=['POST'])
@admin_required
def settings_reset_khatibs_progress():
    """إعادة تعيين تقدم الخطباء"""
    try:
        for khateb in Khateb.query.all():
            khateb.mosques_visited = json.dumps([])
            khateb.rest_weeks = 0
        db.session.commit()
        flash('تم إعادة تعيين تقدم جميع الخطباء بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء التصفير: {str(e)}', 'error')
    return redirect(url_for('settings'))


@app.route('/settings/reset/all', methods=['POST'])
@admin_required
def settings_reset_all():
    """تصفير كامل للنظام مع الاحتفاظ بالمساجد والخطباء"""
    # نسخة أمان تلقائية قبل التصفير (حماية من التصفير بالخطأ)
    safety = create_local_backup('khutba_backup_before_reset_')
    try:
        Assignment.query.delete()
        WeeklySchedule.query.delete()
        for khateb in Khateb.query.all():
            khateb.mosques_visited = json.dumps([])
            khateb.rest_weeks = 0
        db.session.commit()
        extra = ' (نسخة أمان محفوظة باسم %s)' % safety if safety else ''
        flash('تم تصفير النظام بالكامل مع الاحتفاظ بالمساجد والخطباء' + extra, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء التصفير: {str(e)}', 'error')
    return redirect(url_for('settings'))


@app.route('/settings/reset/everything', methods=['POST'])
@admin_required
def settings_reset_everything():
    """حذف جميع البيانات"""
    # نسخة أمان تلقائية قبل الحذف (حماية من التصفير بالخطأ)
    safety = create_local_backup('khutba_backup_before_reset_')
    try:
        Assignment.query.delete()
        WeeklySchedule.query.delete()
        Khateb.query.delete()
        Mosque.query.delete()
        db.session.commit()
        extra = ' (نسخة أمان محفوظة باسم %s)' % safety if safety else ''
        flash('تم حذف جميع المساجد والخطباء والتعيينات' + extra, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء الحذف: {str(e)}', 'error')
    return redirect(url_for('settings'))


@app.route('/assignment/<int:assignment_id>/update', methods=['POST'])
@admin_required
def assignment_update(assignment_id):
    """تعديل تعيين محدد"""
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'success': False, 'message': 'التعيين غير موجود'}), 404
    
    khateb_id = request.form.get('khateb_id', type=int)
    mosque_id = request.form.get('mosque_id', type=int)
    week_date_str = request.form.get('week_date')
    khutba_topic = request.form.get('khutba_topic')
    status = request.form.get('status')
    
    target_khateb_id = khateb_id if khateb_id is not None else assignment.khateb_id
    target_mosque_id = mosque_id if mosque_id is not None else assignment.mosque_id
    target_week_date = assignment.week_date
    if week_date_str:
        try:
            target_week_date = datetime.strptime(week_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    target_status = status if status is not None else assignment.status

    if target_status != 'cancelled':
        # التحقق من عدم تعيين نفس الخطيب في أكثر من مسجد في نفس الجمعة
        dup_khateb = Assignment.query.filter(
            Assignment.khateb_id == target_khateb_id,
            Assignment.week_date == target_week_date,
            Assignment.status != 'cancelled',
            Assignment.id != assignment.id
        ).first()
        if dup_khateb:
            return jsonify({'success': False, 'message': 'لا يمكن توزيع الخطيب على أكثر من مسجد في نفس الجمعة'}), 400

        # التحقق من عدم تعيين أكثر من خطيب لنفس المسجد في نفس الجمعة
        dup_mosque = Assignment.query.filter(
            Assignment.mosque_id == target_mosque_id,
            Assignment.week_date == target_week_date,
            Assignment.status != 'cancelled',
            Assignment.id != assignment.id
        ).first()
        if dup_mosque:
            return jsonify({'success': False, 'message': 'هذا المسجد مخصص له خطيب آخر بالفعل في نفس الجمعة'}), 400

    if khateb_id:
        assignment.khateb_id = khateb_id
    if mosque_id:
        assignment.mosque_id = mosque_id
    if week_date_str:
        assignment.week_date = target_week_date
    if khutba_topic is not None:
        assignment.khutba_topic = khutba_topic
    if status:
        assignment.status = status
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم تعديل التعيين بنجاح'})


@app.route('/khateb/<int:khateb_id>/special/update', methods=['POST'])
@admin_required
def khateb_special_update(khateb_id):
    """تحديث ظروف الخطيب الخاصة"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        return jsonify({'success': False, 'message': 'الخطيب غير موجود'}), 404
    
    availability_mode = request.form.get('availability_mode', 'always')
    alternate_offset = request.form.get('alternate_offset', 0, type=int)
    forbidden_mosques = request.form.getlist('forbidden_mosques')
    
    khateb.availability_mode = availability_mode
    khateb.alternate_offset = alternate_offset
    khateb.forbidden_mosques = json.dumps([int(m) for m in forbidden_mosques if m])
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم حفظ ظروف الخطيب بنجاح'})


@app.route('/settings/week/<date>/delete', methods=['POST'])
@admin_required
def settings_delete_week(date):
    """حذف جميع تعيينات أسبوع معين"""
    try:
        week_date = datetime.strptime(date, '%Y-%m-%d').date()
        Assignment.query.filter_by(week_date=week_date).delete()
        WeeklySchedule.query.filter_by(week_date=week_date).delete()
        db.session.commit()
        flash(f'تم حذف جميع تعيينات أسبوع {date} بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'error')
    return redirect(url_for('settings'))


@app.route('/settings/week/<date>/reassign', methods=['POST'])
@admin_required
def settings_reassign_week(date):
    """إعادة توزيع أسبوع معين تلقائياً"""
    try:
        week_date = datetime.strptime(date, '%Y-%m-%d').date()
        engine = DistributionEngine()
        # حذف التعيينات السابقة لهذا الأسبوع
        Assignment.query.filter_by(week_date=week_date).delete()
        WeeklySchedule.query.filter_by(week_date=week_date).delete()
        db.session.commit()
        success, message = engine.distribute_for_week(week_date)
        if success:
            flash(f'تم إعادة توزيع أسبوع {date} بنجاح', 'success')
        else:
            flash(message, 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ: {str(e)}', 'error')
    return redirect(url_for('settings'))


@app.route('/api/khateb/<int:khateb_id>/schedule')
@admin_required
def api_khateb_schedule(khateb_id):
    """عرض جدول خطيب معين لأسابيع قادمة"""
    weeks = request.args.get('weeks', 4, type=int)
    engine = DistributionEngine()
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        return jsonify({'error': 'الخطيب غير موجود'}), 404
    
    schedule = []
    current = engine.get_current_friday()
    for i in range(weeks):
        week_date = current + timedelta(days=7*i)
        assignment = Assignment.query.filter_by(khateb_id=khateb_id, week_date=week_date).first()
        if assignment:
            schedule.append({
                'week_date': week_date.strftime('%Y-%m-%d'),
                'has_assignment': True,
                'mosque_name': assignment.mosque.name if assignment.mosque else None,
                'topic': assignment.khutba_topic,
                'status': assignment.status
            })
        else:
            schedule.append({
                'week_date': week_date.strftime('%Y-%m-%d'),
                'has_assignment': False
            })
    
    return jsonify({
        'khateb': {'id': khateb.id, 'name': khateb.name, 'current_topic': khateb.current_topic},
        'schedule': schedule
    })


@app.route('/api/distribution/history')
@admin_required
def api_distribution_history():
    """API للحصول على سجل التوزيعات السابقة"""
    # الحصول على آخر 12 أسبوع
    weeks = WeeklySchedule.query.order_by(WeeklySchedule.week_date.desc()).limit(12).all()
    
    history = []
    for week in weeks:
        assignment_count = Assignment.query.filter_by(week_date=week.week_date).count()
        history.append({
            'week_date': week.week_date.strftime('%Y-%m-%d'),
            'assignment_count': assignment_count,
            'khateb_count': len(json.loads(week.khateb_ids or '[]'))
        })
    
    return jsonify(history)


@app.route('/api/distribution/week/<date>')
@admin_required
def api_week_details(date):
    """API للحصول على تفاصيل أسبوع معين"""
    try:
        week_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'تنسيق تاريخ غير صحيح'}), 400
    
    assignments = Assignment.query.filter_by(week_date=week_date).all()
    
    result = {
        'week_date': date,
        'assignments': [assignment.to_dict() for assignment in assignments]
    }
    
    return jsonify(result)


@app.route('/api/assignment/<int:assignment_id>')
@admin_required
def api_assignment_details(assignment_id):
    """API للحصول على تفاصيل تعيين معين"""
    assignment = Assignment.query.get(assignment_id)
    
    if not assignment:
        return jsonify({'error': 'التعيين غير موجود'}), 404
    
    details = assignment.to_dict()
    details.update({
        'created_at': assignment.created_at.strftime('%Y-%m-%d %H:%M:%S') if assignment.created_at else '-'
    })
    
    return jsonify(details)


@app.route('/api/assignment/<int:assignment_id>', methods=['DELETE'])
@admin_required
def api_delete_assignment(assignment_id):
    """API لحذف تعيين"""
    assignment = Assignment.query.get(assignment_id)
    
    if not assignment:
        return jsonify({'success': False, 'message': 'التعيين غير موجود'}), 404
    
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم حذف التعيين بنجاح'})


def cancel_and_reassign(assignment, update_visited=True, attach_original=True):
    """منطق مشترك للاعتذار عن تعيين.

    - يلغي التعيين الأصلي (status = 'cancelled')
    - يبحث عن خطيب بديل لنفس المسجد (غير مُعين لنفس الأسبوع ونفسه لا ونفس الموضوع لا)
    - ينشئ للبديل تعييناً بحالة 'pending'
    - عند update_visited=True تُحدَّث قائمة المساجد المزارة للبديل
    - عند attach_original=True يُلحق الخطيب الأصلي بمسجد آخر غير مخصص للأسبوع

    يعيد: (replacement_assignment_id, attached_assignment_id)
    """
    target_week = assignment.week_date
    target_mosque = assignment.mosque_id
    original_khateb_id = assignment.khateb_id
    original_topic = assignment.khutba_topic

    # إلغاء التعيين الأصلي
    assignment.status = 'cancelled'
    db.session.add(assignment)
    db.session.flush()

    # من المستبعدين: الذين لديهم تعيين (أي حالة ليست ملغية) لنفس الأسبوع
    assigned_khateb_ids = set(a.khateb_id for a in Assignment.query.filter(Assignment.week_date==target_week, Assignment.status!='cancelled').all())

    # بناء قائمة المرشحين (نتجاهل rest_weeks كما طلبت)
    candidates = []
    for k in Khateb.query.all():
        if k.is_active not in (1, True):
            continue
        if not k.has_profile():
            continue
        if k.id == original_khateb_id:
            continue
        if k.id in assigned_khateb_ids:
            continue
        if target_mosque in k.get_forbidden_mosques_list():
            continue
        if k.current_topic == original_topic:
            continue
        visited = set(k.get_visited_mosques_list())
        preferred = (target_mosque not in visited)
        candidates.append((preferred, k))

    candidates.sort(key=lambda x: (not x[0], x[1].id))

    new_assignment_id = None
    if candidates:
        replacement_khateb = candidates[0][1]
        new_assignment = Assignment(
            khateb_id=replacement_khateb.id,
            mosque_id=target_mosque,
            week_date=target_week,
            khutba_topic=replacement_khateb.current_topic,
            status='pending',
            replacement_of_id=assignment.id
        )
        db.session.add(new_assignment)
        db.session.flush()
        new_assignment_id = new_assignment.id

        # تحديث زيارات الخطيب البديل
        if update_visited:
            visited = replacement_khateb.get_visited_mosques_list()
            if target_mosque not in visited:
                visited.append(target_mosque)
                replacement_khateb.mosques_visited = json.dumps(visited)
                db.session.add(replacement_khateb)

    # الآن محاولة إلحاق الخطيب الأصلي بمسجد آخر إن وُجد مسجد غير مخصص
    # ⚠️ لا يُلحق إذا كان لديه تعيين فعّال آخر في نفس الأسبوع (لا يمكن خطبتان في جمعة واحدة)
    attached_assignment_id = None
    if attach_original:
        has_active = Assignment.query.filter(
            Assignment.khateb_id == original_khateb_id,
            Assignment.week_date == target_week,
            Assignment.status != 'cancelled',
            Assignment.id != assignment.id
        ).first()
        if has_active:
            # لديه تعيين آخر فعّال — لا نلحقه بمسجد ثانٍ
            pass
        else:
            all_mosques = [m.id for m in Mosque.query.all()]
            assigned_mosques = set(a.mosque_id for a in Assignment.query.filter(Assignment.week_date==target_week, Assignment.status!='cancelled').all())
            unassigned = [m for m in all_mosques if m not in assigned_mosques]

            if unassigned:
                # اختر مسجد مفضّل لم يزره الخطيب الأصلي
                orig_khateb = Khateb.query.get(original_khateb_id)
                preferred = [m for m in unassigned if m not in orig_khateb.get_visited_mosques_list()]
                chosen = preferred[0] if preferred else unassigned[0]
                new_attach = Assignment(
                    khateb_id=original_khateb_id,
                    mosque_id=chosen,
                    week_date=target_week,
                    khutba_topic=orig_khateb.current_topic,
                    status='pending'
                )
                db.session.add(new_attach)
                db.session.flush()
                attached_assignment_id = new_attach.id

                # تحديث زيارات الخطيب الأصلي
                if update_visited:
                    visited = orig_khateb.get_visited_mosques_list()
                    if chosen not in visited:
                        visited.append(chosen)
                        orig_khateb.mosques_visited = json.dumps(visited)
                        db.session.add(orig_khateb)

    return new_assignment_id, attached_assignment_id


@app.route('/assignment/<int:assignment_id>/apologize', methods=['POST'])
@admin_required
def api_apologize_assignment(assignment_id):
    """API لمعالجة اعتذار عن تعيين محدد (مسجد بعينه).

    سلوك:
    - يتم إلغاء التعيين الأصلي (status = 'cancelled')
    - محاولة إيجاد خطيب بديل (من لم يُعين لنفس الأسبوع، لا يكون نفس الخطيب، لا يملك نفس الموضوع الحالي)
    - إذا وُجد بديل، يُنشئ له تعيينًا للمسجد الأصلي (status='pending') ويُحدّث زيارته
    - ثم نحاول إلحاق الخطيب الأصلي بمسجد آخر غير المقيّد (إذا وُجد مسجد غير مخصص لهذا الأسبوع)
    """
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'success': False, 'message': 'التعيين غير موجود'}), 404

    new_assignment_id, attached_assignment_id = cancel_and_reassign(
        assignment, update_visited=True, attach_original=True
    )

    db.session.commit()

    if new_assignment_id:
        return jsonify({'success': True, 'message': 'تم إلغاء التعيين وإيجاد بديل. تم إلحاقك بمسجد آخر.', 'new_assignment_id': new_assignment_id, 'attached_assignment_id': attached_assignment_id})
    else:
        return jsonify({'success': False, 'message': 'تم إلغاء التعيين لكن لم يتم العثور على بديل حالياً'})


@app.route('/khateb/<int:khateb_id>/apologize_week', methods=['POST'])
@admin_required
def api_apologize_khateb_week(khateb_id):
    """API لمعالجة اعتذار الخطيب عن الأسبوع بالكامل."""
    engine = DistributionEngine()
    target_week = engine.get_current_friday()

    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        return jsonify({'success': False, 'message': 'الخطيب غير موجود'}), 404

    # الحصول على التعيين (إن وُجد) لهذا الخطيب في الأسبوع
    assignment = Assignment.query.filter_by(khateb_id=khateb_id, week_date=target_week).filter(Assignment.status!='cancelled').first()
    if not assignment:
        # ليس له تعيين لهذا الأسبوع
        khateb.rest_weeks = 1
        db.session.add(khateb)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تسجيل راحة للأسبوع، وليس لديك تعيين لهذا الأسبوع'})

    # إلغاء التعيين وإنشاء بديل
    # نستخدم نفس منطق البحث عن بديل في الاعتذار عن تعيين واحد
    resp = api_apologize_assignment(assignment.id)

    # تأكدنا من وضع الراحة للخطيب الذي اعتذر
    khateb.rest_weeks = 1
    db.session.add(khateb)
    db.session.commit()

    return resp


@app.route('/khateb/<int:khateb_id>/update_visits', methods=['POST'])
@admin_required
def api_update_visited_mosques(khateb_id):
    """API لتحديث قائمة المساجد المزارة"""
    data = request.get_json()
    mosque_id = data.get('mosque_id')
    
    if not mosque_id:
        return jsonify({'success': False, 'message': 'معرف المسجد مطلوب'}), 400
    
    engine = DistributionEngine()
    success, message = engine.update_khateb_mosques_visited(khateb_id, mosque_id)
    
    return jsonify({'success': success, 'message': message})


@app.route('/mosque/<int:mosque_id>/delete', methods=['DELETE'])
@admin_required
def api_delete_mosque(mosque_id):
    """API لحذف مسجد"""
    mosque = Mosque.query.get(mosque_id)
    
    if not mosque:
        return jsonify({'success': False, 'message': 'المسجد غير موجود'}), 404
    
    # حذف التعيينات المرتبطة
    assignments = Assignment.query.filter_by(mosque_id=mosque_id).all()
    for assignment in assignments:
        db.session.delete(assignment)
    
    db.session.delete(mosque)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم حذف المسجد بنجاح'})


@app.route('/mosque/<int:mosque_id>/edit', methods=['POST'])
@admin_required
def api_edit_mosque(mosque_id):
    """API لتعديل مسجد"""
    mosque = Mosque.query.get(mosque_id)
    
    if not mosque:
        return jsonify({'success': False, 'message': 'المسجد غير موجود'}), 404
    
    name = request.form.get('name')
    address = request.form.get('address')
    capacity = request.form.get('capacity', type=int)
    
    if not name:
        return jsonify({'success': False, 'message': 'اسم المسجد مطلوب'}), 400
    
    mosque.name = name
    mosque.address = address
    mosque.capacity = capacity
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم تحديث المسجد بنجاح'})


@app.route('/khateb/<int:khateb_id>/delete', methods=['DELETE'])
@admin_required
def api_delete_khateb(khateb_id):
    """API لحذف خطيب"""
    khateb = Khateb.query.get(khateb_id)
    
    if not khateb:
        return jsonify({'success': False, 'message': 'الخطيب غير موجود'}), 404
    
    # حذف التعيينات المرتبطة
    assignments = Assignment.query.filter_by(khateb_id=khateb_id).all()
    for assignment in assignments:
        db.session.delete(assignment)
    
    db.session.delete(khateb)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم حذف الخطيب بنجاح'})


# ============================================
# صفحات الدخول والخروج
# ============================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """صفحة تسجيل الدخول (مدير / خطيب)"""
    if session.get('role') == 'admin':
        return redirect(url_for('settings'))
    if session.get('role') == 'khateb':
        return redirect(url_for('my'))

    if request.method == 'POST':
        role = request.form.get('role', 'admin')

        if role == 'admin':
            password = request.form.get('password', '') or ''
            if password and verify_admin_password(password):
                login_admin()
                flash('تم تسجيل الدخول كمدير بنجاح', 'success')
                return redirect(url_for('settings'))
            flash('كلمة المرور غير صحيحة', 'error')
            return render_template('login.html', role='admin')

        # دخول الخطيب: رقم الجوال + كلمة المرور
        # ملاحظة: حقل كلمة المرور للخطيب اسمه khateb_password (مختلف عن password الخاص بالمدير)
        # حتى لا يقرأ الخادم قيمة حقل المدير الفارغ عند إرسال النموذج من المتصفح.
        phone = (request.form.get('phone', '') or '').strip()
        password = (request.form.get('khateb_password', '') or '').strip()
        if not password:
            password = (request.form.get('password', '') or '').strip()
        normalized = normalize_phone(phone)

        khateb = None
        if normalized:
            for k in Khateb.query.all():
                if normalize_phone(k.phone) == normalized:
                    khateb = k
                    break

        if not khateb:
            flash('لا يوجد خطيب مسجل بهذا الرقم', 'error')
        elif khateb.is_active in (None, 0):
            flash('حسابك بانتظار موافقة المدير على الدخول، يرجى التواصل مع الإدارة', 'error')
        elif not khateb.password_hash:
            flash('لم يتم تعيين كلمة مرور لهذا الحساب، يرجى التواصل مع الإدارة', 'error')
        elif not check_password_hash(khateb.password_hash, password):
            flash('كلمة المرور غير صحيحة', 'error')
        else:
            login_khateb(khateb.id)
            flash('أهلاً بك %s' % khateb.name, 'success')
            return redirect(url_for('my'))

        return render_template('login.html', role='khateb')

    return render_template('login.html', role='admin')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """تسجيل خطيب جديد: الاسم + رقم الجوال + كلمة مرور يختارها بنفسه.
    يبقى الحساب معطّلاً (is_active = 0) حتى يسمح به المدير من صفحة الإعدادات.
    """
    if request.method == 'POST':
        name = (request.form.get('name', '') or '').strip()
        phone = (request.form.get('phone', '') or '').strip()
        password = (request.form.get('password', '') or '').strip()
        confirm_password = (request.form.get('confirm_password', '') or '').strip()

        if not name or not phone or not password:
            flash('الاسم ورقم الجوال وكلمة المرور مطلوبة', 'error')
            return render_template('register.html')
        if len(password) < 6:
            flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل', 'error')
            return render_template('register.html')
        if confirm_password and password != confirm_password:
            flash('كلمتا المرور غير متطابقتين', 'error')
            return render_template('register.html')

        # منع تكرار رقم الجوال (مع مراعاة اختلاف صيغة الرقم)
        normalized = normalize_phone(phone)
        for existing in Khateb.query.all():
            if normalize_phone(existing.phone) == normalized:
                flash('رقم الجوال مسجل مسبقاً، يرجى التواصل مع الإدارة لتفعيل حسابك', 'error')
                return render_template('register.html')

        khateb = Khateb(
            name=name,
            phone=phone,
            current_topic='موضوع افتراضي',
            mosques_visited=json.dumps([]),
            availability_mode='always',
            alternate_offset=0,
            forbidden_mosques=json.dumps([]),
            password_hash=generate_password_hash(password),
            profile_complete=0,
            is_active=0,
        )
        db.session.add(khateb)
        db.session.commit()

        # رمز مؤقت يتيح للخطيب إكمال ملفه (موضوع الخطبة + المساجد + نظام التوفر)
        # قبل موافقة المدير، دون الحاجة لتسجيل الدخول.
        token = secrets.token_urlsafe(24)
        app_setting = AppSetting.query.get('register_token_%s' % token)
        if app_setting:
            db.session.delete(app_setting)
        db.session.add(AppSetting(
            key='register_token_%s' % token,
            value=json.dumps({'khateb_id': khateb.id, 'created': datetime.utcnow().isoformat()}),
            updated_at=datetime.utcnow()
        ))
        db.session.commit()

        flash('تم تسجيل طلبك بنجاح. أكمل بياناتك الآن (موضوع الخطبة والمساجد)، ثم بانتظار موافقة المدير.', 'success')
        return redirect(url_for('my_profile_setup', token=token))

    return render_template('register.html')


@app.route('/logout')
def logout():
    """تسجيل الخروج"""
    logout_session()
    flash('تم تسجيل الخروج', 'success')
    return redirect(url_for('login'))


@app.route('/my/profile', methods=['GET', 'POST'])
def my_profile_setup():
    """صفحة ملف الخطيب: موضوع الخطبة الحالية + المساجد المزارة + المستثناة + نظام التوفر

    يمكن الوصول إليها:
    - بعد التسجيل مباشرة عبر رمز مؤقت (token) قبل موافقة المدير.
    - بعد تسجيل الدخول (لتعديل البيانات لاحقاً).
    """
    khateb = None
    token = (request.values.get('token', '') or '').strip()

    if token:
        setting = AppSetting.query.get('register_token_%s' % token)
        if not setting:
            flash('رابط الإعداد غير صالح أو انتهت صلاحيته، يرجى تسجيل الدخول أو إعادة التسجيل', 'error')
            return redirect(url_for('login'))
        try:
            data = json.loads(setting.value or '{}')
        except Exception:
            data = {}
        khateb = Khateb.query.get(data.get('khateb_id'))
        if not khateb:
            flash('تعذّر العثور على الحساب', 'error')
            return redirect(url_for('login'))
    else:
        khateb = current_khateb()
        if not khateb:
            flash('يرجى تسجيل الدخول أولاً', 'error')
            return redirect(url_for('login'))

    if request.method == 'POST':
        topic = (request.form.get('current_topic', '') or '').strip()
        visited_raw = request.form.getlist('visited_mosques')
        forbidden_raw = request.form.getlist('forbidden_mosques')
        availability_mode = request.form.get('availability_mode', 'always')
        if availability_mode not in ('always', 'alternate'):
            availability_mode = 'always'
        try:
            alternate_offset = int(request.form.get('alternate_offset', 0) or 0)
        except (TypeError, ValueError):
            alternate_offset = 0

        if not topic:
            flash('يرجى كتابة موضوع خطبتك الحالية', 'error')
        else:
            # تحويل القوائم إلى أرقام صحيحة
            try:
                visited = sorted({int(m) for m in visited_raw})
                forbidden = sorted({int(m) for m in forbidden_raw})
            except (TypeError, ValueError):
                visited, forbidden = [], []

            khateb.current_topic = topic[:300]
            khateb.mosques_visited = json.dumps(visited)
            khateb.forbidden_mosques = json.dumps(forbidden)
            khateb.availability_mode = availability_mode
            khateb.alternate_offset = alternate_offset
            khateb.profile_complete = 1
            db.session.add(khateb)

            # استهلاك الرمز المؤقت بعد الحفظ
            if token:
                setting = AppSetting.query.get('register_token_%s' % token)
                if setting:
                    db.session.delete(setting)
            db.session.commit()

            flash('تم حفظ بياناتك بنجاح. حسابك الآن بانتظار موافقة مدير النظام، وسيظهر تلقائياً في توزيع الجدول بعد الموافقة.', 'success')
            return redirect(url_for('login'))

    mosques = Mosque.query.order_by(Mosque.name).all()
    visited = set(khateb.get_visited_mosques_list())
    forbidden = set(khateb.get_forbidden_mosques_list())

    return render_template('my_profile.html',
                           khateb=khateb,
                           mosques=mosques,
                           visited=visited,
                           forbidden=forbidden,
                           token=token)


# ============================================
# صفحة الخطيب /my
# ============================================

@app.route('/my')
@login_required
def my():
    """صفحة الخطيب: الجدول + تأكيد الأداء + إرسال موضوع جديد"""
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    engine = DistributionEngine()
    total_mosques = Mosque.query.count()
    visited = khateb.get_visited_mosques_list()
    visited_count = len(visited)
    needs_new_topic = engine.should_change_topic(khateb.id)

    # جدول الأسابيع الأربعة القادمة (نفس منطق /api/khateb/<id>/schedule)
    current_friday = engine.get_current_friday()
    week_dates = [current_friday + timedelta(days=7 * i) for i in range(4)]
    assignments = Assignment.query.filter(
        Assignment.khateb_id == khateb.id,
        Assignment.week_date.in_(week_dates)
    ).order_by(Assignment.week_date.asc(), Assignment.id.asc()).all()

    by_week = {}
    for a in assignments:
        by_week.setdefault(a.week_date, []).append(a)

    schedule = []
    for wd in week_dates:
        schedule.append({
            'week_date': wd,
            'assignments': by_week.get(wd, [])
        })

    return render_template(
        'my.html',
        khateb=khateb,
        schedule=schedule,
        total_mosques=total_mosques,
        visited_count=visited_count,
        needs_new_topic=needs_new_topic,
        current_friday=current_friday,
        seasonal_active=khateb.is_seasonal_active(),
        seasonal_occasions=SEASONAL_OCCASIONS
    )


@app.route('/my/assignment/<int:assignment_id>/apologize', methods=['POST'])
@login_required
def my_apologize_assignment(assignment_id):
    """اعتذار الخطيب عن تعيين: cancelled + محاولة تعيين بديل"""
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.khateb_id != khateb.id:
        flash('التعيين غير موجود', 'error')
        return redirect(url_for('my'))

    if assignment.status == 'cancelled':
        flash('هذا التعيين ملغى بالفعل', 'error')
        return redirect(url_for('my'))

    replacement_id, _attached_id = cancel_and_reassign(
        assignment, update_visited=False, attach_original=False
    )
    db.session.commit()

    if replacement_id:
        flash('تم تسجيل اعتذارك وسيتم تعيين خطيب بديل في المسجد', 'success')
    else:
        flash('تم تسجيل اعتذارك عن هذه الخطبة', 'success')
    return redirect(url_for('my'))


@app.route('/my/assignment/<int:assignment_id>/undo_apologize', methods=['POST'])
@login_required
def my_undo_apologize(assignment_id):
    """التراجع عن اعتذار الخطيب: إعادة التعيين الملغى وإلغاء البديل الذي حُلّ محلّه"""
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    assignment = Assignment.query.get(assignment_id)
    if not assignment or assignment.khateb_id != khateb.id:
        flash('التعيين غير موجود', 'error')
        return redirect(url_for('my'))

    if assignment.status != 'cancelled':
        flash('هذا التعيين غير ملغى', 'error')
        return redirect(url_for('my'))

    # ⚠️ تحقق: لا يمكن خطبتان في جمعة واحدة
    has_active = Assignment.query.filter(
        Assignment.khateb_id == khateb.id,
        Assignment.week_date == assignment.week_date,
        Assignment.status != 'cancelled',
        Assignment.id != assignment.id
    ).first()
    if has_active:
        flash('لديك تعيين آخر فعّال في نفس الأسبوع — لا يمكن خطبتان في جمعة واحدة', 'error')
        return redirect(url_for('my'))

    # إلغاء التعيين البديل (إن وُجد) لأنه لم تعد هناك حاجة إليه بعد التراجع
    replacements = Assignment.query.filter_by(replacement_of_id=assignment.id).all()
    for rep in replacements:
        if rep.status != 'pending':
            continue
        # إزالة المسجد من زيارات الخطيب البديل (إذ لم يؤدِّ الخطبة بعد)
        rep_khateb = Khateb.query.get(rep.khateb_id)
        if rep_khateb:
            visited = rep_khateb.get_visited_mosques_list()
            if rep.mosque_id in visited:
                visited.remove(rep.mosque_id)
                rep_khateb.mosques_visited = json.dumps(visited)
                db.session.add(rep_khateb)
        rep.status = 'cancelled'
        db.session.add(rep)

    # إعادة التعيين الأصلي
    assignment.status = 'confirmed'
    db.session.add(assignment)
    db.session.commit()

    flash('تم التراجع عن الإلغاء، وأُعيد تعيينك في هذا الأسبوع', 'success')
    return redirect(url_for('my'))


@app.route('/my/seasonal', methods=['POST'])
@login_required
def my_set_seasonal_topic():
    """تفعيل موضوع موسمي مؤقت (خطبة واحدة أو خطبتان) - يعلو على الموضوع الأساسي"""
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    topic = (request.form.get('topic', '') or '').strip()
    if not topic:
        flash('يرجى كتابة موضوع الخطبة الموسمي', 'error')
        return redirect(url_for('my'))

    first_friday, last_friday = seasonal_window(khateb, request.form.get('weeks', 1))

    khateb.seasonal_topic = topic[:300]
    khateb.seasonal_until = last_friday
    db.session.add(khateb)

    # تطبيق الموضوع على التعيينات المستقبلية ضمن نافذة الموسم
    updated = apply_seasonal_to_assignments(khateb, topic, first_friday, last_friday)
    db.session.commit()

    msg = 'تم تفعيل الموضوع الموسمي: %s (حتى %s)' % (topic, last_friday.strftime('%Y-%m-%d'))
    if updated:
        msg += ' — تم تحديث %d تعيين قادم' % updated
    flash(msg, 'success')
    return redirect(url_for('my'))


@app.route('/my/seasonal/cancel', methods=['POST'])
@login_required
def my_cancel_seasonal_topic():
    """إلغاء الموضوع الموسمي والعودة للموضوع الأساسي"""
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    khateb.seasonal_topic = None
    khateb.seasonal_until = None
    db.session.add(khateb)
    db.session.commit()

    flash('تم إلغاء الموضوع الموسمي، وعاد موضوعك الأساسي', 'success')
    return redirect(url_for('my'))


@app.route('/khateb/<int:khateb_id>/seasonal/cancel', methods=['POST'])
@admin_required
def khateb_cancel_seasonal_topic(khateb_id):
    """إلغاء الموضوع الموسمي لخطيب (رقابة إدارية)"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'error')
        return redirect(url_for('settings'))

    khateb.seasonal_topic = None
    khateb.seasonal_until = None
    db.session.add(khateb)
    db.session.commit()

    flash('تم إلغاء الموضوع الموسمي للخطيب %s' % khateb.name, 'success')
    return redirect(url_for('settings'))


@app.route('/my/topic', methods=['POST'])
@login_required
def my_submit_topic():
    """تأكيد موضوع خطبة جديد من الخطيب (تطبيق مباشر بدون تدخل المدير)

       - reset: يُفعَّل فوراً وتُصفَّر المساجد المزارة (بداية جديدة)
       - after_current: يُجدول ويكون موضوع الخطبة القادمة، ويُفعَّل تلقائياً
         بعد إنهاء الخطيب جميع المساجد
    """
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    topic = (request.form.get('topic', '') or '').strip()
    if not topic:
        flash('يرجى كتابة موضوع الخطبة الجديد', 'error')
        return redirect(url_for('my'))

    mode = request.form.get('mode', TOPIC_MODE_RESET)
    if mode not in (TOPIC_MODE_RESET, TOPIC_MODE_AFTER_CURRENT):
        mode = TOPIC_MODE_RESET

    if mode == TOPIC_MODE_AFTER_CURRENT:
        # موضوع الخطبة القادمة: يبقى الموضوع الحالي حتى تنتهي المساجد،
        # ثم يُفعَّل تلقائياً
        khateb.pending_topic = topic[:300]
        khateb.pending_topic_mode = TOPIC_MODE_AFTER_CURRENT
        khateb.pending_topic_approved = 1
        db.session.add(khateb)
        db.session.commit()
        flash('تم تأكيد موضوع الخطبة القادمة: %s — سيُطبَّق تلقائياً بعد إنهائك جميع المساجد' % topic, 'success')
        return redirect(url_for('my'))

    # تطبيق مباشر: بداية جديدة بالموضوع الجديد على جميع المساجد
    activate_new_topic(khateb, topic[:300])
    db.session.commit()
    flash('تم اعتماد موضوعك الجديد: %s — وأُعيد تعيينك على جميع المساجد' % topic, 'success')
    return redirect(url_for('my'))


@app.route('/my/topic/cancel', methods=['POST'])
@login_required
def my_cancel_pending_topic():
    """إلغاء موضوع الخطبة القادمة المجدول"""
    khateb = current_khateb()
    if not khateb:
        logout_session()
        return redirect(url_for('login'))

    khateb.pending_topic = None
    khateb.pending_topic_mode = None
    khateb.pending_topic_approved = 0
    db.session.add(khateb)
    db.session.commit()

    flash('تم إلغاء موضوع الخطبة القادمة المجدول', 'success')
    return redirect(url_for('my'))


# ============================================
# مسارات المدير: حسابات الخطباء واعتماد المواضيع
# ============================================

@app.route('/khateb/<int:khateb_id>/allow', methods=['POST'])
@admin_required
def khateb_allow(khateb_id):
    """السماح للخطيب بالدخول بعد مراجعته في صفحة الإعدادات"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'error')
        return redirect(url_for('settings'))

    if khateb.is_active == 1:
        flash('حساب الشيخ %s مفعّل بالفعل' % khateb.name, 'info')
        return redirect(url_for('settings'))

    # لا يُسمح بالدخول قبل اكتمال بيانات الخطيب (موضوع الخطبة + المساجد + نظام التوفر)
    if not khateb.has_profile():
        flash('لا يمكن السماح للشيخ %s بالدخول قبل أن يكمل بياناته (موضوع الخطبة والمساجد ونظام التوفر).' % khateb.name, 'error')
        return redirect(url_for('settings'))

    khateb.is_active = 1
    db.session.add(khateb)
    db.session.commit()

    flash('تم السماح للشيخ %s بالدخول. سيظهر تلقائياً في توزيع الجدول عند إنشاء التوزيع.' % khateb.name, 'success')
    return redirect(url_for('settings'))


@app.route('/khateb/<int:khateb_id>/set_password', methods=['POST'])
@admin_required
def khateb_set_password(khateb_id):
    """تعيين كلمة مرور جديدة للخطيب (يختارها المدير)"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'error')
        return redirect(url_for('settings'))

    password = (request.form.get('password', '') or '').strip()
    if len(password) < 6:
        flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل', 'error')
        return redirect(url_for('settings'))

    khateb.password_hash = generate_password_hash(password)
    db.session.add(khateb)
    db.session.commit()

    flash('تم تعيين كلمة مرور جديدة للشيخ %s. أخبره بها ليتمكن من الدخول.' % khateb.name, 'success')
    return redirect(url_for('settings'))


@app.route('/khateb/<int:khateb_id>/toggle_active', methods=['POST'])
@admin_required
def khateb_toggle_active(khateb_id):
    """تفعيل / إيقاف دخول الخطيب"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        return jsonify({'success': False, 'message': 'الخطيب غير موجود'}), 404

    khateb.is_active = 0 if khateb.is_active in (None, 1) else 1
    db.session.add(khateb)
    db.session.commit()

    if khateb.is_active and not khateb.has_profile():
        msg = 'تم تفعيل دخول الخطيب — لكن لم يكمل بياناته بعد، لن يظهر في التوزيع حتى يكملها.'
    elif khateb.is_active:
        msg = 'تم تفعيل دخول الخطيب'
    else:
        msg = 'تم إيقاف دخول الخطيب'

    return jsonify({
        'success': True,
        'is_active': khateb.is_active,
        'message': msg
    })


@app.route('/assignment/<int:assignment_id>/complete', methods=['POST'])
@admin_required
def api_complete_assignment(assignment_id):
    """تسجيل أداء الخطبة (من قبل المدير بعد انتهاء الجمعة): completed + إضافة المسجد للمساجد المزارة"""
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'success': False, 'message': 'التعيين غير موجود'}), 404

    if assignment.status == 'cancelled':
        return jsonify({'success': False, 'message': 'هذا التعيين ملغى'}), 400

    assignment.status = 'completed'
    db.session.add(assignment)

    khateb = Khateb.query.get(assignment.khateb_id)
    message = 'تم تسجيل أداء الخطبة'
    if khateb:
        visited = khateb.get_visited_mosques_list()
        if assignment.mosque_id not in visited:
            visited.append(assignment.mosque_id)
            khateb.mosques_visited = json.dumps(visited)
            db.session.add(khateb)

    db.session.commit()

    # تفعيل الموضوع المجدول تلقائياً إذا أنهى الخطيب جميع المساجد
    if khateb and maybe_activate_queued_topic(khateb):
        message += ' — وتم تفعيل موضوعك الجديد: %s' % khateb.current_topic

    return jsonify({'success': True, 'message': message})


@app.route('/khateb/<int:khateb_id>/approve_topic', methods=['POST'])
@admin_required
def khateb_approve_topic(khateb_id):
    """اعتماد الموضوع الجديد المقترح من الخطيب

    - وضع 'reset': يُفعَّل فوراً وتُصفّر المساجد المزارة
    - وضع 'after_current': يُجدول للتفعيل تلقائياً بعد إنهاء الخطيب جميع المساجد
    """
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'error')
        return redirect(url_for('settings'))

    if not khateb.pending_topic:
        flash('لا يوجد موضوع مقترح لهذا الخطيب', 'error')
        return redirect(url_for('settings'))

    topic = khateb.pending_topic
    mode = khateb.pending_topic_mode or TOPIC_MODE_RESET

    if mode == TOPIC_MODE_AFTER_CURRENT:
        # يُجدول: يبقى الموضوع الحالي حتى ينتهي الخطيب من المساجد
        khateb.pending_topic_approved = 1
        db.session.add(khateb)
        db.session.commit()
        flash('تم اعتماد موضوع %s كموضوع قادم للخطيب %s — سيُفعَّل تلقائياً بعد إنهاء جميع المساجد'
              % (topic, khateb.name), 'success')
        return redirect(url_for('settings'))

    activate_new_topic(khateb, topic)
    db.session.commit()
    flash('تم اعتماد الموضوع الجديد لـ %s وتصفير قائمة المساجد المزارة' % khateb.name, 'success')
    return redirect(url_for('settings'))


@app.route('/khateb/<int:khateb_id>/activate_topic', methods=['POST'])
@admin_required
def khateb_activate_topic(khateb_id):
    """تفعيل موضوع الخطيب فوراً (بدون انتظار إنهاء المساجد)"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'error')
        return redirect(url_for('settings'))

    if not khateb.pending_topic:
        flash('لا يوجد موضوع مقترح لهذا الخطيب', 'error')
        return redirect(url_for('settings'))

    topic = khateb.pending_topic
    activate_new_topic(khateb, topic)
    db.session.commit()
    flash('تم تفعيل الموضوع %s للخطيب %s وتصفير المساجد المزارة' % (topic, khateb.name), 'success')
    return redirect(url_for('settings'))


@app.route('/khateb/<int:khateb_id>/reject_topic', methods=['POST'])
@admin_required
def khateb_reject_topic(khateb_id):
    """رفض Topic المقترح وإلغاؤه"""
    khateb = Khateb.query.get(khateb_id)
    if not khateb:
        flash('الخطيب غير موجود', 'error')
        return redirect(url_for('settings'))

    khateb.pending_topic = None
    khateb.pending_topic_mode = None
    khateb.pending_topic_approved = 0
    db.session.add(khateb)
    db.session.commit()
    flash('تم إلغاء الموضوع المقترح للخطيب %s' % khateb.name, 'success')
    return redirect(url_for('settings'))


if __name__ == '__main__':
    # Ensure required folders and the database exist when running directly.
    # Flask 2.3 removed `before_first_request`; initialize here under app context.
    warn_dev_defaults()
    with app.app_context():
        # ترحيل بسيط وقابل للتكرار (إضافة أعمدة ناقصة فقط)
        from migrate import run_migrations
        run_migrations()
        create_directories()

    app.run(debug=False, host='0.0.0.0', port=5000)