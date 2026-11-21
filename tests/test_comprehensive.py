import unittest
import json
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash
from app import (
    app, db, Mosque, Khateb, Assignment, WeeklySchedule, AppSetting,
    DistributionEngine, cancel_and_reassign,
    create_local_backup, validate_backup_file, list_local_backups
)


class BaseTestCase(unittest.TestCase):
    """قاعدة الاختبارات المعزولة في الذاكرة لضمان عدم التأثير على قاعدة البيانات الفعلية"""
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

    def create_mosques(self, count=4):
        mosques = []
        for i in range(1, count + 1):
            m = Mosque(name=f"مسجد {i}", address=f"عنوان {i}")
            db.session.add(m)
            mosques.append(m)
        db.session.commit()
        return mosques

    def create_khatebs(self, count=4, active=1, profile_complete=1, availability_mode='always'):
        khatebs = []
        for i in range(1, count + 1):
            k = Khateb(
                name=f"الشيخ {i}",
                phone=f"050000000{i}",
                current_topic=f"موضوع الخطيب {i}",
                is_active=active,
                profile_complete=profile_complete,
                availability_mode=availability_mode,
                mosques_visited='[]',
                forbidden_mosques='[]'
            )
            k.password_hash = generate_password_hash("password123")
            db.session.add(k)
            khatebs.append(k)
        db.session.commit()
        return khatebs


class TestDistributionLogic(BaseTestCase):
    """اختبارات خوارزمية التوزيع ومنطق الدورات والراحة التناوبية"""

    def test_full_cycle_no_repetition_exact_match(self):
        """التحقق من الدورة الكاملة لـ 4 مساجد و 4 خطباء دون أي تكرار للمسجد"""
        mosques = self.create_mosques(4)
        khatebs = self.create_khatebs(4)
        engine = DistributionEngine()
        start_date = date(2026, 12, 4)

        # 4 أسابيع متتالية
        for week_idx in range(4):
            target_date = start_date + timedelta(days=7 * week_idx)
            success, msg = engine.distribute_for_week(target_date)
            self.assertTrue(success, f"فشل التوزيع للأسبوع {week_idx + 1}: {msg}")

            # التحقق من تغطية جميع المساجد الأربعة
            assignments = Assignment.query.filter_by(week_date=target_date, status='confirmed').all()
            self.assertEqual(len(assignments), 4, f"يجب تعيين 4 مساجد في الأسبوع {week_idx + 1}")

            assigned_mosque_ids = set(a.mosque_id for a in assignments)
            self.assertEqual(len(assigned_mosque_ids), 4, "يجب عدم وجود تكرار لنفس المسجد في نفس الأسبوع")

            assigned_khateb_ids = set(a.khateb_id for a in assignments)
            self.assertEqual(len(assigned_khateb_ids), 4, "يجب عدم وجود تكرار لنفس الخطيب في نفس الأسبوع")

        # بعد 4 أسابيع، كل خطيب يجب أن يكون زار جميع المساجد الأربعة دون أي تكرار
        for k in khatebs:
            k_obj = Khateb.query.get(k.id)
            visited = k_obj.get_visited_mosques_list()
            self.assertEqual(len(visited), 4, f"الخطيب {k.name} يجب أن يكون زار 4 مساجد بالتمام")
            self.assertEqual(set(visited), set(m.id for m in mosques), f"الخطيب {k.name} لم يزر كل المساجد")
            self.assertTrue(engine.should_change_topic(k.id), f"يجب أن يُطلب من الخطيب {k.name} تغيير الموضوع")

        # في الأسبوع الخامس، لا يمكن التوزيع بنفس الموضوع حتى يُغيَّر
        week_5 = start_date + timedelta(days=7 * 4)
        success_w5, msg_w5 = engine.distribute_for_week(week_5)
        self.assertFalse(success_w5, "يجب أن يفشل التوزيع بعد إكمال الدورة وقبل تغيير الموضوع")

    def test_fair_rest_rotation_more_khateebs_than_mosques(self):
        """التحقق من عدالة التناوب في الراحة: 4 مساجد و 6 خطباء (4 يخطبون و 2 في راحة دورية كل أسبوع)"""
        mosques = self.create_mosques(4)
        khatebs = self.create_khatebs(6)
        engine = DistributionEngine()
        start_date = date(2026, 12, 4)

        rest_counts = {k.id: 0 for k in khatebs}
        preach_counts = {k.id: 0 for k in khatebs}

        for week_idx in range(6):
            target_date = start_date + timedelta(days=7 * week_idx)
            success, msg = engine.distribute_for_week(target_date)
            self.assertTrue(success, f"فشل التوزيع للأسبوع {week_idx + 1}: {msg}")

            assignments = Assignment.query.filter_by(week_date=target_date, status='confirmed').all()
            self.assertEqual(len(assignments), 4, "يجب تعيين 4 خطباء فقط على المساجد الـ 4")

            preaching_ids = set(a.khateb_id for a in assignments)
            resting_ids = set(k.id for k in khatebs) - preaching_ids
            self.assertEqual(len(resting_ids), 2, "يجب أن يكون هناك بالضبط 2 خطباء في راحة دورية كل أسبوع")

            for k_id in preaching_ids:
                preach_counts[k_id] += 1
            for k_id in resting_ids:
                rest_counts[k_id] += 1

            # تحقق أسبوعي: من كان في راحة في الأسبوع السابق يجب أن يخطب هذا الأسبوع ولا يستمر في الراحة
            if week_idx > 0:
                prev_date = target_date - timedelta(days=7)
                prev_assignments = Assignment.query.filter_by(week_date=prev_date, status='confirmed').all()
                prev_preaching = set(a.khateb_id for a in prev_assignments)
                prev_resting = set(k.id for k in khatebs) - prev_preaching
                for r_id in prev_resting:
                    self.assertIn(r_id, preaching_ids, f"الخطيب {r_id} كان في راحة الأسبوع الماضي ويجب أن يخطب هذا الأسبوع ولا يستمر في الراحة!")

        # تحقق إجمالي بعد 6 أسابيع: الجميع خطب وتناوب الراحة متوازن (4 خطب و 2 راحة لكل خطيب)
        for k in khatebs:
            self.assertEqual(preach_counts[k.id], 4, f"الخطيب {k.name} يجب أن يكون خطب 4 مرات")
            self.assertEqual(rest_counts[k.id], 2, f"الخطيب {k.name} يجب أن يكون أخذ راحته مرتين")

    def test_forbidden_mosques_strictly_respected(self):
        """التحقق من عدم تعيين الخطيب في المسجد المستثنى له إطلاقاً"""
        mosques = self.create_mosques(4)
        khatebs = self.create_khatebs(4)

        # استثناء المسجد رقم 2 للشيخ 1
        khateb_1 = Khateb.query.get(khatebs[0].id)
        khateb_1.forbidden_mosques = json.dumps([mosques[1].id])
        db.session.commit()

        engine = DistributionEngine()
        start_date = date(2026, 12, 4)

        for week_idx in range(3):
            target_date = start_date + timedelta(days=7 * week_idx)
            success, msg = engine.distribute_for_week(target_date)
            self.assertTrue(success)

            # التأكد من أن الشيخ 1 لم يُعين أبداً في المسجد المستثنى
            a = Assignment.query.filter_by(
                week_date=target_date,
                khateb_id=khateb_1.id,
                mosque_id=mosques[1].id
            ).first()
            self.assertIsNone(a, "تم تعيين الخطيب في مسجد مستثنى وهذا مخالف!")

    def test_alternate_availability_mode(self):
        """التحقق من نظام التوفر (أسبوع متاح / أسبوع غير متاح)"""
        self.create_mosques(4)
        khatebs = self.create_khatebs(4)

        # ضبط الشيخ 1 على نظام أسبوع وأسبوع
        khateb_1 = Khateb.query.get(khatebs[0].id)
        khateb_1.availability_mode = 'alternate'
        khateb_1.alternate_offset = 0
        db.session.commit()

        engine = DistributionEngine()
        friday_1 = date(2026, 12, 4)
        friday_2 = date(2026, 12, 11)

        available_w1 = [k.id for k in engine.get_available_khutbas(friday_1)]
        available_w2 = [k.id for k in engine.get_available_khutbas(friday_2)]

        # يجب أن يكون متاحاً في أسبوع وغير متاح في الأسبوع التالي
        is_avail_w1 = khateb_1.id in available_w1
        is_avail_w2 = khateb_1.id in available_w2
        self.assertNotEqual(is_avail_w1, is_avail_w2, "نظام أسبوع وأسبوع لم يتبادل التوفر بين الأسبوعين!")

    def test_topic_change_resets_cycle(self):
        """التحقق من أن تغيير الموضوع يعيد ضبط الدورة للمساجد المزارة"""
        mosques = self.create_mosques(4)
        khatebs = self.create_khatebs(1)
        khateb = khatebs[0]

        # محاكاة زيارة الخطيب لمسجدين
        khateb.mosques_visited = json.dumps([mosques[0].id, mosques[1].id])
        db.session.commit()

        engine = DistributionEngine()
        unvisited_before = engine.get_unvisited_mosques(khateb.id)
        self.assertEqual(len(unvisited_before), 2)

        # تغيير الموضوع
        engine.reset_khateb_mosques(khateb.id)
        khateb_updated = Khateb.query.get(khateb.id)
        khateb_updated.current_topic = "موضوع جديد تماماً"
        khateb_updated.last_topic_change = datetime.utcnow()
        db.session.commit()

        unvisited_after = engine.get_unvisited_mosques(khateb.id)
        self.assertEqual(len(unvisited_after), 4, "بعد تغيير الموضوع يجب أن تصبح جميع المساجد متاحة من جديد")


class TestApologyAndIntegrity(BaseTestCase):
    """اختبارات الاعتذار، الاستبدال التلقائي، ومنع الخلل البرمجي والازدواجية"""

    def test_apology_creates_confirmed_replacement_and_blocks_undo(self):
        """اختبار: اعتذار الخطيب ينشئ بديلاً مؤكداً تلقائياً، والتراجع ملغي ومحمي من الانهيار"""
        mosques = self.create_mosques(2)
        khatebs = self.create_khatebs(3)  # خطيبان يعينان، وواحد احتياط

        target_date = date(2026, 12, 4)
        # تعيين الخطيب 1 في المسجد 1
        a1 = Assignment(
            khateb_id=khatebs[0].id,
            mosque_id=mosques[0].id,
            week_date=target_date,
            khutba_topic=khatebs[0].current_topic,
            status='confirmed'
        )
        # تعيين الخطيب 2 في المسجد 2
        a2 = Assignment(
            khateb_id=khatebs[1].id,
            mosque_id=mosques[1].id,
            week_date=target_date,
            khutba_topic=khatebs[1].current_topic,
            status='confirmed'
        )
        db.session.add_all([a1, a2])
        db.session.commit()

        # الخطيب 3 هو الاحتياط المتاح حالياً
        # اعتذار الخطيب 1 عبر cancel_and_reassign
        rep_id, _ = cancel_and_reassign(a1, update_visited=True, attach_original=False)
        db.session.commit()

        self.assertIsNotNone(rep_id, "يجب إيجاد بديل من الخطباء الاحتياط")
        rep_assignment = Assignment.query.get(rep_id)

        # التحقق من أن البديل تم تأكيده تلقائياً ومباشرة
        self.assertEqual(rep_assignment.status, 'confirmed', "الخطيب البديل يجب أن تكون حالته مؤكدة تلقائياً")
        self.assertEqual(rep_assignment.khateb_id, khatebs[2].id, "الخطيب البديل يجب أن يكون الخطيب الاحتياط")
        self.assertEqual(rep_assignment.mosque_id, mosques[0].id, "البديل يجب أن يعين في نفس مسجد الخطيب المعتذر")

        # التحقق من أن التعيين الأصلي أصبح ملغى
        self.assertEqual(a1.status, 'cancelled')

        # محاولة التراجع عن الاعتذار عبر المسار البرمجي
        with self.client.session_transaction() as sess:
            sess['role'] = 'khateb'
            sess['khateb_id'] = khatebs[0].id

        res_undo = self.client.post(f'/my/assignment/{a1.id}/undo_apologize', follow_redirects=True)
        self.assertEqual(res_undo.status_code, 200)
        html = res_undo.data.decode('utf-8')
        self.assertIn("لا يمكن التراجع عن الاعتذار", html, "يجب رفض التراجع عن الاعتذار صراحة لحماية النظام من الازدواجية")

        # التأكد من عدم حدوث خلل في قاعدة البيانات وأن المسجد لم يُعيّن له خطيبان
        active_in_mosque = Assignment.query.filter(
            Assignment.mosque_id == mosques[0].id,
            Assignment.week_date == target_date,
            Assignment.status != 'cancelled'
        ).all()
        self.assertEqual(len(active_in_mosque), 1, "يجب أن يكون هناك خطيب نشط واحد فقط للمسجد")

    def test_unique_constraint_prevents_duplicate_active_assignments(self):
        """التحقق من أن قيد الفهرس الفريد يمنع تكرار خطيبين نشطين لنفس المسجد في نفس الأسبوع"""
        mosques = self.create_mosques(1)
        khatebs = self.create_khatebs(2)
        target_date = date(2026, 12, 4)

        a1 = Assignment(
            khateb_id=khatebs[0].id,
            mosque_id=mosques[0].id,
            week_date=target_date,
            khutba_topic="موضوع 1",
            status='confirmed'
        )
        db.session.add(a1)
        db.session.commit()

        # محاولة إضافة تعيين نشط آخر لنفس المسجد ونفس الأسبوع
        a2 = Assignment(
            khateb_id=khatebs[1].id,
            mosque_id=mosques[0].id,
            week_date=target_date,
            khutba_topic="موضوع 2",
            status='confirmed'
        )
        db.session.add(a2)
        with self.assertRaises(Exception):
            db.session.commit()
        db.session.rollback()


class TestSecurityAndAuth(BaseTestCase):
    """اختبارات الصلاحيات والحماية وإدارة الجلسات"""

    def test_unauthorized_access_redirects_to_login(self):
        """التحقق من أن الصفحات المحمية تحول الزائر غير المسجل إلى صفحة الدخول"""
        protected_routes = ['/distribution', '/settings', '/khutbas', '/mosques', '/my']
        for route in protected_routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 302, f"المسار {route} يجب أن يحول الزائر غير المسجل")
            self.assertIn('/login', res.headers['Location'])

    def test_khateb_cannot_access_admin_pages(self):
        """التحقق من أن حساب الخطيب لا يمكنه الوصول لصفحات إدارة النظام"""
        khatebs = self.create_khatebs(1)
        with self.client.session_transaction() as sess:
            sess['role'] = 'khateb'
            sess['khateb_id'] = khatebs[0].id

        admin_routes = ['/settings', '/distribution', '/khutbas', '/mosques']
        for route in admin_routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 302)
            self.assertIn('/my', res.headers['Location'], f"الخطيب يجب أن يُحوَّل إلى /my عند محاولة فتح {route}")

    def test_khateb_login_flow(self):
        """التحقق من تسجيل دخول الخطيب برقم الهاتف وكلمة المرور المشفرة"""
        khatebs = self.create_khatebs(1)
        k = khatebs[0]

        # تسجيل دخول خاطئ
        res_fail = self.client.post('/login', data={'role': 'khateb', 'phone': k.phone, 'password': 'wrongpassword'}, follow_redirects=True)
        self.assertIn('كلمة المرور غير صحيحة', res_fail.data.decode('utf-8'))

        # تسجيل دخول صحيح
        res_success = self.client.post('/login', data={'role': 'khateb', 'phone': k.phone, 'password': 'password123'}, follow_redirects=True)
        self.assertEqual(res_success.status_code, 200)
        self.assertIn(f'أهلاً بك {k.name}', res_success.data.decode('utf-8'))


class TestUIRenderingAndAPIs(BaseTestCase):
    """اختبارات استجابة القوالب والـ APIs بدون أي أخطاء 500"""

    def test_admin_pages_render_successfully(self):
        """التحقق من عرض صفحات لوحة التحكم للمدير بنجاح (HTTP 200)"""
        self.create_mosques(2)
        self.create_khatebs(2)

        with self.client.session_transaction() as sess:
            sess['role'] = 'admin'

        routes = [
            '/',
            '/distribution',
            '/distribution?date=2026-12-04',
            '/khutbas',
            '/mosques',
            '/settings'
        ]
        for r in routes:
            res = self.client.get(r)
            self.assertEqual(res.status_code, 200, f"الصفحة {r} فشلت في العرض")
            html = res.data.decode('utf-8')
            if 'distribution' in r:
                self.assertIn('جدول الخطباء الاحتياطي', html, "جدول الاحتياطي مفقود في صفحة التوزيع")

    def test_apis_return_valid_json(self):
        """التحقق من سلامة وصحة مخرجات جميع واجهات الـ JSON APIs"""
        self.create_mosques(2)
        khatebs = self.create_khatebs(3)
        target_date = date(2026, 12, 4)

        with self.client.session_transaction() as sess:
            sess['role'] = 'admin'

        engine = DistributionEngine()
        engine.distribute_for_week(target_date)

        # 1. API تفاصيل الأسبوع
        res_week = self.client.get(f'/api/distribution/week/{target_date}')
        self.assertEqual(res_week.status_code, 200)
        data_week = res_week.get_json()
        self.assertIn('assignments', data_week)
        self.assertIn('reserve_khutbas', data_week)
        self.assertEqual(len(data_week['reserve_khutbas']), 1)  # خطيب واحد احتياط

        # 2. API سجل الأسابيع
        res_hist = self.client.get('/api/distribution/history')
        self.assertEqual(res_hist.status_code, 200)
        self.assertIsInstance(res_hist.get_json(), list)

        # 3. API جدول الخطيب
        res_sched = self.client.get(f'/api/khateb/{khatebs[0].id}/schedule')
        self.assertEqual(res_sched.status_code, 200)
        data_sched = res_sched.get_json()
        self.assertIn('schedule', data_sched)

        # 4. API حالة الخطباء
        res_status = self.client.get('/api/khutbas/status')
        self.assertEqual(res_status.status_code, 200)


class TestBackupAndRestore(BaseTestCase):
    """اختبار وظيفة النسخ الاحتياطي واستعادة البيانات"""

    def test_backup_validation(self):
        """التحقق من صحة ملفات النسخ الاحتياطي"""
        # مسار غير موجود
        ok, _ = validate_backup_file('/non/existent/path.db')
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
