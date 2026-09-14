from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("LICENSE_DB_PATH", str(BASE_DIR / "license.db"))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("LICENSE_SECRET_KEY", "change-this-secret-key")

DURATION_PRESETS = {
    "1day": ("1일", timedelta(days=1)),
    "3day": ("3일", timedelta(days=3)),
    "1week": ("1주일", timedelta(weeks=1)),
    "1month": ("1개월", timedelta(days=30)),
    "3month": ("3개월", timedelta(days=90)),
    "1year": ("1년", timedelta(days=365)),
    "unlimited": ("무제한", None),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            mac_address TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT,
            memo TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    cur = db.execute("SELECT COUNT(*) AS c FROM admin")
    if cur.fetchone()["c"] == 0:
        admin_user = os.environ.get("LICENSE_ADMIN_USER", "admin")
        admin_pw = os.environ.get("LICENSE_ADMIN_PASSWORD", "admin1234")
        db.execute(
            "INSERT INTO admin (username, password_hash) VALUES (?, ?)",
            (admin_user, generate_password_hash(admin_pw)),
        )
        db.commit()
        print(f"[license_server] 최초 관리자 계정 생성: {admin_user} / {admin_pw} (반드시 로그인 후 비밀번호를 변경하세요)")
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def user_status(row: sqlite3.Row) -> tuple[str, str]:
    """(상태라벨, css클래스) 반환"""
    if not row["is_active"]:
        return "비활성", "status-disabled"
    exp = _parse_iso(row["expires_at"])
    if exp is None:
        return "무제한", "status-unlimited"
    if exp < now_utc():
        return "만료", "status-expired"
    remain = exp - now_utc()
    if remain <= timedelta(days=1):
        return "곧만료", "status-soon"
    return "활성", "status-active"


@app.context_processor
def inject_helpers():
    return {"user_status": user_status, "duration_presets": DURATION_PRESETS}


# ---------------------------------------------------------------- admin ui

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard") if session.get("admin_id") else url_for("login"))


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        row = db.execute("SELECT * FROM admin WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session["admin_id"] = row["id"]
            session["admin_username"] = row["username"]
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        error = "아이디 또는 비밀번호가 올바르지 않습니다."
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/dashboard")
@login_required
def dashboard():
    db = get_db()
    q = request.args.get("q", "").strip()
    if q:
        rows = db.execute(
            "SELECT * FROM users WHERE username LIKE ? ORDER BY created_at DESC",
            (f"%{q}%",),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return render_template("dashboard.html", users=rows, q=q, admin_username=session.get("admin_username"))


@app.route("/admin/users/new", methods=["GET", "POST"])
@login_required
def user_new():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        duration = request.form.get("duration", "1month")
        memo = request.form.get("memo", "").strip()
        if not username or not password:
            error = "아이디와 비밀번호를 입력하세요."
        else:
            db = get_db()
            exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if exists:
                error = "이미 존재하는 아이디입니다."
            else:
                _, delta = DURATION_PRESETS.get(duration, DURATION_PRESETS["1month"])
                expires_at = _iso(now_utc() + delta) if delta else None
                ts = _iso(now_utc())
                db.execute(
                    """INSERT INTO users
                       (username, password_hash, mac_address, is_active, expires_at, memo, created_at, updated_at)
                       VALUES (?, ?, NULL, 1, ?, ?, ?, ?)""",
                    (username, generate_password_hash(password), expires_at, memo, ts, ts),
                )
                db.commit()
                return redirect(url_for("dashboard"))
    return render_template("user_form.html", error=error, user=None)


@app.route("/admin/users/<int:user_id>/extend", methods=["POST"])
@login_required
def user_extend(user_id: int):
    duration = request.form.get("duration", "1month")
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        _, delta = DURATION_PRESETS.get(duration, DURATION_PRESETS["1month"])
        if delta is None:
            new_expiry = None
        else:
            current = _parse_iso(row["expires_at"])
            base = current if (current and current > now_utc()) else now_utc()
            new_expiry = _iso(base + delta)
        db.execute(
            "UPDATE users SET expires_at = ?, updated_at = ? WHERE id = ?",
            (new_expiry, _iso(now_utc()), user_id),
        )
        db.commit()
    return redirect(url_for("dashboard"))


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def user_toggle(user_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        db.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
            (0 if row["is_active"] else 1, _iso(now_utc()), user_id),
        )
        db.commit()
    return redirect(url_for("dashboard"))


@app.route("/admin/users/<int:user_id>/reset_mac", methods=["POST"])
@login_required
def user_reset_mac(user_id: int):
    db = get_db()
    db.execute(
        "UPDATE users SET mac_address = NULL, updated_at = ? WHERE id = ?",
        (_iso(now_utc()), user_id),
    )
    db.commit()
    return redirect(url_for("dashboard"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id: int):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return redirect(url_for("dashboard"))


@app.route("/admin/users/<int:user_id>/password", methods=["POST"])
@login_required
def user_password(user_id: int):
    new_password = request.form.get("password", "")
    if new_password:
        db = get_db()
        db.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (generate_password_hash(new_password), _iso(now_utc()), user_id),
        )
        db.commit()
    return redirect(url_for("dashboard"))


@app.route("/admin/account", methods=["GET", "POST"])
@login_required
def account():
    error = None
    success = None
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        db = get_db()
        row = db.execute("SELECT * FROM admin WHERE id = ?", (session["admin_id"],)).fetchone()
        if not row or not check_password_hash(row["password_hash"], current_pw):
            error = "현재 비밀번호가 올바르지 않습니다."
        elif not new_pw:
            error = "새 비밀번호를 입력하세요."
        else:
            db.execute(
                "UPDATE admin SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new_pw), session["admin_id"]),
            )
            db.commit()
            success = "비밀번호가 변경되었습니다."
    return render_template("account.html", error=error, success=success)


# ---------------------------------------------------------------- public api

@app.route("/api/v1/verify", methods=["POST"])
def api_verify():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    mac_address = str(data.get("mac_address", "")).strip()

    if not username or not password:
        return jsonify(success=False, message="아이디와 비밀번호를 입력하세요."), 400

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify(success=False, message="아이디 또는 비밀번호가 올바르지 않습니다."), 200

    if not row["is_active"]:
        return jsonify(success=False, message="비활성화된 계정입니다. 관리자에게 문의하세요."), 200

    expires_at = _parse_iso(row["expires_at"])
    if expires_at is not None and expires_at < now_utc():
        return jsonify(success=False, message="이용권이 만료되었습니다."), 200

    stored_mac = row["mac_address"]
    if mac_address:
        if not stored_mac:
            db.execute(
                "UPDATE users SET mac_address = ?, updated_at = ? WHERE id = ?",
                (mac_address, _iso(now_utc()), row["id"]),
            )
            db.commit()
        elif stored_mac != mac_address:
            return jsonify(
                success=False,
                message="다른 기기에서 등록된 계정입니다. 관리자에게 기기 초기화를 요청하세요.",
            ), 200

    return jsonify(
        success=True,
        message="인증 성공",
        expires_at=_iso(expires_at) if expires_at else None,
    )


@app.route("/healthz")
def healthz():
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
