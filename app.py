import os
import re
import asyncio
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
from telethon import TelegramClient, errors
from cryptography.fernet import Fernet
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# ===== إعداد Supabase =====
SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://fxbwftemogwugxapmmhu.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ4YndmdGVtb2d3dWd4YXBtbWh1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE2MTA4MzcsImV4cCI6MjA5NzE4NjgzN30.I8HDW067cifXpwOw195WgYJNgUehPOvWFV2WrN12n0k')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===== مفاتيح تلجرام =====
API_ID = int(os.environ.get('TELEGRAM_API_ID', 32220564))
API_HASH = os.environ.get('TELEGRAM_API_HASH', 'c3048de549dd3c07bb9de40d28db5a04')

# ===== مفتاح التشفير (يجب توليده مرة واحدة ووضعه في البيئة) =====
# لتوليد مفتاح جديد: استخدم هذا الأمر في بايثون:
# from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', 'akgDxHnKRtjWwwL84PkUn4TPK_o3Nm8r_3G5hKcgRkg=')
cipher = Fernet(ENCRYPTION_KEY.encode())

# ===== دوال مساعدة =====

def encrypt_session(session_string: str) -> str:
    """تشفير نص الجلسة قبل الحفظ في قاعدة البيانات"""
    return cipher.encrypt(session_string.encode()).decode()

def decrypt_session(encrypted: str) -> str:
    """فك تشفير الجلسة المسترجعة من قاعدة البيانات"""
    return cipher.decrypt(encrypted.encode()).decode()

# ===== مسارات المصادقة =====

@app.route('/')
def home():
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if not email or not password:
            return "البريد الإلكتروني وكلمة المرور مطلوبة", 400
        
        # التحقق من وجود البريد مسبقاً
        existing = supabase.table("users").select("*").eq("email", email).execute()
        if len(existing.data) > 0:
            return "البريد الإلكتروني مستخدم بالفعل", 400
        
        hashed = generate_password_hash(password)
        supabase.table("users").insert({
            "email": email,
            "password_hash": hashed,
            "plan": "free"
        }).execute()
        
        return redirect('/login')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not email or not password:
            return "البريد الإلكتروني وكلمة المرور مطلوبة", 400
        
        user = supabase.table("users").select("*").eq("email", email).execute()
        if len(user.data) == 0:
            return "المستخدم غير موجود", 400
        
        user_data = user.data[0]
        if not check_password_hash(user_data['password_hash'], password):
            return "كلمة المرور غير صحيحة", 400
        
        session['user_id'] = user_data['id']
        session['email'] = user_data['email']
        return redirect('/dashboard')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ===== مسارات ربط حساب تلجرام =====

@app.route('/request-telegram-code', methods=['POST'])
def request_telegram_code():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
    
    user_id = session['user_id']
    phone = request.form.get('phone_number')
    
    if not phone:
        return jsonify({"error": "رقم الهاتف مطلوب"}), 400
    
    # تنظيف الرقم
    phone = re.sub(r'[^0-9+]', '', phone)
    if not phone.startswith('+'):
        phone = '+' + phone
    
    # تشغيل عملية طلب الكود في حلقة asyncio
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
        result = loop.run_until_complete(client.send_code_request(phone))
        # حفظ بيانات العميل في الذاكرة (للاستخدام المؤقت)
        # نضع معرف المستخدم كمفتاح
        pending_logins[user_id] = {
            'client': client,
            'phone': phone,
            'phone_code_hash': result.phone_code_hash
        }
        return jsonify({"success": True, "message": "تم إرسال رمز التحقق إلى تلجرام"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/verify-telegram-code', methods=['POST'])
def verify_telegram_code():
    if 'user_id' not in session:
        return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
    
    user_id = session['user_id']
    code = request.form.get('code')
    password = request.form.get('password', '')
    
    if user_id not in pending_logins:
        return jsonify({"error": "انتهت صلاحية الطلب، حاول مرة أخرى"}), 400
    
    data = pending_logins[user_id]
    client = data['client']
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if password:
            loop.run_until_complete(client.sign_in(data['phone'], code, password=password))
        else:
            loop.run_until_complete(client.sign_in(data['phone'], code, phone_code_hash=data['phone_code_hash']))
        
        # حفظ الجلسة
        session_string = client.session.save()
        encrypted = encrypt_session(session_string)
        
        # حذف من الذاكرة
        del pending_logins[user_id]
        
        # حفظ في قاعدة البيانات
        supabase.table("telegram_sessions").insert({
            "user_id": user_id,
            "phone_number": data['phone'],
            "session_string": encrypted
        }).execute()
        
        return jsonify({"success": True, "message": "تم ربط الحساب بنجاح"})
    
    except errors.SessionPasswordNeededError:
        return jsonify({"error": "password_needed", "message": "يتطلب التحقق بخطوتين، أرسل كلمة المرور"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/remove-session/<session_id>', methods=['POST'])
def remove_session(session_id):
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    supabase.table("telegram_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
    return redirect('/dashboard')

# ===== لوحة التحكم =====

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    
    user_id = session['user_id']
    resp = supabase.table("telegram_sessions").select("*").eq("user_id", user_id).execute()
    sessions = resp.data
    
    return render_template('dashboard.html', user_email=session.get('email'), sessions=sessions)

# ===== تشغيل التطبيق (للتجربة المحلية) =====
if __name__ == '__main__':
    # هذا المتغير لتخزين الجلسات المؤقتة
    pending_logins = {}
    app.run(debug=True, host='0.0.0.0', port=5000)
