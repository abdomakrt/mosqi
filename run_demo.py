#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ملف تشغيل تجريبي لنظام توزيع الخطباء
作者: MiniMax Agent
"""

import sys
import os
import subprocess
import time

def check_requirements():
    """فحص المتطلبات"""
    print("🔍 فحص المتطلبات...")
    
    # فحص Python
    if sys.version_info < (3, 8):
        print("❌ يتطلب Python 3.8 أو أحدث")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    
    # فحص pip
    try:
        import pip
        print("✅ pip متوفر")
    except ImportError:
        print("❌ pip غير متوفر")
        return False
    
    return True

def install_dependencies():
    """تثبيت المكتبات المطلوبة"""
    print("\n📦 تثبيت المكتبات المطلوبة...")
    
    requirements = [
        "Flask==2.3.3",
        "Flask-SQLAlchemy==3.0.5"
    ]
    
    for req in requirements:
        print(f"تثبيت {req}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", req], 
                                stdout=subprocess.DEVNULL, 
                                stderr=subprocess.DEVNULL)
            print(f"✅ تم تثبيت {req}")
        except subprocess.CalledProcessError:
            print(f"❌ فشل في تثبيت {req}")
            return False
    
    return True

def run_system():
    """تشغيل النظام"""
    print("\n🚀 تشغيل نظام توزيع الخطباء...")
    print("=" * 60)
    
    try:
        # استيراد وتشغيل التطبيق
        from app import app, db
        
        print("✅ تم تحميل التطبيق بنجاح")
        print("🌐 بدء الخادم على http://localhost:5000")
        print("📱 افتح المتصفح واذهب للرابط أعلاه")
        print("🛑 اضغط Ctrl+C لإيقاف الخادم")
        print("=" * 60)
        
        # تشغيل الخادم
        app.run(debug=False, host='0.0.0.0', port=5000)
        
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف الخادم بواسطة المستخدم")
    except Exception as e:
        print(f"\n❌ خطأ في تشغيل النظام: {e}")
        return False
    
    return True

def show_demo_info():
    """عرض معلومات التجربة"""
    print("🎯 نظام توزيع الخطباء - تجربة تفاعلية")
    print("=" * 60)
    print("📋 ما ستجده في النظام:")
    print("   • 6 مساجد عينة جاهزة")
    print("   • 8 خطباء بمواضيع مختلفة")
    print("   • واجهة عربية كاملة")
    print("   • نظام توزيع ذكي")
    print("   • تتبع التقدم والحالة")
    print("=" * 60)
    print("🎮 خطوات التجربة:")
    print("   1. استكشف الصفحة الرئيسية")
    print("   2. راجع قائمة المساجد والخطباء")
    print("   3. أنشئ توزيع جديد للجمعة")
    print("   4. تابع حالة الخطباء")
    print("=" * 60)

def main():
    """الدالة الرئيسية"""
    print("🏛️ مرحباً بك في نظام توزيع الخطباء")
    print("المؤلف: MiniMax Agent")
    print("التاريخ: 2025-10-30\n")
    
    # عرض معلومات التجربة
    show_demo_info()
    
    # فحص المتطلبات
    if not check_requirements():
        print("\n❌ فشل في فحص المتطلبات. يرجى تثبيت Python 3.8+ و pip")
        input("اضغط Enter للخروج...")
        return
    
    # تثبيت المكتبات
    install_choice = input("\n❓ هل تريد تثبيت المكتبات المطلوبة؟ (y/n): ").lower()
    if install_choice in ['y', 'yes', 'نعم', 'ن']:
        if not install_dependencies():
            print("\n❌ فشل في تثبيت المكتبات")
            input("اضغط Enter للخروج...")
            return
    
    # تشغيل النظام
    print("\n✨ جاهز للتشغيل!")
    start_choice = input("❓ هل تريد بدء النظام الآن؟ (y/n): ").lower()
    if start_choice in ['y', 'yes', 'نعم', 'ن']:
        run_system()
    else:
        print("👋 شكراً لاستخدام النظام!")

if __name__ == "__main__":
    main()