"""
نظام الجدولة التلقائية للمكافآت
==========================================
يقوم بحساب المكافآت تلقائياً بناءً على الفترات المحددة

يمكن تشغيل المجدول بطرق مختلفة:
- يومياً: للتحقق من المكافآت المستحقة
- أسبوعياً: لحساب المكافآت الأسبوعية
- شهرياً: لحساب المكافآت الشهرية (في أول يوم من الشهر)
"""

import schedule
import time
from threading import Thread
from datetime import datetime, date, timedelta
from calendar import monthrange
from bonus_calculator import BonusCalculator


class BonusScheduler:
    """مجدول المكافآت التلقائي"""
    
    def __init__(self, app):
        self.app = app
        self.is_running = False
        self._scheduler = schedule.Scheduler()
        
    def calculate_daily_bonuses(self):
        """حساب المكافآت اليومية"""
        with self.app.app_context():
            try:
                today = date.today()
                yesterday = today - timedelta(days=1)
                
                print(f"[BonusScheduler] حساب المكافآت اليومية: {yesterday}")
                
                bonuses = BonusCalculator.calculate_all_bonuses_for_period(
                    period_start=yesterday,
                    period_end=yesterday,
                    auto_approve=False  # تتطلب الموافقة اليدوية
                )
                
                if bonuses:
                    print(f"[BonusScheduler] ✓ تم حساب {len(bonuses)} مكافأة يومية")
                else:
                    print(f"[BonusScheduler] لا توجد مكافآت يومية لحسابها")
                    
            except Exception as e:
                print(f"[BonusScheduler] ❌ خطأ في حساب المكافآت اليومية: {e}")
    
    def calculate_weekly_bonuses(self):
        """حساب المكافآت الأسبوعية"""
        with self.app.app_context():
            try:
                today = date.today()
                # الأسبوع الماضي (من الاثنين إلى الأحد)
                last_monday = today - timedelta(days=today.weekday() + 7)
                last_sunday = last_monday + timedelta(days=6)
                
                print(f"[BonusScheduler] حساب المكافآت الأسبوعية: {last_monday} إلى {last_sunday}")
                
                bonuses = BonusCalculator.calculate_all_bonuses_for_period(
                    period_start=last_monday,
                    period_end=last_sunday,
                    auto_approve=False
                )
                
                if bonuses:
                    print(f"[BonusScheduler] ✓ تم حساب {len(bonuses)} مكافأة أسبوعية")
                else:
                    print(f"[BonusScheduler] لا توجد مكافآت أسبوعية لحسابها")
                    
            except Exception as e:
                print(f"[BonusScheduler] ❌ خطأ في حساب المكافآت الأسبوعية: {e}")
    
    def calculate_monthly_bonuses(self):
        """حساب المكافآت الشهرية"""
        with self.app.app_context():
            try:
                today = date.today()
                
                # الشهر الماضي
                if today.month == 1:
                    last_month_year = today.year - 1
                    last_month = 12
                else:
                    last_month_year = today.year
                    last_month = today.month - 1
                
                # أول يوم وآخر يوم من الشهر الماضي
                period_start = date(last_month_year, last_month, 1)
                last_day = monthrange(last_month_year, last_month)[1]
                period_end = date(last_month_year, last_month, last_day)
                
                print(f"[BonusScheduler] حساب المكافآت الشهرية: {period_start} إلى {period_end}")
                
                bonuses = BonusCalculator.calculate_all_bonuses_for_period(
                    period_start=period_start,
                    period_end=period_end,
                    auto_approve=False
                )
                
                if bonuses:
                    total_amount = sum(b.amount for b in bonuses)
                    print(f"[BonusScheduler] ✓ تم حساب {len(bonuses)} مكافأة شهرية بإجمالي {total_amount} ريال")
                else:
                    print(f"[BonusScheduler] لا توجد مكافآت شهرية لحسابها")
                    
            except Exception as e:
                print(f"[BonusScheduler] ❌ خطأ في حساب المكافآت الشهرية: {e}")
    
    def check_pending_bonuses(self):
        """التحقق من المكافآت المعلقة وإرسال تنبيهات"""
        with self.app.app_context():
            try:
                from models import EmployeeBonus
                
                pending_count = EmployeeBonus.query.filter_by(status='pending').count()
                
                if pending_count > 0:
                    print(f"[BonusScheduler] ⚠️ يوجد {pending_count} مكافأة معلقة تحتاج إلى موافقة")
                    
            except Exception as e:
                print(f"[BonusScheduler] ❌ خطأ في التحقق من المكافآت المعلقة: {e}")
    
    def setup_schedule(self):
        """إعداد جدول المهام"""
        # حساب المكافآت اليومية - كل يوم الساعة 1:00 صباحاً
        self._scheduler.every().day.at("01:00").do(self.calculate_daily_bonuses)
        
        # حساب المكافآت الأسبوعية - كل يوم اثنين الساعة 2:00 صباحاً
        self._scheduler.every().monday.at("02:00").do(self.calculate_weekly_bonuses)
        
        # حساب المكافآت الشهرية - أول يوم من كل شهر الساعة 3:00 صباحاً
        self._scheduler.every().day.at("03:00").do(self._check_and_calculate_monthly)
        
        # التحقق من المكافآت المعلقة - كل 6 ساعات
        self._scheduler.every(6).hours.do(self.check_pending_bonuses)
        
        print("[BonusScheduler] ✓ تم إعداد جدول المكافآت التلقائية")
        print("[BonusScheduler] - مكافآت يومية: 1:00 صباحاً")
        print("[BonusScheduler] - مكافآت أسبوعية: الاثنين 2:00 صباحاً")
        print("[BonusScheduler] - مكافآت شهرية: أول يوم من الشهر 3:00 صباحاً")
        print("[BonusScheduler] - فحص المكافآت المعلقة: كل 6 ساعات")
    
    def _check_and_calculate_monthly(self):
        """التحقق إذا كان اليوم هو أول يوم من الشهر"""
        today = date.today()
        if today.day == 1:
            self.calculate_monthly_bonuses()
    
    def start(self):
        """بدء المجدول في خيط منفصل"""
        if self.is_running:
            print("[BonusScheduler] المجدول يعمل بالفعل")
            return
        
        self.setup_schedule()
        self.is_running = True
        
        def run_scheduler():
            while self.is_running:
                self._scheduler.run_pending()
                time.sleep(60)  # التحقق كل دقيقة
        
        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        print("[BonusScheduler] 🚀 بدأ مجدول المكافآت")
    
    def stop(self):
        """إيقاف المجدول"""
        self.is_running = False
        self._scheduler.clear()
        print("[BonusScheduler] ⏸️ توقف مجدول المكافآت")
    
    def run_now(self, task_type='daily'):
        """تشغيل مهمة فوراً للاختبار"""
        with self.app.app_context():
            if task_type == 'daily':
                self.calculate_daily_bonuses()
            elif task_type == 'weekly':
                self.calculate_weekly_bonuses()
            elif task_type == 'monthly':
                self.calculate_monthly_bonuses()
            elif task_type == 'check':
                self.check_pending_bonuses()
            else:
                print(f"[BonusScheduler] نوع مهمة غير معروف: {task_type}")


# متغير عام للمجدول
_scheduler_instance = None


def get_bonus_scheduler(app):
    """الحصول على نسخة المجدول الوحيدة"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = BonusScheduler(app)
    return _scheduler_instance


def start_bonus_scheduler(app):
    """بدء مجدول المكافآت"""
    scheduler = get_bonus_scheduler(app)
    scheduler.start()
    return scheduler
