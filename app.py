from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import date

app = Flask(__name__)
app.secret_key = "mastihub-secret-key"

DB = "mastihub.db"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
DAILY_LIMIT = 1000
POINTS_PER_100 = 10

MISSIONS = [
    ("Daily Quiz", 100),
    ("Tap Challenge", 100),
    ("Memory Challenge", 100),
    ("Puzzle Mission", 100),
    ("Quick Challenge", 100),
    ("Speed Challenge", 100),
    ("Bonus Mission", 100),
    ("Lucky Mission", 100),
    ("Final Challenge", 100),
    ("Daily Bonus", 100)
]


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    # Add daily tracking columns to older databases
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]

    if "today_points" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN today_points INTEGER DEFAULT 0")

    if "last_date" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_date TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            today_points INTEGER DEFAULT 0,
            last_date TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS completed_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mission_id INTEGER NOT NULL,
            completed_date TEXT NOT NULL,
            UNIQUE(user_id, mission_id, completed_date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            points_used INTEGER NOT NULL,
            upi TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


@app.route("/")
def home():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("login"))

    today = str(date.today())

    completed_rows = conn.execute(
        """
        SELECT mission_id
        FROM completed_missions
        WHERE user_id = ?
        AND completed_date = ?
        """,
        (user["id"], today)
    ).fetchall()

    conn.close()

    completed = {row["mission_id"] for row in completed_rows}

    missions = []

    for i, (title, points) in enumerate(MISSIONS, start=1):
        missions.append({
            "id": i,
            "title": title,
            "points": points,
            "completed": i in completed
        })

    return render_template(
        "index.html",
        user=user,
        missions=missions
    )


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if len(username) < 3:
            return "Username कम से कम 3 अक्षर का होना चाहिए।"

        if len(password) < 6:
            return "Password कम से कम 6 अक्षर का होना चाहिए।"

        conn = get_db()

        try:
            conn.execute(
                """
                INSERT INTO users (username, password, points, today_points, last_date)
                VALUES (?, ?, 0, 0, ?)
                """,
                (username, generate_password_hash(password), str(date.today()))
            )

            conn.commit()

        except sqlite3.IntegrityError:
            conn.close()
            return "यह username पहले से मौजूद है।"

        conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin"))

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]

            return redirect(url_for("home"))

        return "Username या password गलत है।"

    return render_template("login.html")


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


@app.route("/mission/<int:mission_id>")
def mission(mission_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if mission_id < 1 or mission_id > len(MISSIONS):
        return redirect(url_for("home"))

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("login"))

    today = str(date.today())

    # Reset daily earning counter when a new day starts
    if user["last_date"] != today:
        conn.execute(
            """
            UPDATE users
            SET today_points = 0,
                last_date = ?
            WHERE id = ?
            """,
            (today, user["id"])
        )
        conn.commit()

        user = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user["id"],)
        ).fetchone()

    # Check whether this mission is already completed today
    already_done = conn.execute(
        """
        SELECT id
        FROM completed_missions
        WHERE user_id = ?
        AND mission_id = ?
        AND completed_date = ?
        """,
        (user["id"], mission_id, today)
    ).fetchone()

    if already_done:
        conn.close()
        return redirect(url_for("home"))

    # Maximum 1000 points
    if user["today_points"] >= DAILY_LIMIT:
        conn.close()
        return redirect(url_for("home"))

    reward = MISSIONS[mission_id - 1][1]

    reward = min(
        reward,
        DAILY_LIMIT - user["today_points"]
    )

    conn.execute(
        """
        UPDATE users
        SET points = points + ?,
            today_points = today_points + ?,
            last_date = ?
        WHERE id = ?
        """,
        (reward, reward, today, user["id"])
    )

    conn.execute(
        """
        INSERT INTO completed_missions
        (user_id, mission_id, completed_date)
        VALUES (?, ?, ?)
        """,
        (user["id"], mission_id, today)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("home"))


@app.route("/withdraw", methods=["GET", "POST"])
def withdraw():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if request.method == "POST":

        try:
            amount = int(request.form.get("amount", "0"))
        except ValueError:
            amount = 0

        upi = request.form.get("upi", "").strip()

        # 100 points = ₹10
        points_needed = amount * 10

        if amount < 10:
            conn.close()
            return render_template(
                "withdraw.html",
                user=user,
                error="Minimum withdrawal ₹10 है।"
            )

        if not upi:
            conn.close()
            return render_template(
                "withdraw.html",
                user=user,
                error="UPI ID डालें।"
            )

        if points_needed > user["points"]:
            conn.close()
            return render_template(
                "withdraw.html",
                user=user,
                error="आपके पास पर्याप्त points नहीं हैं।"
            )

        conn.execute(
            """
            INSERT INTO withdrawals
            (user_id, amount, points_used, upi, status, created_at)
            VALUES (?, ?, ?, ?, 'Pending', ?)
            """,
            (
                user["id"],
                amount,
                points_needed,
                upi,
                str(date.today())
            )
        )

        conn.execute(
            """
            UPDATE users
            SET points = points - ?
            WHERE id = ?
            """,
            (points_needed, user["id"])
        )

        conn.commit()
        conn.close()

        return redirect(url_for("history"))

    conn.close()

    return render_template(
        "withdraw.html",
        user=user
    )


@app.route("/history")
def history():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    withdrawals = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "history.html",
        withdrawals=withdrawals
    )




@app.route("/admin/revenue", methods=["POST"])
def admin_revenue():
    if not session.get("admin"):
        return redirect(url_for("login"))

    try:
        amount = float(request.form.get("amount", "0"))
    except ValueError:
        amount = 0

    source = request.form.get("source", "").strip()

    if amount <= 0 or not source:
        return redirect(url_for("admin"))

    conn = get_db()
    conn.execute("""
        INSERT INTO platform_revenue
        (amount, source, created_at)
        VALUES (?, ?, ?)
    """, (amount, source, str(date.today())))

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))



@app.route("/admin/revenue/<int:revenue_id>/delete", methods=["GET", "POST"])
def delete_revenue(revenue_id):

    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = get_db()

    conn.execute(
        "DELETE FROM platform_revenue WHERE id = ?",
        (revenue_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))

@app.route("/admin")
def admin():

    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = get_db()

    withdrawals = conn.execute("""
        SELECT withdrawals.*, users.username
        FROM withdrawals
        JOIN users ON users.id = withdrawals.user_id
        ORDER BY withdrawals.id DESC
    """).fetchall()

    users = conn.execute("""
        SELECT id, username, points
        FROM users
        ORDER BY id DESC
    """).fetchall()

    total_users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    total_points = conn.execute(
        "SELECT COALESCE(SUM(points), 0) AS s FROM users"
    ).fetchone()["s"]

    total_withdrawals = conn.execute(
        "SELECT COUNT(*) AS c FROM withdrawals"
    ).fetchone()["c"]

    approved_withdrawals = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS s
        FROM withdrawals
        WHERE status = 'Approved'
    """).fetchone()["s"]

    pending_withdrawals = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS s
        FROM withdrawals
        WHERE status = 'Pending'
    """).fetchone()["s"]

    # 1000 points = ₹100
    reward_value = total_points / 10

    total_revenue = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM platform_revenue"
    ).fetchone()["s"]

    revenue_history = conn.execute("""
        SELECT id, amount, source, created_at
        FROM platform_revenue
        ORDER BY id DESC
    """).fetchall()

    admin_net = total_revenue - approved_withdrawals

    conn.close()

    return render_template(
        "admin.html",
        withdrawals=withdrawals,
        users=users,
        total_users=total_users,
        total_points=total_points,
        reward_value=reward_value,
        total_withdrawals=total_withdrawals,
        approved_withdrawals=approved_withdrawals,
        pending_withdrawals=pending_withdrawals,
        total_revenue=total_revenue,
        revenue_history=revenue_history,
        admin_net=admin_net
    )


@app.route("/admin/withdraw/<int:withdrawal_id>/<action>")
def admin_withdraw(withdrawal_id, action):

    if not session.get("admin"):
        return redirect(url_for("login"))

    if action not in ("approve", "reject"):
        return redirect(url_for("admin"))

    conn = get_db()

    withdrawal = conn.execute(
        "SELECT * FROM withdrawals WHERE id = ?",
        (withdrawal_id,)
    ).fetchone()

    if not withdrawal or withdrawal["status"] != "Pending":
        conn.close()
        return redirect(url_for("admin"))

    if action == "approve":

        conn.execute(
            "UPDATE withdrawals SET status='Approved' WHERE id=?",
            (withdrawal_id,)
        )

    else:

        conn.execute(
            "UPDATE users SET points=points+? WHERE id=?",
            (withdrawal["points_used"], withdrawal["user_id"])
        )

        conn.execute(
            "UPDATE withdrawals SET status='Rejected' WHERE id=?",
            (withdrawal_id,)
        )

    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("login"))


init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

