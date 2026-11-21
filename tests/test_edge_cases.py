import unittest
import json
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash
from app import (
    app, db, Mosque, Khateb, Assignment, WeeklySchedule,
    DistributionEngine, normalize_phone
)


class EdgeCasesTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test-secret-key'
        self.app = app
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_more_mosques_than_khateebs_partial_coverage(self):
        """اختبار حالة نقص الخطباء: 5 مساجد و 3 خطباء فقط (يجب تغطية 3 مساجد وبقاء 2 دون انهيار)"""
        for i in range(1, 6):
            db.session.add(Mosque(name=f"مسجد {i}"))
        for i in range(1, 4):
            k = Khateb(name=f"الشيخ {i}", phone=f"05000000{i}", is_active=1, profile_complete=1, current_topic="موضوع")
            db.session.add(k)
        db.session.commit()

        engine = DistributionEngine()
        target_date = date(2026, 12, 4)
        success, msg = engine.distribute_for_week(target_date)
        self.assertTrue(success, f"التوزيع الجزئي يجب أن ينجح: {msg}")

        assignments = Assignment.query.filter_by(week_date=target_date, status='confirmed').all()
        self.assertEqual(len(assignments), 3, "يجب تعيين جميع الخطباء المتاحين الـ 3")
        assigned_mosques = set(a.mosque_id for a in assignments)
        self.assertEqual(len(assigned_mosques), 3, "لا يوجد تكرار في المساجد المعينة")

    def test_seasonal_topic_lifecycle(self):
        """اختبار دورة حياة الموضوع الموسمي المؤقت وانتهاء صلاحيته"""
        m = Mosque(name="مسجد 1")
        k = Khateb(name="الشيخ 1", phone="050000001", is_active=1, profile_complete=1, current_topic="موضوع أساسي")
        db.session.add_all([m, k])
        db.session.commit()

        # تفعيل موضوع موسمي حتى 2026-12-10
        k.seasonal_topic = "فضل رمضان"
        k.seasonal_until = date(2026, 12, 10)
        db.session.commit()

        engine = DistributionEngine()

        # جمعة قبل الانتهاء: يجب أن يكون موضوع الخطبة هو الموضوع الموسمي
        friday_before = date(2026, 12, 4)
        self.assertTrue(k.is_seasonal_active(friday_before))
        success1, _ = engine.distribute_for_week(friday_before)
        self.assertTrue(success1)
        a1 = Assignment.query.filter_by(week_date=friday_before).first()
        self.assertEqual(a1.khutba_topic, "فضل رمضان")

        # جمعة بعد الانتهاء: يجب أن يعود تلقائياً للموضوع الأساسي
        friday_after = date(2026, 12, 11)
        self.assertFalse(k.is_seasonal_active(friday_after))

    def test_phone_normalization_arabic_and_symbols(self):
        """التحقق من توحيد أرقام الهواتف بكافة الصيغ (أرقام عربية وإنجليزية ومسافات وفواصل)"""
        expected = "966501234567"
        self.assertEqual(normalize_phone("0501234567"), expected)
        self.assertEqual(normalize_phone("050-123-4567"), expected)
        self.assertEqual(normalize_phone(" 050 123 4567 "), expected)
        # أرقام مشرقية (عربية)
        self.assertEqual(normalize_phone("٠٥٠١٢٣٤٥٦٧"), expected)
        # مع كود الدولة
        self.assertEqual(normalize_phone("+966501234567"), expected)

    def test_delete_mosque_cleans_assignments(self):
        """التحقق من أن حذف المسجد لا يترك بيانات تالفة في التعيينات"""
        m = Mosque(name="مسجد تجريبي")
        k = Khateb(name="الشيخ 1", phone="050000001", is_active=1, profile_complete=1, current_topic="موضوع")
        db.session.add_all([m, k])
        db.session.commit()

        target_date = date(2026, 12, 4)
        a = Assignment(khateb_id=k.id, mosque_id=m.id, week_date=target_date, khutba_topic="موضوع", status='confirmed')
        db.session.add(a)
        db.session.commit()

        # تسجيل دخول المدير وحذف المسجد عبر API
        with self.client.session_transaction() as sess:
            sess['role'] = 'admin'

        res = self.client.delete(f'/mosque/{m.id}/delete')
        self.assertEqual(res.status_code, 200)

        # التحقق من حذف المسجد وحذف التعيين المرتبط به
        self.assertIsNone(Mosque.query.get(m.id))
        self.assertIsNone(Assignment.query.filter_by(mosque_id=m.id).first())

    def test_delete_khateb_cleans_assignments(self):
        """التحقق من أن حذف الخطيب ينظف التعيينات المرتبطة به"""
        m = Mosque(name="مسجد 1")
        k = Khateb(name="الشيخ للمسح", phone="050000099", is_active=1, profile_complete=1, current_topic="موضوع")
        db.session.add_all([m, k])
        db.session.commit()

        target_date = date(2026, 12, 4)
        a = Assignment(khateb_id=k.id, mosque_id=m.id, week_date=target_date, khutba_topic="موضوع", status='confirmed')
        db.session.add(a)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['role'] = 'admin'

        res = self.client.delete(f'/khateb/{k.id}/delete')
        self.assertEqual(res.status_code, 200)

        self.assertIsNone(Khateb.query.get(k.id))
        self.assertIsNone(Assignment.query.filter_by(khateb_id=k.id).first())


if __name__ == '__main__':
    unittest.main()
