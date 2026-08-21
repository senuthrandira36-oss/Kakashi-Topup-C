import os, sqlite3
from functools import wraps
from flask import Flask, render_template, request, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kakashi-topup-local-secret-2026")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=False, PERMANENT_SESSION_LIFETIME=86400)
DB = os.path.join(os.path.dirname(__file__), "database.db")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@kakashi.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_WHATSAPP = "94766559214"
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "KAKASHI-ADMIN-2026")

def get_db():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    return con

def init_db():
    con=get_db()
    con.execute("""CREATE TABLE IF NOT EXISTS members(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, whatsapp TEXT NOT NULL,
        password_hash TEXT NOT NULL, role TEXT DEFAULT 'member',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER,
        customer_name TEXT NOT NULL, whatsapp TEXT NOT NULL, email TEXT NOT NULL,
        package TEXT NOT NULL, price TEXT NOT NULL, bonus TEXT NOT NULL,
        uid TEXT NOT NULL, region TEXT NOT NULL, player_name TEXT NOT NULL,
        receipt TEXT, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, confirmed_at TEXT)""")
    con.commit(); con.close()

def is_admin_request():
    return session.get("role") == "admin" or request.headers.get("X-Admin-Key") == ADMIN_API_KEY

def admin_required(fn):
    @wraps(fn)
    def w(*a,**k):
        if not is_admin_request(): return jsonify(message="Admin access only"),403
        return fn(*a,**k)
    return w

@app.route("/")
def index(): return render_template("index.html")

@app.get("/api/me")
def me():
    if "role" not in session: return jsonify(user=None)
    return jsonify(user={"id":session["member_id"],"name":session["name"],"email":session["email"],"whatsapp":session["whatsapp"],"role":session["role"]})

@app.post("/api/register")
def register():
    d=request.get_json(force=True)
    name,email,whatsapp,password=(d.get("name","").strip(),d.get("email","").strip().lower(),d.get("whatsapp","").strip(),d.get("password",""))
    if not all([name,email,whatsapp,password]): return jsonify(message="Please fill all fields"),400
    if len(password)<6:return jsonify(message="Password must be at least 6 characters"),400
    con=get_db()
    try:
        con.execute("INSERT INTO members(name,email,whatsapp,password_hash) VALUES(?,?,?,?)",(name,email,whatsapp,generate_password_hash(password)))
        con.commit()
    except sqlite3.IntegrityError:
        con.close(); return jsonify(message="Email already registered"),409
    con.close(); return jsonify(ok=True)

@app.post("/api/login")
def login():
    d=request.get_json(force=True); email=d.get("email","").strip().lower(); password=d.get("password","")
    if email==ADMIN_EMAIL.lower() and password==ADMIN_PASSWORD:
        session.clear(); session.permanent = True; session.update(role="admin",member_id=0,name="Admin Kakashi",email=ADMIN_EMAIL,whatsapp=ADMIN_WHATSAPP)
        return jsonify(user={"id":0,"name":"Admin Kakashi","email":ADMIN_EMAIL,"whatsapp":ADMIN_WHATSAPP,"role":"admin"})
    con=get_db(); u=con.execute("SELECT * FROM members WHERE email=?",(email,)).fetchone(); con.close()
    if not u or not check_password_hash(u["password_hash"],password): return jsonify(message="Invalid email or password"),401
    session.clear(); session.permanent = True; session.update(role="member",member_id=u["id"],name=u["name"],email=u["email"],whatsapp=u["whatsapp"])
    return jsonify(user={"id":u["id"],"name":u["name"],"email":u["email"],"whatsapp":u["whatsapp"],"role":"member"})

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.post("/api/orders")
def create_order():
    d=request.get_json(force=True)
    required=["package","price","bonus","uid","region","playerName","whatsapp","email","customerName"]
    if not all(str(d.get(k,"")).strip() for k in required): return jsonify(message="Please complete all order fields"),400
    con=get_db()
    cur=con.execute("""INSERT INTO orders(member_id,customer_name,whatsapp,email,package,price,bonus,uid,region,player_name,receipt)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(session.get("member_id"),d["customerName"],d["whatsapp"],d["email"],d["package"],d["price"],d["bonus"],d["uid"],d["region"],d["playerName"],d.get("receipt","")))
    oid=cur.lastrowid; con.commit()
    o=con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone(); con.close()
    return jsonify(order=dict(o))

@app.get("/api/my-orders")
def my_orders():
    if session.get("role")!="member": return jsonify(message="Login required"),401
    con=get_db(); rows=con.execute("SELECT * FROM orders WHERE member_id=? ORDER BY id DESC",(session["member_id"],)).fetchall(); con.close()
    return jsonify(orders=[dict(r) for r in rows])

def order_row(con,oid): return con.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()

@app.get("/api/admin/orders")
@admin_required
def admin_orders():
    status=request.args.get("status","all")
    con=get_db()
    q="SELECT * FROM orders"; args=()
    if status in ("pending","confirmed","cancelled"): q+=" WHERE status=?"; args=(status,)
    q+=" ORDER BY id DESC"
    rows=con.execute(q,args).fetchall()
    stats={"total":con.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
           "pending":con.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0],
           "confirmed":con.execute("SELECT COUNT(*) FROM orders WHERE status='confirmed'").fetchone()[0],
           "members":con.execute("SELECT COUNT(*) FROM members").fetchone()[0]}
    con.close(); return jsonify(orders=[dict(r) for r in rows],stats=stats)

@app.get("/api/admin/order/<int:oid>")
@admin_required
def admin_get(oid):
    con=get_db(); o=order_row(con,oid); con.close()
    if not o:return jsonify(message="Order not found"),404
    return jsonify(order=dict(o))

@app.post("/api/admin/order/<int:oid>/<action>")
@admin_required
def admin_action(oid,action):
    status={"confirm":"confirmed","cancel":"cancelled"}.get(action)
    if not status:return jsonify(message="Invalid action"),400
    con=get_db(); o=order_row(con,oid)
    if not o:con.close();return jsonify(message="Order not found"),404
    con.execute("UPDATE orders SET status=?,confirmed_at=CURRENT_TIMESTAMP WHERE id=?",(status,oid));con.commit()
    o=order_row(con,oid);con.close();return jsonify(order=dict(o))

# Initialize database on app startup (works with Gunicorn/production imports).
init_db()

if __name__=="__main__":
    app.run(debug=True)
