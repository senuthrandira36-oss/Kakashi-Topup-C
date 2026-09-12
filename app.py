import os, sqlite3, secrets, time, hashlib, json, urllib.request, urllib.error, threading
try:
    import fcntl
except ImportError:
    fcntl = None
from functools import wraps
from flask import Flask, render_template, request, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-in-production')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=86400)
DB = os.path.join(os.path.dirname(__file__), 'database.db')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'Kakashi@gmail.com')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Kakashi23@')
ADMIN_WHATSAPP = os.environ.get('ADMIN_WHATSAPP', '94766559214')
ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY', 'KAKASHI-ADMIN-2026')
TEXTLK_API_TOKEN = os.environ.get('TEXTLK_API_TOKEN', '')
TEXTLK_SENDER_ID = os.environ.get('TEXTLK_SENDER_ID', '')
TEXTLK_URL = 'https://app.text.lk/api/v3/sms/send'
OTP_EXPIRY_SECONDS = 300
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5
EZ_CASH = '0762802142'

PACKAGES = {
 'SG': {
  'diamonds': [('25 Diamonds',120),('100 Diamonds',355),('310 Diamonds',1000),('520 Diamonds',1600),('1060 Diamonds',3180),('2180 Diamonds',6380),('5600 Diamonds',15720),('11500 Diamonds',32375)],
  'membership': [('Weekly Lite',150),('Weekly',595),('Weekly Max',755),('Monthly',2800),('VIP',3540),('VIP Plus',3550),('SVIP',5000),('SVIP Plus',5510)],
  'level': [('Level 06',150),('Level 10',255),('Level 15',255),('Level 20',255),('Level 25',255),('Level 30',355)]
 },
 'IND': {
  'diamonds': [('5 Diamonds',30),('50 Diamonds',240),('70 Diamonds',320),('140 Diamonds',550),('720 Diamonds',2800),('7290 Diamonds',28000)],
  'membership': [('Weekly',740),('Monthly',2000)],
  'level': [('Level 06',180),('Level 10',310),('Level 15',310),('Level 20',310),('Level 25',310),('Level 30',420)]
 }
}

# SQLite configuration. Keep connections short-lived and let SQLite handle
# brief concurrent access with WAL + busy_timeout. Do NOT hold a process/file lock
# for the lifetime of a connection, because that can make HTTP requests wait for
# another worker and eventually produce Gateway Timeout.
def db():
    c = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=NORMAL')
    return c

def init_db():
 c=db()
 c.execute('''CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,whatsapp TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT DEFAULT 'member',verified INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
 c.execute('''CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,customer_name TEXT NOT NULL,whatsapp TEXT NOT NULL,email TEXT NOT NULL,game TEXT NOT NULL,package TEXT NOT NULL,unit_price INTEGER NOT NULL,quantity INTEGER NOT NULL,price INTEGER NOT NULL,bonus TEXT DEFAULT '',uid TEXT NOT NULL,region TEXT NOT NULL,player_name TEXT DEFAULT '',payment_method TEXT NOT NULL,receipt TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP,confirmed_at TEXT,cancelled_at TEXT)''')
 c.execute('''CREATE TABLE IF NOT EXISTS wallet(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER UNIQUE NOT NULL,balance INTEGER DEFAULT 0,reserved INTEGER DEFAULT 0)''')
 c.execute('''CREATE TABLE IF NOT EXISTS wallet_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER NOT NULL,type TEXT NOT NULL,amount INTEGER NOT NULL,status TEXT DEFAULT 'pending',receipt TEXT,payment_method TEXT,payment_number TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,approved_at TEXT,order_id INTEGER)''')
 for stmt in ("ALTER TABLE wallet ADD COLUMN reserved INTEGER DEFAULT 0","ALTER TABLE wallet_transactions ADD COLUMN order_id INTEGER"):
  try: c.execute(stmt)
  except sqlite3.OperationalError: pass
 c.execute("UPDATE orders SET status='completed' WHERE status='confirmed'")
 c.execute('''CREATE TABLE IF NOT EXISTS otp(
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   email TEXT NOT NULL,
   code TEXT NOT NULL,
   purpose TEXT NOT NULL,
   expires_at INTEGER NOT NULL,
   used INTEGER DEFAULT 0,
   attempts INTEGER DEFAULT 0,
   created_at INTEGER DEFAULT 0
  )''')
 for stmt in (
  "ALTER TABLE otp ADD COLUMN attempts INTEGER DEFAULT 0",
  "ALTER TABLE otp ADD COLUMN created_at INTEGER DEFAULT 0"
 ):
  try: c.execute(stmt)
  except sqlite3.OperationalError: pass
 c.commit(); c.close()

def current_user():
 if not session.get('member_id'): return None
 return dict(id=session['member_id'],name=session.get('name'),email=session.get('email'),whatsapp=session.get('whatsapp'),role=session.get('role'))

def admin_request(): return session.get('role')=='admin' or request.headers.get('X-Admin-Key')==ADMIN_API_KEY

def admin_required(fn):
 @wraps(fn)
 def w(*a,**k):
  if not admin_request(): return jsonify(message='Admin access only'),403
  return fn(*a,**k)
 return w

def member_required(fn):
 @wraps(fn)
 def w(*a,**k):
  if session.get('role')!='member': return jsonify(message='Login required'),401
  return fn(*a,**k)
 return w

def money_int(v):
 try:return int(float(v))
 except:return 0

# OTP / SMS helpers
def normalize_phone(phone):
    p = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if p.startswith('0094'):
        p = p[2:]
    if p.startswith('0'):
        p = '94' + p[1:]
    if p.startswith('94') and len(p) == 11:
        return p
    return None

def hash_otp(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()

def send_sms(recipient, message):
    if not TEXTLK_API_TOKEN or not TEXTLK_SENDER_ID:
        raise RuntimeError('SMS service is not configured. Set TEXTLK_API_TOKEN and TEXTLK_SENDER_ID on the server.')
    payload = json.dumps({
        'recipient': recipient,
        'sender_id': TEXTLK_SENDER_ID,
        'type': 'plain',
        'message': message
    }).encode('utf-8')
    req = urllib.request.Request(
        TEXTLK_URL,
        data=payload,
        headers={
            'Authorization': f'Bearer {TEXTLK_API_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            body = json.loads(response.read().decode('utf-8') or '{}')
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            detail = ''
        raise RuntimeError(f'SMS provider HTTP {exc.code}: {detail or exc.reason}') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f'SMS provider connection failed: {exc}') from exc
    if body.get('status') not in (True, 'success'):
        raise RuntimeError(body.get('message') or 'SMS provider rejected the message')
    return body

def create_and_send_otp(email, purpose, phone, label='OTP'):
    email = email.strip().lower()
    now = int(time.time())
    c = db()
    recent = c.execute(
        "SELECT created_at FROM otp WHERE email=? AND purpose=? AND used=0 ORDER BY id DESC LIMIT 1",
        (email, purpose)
    ).fetchone()
    if recent and recent['created_at'] and now - int(recent['created_at']) < OTP_RESEND_SECONDS:
        wait = OTP_RESEND_SECONDS - (now - int(recent['created_at']))
        c.close()
        raise ValueError(f'Please wait {wait} seconds before requesting another OTP')
    c.execute("UPDATE otp SET used=1 WHERE email=? AND purpose=? AND used=0", (email, purpose))
    code = f'{secrets.randbelow(1000000):06d}'
    c.execute(
        "INSERT INTO otp(email,code,purpose,expires_at,used,attempts,created_at) VALUES(?,?,?,?,0,0,?)",
        (email, hash_otp(code), purpose, now + OTP_EXPIRY_SECONDS, 0, now)
    )
    otp_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit()
    c.close()
    try:
        send_sms(phone, f'Kakashi Topup Center: Your {label} is {code}. It expires in 5 minutes.')
    except Exception:
        c = db()
        c.execute("UPDATE otp SET used=1 WHERE id=?", (otp_id,))
        c.commit()
        c.close()
        raise
    return True

def verify_otp_code(email, purpose, code):
    email = email.strip().lower()
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return False, 'OTP must be 6 digits'
    c = db()
    row = c.execute(
        "SELECT * FROM otp WHERE email=? AND purpose=? AND used=0 ORDER BY id DESC LIMIT 1",
        (email, purpose)
    ).fetchone()
    if not row:
        c.close()
        return False, 'Invalid or expired OTP'
    if int(row['expires_at']) <= int(time.time()):
        c.execute("UPDATE otp SET used=1 WHERE id=?", (row['id'],))
        c.commit(); c.close()
        return False, 'Invalid or expired OTP'
    if int(row['attempts'] or 0) >= OTP_MAX_ATTEMPTS:
        c.execute("UPDATE otp SET used=1 WHERE id=?", (row['id'],))
        c.commit(); c.close()
        return False, 'Too many incorrect attempts. Request a new OTP.'
    if not secrets.compare_digest(row['code'], hash_otp(code)):
        attempts = int(row['attempts'] or 0) + 1
        if attempts >= OTP_MAX_ATTEMPTS:
            c.execute("UPDATE otp SET attempts=?,used=1 WHERE id=?", (attempts, row['id']))
        else:
            c.execute("UPDATE otp SET attempts=? WHERE id=?", (attempts, row['id']))
        c.commit(); c.close()
        remaining = max(0, OTP_MAX_ATTEMPTS - attempts)
        return False, f'Invalid OTP. {remaining} attempts remaining.'
    c.execute("UPDATE otp SET used=1 WHERE id=?", (row['id'],))
    c.commit(); c.close()
    return True, ''

def save_otp(email, purpose, phone=None, label='OTP'):
    # Compatibility wrapper for existing reset/register callers.
    if not phone:
        c = db()
        u = c.execute("SELECT whatsapp FROM members WHERE lower(email)=?", (email.lower(),)).fetchone()
        c.close()
        phone = u['whatsapp'] if u else None
    normalized = normalize_phone(phone)
    if not normalized:
        raise ValueError('Invalid Sri Lankan mobile number')
    return create_and_send_otp(email, purpose, normalized, label)

@app.route('/')
def index(): return render_template('index.html')

@app.get('/api/me')
def me(): return jsonify(user=current_user())

@app.post('/api/register')
def register():
    d=request.get_json(force=True)
    name=d.get('name','').strip()
    email=d.get('email','').strip().lower()
    phone=d.get('whatsapp','').strip()
    password=d.get('password','')
    normalized=normalize_phone(phone)
    if not all([name,email,phone,password]): return jsonify(message='Please fill all fields'),400
    if len(password)<6:return jsonify(message='Password must be at least 6 characters'),400
    if not normalized:return jsonify(message='Enter a valid Sri Lankan mobile number'),400
    c=db()
    try:
        # One short transaction for member + wallet creation. The connection-level
        # advisory lock prevents concurrent workers from fighting over SQLite.
        c.execute('BEGIN IMMEDIATE')
        cur=c.execute(
            "INSERT INTO members(name,email,whatsapp,password_hash,verified) VALUES(?,?,?,?,0)",
            (name,email,phone,generate_password_hash(password))
        )
        mid=cur.lastrowid
        c.execute('INSERT INTO wallet(member_id,balance) VALUES(?,0)',(mid,))
        c.commit()
    except sqlite3.IntegrityError:
        try: c.rollback()
        except Exception: pass
        c.close()
        return jsonify(message='Email already registered'),409
    except sqlite3.OperationalError as exc:
        try: c.rollback()
        except Exception: pass
        c.close()
        if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
            return jsonify(message='Database is temporarily busy. Please retry once.'),503
        return jsonify(message='Database error while creating the account.'),500
    except Exception:
        try: c.rollback()
        except Exception: pass
        c.close()
        return jsonify(message='Unable to create the account safely.'),500
    c.close()
    try:
        create_and_send_otp(email,'register',normalized,'registration OTP')
    except ValueError as exc:
        return jsonify(message=str(exc)),429
    except Exception as exc:
        return jsonify(message=str(exc)),502
    return jsonify(ok=True,otp_required=True,message='OTP sent to your registered mobile number')

@app.post('/api/verify-otp')
def verify_otp():
    d=request.get_json(force=True)
    email=d.get('email','').strip().lower()
    code=d.get('otp','').strip()
    purpose=d.get('purpose','register').strip()
    if purpose not in ('register','login'):
        return jsonify(message='Invalid OTP purpose'),400
    ok,msg=verify_otp_code(email,purpose,code)
    if not ok:return jsonify(message=msg),400
    c=db()
    if purpose=='register':
        c.execute('UPDATE members SET verified=1 WHERE email=?',(email,))
        c.commit(); c.close()
        return jsonify(ok=True,purpose='register')
    pending=session.get('pending_login')
    if not pending or pending.get('email')!=email:
        c.close(); return jsonify(message='Login session expired. Please login again.'),401
    session.pop('pending_login',None)
    if pending.get('role')=='admin':
        session.clear(); session.permanent=True
        session.update(role='admin',member_id=0,name='Admin Kakashi',email=ADMIN_EMAIL,whatsapp=ADMIN_WHATSAPP)
        c.close()
        return jsonify(ok=True,user=current_user())
    u=c.execute('SELECT * FROM members WHERE email=?',(email,)).fetchone()
    c.close()
    if not u:return jsonify(message='Account not found'),404
    session.clear(); session.permanent=True
    session.update(role='member',member_id=u['id'],name=u['name'],email=u['email'],whatsapp=u['whatsapp'])
    return jsonify(ok=True,user=current_user())

@app.post('/api/login')
def login():
    d=request.get_json(force=True)
    email=d.get('email','').strip().lower()
    password=d.get('password','')
    if not email or not password:return jsonify(message='Email and password are required'),400
    role='member'
    phone=None
    name=None
    if email==ADMIN_EMAIL.lower() and secrets.compare_digest(password, ADMIN_PASSWORD):
        role='admin'; phone=ADMIN_WHATSAPP; name='Admin Kakashi'
    else:
        c=db(); u=c.execute('SELECT * FROM members WHERE email=?',(email,)).fetchone(); c.close()
        if not u or not check_password_hash(u['password_hash'],password):return jsonify(message='Invalid email or password'),401
        if not u['verified']:return jsonify(message='Please verify your account first'),403
        phone=u['whatsapp']; name=u['name']
    normalized=normalize_phone(phone)
    if not normalized:return jsonify(message='A valid mobile number is required for OTP login'),500
    session.clear()
    session['pending_login']={'email':email,'role':role,'name':name}
    try:
        create_and_send_otp(email,'login',normalized,'login OTP')
    except ValueError as exc:
        session.pop('pending_login',None)
        return jsonify(message=str(exc)),429
    except Exception as exc:
        session.pop('pending_login',None)
        return jsonify(message=str(exc)),502
    return jsonify(ok=True,otp_required=True,masked_phone='******'+normalized[-4:])

@app.post('/api/resend-otp')
def resend_otp():
    d=request.get_json(force=True)
    purpose=d.get('purpose','').strip()
    email=d.get('email','').strip().lower()
    if purpose=='login':
        pending=session.get('pending_login')
        if not pending or pending.get('email')!=email:return jsonify(message='Login session expired. Please login again.'),401
        if pending.get('role')=='admin':
            phone=ADMIN_WHATSAPP
        else:
            c=db(); u=c.execute('SELECT whatsapp FROM members WHERE email=?',(email,)).fetchone(); c.close()
            if not u:return jsonify(message='Account not found'),404
            phone=u['whatsapp']
        label='login OTP'
    elif purpose=='register':
        c=db(); u=c.execute('SELECT whatsapp FROM members WHERE email=?',(email,)).fetchone(); c.close()
        if not u:return jsonify(message='Account not found'),404
        phone=u['whatsapp']; label='registration OTP'
    else:
        return jsonify(message='Invalid OTP purpose'),400
    normalized=normalize_phone(phone)
    if not normalized:return jsonify(message='Invalid mobile number'),400
    try:
        create_and_send_otp(email,purpose,normalized,label)
    except ValueError as exc:return jsonify(message=str(exc)),429
    except Exception as exc:return jsonify(message=str(exc)),502
    return jsonify(ok=True)

@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)

@app.post('/api/forgot-password')
def forgot():
    d=request.get_json(force=True)
    identity=d.get('identity','').strip()
    c=db()
    u=c.execute('SELECT email,whatsapp FROM members WHERE lower(email)=? OR whatsapp=?',(identity.lower(),identity)).fetchone()
    c.close()
    if not u:return jsonify(message='Account not found'),404
    normalized=normalize_phone(u['whatsapp'])
    if not normalized:return jsonify(message='Account has an invalid mobile number'),400
    try:create_and_send_otp(u['email'],'reset',normalized,'password reset OTP')
    except ValueError as exc:return jsonify(message=str(exc)),429
    except Exception as exc:return jsonify(message=str(exc)),502
    return jsonify(ok=True,email=u['email'])

@app.post('/api/reset-password')
def reset():
    d=request.get_json(force=True)
    email=d.get('email','').strip().lower()
    code=d.get('otp','').strip()
    newp=d.get('password','')
    if len(newp)<6:return jsonify(message='Password must be at least 6 characters'),400
    ok,msg=verify_otp_code(email,'reset',code)
    if not ok:return jsonify(message=msg),400
    c=db()
    c.execute('UPDATE members SET password_hash=? WHERE email=?',(generate_password_hash(newp),email))
    c.commit(); c.close()
    return jsonify(ok=True)

@app.post('/api/resend-reset-otp')
def resend_reset_otp():
    d=request.get_json(force=True); email=d.get('email','').strip().lower()
    c=db(); u=c.execute('SELECT whatsapp FROM members WHERE email=?',(email,)).fetchone(); c.close()
    if not u:return jsonify(message='Account not found'),404
    normalized=normalize_phone(u['whatsapp'])
    try:create_and_send_otp(email,'reset',normalized,'password reset OTP')
    except ValueError as exc:return jsonify(message=str(exc)),429
    except Exception as exc:return jsonify(message=str(exc)),502
    return jsonify(ok=True)

@app.post('/api/verify-uid')
def verify_uid():
 d=request.get_json(force=True); uid=str(d.get('uid','')).strip(); region=d.get('region','')
 if not uid.isdigit() or len(uid)<6:return jsonify(message='Invalid UID'),400
 # Manual mode: no external Free Fire API. UID format is checked only.
 return jsonify(ok=True,playerName='UID format verified (manual top-up)')

@app.get('/api/wallet')
@member_required
def wallet():
 c=db(); r=c.execute("SELECT balance,COALESCE(reserved,0) AS reserved FROM wallet WHERE member_id=?",(session['member_id'],)).fetchone(); c.close()
 balance=int(r['balance']) if r else 0; reserved=int(r['reserved']) if r else 0
 return jsonify(balance=balance,reserved=reserved,available_balance=max(0,balance-reserved),ez_cash=EZ_CASH)

@app.get('/api/wallet/transactions')
@member_required
def wallet_transactions():
 c=db(); rows=c.execute('SELECT * FROM wallet_transactions WHERE member_id=? ORDER BY id DESC',(session['member_id'],)).fetchall(); c.close(); return jsonify(transactions=[dict(x) for x in rows])

@app.post('/api/wallet/recharge')
@member_required
def wallet_recharge():
 d=request.get_json(force=True); amount=money_int(d.get('amount')); receipt=d.get('receipt','')
 if amount<=0:return jsonify(message='Invalid amount'),400
 if not receipt:return jsonify(message='Payment receipt required'),400
 c=db(); cur=c.execute("INSERT INTO wallet_transactions(member_id,type,amount,status,receipt,payment_method,payment_number) VALUES(?,?,?,?,?,?,?)",(session['member_id'],'Wallet Recharge',amount,'pending',receipt,d.get('payment_method','eZ Cash'),EZ_CASH)); c.commit(); tid=cur.lastrowid; c.close(); return jsonify(ok=True,transaction_id=tid)

@app.get('/api/admin/wallet-recharges')
@admin_required
def admin_recharges():
 status=request.args.get('status','pending'); c=db(); q='''SELECT wt.*,m.name,m.email,m.whatsapp FROM wallet_transactions wt JOIN members m ON m.id=wt.member_id WHERE wt.type='Wallet Recharge' ''' ; args=[]
 if status in ('pending','approved','cancelled'): q+=' AND wt.status=?'; args.append(status)
 q+=' ORDER BY wt.id DESC'; rows=c.execute(q,args).fetchall(); c.close(); return jsonify(recharges=[dict(r) for r in rows])

@app.post('/api/admin/wallet-recharge/<int:tid>/<action>')
@admin_required
def admin_wallet_action(tid,action):
 if action not in ('approve','cancel'):return jsonify(message='Invalid action'),400
 c=db(); t=c.execute('SELECT * FROM wallet_transactions WHERE id=?',(tid,)).fetchone()
 if not t:c.close();return jsonify(message='Recharge not found'),404
 if t['status']!='pending':c.close();return jsonify(message='Recharge already processed'),400
 if action=='approve':
  c.execute('UPDATE wallet_transactions SET status=\'approved\',approved_at=CURRENT_TIMESTAMP WHERE id=?',(tid,)); c.execute('UPDATE wallet SET balance=balance+? WHERE member_id=?',(t['amount'],t['member_id']));
 else:c.execute('UPDATE wallet_transactions SET status=\'cancelled\' WHERE id=?',(tid,))
 c.commit(); r=c.execute('SELECT * FROM wallet_transactions WHERE id=?',(tid,)).fetchone(); c.close(); return jsonify(ok=True,recharge=dict(r))

@app.post('/api/orders')
@member_required
def create_order():
 d=request.get_json(force=True); uid=str(d.get('uid','')).strip(); game=d.get('game','').strip(); region=d.get('region','').strip()
 package=d.get('package','').strip(); q=max(1,min(10,money_int(d.get('quantity',1)))); pay=d.get('payment_method','').strip()
 receipt=d.get('receipt','') or ''; unit=money_int(d.get('unit_price')); total=unit*q
 if region not in ('SG','IND') or not uid.isdigit() or len(uid)<6:return jsonify(message='Please enter a valid UID and game region'),400
 if not package or unit<=0:return jsonify(message='Invalid package'),400
 valid_prices={name:price for name,price in PACKAGES[region].get('diamonds',[])+PACKAGES[region].get('membership',[])+PACKAGES[region].get('level',[])}
 if package not in valid_prices or valid_prices[package]!=unit:return jsonify(message='Package price mismatch'),400
 if pay not in ('My Wallet','Bank Transfer'):return jsonify(message='Invalid payment method'),400
 if pay=='Bank Transfer' and not receipt:return jsonify(message='Bank transfer receipt required'),400
 c=db()
 try:
  c.execute("BEGIN IMMEDIATE"); u=c.execute("SELECT * FROM members WHERE id=?",(session['member_id'],)).fetchone()
  if not u:c.rollback(); c.close(); return jsonify(message='Member account not found'),401
  if pay=='My Wallet':
   w=c.execute("SELECT balance,COALESCE(reserved,0) AS reserved FROM wallet WHERE member_id=?",(session['member_id'],)).fetchone()
   if not w:c.execute("INSERT INTO wallet(member_id,balance,reserved) VALUES(?,?,0)",(session['member_id'],0)); balance=reserved=0
   else:balance=int(w['balance']); reserved=int(w['reserved'])
   available=balance-reserved
   if available<total:c.rollback(); c.close(); return jsonify(message=f'Insufficient wallet balance. Available Rs. {max(0,available)}. Required Rs. {total}'),400
   c.execute("UPDATE wallet SET reserved=COALESCE(reserved,0)+? WHERE member_id=?",(total,session['member_id']))
  cur=c.execute("INSERT INTO orders(member_id,customer_name,whatsapp,email,game,package,unit_price,quantity,price,bonus,uid,region,player_name,payment_method,receipt,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending')",
                (u['id'],u['name'],u['whatsapp'],u['email'],game,package,unit,q,total,d.get('bonus',''),uid,region,d.get('playerName','Unknown'),pay,receipt))
  oid=cur.lastrowid
  if pay=='My Wallet':
   c.execute("INSERT INTO wallet_transactions(member_id,type,amount,status,payment_method,payment_number,order_id) VALUES(?,?,?,'pending',?,?,?)",
             (session['member_id'],'Order Payment',-total,'My Wallet','',oid))
  c.commit(); o=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone(); c.close(); return jsonify(ok=True,order=dict(o))
 except Exception:
  try:c.rollback()
  except:pass
  c.close(); return jsonify(message='Unable to create order safely. Please try again.'),500

@app.get('/api/my-orders')
@member_required
def my_orders():
 c=db(); rows=c.execute('SELECT * FROM orders WHERE member_id=? ORDER BY id DESC',(session['member_id'],)).fetchall(); c.close(); return jsonify(orders=[dict(r) for r in rows])

@app.get('/api/admin/orders')
@admin_required
def admin_orders():
 status=request.args.get('status','all'); c=db(); q='SELECT * FROM orders'; args=[]
 if status in ('pending','completed','cancelled'):q+=' WHERE status=?';args=[status]
 q+=' ORDER BY id DESC'; rows=c.execute(q,args).fetchall(); stats={}
 for k in ('total','pending','completed','cancelled'):
  stats[k]=c.execute('SELECT COUNT(*) FROM orders'+((' WHERE status=?') if k!='total' else ''),((k,) if k!='total' else ())).fetchone()[0]
 stats['confirmed']=stats['completed']; stats['members']=c.execute('SELECT COUNT(*) FROM members').fetchone()[0]; c.close()
 return jsonify(orders=[dict(r) for r in rows],stats=stats)

@app.get('/api/admin/order/<int:oid>')
@admin_required
def admin_get_order(oid):
 c=db(); o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); c.close()
 return (jsonify(order=dict(o)) if o else (jsonify(message='Order not found'),404))

@app.post('/api/admin/order/<int:oid>/<action>')
@admin_required
def admin_order_action(oid,action):
 if action not in ('confirm','cancel'):return jsonify(message='Invalid action'),400
 c=db()
 try:
  c.execute("BEGIN IMMEDIATE"); o=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
  if not o:c.rollback(); c.close(); return jsonify(message='Order not found'),404
  if o['status']!='pending':c.rollback(); c.close(); return jsonify(message=f'Order already {o["status"]}'),400
  if action=='confirm':
   if o['payment_method']=='My Wallet':
    w=c.execute("SELECT balance,COALESCE(reserved,0) AS reserved FROM wallet WHERE member_id=?",(o['member_id'],)).fetchone()
    if not w or int(w['reserved'])<int(o['price']) or int(w['balance'])<int(o['price']):
     c.rollback(); c.close(); return jsonify(message='Wallet reservation is missing or insufficient; order was not confirmed'),409
    c.execute("UPDATE wallet SET balance=balance-?,reserved=reserved-? WHERE member_id=?",(o['price'],o['price'],o['member_id']))
    c.execute("UPDATE wallet_transactions SET status='approved',approved_at=CURRENT_TIMESTAMP WHERE order_id=? AND type='Order Payment' AND status='pending'",(oid,))
   c.execute("UPDATE orders SET status='completed',confirmed_at=CURRENT_TIMESTAMP WHERE id=?",(oid,))
  else:
   if o['payment_method']=='My Wallet':
    w=c.execute("SELECT COALESCE(reserved,0) AS reserved FROM wallet WHERE member_id=?",(o['member_id'],)).fetchone()
    if w and int(w['reserved'])>=int(o['price']):c.execute("UPDATE wallet SET reserved=reserved-? WHERE member_id=?",(o['price'],o['member_id']))
    c.execute("UPDATE wallet_transactions SET status='cancelled',approved_at=CURRENT_TIMESTAMP WHERE order_id=? AND type='Order Payment' AND status='pending'",(oid,))
    c.execute("INSERT INTO wallet_transactions(member_id,type,amount,status,payment_method,order_id) VALUES(?, 'Refund', ?, 'approved', 'My Wallet', ?)",(o['member_id'],o['price'],oid))
   c.execute("UPDATE orders SET status='cancelled',cancelled_at=CURRENT_TIMESTAMP WHERE id=?",(oid,))
  c.commit(); o=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone(); c.close(); return jsonify(ok=True,order=dict(o))
 except Exception:
  try:c.rollback()
  except:pass
  c.close(); return jsonify(message='Could not process this order safely'),500

@app.get('/api/admin/members')
@admin_required
def admin_members():
 c=db(); rows=c.execute('SELECT id,name,email,whatsapp,created_at FROM members ORDER BY id DESC').fetchall(); c.close(); return jsonify(members=[dict(r) for r in rows])

init_db()
if __name__=='__main__': app.run(debug=True)
