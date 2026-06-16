import re
from telethon import TelegramClient, errors
from cryptography.fernet import Fernet

# مفتاح التشفير (خليه في متغيرات البيئة Vercel عشان الأمان)
# أنشئ مفتاح مرة وحدة وضعه في ENV
# ENCRYPTION_KEY = Fernet.generate_key()  # استخدم هذا مرة وانسخ الناتج
ENCRYPTION_KEY = "your-encryption-key-here"  # ضع المفتاح من ENV
cipher = Fernet(ENCRYPTION_KEY)

# متغيرات مؤقتة لتخزين عمليات تسجيل الدخول قيد التقدم (استخدم Redis لو عندك زوار كثار)
pending_logins = {}  # {user_id: {client, phone, phone_code_hash}}

@app.route('/request-telegram-code', methods=['POST'])
def request_telegram_code():
    if 'user_id' not in session:
        return {"error": "يجب تسجيل الدخول أولاً"}, 401
    
    user_id = session['user_id']
    phone = request.form.get('phone_number')
    
    # تنظيف رقم الهاتف
    phone = re.sub(r'[^0-9+]', '', phone)
    if not phone.startswith('+'):
        phone = '+' + phone
    
    # إنشاء عميل تلجرام مؤقت (نستخدم جلسة وهمية)
    client = TelegramClient(f'session_{user_id}', api_id, api_hash)
    # api_id و api_hash تجيبهم من my.telegram.org
    
    try:
        # طلب إرسال الكود
        result = client.send_code_request(phone)
        pending_logins[user_id] = {
            'client': client,
            'phone': phone,
            'phone_code_hash': result.phone_code_hash
        }
        return {"success": True, "message": "تم إرسال رمز التحقق إلى تلجرام"}
    except Exception as e:
        return {"error": str(e)}, 400


@app.route('/verify-telegram-code', methods=['POST'])
def verify_telegram_code():
    if 'user_id' not in session:
        return {"error": "يجب تسجيل الدخول أولاً"}, 401
    
    user_id = session['user_id']
    code = request.form.get('code')
    password = request.form.get('password')  # للتحقق بخطوتين (اختياري)
    
    if user_id not in pending_logins:
        return {"error": "انتهت صلاحية الطلب، حاول مرة أخرى"}, 400
    
    data = pending_logins[user_id]
    client = data['client']
    
    try:
        # تسجيل الدخول بالكود
        if password:
            await client.sign_in(data['phone'], code, password=password)
        else:
            await client.sign_in(data['phone'], code, phone_code_hash=data['phone_code_hash'])
        
        # حفظ الجلسة بشكل مشفر
        session_string = client.session.save()  # نص الجلسة
        encrypted_session = cipher.encrypt(session_string.encode()).decode()
        
        # حذف الجلسة المؤقتة من الذاكرة
        del pending_logins[user_id]
        
        # حفظ في قاعدة البيانات
        supabase.table("telegram_sessions").insert({
            "user_id": user_id,
            "phone_number": data['phone'],
            "session_string": encrypted_session
        }).execute()
        
        return {"success": True, "message": "تم ربط الحساب بنجاح"}
        
    except errors.SessionPasswordNeededError:
        # إذا طلب كلمة مرور التحقق بخطوتين
        return {"error": "password_needed", "message": "الحساب مفعل عليه التحقق بخطوتين، أرسل كلمة المرور"}
    except Exception as e:
        return {"error": str(e)}, 400
