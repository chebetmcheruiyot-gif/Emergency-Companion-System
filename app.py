from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import sys, os, threading
import africastalking
import requests
import re
from dotenv import load_dotenv
 
# Load environment variables
load_dotenv()
 
sys.path.append(os.path.join(os.path.dirname(__file__), 'ml'))
from ml.chat_engine import get_response  # type: ignore (fallback only)
 
app = Flask(
    __name__,
    template_folder="frontend/templates",
    static_folder="frontend/static",
    static_url_path="/static"
)
 
app.config["SECRET_KEY"]                     = os.getenv("SECRET_KEY", "emergency-secret-key-2024")
app.config["SQLALCHEMY_DATABASE_URI"]        = "sqlite:///users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAIL_SERVER"]                    = "smtp.gmail.com"
app.config["MAIL_PORT"]                      = 587
app.config["MAIL_USE_TLS"]                   = True
app.config["MAIL_USERNAME"]                  = os.getenv("MAIL_USERNAME", "chebetmcheruiyot@gmail.com")
app.config["MAIL_PASSWORD"]                  = os.getenv("MAIL_PASSWORD", "tedmheejkmifzgas")
app.config["MAIL_DEFAULT_SENDER"]            = ("Emergency System", app.config["MAIL_USERNAME"])
app.config["UPLOAD_FOLDER"]                  = os.path.join(os.path.dirname(__file__), "../frontend/static/uploads")
app.config["MAX_CONTENT_LENGTH"]             = 16 * 1024 * 1024  # 16MB max
 
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov'}
 
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
 
db         = SQLAlchemy(app)
mail       = Mail(app)
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
 
# AFRICA'S TALKING 
AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
AT_API_KEY  = os.getenv("AT_API_KEY", "")
AT_ENV      = os.getenv("AT_ENV", "sandbox")
 
# Groq API Key
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
 
import ssl
import urllib3
urllib3.disable_warnings()
ssl._create_default_https_context = ssl._create_unverified_context
africastalking.initialize(AT_USERNAME, AT_API_KEY)
sms = africastalking.SMS
 
# Alert types that trigger SMS (location_share is excluded)
SMS_ALERT_TYPES = {'medical', 'police', 'fire', 'accident', 'panic'}
 
# Human-readable alert names for the SMS message
ALERT_LABELS = {
    'medical':  'MEDICAL EMERGENCY',
    'police':   'POLICE EMERGENCY',
    'fire':     'FIRE EMERGENCY',
    'accident': 'ROAD ACCIDENT',
    'panic':    'PANIC ALERT',
}
 
def format_phone_ke(phone):
    """
    Normalize Kenyan phone numbers to international format.
    07xxxxxxxx → +2547xxxxxxxx
    2547xxxxxxxx → +2547xxxxxxxx
    +2547xxxxxxxx → unchanged
    """
    phone = str(phone).strip().replace(' ', '').replace('-', '')
    if phone.startswith('+'):
        return phone
    if phone.startswith('254'):
        return '+' + phone
    if phone.startswith('0'):
        return '+254' + phone[1:]
    return '+254' + phone
 
def send_kin_sms(user, alert_type, latitude=None, longitude=None):
    """
    Sends an SMS to the user's next of kin in a background thread.
    Uses relationship field to personalise message.
    """
    if alert_type not in SMS_ALERT_TYPES:
        return
 
    def _send():
        try:
            alert_label = ALERT_LABELS.get(alert_type, alert_type.upper())
            first_name = user.fullname.split()[0]
 
            # Build location string
            if latitude and longitude:
                maps_link = f"https://maps.google.com/?q={latitude},{longitude}"
                location_line = f"Location: {maps_link}"
            else:
                location_line = "Location: Not available"
 
            # --- Intelligent relationship mapping ---
            relationship = (user.relationship or "family member").lower().strip()
            
            # Map common relationships to "your child"
            if relationship in ['mother', 'father', 'mom', 'dad', 'mum', 'dad']:
                relation_display = "your child"
            else:
                relation_display = f"your {relationship}"
 
            message = (
                f"🚨 EMERGENCY ALERT\n"
                f"{alert_label}\n\n"
                f"{first_name} ({relation_display}) has triggered an emergency alert.\n"
                f"{location_line}\n\n"
                f"Please contact them immediately.\n"
                f"— Emergency Response System"
            )
 
            kin_phone = format_phone_ke(user.kin_phone)
 
            response = sms.send(message, [kin_phone])
 
            recipient = response['SMSMessageData']['Recipients'][0]
            status = recipient['status']
            status_code = recipient['statusCode']
 
            if status == 'UserInBlacklist':
                print(f"[SMS WARNING] Number {kin_phone} is blacklisted. SMS not sent. (Code: {status_code})")
            elif status == 'Success':
                print(f"[SMS SUCCESS] Sent to {kin_phone}. Message ID: {recipient.get('messageId')}")
            else:
                print(f"[SMS INFO] {kin_phone} - Status: {status} (Code: {status_code})")
 
        except KeyError as e:
            print(f"[SMS ERROR] Unexpected response format: {e} - Full response: {response}")
        except Exception as e:
            print(f"[SMS ERROR] {e}")
 
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
 
# ============================
# MODELS
# ============================
class User(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    fullname     = db.Column(db.String(100), nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    phone        = db.Column(db.String(20), nullable=False)
    kin_name     = db.Column(db.String(100), nullable=False)
    kin_phone    = db.Column(db.String(20), nullable=False)
    kin_location = db.Column(db.String(150), nullable=False)
    relationship = db.Column(db.String(100), nullable=False, default="family member")
    password     = db.Column(db.String(200), nullable=False)
 
class Alert(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, nullable=False)
    alert_type    = db.Column(db.String(50), nullable=False)
    latitude      = db.Column(db.String(50))
    longitude     = db.Column(db.String(50))
    status        = db.Column(db.String(20), default="pending")
    dispatched_to = db.Column(db.String(50))
    evidence_photo = db.Column(db.String(255))   # stores filename of uploaded evidence
    timestamp     = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=3)
    )
 
class ResponderUnit(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    unit_type = db.Column(db.String(50), unique=True, nullable=False)
    name      = db.Column(db.String(100), nullable=False)
    phone     = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
 
with app.app_context():
    db.create_all()
    # Add relationship column if it doesn't exist (for existing databases)
    import sqlalchemy as sa
    inspector = sa.inspect(db.engine)
    existing_cols = [c['name'] for c in inspector.get_columns('user')]
    if 'relationship' not in existing_cols:
        db.engine.execute('ALTER TABLE user ADD COLUMN relationship VARCHAR(100) DEFAULT "family member"')
    alert_cols = [c['name'] for c in inspector.get_columns('alert')]
    if 'evidence_photo' not in alert_cols:
        db.engine.execute('ALTER TABLE alert ADD COLUMN evidence_photo VARCHAR(255)')
    # Create uploads folder if it doesn't exist
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    
    defaults = [
        ('ambulance', 'Ambulance Unit', '0700000001'),
        ('fire',      'Fire Brigade',   '0700000002'),
        ('police',    'Police Unit',    '0700000003'),
        ('rescue',    'Rescue Team',    '0700000004'),
    ]
    for utype, uname, uphone in defaults:
        if not ResponderUnit.query.filter_by(unit_type=utype).first():
            db.session.add(ResponderUnit(unit_type=utype, name=uname, phone=uphone))
    db.session.commit()
 
# ============================
# LOGIN REQUIRED
# ============================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated
 
# ============================
# ROUTES
# ============================
@app.route("/")
def home():
    return render_template("index.html")
 
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname, email, phone = request.form["fullname"], request.form["email"], request.form["phone"]
        kin_name, kin_phone, kin_location = request.form["kin_name"], request.form["kin_phone"], request.form["kin_location"]
        relationship = request.form["relationship"]
        password = request.form["password"]
        if User.query.filter_by(email=email).first():
            flash("Email already registered!", "danger")
            return redirect(url_for("register"))
        db.session.add(User(
            fullname=fullname, email=email, phone=phone,
            kin_name=kin_name, kin_phone=kin_phone, kin_location=kin_location,
            relationship=relationship,
            password=generate_password_hash(password)
        ))
        db.session.commit()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")
 
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form["email"]).first()
        if user and check_password_hash(user.password, request.form["password"]):
            session.clear()
            session.update({
                'user_id': user.id, 'fullname': user.fullname,
                'email': user.email, 'phone': user.phone,
                'kin_name': user.kin_name, 'kin_phone': user.kin_phone,
                'kin_location': user.kin_location,
                'relationship': user.relationship
            })
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password!", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")
 
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))
 
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email_or_phone = request.form.get('email_or_phone', '').strip()
        user = User.query.filter(
            (User.email == email_or_phone) | (User.phone == email_or_phone)
        ).first()
        if not user:
            flash("No account found with that email or phone.", "danger")
            return redirect(url_for('forgot_password'))
        token     = serializer.dumps(user.email, salt='password-reset')
        reset_url = url_for('reset_password', token=token, _external=True)
        try:
            msg = Message(subject="Emergency System — Password Reset", recipients=[user.email])
            msg.html = f"""
            <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;background:#060f08;color:#f0f7f2;padding:32px;border-radius:12px;border:1px solid rgba(46,204,113,0.2);">
              <h2 style="color:#2ecc71;letter-spacing:2px;">PASSWORD RESET</h2>
              <p style="color:#8fada0;font-size:13px;margin:16px 0;">Hi {user.fullname.split()[0]}, you requested a password reset.</p>
              <a href="{reset_url}" style="display:inline-block;padding:13px 28px;background:linear-gradient(135deg,#1e7a3e,#2ecc71);color:#fff;text-decoration:none;border-radius:10px;font-weight:700;letter-spacing:2px;font-size:14px;margin:20px 0;">RESET MY PASSWORD</a>
              <p style="color:#8fada0;font-size:11px;margin-top:24px;">Expires in <strong style="color:#2ecc71;">30 minutes</strong>.</p>
              <hr style="border:1px solid rgba(46,204,113,0.1);margin:20px 0;">
              <p style="color:rgba(143,173,160,0.4);font-size:10px;letter-spacing:2px;">EMERGENCY RESPONSE SYSTEM v2.0</p>
            </div>"""
            mail.send(msg)
            flash("Password reset link sent to your email!", "success")
        except Exception as e:
            print(f"Mail error: {e}")
            flash("Could not send email. Please check your email configuration.", "danger")
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')
 
@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=1800)
    except SignatureExpired:
        flash("Reset link has expired.", "danger"); return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("Invalid reset link.", "danger"); return redirect(url_for('forgot_password'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Account not found.", "danger"); return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        new_pw  = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template('reset_password.html', token=token)
        if new_pw != confirm:
            flash("Passwords do not match.", "danger")
            return render_template('reset_password.html', token=token)
        user.password = generate_password_hash(new_pw)
        db.session.commit()
        flash("Password updated! Please login.", "success")
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)
 
# ----------------------------
# DASHBOARD
# ----------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    total_alerts = Alert.query.filter_by(user_id=session['user_id']).count()
    return render_template('dashboard.html', total_alerts=total_alerts)
 
# ----------------------------
# ALERT HISTORY
# ----------------------------
@app.route('/alert_history')
@login_required
def alert_history():
    alerts = Alert.query.filter_by(user_id=session['user_id'])\
                        .order_by(Alert.timestamp.desc()).all()
    counts = {
        'medical':  sum(1 for a in alerts if a.alert_type == 'medical'),
        'police':   sum(1 for a in alerts if a.alert_type == 'police'),
        'fire':     sum(1 for a in alerts if a.alert_type == 'fire'),
        'accident': sum(1 for a in alerts if a.alert_type == 'accident'),
        'panic':    sum(1 for a in alerts if a.alert_type == 'panic'),
    }
    return render_template('alert_history.html', alerts=alerts, counts=counts)
 
# ----------------------------
# UPDATE PROFILE (includes relationship)
# ----------------------------
@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json()
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'status': 'error'}), 404
    # Allowed fields to update
    for field in ['fullname', 'phone', 'kin_name', 'kin_phone', 'kin_location', 'relationship']:
        if field in data:
            setattr(user, field, data.get(field, getattr(user, field)))
            session[field] = getattr(user, field)
    db.session.commit()
    return jsonify({'status': 'ok'})
 
# ----------------------------
# CHANGE PASSWORD
# ----------------------------
@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    data       = request.get_json()
    current_pw = data.get('current_password', '')
    new_pw     = data.get('new_password', '')
    confirm_pw = data.get('confirm_password', '')
    user       = User.query.get(session['user_id'])
    if not check_password_hash(user.password, current_pw):
        return jsonify({'status': 'error', 'msg': 'Current password is incorrect.'})
    if len(new_pw) < 6:
        return jsonify({'status': 'error', 'msg': 'New password must be at least 6 characters.'})
    if new_pw != confirm_pw:
        return jsonify({'status': 'error', 'msg': 'New passwords do not match.'})
    user.password = generate_password_hash(new_pw)
    db.session.commit()
    return jsonify({'status': 'ok', 'msg': 'Password changed successfully!'})
 
# ----------------------------
# ----------------------------
# FISH AUDIO TTS
# ----------------------------
FISH_API_KEY  = os.getenv("FISH_API_KEY",  "09252bca3555437e91f13ee28335d1b3")
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "63ea5b49f08041dea514ee659d35ac10")
 
@app.route('/tts', methods=['POST'])
@login_required
def tts():
    """Proxy Fish Audio TTS — keeps API key server-side, avoids CORS."""
    from flask import Response
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400
    try:
        r = requests.post(
            'https://api.fish.audio/v1/tts',
            headers={
                'Authorization': f'Bearer {FISH_API_KEY}',
                'Content-Type':  'application/json'
            },
            json={
                'text':         text,
                'reference_id': FISH_VOICE_ID,
                'format':       'mp3',
                'latency':      'normal',
                'streaming':    False
            },
            timeout=15
        )
        if r.status_code == 200:
            return Response(r.content, mimetype='audio/mpeg')
        else:
            print(f"[Fish Audio Error] {r.status_code}: {r.text}")
            return jsonify({'error': 'TTS failed'}), 502
    except Exception as e:
        print(f"[Fish Audio Exception] {e}")
        return jsonify({'error': str(e)}), 500
 
 
# ----------------------------
# PWA ROUTES
# ----------------------------
@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')
 
@app.route('/service-worker.js')
def service_worker():
    from flask import Response, send_from_directory
    response = send_from_directory(app.static_folder, 'service-worker.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response
 
@app.route('/offline')
def offline():
    return render_template('offline.html')
 
# CHAT — GROQ PRIMARY / GEMINI FALLBACK / SWAHILI SUPPORT
# ----------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
 
SHELLY_SYSTEM_EN = (
    "You are SHELLY, a calm expert emergency response assistant. "
    "Give ONLY brief numbered action steps the user must follow right now. "
    "No bold text. No asterisks. No labels. No preamble. Be concise and direct. "
    "Always respond in English."
)
SHELLY_SYSTEM_SW = (
    "Wewe ni SHELLY, msaidizi wa dharura mwenye ujuzi na utulivu. "
    "Toa hatua fupi za nambari ambazo mtumiaji lazima azifuate sasa hivi. "
    "Bila maandishi mazito. Bila nyota. Bila lebo. Jibu kwa Kiswahili tu."
)
 
def detect_language(text):
    """Simple Swahili keyword detector."""
    sw_words = ['msaada','moto','ajali','polisi','damu','pumzika','pumua','nini','hii',
                'ninaumia','hatari','dharura','gari','mgonjwa','hospitali','daktari',
                'habari','hujambo','asante','tafadhali','sasa','haraka','nipe']
    lower = text.lower()
    hits  = sum(1 for w in sw_words if w in lower)
    return 'sw' if hits >= 1 else 'en'
 
def clean_chat(text):
    text = text.replace("**","").replace("*","")
    text = re.sub(r'^\d+\.\s*', '', text, flags=re.MULTILINE)
    return text.replace("SHELLY:","").replace("Assistant:","").strip()
 
def call_groq_chat(message, context, language):
    if not GROQ_API_KEY:
        return None
    system = SHELLY_SYSTEM_SW if language == 'sw' else SHELLY_SYSTEM_EN
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": f"Previous conversation:\n{context}\n\nCurrent emergency: {message}"}
                ],
                "max_tokens": 180, "temperature": 0.3
            },
            timeout=8
        )
        if r.status_code == 200:
            return clean_chat(r.json()["choices"][0]["message"]["content"])
    except requests.exceptions.Timeout:
        pass
    except Exception:
        pass
    return None
 
def call_gemini_chat(message, context, language):
    if not GEMINI_API_KEY:
        return None
    system = SHELLY_SYSTEM_SW if language == 'sw' else SHELLY_SYSTEM_EN
    try:
        prompt = f"{system}\n\nPrevious conversation:\n{context}\n\nCurrent emergency: {message}"
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 300, "temperature": 0.3}},
            timeout=10
        )
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return clean_chat(text)
    except Exception:
        pass
    return None
 
@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data     = request.get_json() or {}
    message  = data.get('message', '').strip()
    language = data.get('language', 'auto')   # 'en', 'sw', or 'auto'
 
    if not message:
        return jsonify({'response': 'Please describe your emergency.'})
 
    # Auto-detect language if not specified
    if language == 'auto':
        language = detect_language(message)
 
    msg_lower = message.lower().strip()
 
    # Quick greetings
    greet_en = {'hi','hello','hey'}
    greet_sw = {'habari','hujambo','mambo','sasa'}
    if msg_lower in greet_en | greet_sw:
        resp = "Habari! Mimi ni SHELLY, msaidizi wako wa dharura. Niambie kinachoendelea." if language == 'sw' \
               else "Hi there. I'm SHELLY, your emergency assistant. Tell me what's happening."
        return jsonify({'response': resp, 'language': language})
 
    bye_words = {'thank you','thanks','goodbye','bye','asante','kwaheri'}
    if msg_lower in bye_words:
        resp = "Kaa salama. Kwaheri!" if language == 'sw' else "Stay safe. Goodbye!"
        return jsonify({'response': resp, 'language': language})
 
    # Build conversation context
    if 'chat_history' not in session:
        session['chat_history'] = []
    session['chat_history'].append({'role': 'user', 'content': message})
    if len(session['chat_history']) > 10:
        session['chat_history'] = session['chat_history'][-10:]
 
    context = ""
    for entry in session['chat_history'][-6:]:
        prefix = "User" if entry['role'] == 'user' else "Assistant"
        context += f"{prefix}: {entry['content']}\n"
 
    # Priority 1 — Groq
    result = call_groq_chat(message, context, language)
 
    # Priority 2 — Claude (fallback when Groq fails)
    if not result:
        result = call_gemini_chat(message, context, language)
 
    # Priority 3 — ML model
    if not result:
        try:
            result = get_response(message, language=language)
        except Exception:
            result = None
 
    # Priority 4 — hardcoded final fallback
    if not result:
        result = "Piga simu 999 mara moja." if language == 'sw' else "Call 999 immediately for emergency assistance."
 
    session['chat_history'].append({'role': 'assistant', 'content': result})
    session.modified = True
    return jsonify({'response': result, 'language': language})
 
# ----------------------------
# EMERGENCY PAGES
# ----------------------------
@app.route("/emergency/medical")
@login_required
def medical():
    return render_template("medical.html")
 
@app.route("/emergency/police")
@login_required
def police():
    return render_template("police.html")
 
@app.route("/emergency/police_report", methods=["POST"])
@login_required
def police_report():
    flash("Police report sent successfully!", "success")
    return redirect(url_for("dashboard"))
 
@app.route("/upload_evidence", methods=["POST"])
@login_required
def upload_evidence():
    """Upload photo/video evidence and attach it to the user's latest alert."""
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'msg': 'No file selected.'})
 
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'msg': 'No file selected.'})
 
    if not allowed_file(file.filename):
        return jsonify({'status': 'error', 'msg': 'File type not allowed. Use JPG, PNG, GIF, WEBP, MP4 or MOV.'})
 
    # Save file with a unique name to prevent overwriting
    ext       = file.filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename  = secure_filename(f"evidence_{session['user_id']}_{timestamp}.{ext}")
    filepath  = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)
 
    # Attach to the user's most recent alert
    alert = Alert.query.filter_by(user_id=session['user_id'])\
                       .order_by(Alert.id.desc()).first()
    if alert:
        alert.evidence_photo = filename
        db.session.commit()
 
    return jsonify({
        'status': 'ok',
        'msg':      'Evidence uploaded successfully.',
        'filename': filename,
        'url':      f"/static/uploads/{filename}"
    })
 
@app.route("/emergency/fire")
@login_required
def fire():
    return render_template("fire.html")
 
@app.route("/emergency/accident")
@login_required
def accident():
    return render_template("accident.html")
 
# ----------------------------
# SEND EMERGENCY ALERT
# ----------------------------
@app.route("/send_alert/<alert_type>", methods=["POST"])
@login_required
def send_alert(alert_type):
    lat = request.form.get("latitude")
    lng = request.form.get("longitude")
 
    alert = Alert(
        user_id    = session['user_id'],
        alert_type = alert_type,
        latitude   = lat,
        longitude  = lng
    )
    db.session.add(alert)
    db.session.commit()
 
    user = User.query.get(session['user_id'])
    #send_kin_sms(user, alert_type, lat, lng)
    #send_user_alert_email(user, alert_type, lat, lng)   # ← NEW
 
    total = Alert.query.filter_by(user_id=session['user_id']).count()
    return jsonify({'status': 'ok', 'total_alerts': total})
 
 
def send_user_alert_email(user, alert_type, latitude=None, longitude=None):
    """Send an email confirmation to the user themselves after their alert fires."""
    if not user.email:
        return
    def _send():
        try:
            alert_label = ALERT_LABELS.get(alert_type, alert_type.upper())
            maps_line   = f"https://maps.google.com/?q={latitude},{longitude}" if latitude and longitude else "Not available"
            time_str    = datetime.now().strftime("%d %b %Y at %H:%M")
            msg = Message(
                subject = f"🚨 Emergency Alert Sent — {alert_label}",
                recipients = [user.email]
            )
            msg.html = f"""
            <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;background:#060f08;color:#f0f7f2;border-radius:14px;overflow:hidden;border:1px solid #1e7a3e;">
              <div style="background:linear-gradient(135deg,#1e7a3e,#2ecc71);padding:24px 28px;">
                <h2 style="margin:0;font-size:20px;letter-spacing:2px;text-transform:uppercase;">🚨 Alert Confirmed</h2>
                <p style="margin:6px 0 0;font-size:12px;opacity:0.85;">Emergency Response System</p>
              </div>
              <div style="padding:24px 28px;">
                <p style="font-size:14px;">Hi <strong>{user.fullname.split()[0]}</strong>,</p>
                <p style="font-size:14px;color:#8fada0;">Your <strong style="color:#2ecc71;">{alert_label}</strong> alert was successfully sent on <strong>{time_str}</strong>.</p>
                <div style="background:#0d1f14;border:1px solid #1e7a3e;border-radius:10px;padding:16px;margin:18px 0;">
                  <p style="margin:0 0 6px;font-size:11px;color:#8fada0;letter-spacing:2px;text-transform:uppercase;">Alert Details</p>
                  <p style="margin:4px 0;font-size:13px;"><strong>Type:</strong> {alert_label}</p>
                  <p style="margin:4px 0;font-size:13px;"><strong>Time:</strong> {time_str}</p>
                  <p style="margin:4px 0;font-size:13px;"><strong>Location:</strong> <a href="{maps_line}" style="color:#2ecc71;">{maps_line}</a></p>
                </div>
                <p style="font-size:13px;color:#8fada0;">Emergency responders have been notified. Your next of kin <strong style="color:#f0f7f2;">{user.kin_name}</strong> has also been contacted via SMS.</p>
                <p style="font-size:13px;color:#8fada0;margin-top:16px;">Stay calm and follow the on-screen instructions. Help is on the way.</p>
              </div>
              <div style="padding:16px 28px;border-top:1px solid #1e7a3e;font-size:10px;color:#8fada0;letter-spacing:1px;">
                EMERGENCY RESPONSE SYSTEM — DO NOT REPLY TO THIS EMAIL
              </div>
            </div>
            """
            mail.send(msg)
        except Exception as e:
            print(f"[USER EMAIL ERROR] {e}")
    threading.Thread(target=_send, daemon=True).start()
 
 
@app.route('/alert_status_latest')
@login_required
def alert_status_latest():
    """Returns the status of the user's most recent non-resolved alert."""
    alert = Alert.query.filter_by(user_id=session['user_id'])\
                       .order_by(Alert.id.desc()).first()
    if not alert:
        return jsonify({'status': None})
    return jsonify({'status': alert.status or 'pending', 'alert_id': alert.id})
 
# ----------------------------
# MAP & LOCATION
# ----------------------------
@app.route("/map")
@login_required
def map_page():
    return render_template("map.html")
 
@app.route("/save_location", methods=["POST"])
@login_required
def save_location():
    data = request.get_json()
    lat  = data.get("latitude")
    lng  = data.get("longitude")
    if not lat or not lng:
        return jsonify({"status": "error", "msg": "No coordinates provided"}), 400
    db.session.add(Alert(
        user_id    = session['user_id'],
        alert_type = "location_share",
        latitude   = str(lat),
        longitude  = str(lng)
    ))
    db.session.commit()
    total = Alert.query.filter_by(user_id=session['user_id']).count()
    return jsonify({"status": "ok", "msg": "Location saved.", "total_alerts": total})
 
# ============================
# ADMIN CONFIG (unchanged)
# ============================
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "emergency@admin2024")
 
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            flash("Admin access required.", "danger")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated
 
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['is_admin']   = True
            session['admin_name'] = username
            return redirect(url_for('admin_dashboard'))
        flash("Invalid admin credentials.", "danger")
        return redirect(url_for('admin_login'))
    return render_template('admin_login.html')
 
@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    session.pop('admin_name', None)
    return redirect(url_for('admin_login'))
 
@app.route('/admin')
@admin_required
def admin_dashboard():
    from datetime import date as dt_date
    all_users  = User.query.all()
    all_alerts = Alert.query.order_by(Alert.timestamp.desc()).all()
    user_map   = {u.id: u for u in all_users}
 
    def enrich(a):
        u = user_map.get(a.user_id)
        a.user_name     = u.fullname if u else "Unknown"
        a.user_phone    = u.phone    if u else "—"
        a.user_initials = "".join(w[0] for w in a.user_name.split()[:2]).upper()
        if not a.status: a.status = "pending"
        if not hasattr(a, "dispatched_to"): a.dispatched_to = None
        return a
 
    enriched = [enrich(a) for a in all_alerts]
    for u in all_users:
        u.initials    = "".join(w[0] for w in u.fullname.split()[:2]).upper()
        u.alert_count = sum(1 for a in all_alerts if a.user_id == u.id)
 
    today        = dt_date.today()
    alerts_today = sum(1 for a in all_alerts if a.timestamp and a.timestamp.date() == today)
    unresolved   = sum(1 for a in all_alerts if (a.status or "pending") != "resolved")
    units        = ResponderUnit.query.all()
 
    return render_template("admin_dashboard.html",
        total_users   = len(all_users),
        total_alerts  = len(all_alerts),
        alerts_today  = alerts_today,
        unresolved    = unresolved,
        recent_alerts = enriched[:10],
        all_alerts    = enriched,
        users         = all_users,
        units         = units,
        now           = datetime.now().strftime("%d %b %Y, %H:%M"),
        admin_name    = session.get("admin_name", "Admin")
    )
 
@app.route('/admin/update_status', methods=['POST'])
@admin_required
def admin_update_status():
    try:
        data       = request.get_json(force=True)
        alert_id   = int(data.get('alert_id'))
        new_status = data.get('status', 'pending')
        alert = Alert.query.filter_by(id=alert_id).first()
        if not alert:
            return jsonify({'status': 'error', 'msg': 'Alert not found'}), 404
        alert.status = new_status
        db.session.commit()
        unresolved = Alert.query.filter(Alert.status != 'resolved').count()
        return jsonify({'status': 'ok', 'unresolved': unresolved})
    except Exception as e:
        db.session.rollback()
        print(f"[STATUS ERROR] {e}")
        return jsonify({'status': 'error', 'msg': str(e)}), 500
 
@app.route('/admin/dispatch', methods=['POST'])
@admin_required
def admin_dispatch():
    try:
        data      = request.get_json(force=True)
        alert_id  = int(data.get('alert_id'))
        unit_type = data.get('unit_type')
        alert = Alert.query.filter_by(id=alert_id).first()
        if not alert:
            return jsonify({'status': 'error', 'msg': 'Alert not found'}), 404
        unit = ResponderUnit.query.filter_by(unit_type=unit_type).first()
        if not unit:
            return jsonify({'status': 'error', 'msg': 'Unit not found'}), 404
        alert.dispatched_to = unit_type
        alert.status        = 'responding'
        db.session.commit()
        print(f"[DISPATCH] {unit.name} ({unit.phone}) -> Alert #{alert_id}")
        unresolved = Alert.query.filter(Alert.status != 'resolved').count()
        return jsonify({'status': 'ok', 'unit_name': unit.name, 'unit_phone': unit.phone, 'unresolved': unresolved})
    except Exception as e:
        db.session.rollback()
        print(f"[DISPATCH ERROR] {e}")
        return jsonify({'status': 'error', 'msg': str(e)}), 500
 
@app.route('/admin/units', methods=['GET'])
@admin_required
def admin_get_units():
    units = ResponderUnit.query.all()
    return jsonify([{'id': u.id, 'unit_type': u.unit_type, 'name': u.name, 'phone': u.phone} for u in units])
 
@app.route('/admin/units/update', methods=['POST'])
@admin_required
def admin_update_unit():
    try:
        data = request.get_json(force=True)
        unit = ResponderUnit.query.filter_by(unit_type=data.get('unit_type')).first()
        if not unit:
            return jsonify({'status': 'error', 'msg': 'Unit not found'}), 404
        unit.name  = data.get('name',  unit.name)
        unit.phone = data.get('phone', unit.phone)
        db.session.commit()
        return jsonify({'status': 'ok'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'msg': str(e)}), 500
 
@app.route('/admin/change_password', methods=['POST'])
@admin_required
def admin_change_password():
    global ADMIN_PASSWORD
    data = request.get_json(force=True)
    if data.get('current_password') != ADMIN_PASSWORD:
        return jsonify({'status': 'error', 'msg': 'Current password incorrect.'})
    new_pw = data.get('new_password', '')
    if len(new_pw) < 6:
        return jsonify({'status': 'error', 'msg': 'Password must be at least 6 characters.'})
    if new_pw != data.get('confirm_password'):
        return jsonify({'status': 'error', 'msg': 'Passwords do not match.'})
    ADMIN_PASSWORD = new_pw
    return jsonify({'status': 'ok', 'msg': 'Admin password updated!'})
 
# ============================
# ADMIN NOTIFICATION API ENDPOINTS
# ============================
@app.route('/admin/latest_alert_id')
@admin_required
def latest_alert_id():
    latest = Alert.query.order_by(Alert.id.desc()).first()
    return jsonify({'latest_id': latest.id if latest else 0})
 
@app.route('/admin/unresolved_count')
@admin_required
def unresolved_count():
    unresolved = Alert.query.filter(Alert.status != 'resolved').count()
    return jsonify({'unresolved': unresolved})
 
@app.route('/admin/alert/<int:alert_id>')
@admin_required
def admin_get_alert(alert_id):
    """Return details of a single alert — used by frontend notification system."""
    alert = Alert.query.filter_by(id=alert_id).first()
    if not alert:
        return jsonify({'status': 'error', 'msg': 'Not found'}), 404
    user = User.query.get(alert.user_id)
    return jsonify({
        'status':         'ok',
        'id':             alert.id,
        'alert_type':     alert.alert_type,
        'user_name':      user.fullname if user else 'Unknown',
        'user_phone':     user.phone    if user else '—',
        'timestamp':      alert.timestamp.strftime('%d %b %Y, %H:%M') if alert.timestamp else '—',
        'latitude':       alert.latitude,
        'longitude':      alert.longitude,
        'evidence_photo': f"/static/uploads/{alert.evidence_photo}" if alert.evidence_photo else None,
    })
 
 
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)