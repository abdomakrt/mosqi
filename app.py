#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام توزيع الخطباء على المساجد
作者: MiniMax Agent
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
import json
from dataclasses import dataclass
from typing import List, Dict, Optional

app = Flask(__name__)
app.secret_key = 'خطبة_توزيع_مفاتيح_سرية_2025'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///khutba_distribution.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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


class Khateb(db.Model):
    """نموذج الخطيب"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    current_topic = db.Column(db.String(300), default="موضوع افتراضي")
    last_topic_change = db.Column(db.DateTime, default=datetime.utcnow)
    mosques_visited = db.Column(db.Text)  # JSON array of mosque IDs
    rest_weeks = db.Column(db.Integer, default=0)  # أسابيع الراحة
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
            'mosques_visited': json.loads(self.mosques_visited or '[]')
        }

    def get_visited_mosques_list(self):
        """إرجاع قائمة المساجد المزارة"""
        return json.loads(self.mosques_visited or '[]')


class Assignment(db.Model):
    """نموذج التعيين الأسبوعي"""
    id = db.Column(db.Integer, primary_key=True)
    khateb_id = db.Column(db.Integer, db.ForeignKey('khateb.id'), nullable=False)
    mosque_id = db.Column(db.Integer, db.ForeignKey('mosque.id'), nullable=False)
    week_date = db.Column(db.Date, nullable=False)  # تاريخ الجمعة
    khutba_topic = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='confirmed')  # confirmed, completed, cancelled
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

    def get_available_khutbas(self):
        """الحصول على قائمة الخطباء المتاحين (غير في راحة)"""
        khutbas = Khateb.query.filter(Khateb.rest_weeks == 0).all()
        return khutbas

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
        # التأكد من عدم وجود توزيع مسبق لهذا الأسبوع
        existing = Assignment.query.filter_by(week_date=target_friday).first()
        if existing:
            return False, "يوجد توزيع مسبق لهذا الأسبوع"

        # تحديث أسابيع الراحة
        self.update_rest_weeks()

        # الحصول على الخطباء المتاحين
        available_khutbas = self.get_available_khutbas()
        mosques = Mosque.query.all()

        if len(available_khutbas) == 0:
            return False, "لا يوجد خطباء متاحون حالياً"

        if len(mosques) == 0:
            return False, "لا يوجد مساجد مسجلة"

        assignments = []
        
        # توزيع الذكي: كل خطيب يذهب لمسجد لم يزره من قبل
        used_mosques = set()
        
        for khateb in available_khutbas:
            unvisited = self.get_unvisited_mosques(khateb.id)
            
            # تصفية المساجد المستخدمة بالفعل هذا الأسبوع
            available_mosques = [m_id for m_id in unvisited if m_id not in used_mosques]
            
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
                    khutba_topic=khateb.current_topic
                )
                assignments.append(assignment)
        
        # إذا لم تُوزع جميع المساجد، استخدم خطباء عاديين
        remaining_mosques = [m for m in mosques if m.id not in used_mosques]
        
        if remaining_mosques and len(available_khutbas) > len(assignments):
            for i, mosque in enumerate(remaining_mosques):
                if i < len(available_khutbas) - len(assignments):
                    khateb = available_khutbas[i]
                    assignment = Assignment(
                        khateb_id=khateb.id,
                        mosque_id=mosque.id,
                        week_date=target_friday,
                        khutba_topic=khateb.current_topic
                    )
                    assignments.append(assignment)

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
        """فحص إذا كان يجب على الخطيب تغيير الموضوع"""
        khateb = Khateb.query.get(khateb_id)
        visited = khateb.get_visited_mosques_list()
        total_mosques = len(Mosque.query.all())
        
        return len(visited) >= total_mosques

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
                mosques_visited=json.dumps([])
            )
            db.session.add(khateb)

    db.session.commit()


# ============================================
# Routes - صفحات الويب
# ============================================

@app.route('/')
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
def mosques():
    """صفحة إدارة المساجد"""
    mosques = Mosque.query.all()
    # Convert SQLAlchemy models to dictionaries for JSON serialization
    mosque_list = [mosque.to_dict() for mosque in mosques]
    return render_template('mosques.html', mosques=mosque_list)


@app.route('/mosque/add', methods=['POST'])
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
def khutbas():
    """صفحة إدارة الخطباء"""
    khutbas = Khateb.query.all()
    mosques = Mosque.query.all()
    return render_template('khutbas.html', khutbas=khutbas, mosques=mosques)


@app.route('/khateb/add', methods=['POST'])
def add_khateb():
    """إضافة خطيب جديد"""
    name = request.form.get('name')
    phone = request.form.get('phone')
    topic = request.form.get('topic', 'موضوع افتراضي')
    visited_mosques = request.form.getlist('visited_mosques')
    
    if not name:
        flash('اسم الخطيب مطلوب', 'error')
        return redirect(url_for('khutbas'))
    
    khateb = Khateb(
        name=name,
        phone=phone,
        current_topic=topic,
        mosques_visited=json.dumps([int(m) for m in visited_mosques])
    )
    db.session.add(khateb)
    db.session.commit()
    
    flash('تم إضافة الخطيب بنجاح', 'success')
    return redirect(url_for('khutbas'))


@app.route('/distribution')
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
    
    return redirect(url_for('distribution'))


@app.route('/khateb/<int:khateb_id>/change_topic', methods=['POST'])
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
        'progress_percentage': (len(visited_mosques) / total_mosques) * 100,
        'should_change_topic': should_change,
        'visited_mosques': visited_mosques
    }
    
    return jsonify(status)


@app.route('/api/khutbas/status')
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
            'progress_percentage': (len(visited_mosques) / total_mosques) * 100,
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
    
    # إنشاء قاعدة البيانات وإضافة البيانات العينة
    db.create_all()
    init_sample_data()


@app.route('/api/distribution/history')
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
def api_assignment_details(assignment_id):
    """API للحصول على تفاصيل تعيين معين"""
    assignment = Assignment.query.get(assignment_id)
    
    if not assignment:
        return jsonify({'error': 'التعيين غير موجود'}), 404
    
    details = assignment.to_dict()
    details.update({
        'created_at': assignment.created_at.strftime('%Y-%m-%d %H:%M:%S')
    })
    
    return jsonify(details)


@app.route('/api/assignment/<int:assignment_id>', methods=['DELETE'])
def api_delete_assignment(assignment_id):
    """API لحذف تعيين"""
    assignment = Assignment.query.get(assignment_id)
    
    if not assignment:
        return jsonify({'success': False, 'message': 'التعيين غير موجود'}), 404
    
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم حذف التعيين بنجاح'})


@app.route('/khateb/<int:khateb_id>/update_visits', methods=['POST'])
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


if __name__ == '__main__':
    # Ensure required folders and the database exist when running directly.
    # Flask 2.3 removed `before_first_request`; initialize here under app context.
    with app.app_context():
        create_directories()

    app.run(debug=True, host='0.0.0.0', port=5000)