#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مثال مبسط لخوارزمية التوزيع
作者: MiniMax Agent
"""

from dataclasses import dataclass
import random


@dataclass
class Employee:
    """موظف في المجموعة الأولى"""
    name: str
    id_number: int
    
    def __str__(self):
        return f"{self.name} (ID: {self.id_number})"


def simple_distribution_example():
    """مثال بسيط للتوزيع"""
    
    # المجموعة الأولى: موظفين
    employees = [
        Employee("أحمد", 1001),
        Employee("فاطمة", 1002), 
        Employee("محمد", 1003)
    ]
    
    # المجموعة الثانية: المهام
    tasks = ["مهمة_التقارير", "مهمة_المبيعات", "مهمة_التسويق", "مهمة_الدعم"]
    
    print("🎯 بدء خوارزمية التوزيع المبسطة")
    print(f"عدد الموظفين: {len(employees)}")
    print(f"عدد المهام: {len(tasks)}")
    
    cycle = 1
    
    while cycle <= 2:  # دورتان فقط للعرض
        print(f"\n🔄 الدورة رقم {cycle}")
        print("-" * 40)
        
        for employee in employees:
            # عرض معلومات الموظف
            print(f"\n👤 معالجة الموظف: {employee.name}")
            print(f"   الرقم الحالي: {employee.id_number}")
            
            # تغيير الرقم
            old_id = employee.id_number
            employee.id_number = random.randint(2000, 2999)
            print(f"   تم تغيير الرقم من {old_id} إلى {employee.id_number}")
            
            # المرور على المهام
            print("   🔄 المرور على المهام:")
            for i, task in enumerate(tasks, 1):
                print(f"      [{i}] معالجة: {task}")
            
            print(f"   ✅ انتهى معالجة {employee.name}")
        
        print(f"\n📊 ملخص الدورة {cycle}:")
        for emp in employees:
            print(f"   {emp}")
            
        cycle += 1
    
    print(f"\n✅ انتهت عملية التوزيع بعد {cycle-1} دورة")


def alternative_implementation():
    """تنفيذ بديل باستخدام functions"""
    
    def process_distribution_cycle(group1, group2):
        """معالجة دورة واحدة من التوزيع"""
        print(f"🔄 معالجة دورة جديدة - {len(group1)} عنصر في المجموعة الأولى")
        
        for element in group1:
            print(f"\nالعنصر: {element}")
            
            # تغيير الرقم
            element['رقم'] = random.randint(1000, 9999)
            print(f"  تم تغيير الرقم إلى: {element['رقم']}")
            
            # المرور على المجموعة الثانية
            print("  معالجة عناصر المجموعة الثانية:")
            for item in group2:
                print(f"    ✨ {item}")
        
        return True
    
    # مثال بالdictionaries
    group1_data = [
        {"اسم": "محمد", "رقم": 1001},
        {"اسم": "فاطمة", "رقم": 1002}
    ]
    
    group2_data = ["مهمة_1", "مهمة_2", "مهمة_3"]
    
    print("\n🔄 مثال بديل باستخدام Dictionaries")
    
    # تنفيذ دورتين
    for cycle in range(1, 3):
        print(f"\nالدورة رقم {cycle}")
        process_distribution_cycle(group1_data, group2_data)


def main():
    """الدالة الرئيسية"""
    print("=" * 50)
    print("أمثلة خوارزمية التوزيع")
    print("المؤلف: MiniMax Agent")
    print("=" * 50)
    
    # تشغيل المثال البسيط
    simple_distribution_example()
    
    print("\n" + "="*50)
    
    # تشغيل المثال البديل
    alternative_implementation()
    
    print("\n" + "="*50)
    print("تم تشغيل جميع الأمثلة بنجاح! ✅")


if __name__ == "__main__":
    main()