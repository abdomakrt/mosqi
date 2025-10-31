#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
خوارزمية توزيع مجموعة على مجموعة أخرى مع التنبيه وتغيير الأرقام
作者: MiniMax Agent
"""

from typing import List, Dict, Any
import time
import random
from dataclasses import dataclass


@dataclass
class Element:
    """عنصر في المجموعة الأولى"""
    name: str
    number: int
    distribution_count: int = 0
    
    def __str__(self):
        return f"الاسم: {self.name}, الرقم: {self.number}"


class DistributionAlgorithm:
    """خوارزمية التوزيع بين المجموعات"""
    
    def __init__(self, group1: List[Element], group2: List[Any]):
        self.group1 = group1
        self.group2 = group2
        self.distribution_log = []
        
    def display_current_state(self, current_element: Element):
        """عرض الحالة الحالية"""
        print(f"\n{'='*50}")
        print(f"العنصر الحالي: {current_element}")
        print(f"توزيع سابق: {current_element.distribution_count} مرة")
        print(f"حجم المجموعة الثانية: {len(self.group2)} عنصر")
        print(f"{'='*50}\n")
        
    def alert_change_required(self, current_element: Element):
        """تنبيه ضرورة تغيير الرقم"""
        old_number = current_element.number
        new_number = random.randint(100, 999)
        current_element.number = new_number
        current_element.distribution_count += 1
        
        print(f"⚠️  تنبيه: يجب تغيير الرقم")
        print(f"الرقم القديم: {old_number}")
        print(f"الرقم الجديد: {new_number}")
        
        # تسجيل في السجل
        log_entry = {
            'element_name': current_element.name,
            'old_number': old_number,
            'new_number': new_number,
            'distribution_round': current_element.distribution_count
        }
        self.distribution_log.append(log_entry)
        
        return new_number
        
    def process_group2_elements(self, current_element: Element):
        """معالجة جميع عناصر المجموعة الثانية"""
        print(f"بدء المرور على عناصر المجموعة الثانية للعنصر: {current_element.name}")
        
        for i, item in enumerate(self.group2, 1):
            print(f"  [{i}/{len(self.group2)}] معالجة العنصر: {item}")
            time.sleep(0.1)  # محاكاة المعالجة
            
        print(f"انتهاء المرور على عناصر المجموعة الثانية للعنصر: {current_element.name}")
        
    def distribute_all_elements(self, show_steps: bool = True):
        """توزيع جميع عناصر المجموعة الأولى على المجموعة الثانية"""
        print("🚀 بدء عملية التوزيع الشاملة")
        print(f"عدد عناصر المجموعة الأولى: {len(self.group1)}")
        print(f"عدد عناصر المجموعة الثانية: {len(self.group2)}")
        
        if show_steps:
            input("اضغط Enter لبدء العملية...")
            
        cycle_count = 1
        
        while True:
            print(f"\n🔄 دورة توزيع جديدة - الدورة رقم: {cycle_count}")
            
            any_changes_made = False
            
            for element in self.group1:
                # عرض الحالة الحالية
                if show_steps:
                    self.display_current_state(element)
                
                # تنبيه تغيير الرقم
                print(f"\n🔔 خطوة التنبيه:")
                self.alert_change_required(element)
                any_changes_made = True
                
                if show_steps:
                    input("اضغط Enter للمتابعة...")
                
                # معالجة عناصر المجموعة الثانية
                print(f"\n📋 خطوة المعالجة:")
                self.process_group2_elements(element)
                
                if show_steps:
                    input("اضغط Enter للانتقال للعنصر التالي...")
                    
            # عرض ملخص الدورة
            print(f"\n📊 ملخص الدورة رقم {cycle_count}:")
            for element in self.group1:
                print(f"  - {element.name}: توزيع {element.distribution_count} مرة")
                
            # سؤال المتابعة
            if show_steps:
                continue_choice = input("\nهل تريد الاستمرار للدورة التالية؟ (y/n): ").lower()
                if continue_choice not in ['y', 'yes', 'نعم', 'ن']:
                    break
            
            cycle_count += 1
            
            # تجنب حلقة لا نهائية في العرض التلقائي
            if not show_steps and cycle_count > 3:
                print("تم تنفيذ 3 دورات (الحد الأقصى للعرض التلقائي)")
                break
                
        print(f"\n✅ انتهت عملية التوزيع بعد {cycle_count-1} دورة")
        
    def show_distribution_log(self):
        """عرض سجل التوزيع"""
        print(f"\n📋 سجل التوزيع:")
        print(f"{'الدورة':<6} {'العنصر':<15} {'الرقم القديم':<10} {'الرقم الجديد':<10}")
        print("-" * 50)
        
        for entry in self.distribution_log:
            print(f"{entry['distribution_round']:<6} {entry['element_name']:<15} "
                  f"{entry['old_number']:<10} {entry['new_number']:<10}")


def create_sample_groups():
    """إنشاء مجموعات عينة للاختبار"""
    # إنشاء عناصر المجموعة الأولى
    group1_elements = [
        Element("أحمد", 1001),
        Element("فاطمة", 1002),
        Element("محمد", 1003),
        Element("عائشة", 1004),
        Element("عمر", 1005)
    ]
    
    # إنشاء عناصر المجموعة الثانية
    group2_elements = [
        "مهمة_01", "مهمة_02", "مهمة_03", "مهمة_04", "مهمة_05",
        "مهمة_06", "مهمة_07", "مهمة_08", "مهمة_09", "مهمة_10"
    ]
    
    return group1_elements, group2_elements


def interactive_mode():
    """الوضع التفاعلي"""
    print("🎯 الوضع التفاعلي - خوارزمية التوزيع")
    
    # إنشاء المجموعات
    group1, group2 = create_sample_groups()
    
    # إنشاء خوارزمية التوزيع
    algorithm = DistributionAlgorithm(group1, group2)
    
    # تشغيل التوزيع
    algorithm.distribute_all_elements(show_steps=True)
    
    # عرض السجل
    algorithm.show_distribution_log()


def automatic_mode():
    """الوضع التلقائي"""
    print("🤖 الوضع التلقائي - خوارزمية التوزيع")
    
    # إنشاء المجموعات
    group1, group2 = create_sample_groups()
    
    # إنشاء خوارزمية التوزيع
    algorithm = DistributionAlgorithm(group1, group2)
    
    # تشغيل التوزيع (بدون تفاعل)
    algorithm.distribute_all_elements(show_steps=False)


def main():
    """الدالة الرئيسية"""
    print("=" * 60)
    print("خوارزمية توزيع مجموعة على مجموعة أخرى")
    print("المؤلف: MiniMax Agent")
    print("=" * 60)
    
    while True:
        print("\nاختر وضع التشغيل:")
        print("1. الوضع التفاعلي (مع عرض الخطوات)")
        print("2. الوضع التلقائي (عرض سريع)")
        print("3. خروج")
        
        choice = input("اختيارك (1-3): ").strip()
        
        if choice == "1":
            interactive_mode()
        elif choice == "2":
            automatic_mode()
        elif choice == "3":
            print("تم إنهاء البرنامج")
            break
        else:
            print("اختيار غير صحيح، يرجى المحاولة مرة أخرى")
            
        # سؤال المتابعة
        continue_choice = input("\nهل تريد تشغيل البرنامج مرة أخرى؟ (y/n): ").lower()
        if continue_choice not in ['y', 'yes', 'نعم']:
            break


if __name__ == "__main__":
    main()