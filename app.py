import os, sqlite3, secrets, time
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

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

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
 c.execute('''CREATE TABLE IF NOT EXISTS otp(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT NOT NULL,code TEXT NOT NULL,purpose TEXT NOT NULL,expires_at INTEGER NOT NULL,used INTEGER DEFAULT 0)''')
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

# fix accidental SQL placeholder with helper override
def save_otp(email,purpose):
 code=f'{secrets.randbelow(1000000):06d}'
 c=db(); c.execute("UPDATE otp SET used=1 WHERE email=? AND purpose=? AND used=0",(email,purpose)); c.execute("INSERT INTO otp(email,code,purpose,expires_at) VALUES(?,?,?,?)",(email,code,purpose,int(time.time())+600)); c.commit(); c.close(); print(f'[KAKASHI DEV OTP] {purpose} for {email}: {code}'); return code

@app.route('/')
def index(): return render_template('index.html')

@app.get('/api/me')
def me(): return jsonify(user=current_user())

@app.post('/api/register')
def register():
 d=request.get_json(force=True); name=d.get('name','').strip(); email=d.get('email','').strip().lower(); phone=d.get('whatsapp','').strip(); password=d.get('password','')
 if not all([name,email,phone,password]): return jsonify(message='Please fill all fields'),400
 if len(password)<6:return jsonify(message='Password must be at least 6 characters'),400
 c=db()
 try:
  cur=c.execute("INSERT INTO members(name,email,whatsapp,password_hash) VALUES(?,?,?,?)",(name,email,phone,generate_password_hash(password))); mid=cur.lastrowid; c.execute('INSERT INTO wallet(member_id,balance) VALUES(?,0)',(mid,)); c.commit()
 except sqlite3.IntegrityError: c.close(); return jsonify(message='Email already registered'),409
 c.close(); save_otp(email,'register')
 # No SMS API: OTP is printed in server console; account can be verified by /api/verify-otp.
 return jsonify(ok=True,otp_required=True,message='OTP generated. Check the server console in manual mode.')

@app.post('/api/verify-otp')
def verify_otp():
 d=request.get_json(force=True); email=d.get('email','').strip().lower(); code=d.get('otp','').strip()
 c=db(); row=c.execute("SELECT * FROM otp WHERE email=? AND purpose='register' AND code=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1",(email,code,int(time.time()))).fetchone()
 if not row:c.close();return jsonify(message='Invalid or expired OTP'),400
 c.execute('UPDATE otp SET used=1 WHERE id=?',(row['id'],)); c.execute('UPDATE members SET verified=1 WHERE email=?',(email,)); c.commit(); c.close(); return jsonify(ok=True)

@app.post('/api/login')
def login():
 d=request.get_json(force=True); email=d.get('email','').strip().lower(); password=d.get('password','')
 if email==ADMIN_EMAIL.lower() and password==ADMIN_PASSWORD:
  session.clear(); session.permanent=True; session.update(role='admin',member_id=0,name='Admin Kakashi',email=ADMIN_EMAIL,whatsapp=ADMIN_WHATSAPP); return jsonify(user=current_user())
 c=db(); u=c.execute('SELECT * FROM members WHERE email=?',(email,)).fetchone(); c.close()
 if not u or not check_password_hash(u['password_hash'],password):return jsonify(message='Invalid email or password'),401
 if not u['verified']:return jsonify(message='Please verify your account first'),403
 session.clear(); session.permanent=True; session.update(role='member',member_id=u['id'],name=u['name'],email=u['email'],whatsapp=u['whatsapp']); return jsonify(user=current_user())

@app.post('/api/logout')
def logout(): session.clear(); return jsonify(ok=True)

@app.post('/api/forgot-password')
def forgot():
 d=request.get_json(force=True); identity=d.get('identity','').strip().lower(); c=db(); u=c.execute('SELECT email FROM members WHERE lower(email)=? OR whatsapp=?',(identity,identity)).fetchone(); c.close()
 if not u:return jsonify(message='Account not found'),404
 save_otp(u['email'],'reset'); return jsonify(ok=True,message='Reset OTP generated. Check server console in manual mode.')

@app.post('/api/reset-password')
def reset():
 d=request.get_json(force=True); email=d.get('email','').strip().lower(); code=d.get('otp','').strip(); newp=d.get('password','')
 if len(newp)<6:return jsonify(message='Password must be at least 6 characters'),400
 c=db(); row=c.execute("SELECT * FROM otp WHERE email=? AND purpose='reset' AND code=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1",(email,code,int(time.time()))).fetchone()
 if not row:c.close();return jsonify(message='Invalid or expired OTP'),400
 c.execute('UPDATE members SET password_hash=? WHERE email=?',(generate_password_hash(newp),email)); c.execute('UPDATE otp SET used=1 WHERE id=?',(row['id'],)); c.commit(); c.close(); return jsonify(ok=True)

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
