/**
 * ملف JavaScript الرئيسي لنظام توزيع الخطباء
 * 作者: MiniMax Agent
 */

// ============================================
// إعداد عام
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    console.log('تم تحميل نظام توزيع الخطباء');
    
    // إضافة تأثيرات الحركة للعناصر
    initAnimations();
    
    // تحديث الساعة
    updateClock();
    setInterval(updateClock, 1000);
    
    // إضافة تنبيهات النقر
    initTooltips();
    
    // تحديث الإشعارات
    initNotifications();
});

// ============================================
// الوظائف العامة
// ============================================

/**
 * تحديث الساعة الحالية
 */
function updateClock() {
    const clockElement = document.getElementById('currentTime');
    if (clockElement) {
        const now = new Date();
        const timeString = now.toLocaleTimeString('ar-SA', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
        clockElement.textContent = timeString;
    }
}

/**
 * إعداد الحركة للعناصر
 */
function initAnimations() {
    // تأثير التدوير للعناصر التفاعلية
    const interactiveElements = document.querySelectorAll('.btn, .card, .table tbody tr');
    
    interactiveElements.forEach(element => {
        element.addEventListener('mouseenter', function() {
            this.style.transform = 'scale(1.02)';
        });
        
        element.addEventListener('mouseleave', function() {
            this.style.transform = 'scale(1)';
        });
    });
    
    // تأثير الظهور التدريجي
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('fade-in');
            }
        });
    });
    
    document.querySelectorAll('.card, .row > div').forEach(el => {
        observer.observe(el);
    });
}

/**
 * إعداد النقرات (Tooltips)
 */
function initTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[title]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

/**
 * إعداد الإشعارات
 */
function initNotifications() {
    // فحص إذا كان هناك إشعارات معلقة
    const pendingNotifications = localStorage.getItem('pendingNotifications');
    if (pendingNotifications) {
        const notifications = JSON.parse(pendingNotifications);
        notifications.forEach(notification => {
            showNotification(notification.message, notification.type);
        });
        localStorage.removeItem('pendingNotifications');
    }
}

/**
 * عرض إشعار
 */
function showNotification(message, type = 'info', duration = 5000) {
    const notificationId = 'notification-' + Date.now();
    const iconMap = {
        'success': 'fas fa-check-circle',
        'error': 'fas fa-exclamation-triangle',
        'warning': 'fas fa-exclamation-circle',
        'info': 'fas fa-info-circle'
    };
    
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show notification`;
    notification.id = notificationId;
    notification.innerHTML = `
        <i class="${iconMap[type]}"></i>
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Append to body and position fixed so notification doesn't block underlying UI
    notification.style.position = 'fixed';
    notification.style.top = '20px';
    notification.style.left = '20px';
    notification.style.width = '320px';
    notification.style.zIndex = 1080;
    document.body.appendChild(notification);
    
    // إخفاء تلقائي
    setTimeout(() => {
        if (document.getElementById(notificationId)) {
            const bsAlert = new bootstrap.Alert(document.getElementById(notificationId));
            bsAlert.close();
        }
    }, duration);
}

// ============================================
// وظائف إدارة البيانات
// ============================================

/**
 * تحميل البيانات مع معالجة الأخطاء
 */
async function fetchWithErrorHandling(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        return { success: true, data };
        
    } catch (error) {
        console.error('Fetch error:', error);
        return { success: false, error: error.message };
    }
}

/**
 * حفظ البيانات محلياً
 */
function saveToLocalStorage(key, data) {
    try {
        localStorage.setItem(key, JSON.stringify(data));
        return true;
    } catch (error) {
        console.error('LocalStorage error:', error);
        return false;
    }
}

/**
 * تحميل البيانات من التخزين المحلي
 */
function loadFromLocalStorage(key) {
    try {
        const data = localStorage.getItem(key);
        return data ? JSON.parse(data) : null;
    } catch (error) {
        console.error('LocalStorage read error:', error);
        return null;
    }
}

// ============================================
// وظائف التنسيق والعرض
// ============================================

/**
 * تنسيق التاريخ
 */
function formatDate(date) {
    const options = {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        weekday: 'long'
    };
    return new Date(date).toLocaleDateString('ar-SA', options);
}

/**
 * تنسيق الأرقام
 */
function formatNumber(number) {
    return number.toLocaleString('ar-SA');
}

/**
 * اقتطاع النص
 */
function truncateText(text, maxLength = 50) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

/**
 * توليد لون عشوائي
 */
function generateRandomColor() {
    const colors = [
        '#3498db', '#e74c3c', '#2ecc71', '#f39c12',
        '#9b59b6', '#1abc9c', '#34495e', '#e67e22'
    ];
    return colors[Math.floor(Math.random() * colors.length)];
}

// ============================================
// وظائف الطباعة والتصدير
// ============================================

/**
 * طباعة المحتوى
 */
function printContent(elementId = null) {
    const element = elementId ? document.getElementById(elementId) : document.body;
    const originalContents = document.body.innerHTML;
    const printContents = element.innerHTML;
    
    document.body.innerHTML = printContents;
    window.print();
    document.body.innerHTML = originalContents;
    location.reload();
}

/**
 * تصدير البيانات إلى CSV
 */
function exportToCSV(data, filename = 'data.csv') {
    const csvContent = "data:text/csv;charset=utf-8," 
        + data.map(row => row.join(',')).join('\n');
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * تصدير البيانات إلى JSON
 */
function exportToJSON(data, filename = 'data.json') {
    const dataStr = JSON.stringify(data, null, 2);
    const dataBlob = new Blob([dataStr], {type: 'application/json'});
    
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// ============================================
// وظائف التحقق من الصحة
// ============================================

/**
 * التحقق من صحة رقم الهاتف
 */
function validatePhoneNumber(phone) {
    const phoneRegex = /^(\+966|0)?5[0-9]{8}$/;
    return phoneRegex.test(phone.replace(/\s/g, ''));
}

/**
 * التحقق من صحة البريد الإلكتروني
 */
function validateEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

/**
 * التحقق من صحة التاريخ
 */
function validateDate(date) {
    const dateObj = new Date(date);
    return dateObj instanceof Date && !isNaN(dateObj);
}

// ============================================
// وظائف الواجهة التفاعلية
// ============================================

/**
 * تبديل الحالة للمجموعة
 */
function toggleGroupCollapse(groupId) {
    const group = document.getElementById(groupId);
    if (group) {
        group.classList.toggle('collapsed');
    }
}

/**
 * تحديد/إلغاء تحديد الكل في قائمة
 */
function toggleSelectAll(selectAllId, checkboxName) {
    const selectAll = document.getElementById(selectAllId);
    const checkboxes = document.querySelectorAll(`input[name="${checkboxName}"]`);
    
    checkboxes.forEach(checkbox => {
        checkbox.checked = selectAll.checked;
    });
}

/**
 * فلترة الجدول
 */
function filterTable(tableId, searchInputId) {
    const searchInput = document.getElementById(searchInputId);
    const table = document.getElementById(tableId);
    const searchTerm = searchInput.value.toLowerCase();
    
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// ============================================
// وظائف الووردبريس المتخصصة
// ============================================

/**
 * تحديث حالة الخطباء
 */
async function updateKhatebStatus(khatebId) {
    const response = await fetchWithErrorHandling(`/khateb/${khatebId}/status`);
    if (response.success) {
        return response.data;
    }
    throw new Error(response.error);
}

/**
 * تحديث قائمة المساجد المزارة
 */
async function updateVisitedMosques(khatebId, mosqueId) {
    const response = await fetchWithErrorHandling(`/khateb/${khatebId}/update_visits`, {
        method: 'POST',
        body: JSON.stringify({ mosque_id: mosqueId })
    });
    return response;
}

/**
 * إنشاء توزيع جديد
 */
async function createDistribution(targetDate) {
    const response = await fetchWithErrorHandling('/distribution/create', {
        method: 'POST',
        body: JSON.stringify({ target_date: targetDate })
    });
    return response;
}

// ============================================
// معالجة الأخطاء العامة
// ============================================

/**
 * معالج الأخطاء العام
 */
window.addEventListener('error', function(event) {
    console.error('خطأ عام:', event.error);
    
    // إظهار رسالة خطأ مناسبة للمستخدم
    showNotification('حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.', 'error');
});

/**
 * معالج أخطاء الشبكة
 */
window.addEventListener('unhandledrejection', function(event) {
    console.error('خطأ شبكة:', event.reason);
    
    // إظهار رسالة خطأ للمستخدم
    showNotification('خطأ في الاتصال بالشبكة. تأكد من اتصالك بالإنترنت.', 'error');
});

// ============================================
// تصدير الوظائف للاستخدام العام
// ============================================

// جعل الوظائف متاحة عالمياً
window.KhutbaSystem = {
    showNotification,
    fetchWithErrorHandling,
    formatDate,
    formatNumber,
    validatePhoneNumber,
    validateEmail,
    validateDate,
    printContent,
    exportToCSV,
    exportToJSON,
    updateKhatebStatus,
    createDistribution,
    saveToLocalStorage,
    loadFromLocalStorage
};

console.log('تم تحميل جميع وظائف نظام توزيع الخطباء بنجاح');