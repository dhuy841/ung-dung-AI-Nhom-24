import os
import json
import re
import secrets
import sqlite3
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from time import time

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash


SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    email_verified INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL CHECK (role IN ('president', 'lead', 'member')),
    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    skills TEXT NOT NULL DEFAULT '',
    availability TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'ongoing', 'completed', 'cancelled')),
    created_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS attendance (
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'present' CHECK (status IN ('present', 'absent', 'excused')),
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (activity_id, user_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    due_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo'
        CHECK (status IN ('todo', 'in_progress', 'done')),
    priority TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('normal', 'important', 'urgent')),
    created_by INTEGER REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS email_codes (
    email TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('register', 'reset', 'email_change', 'account_verify')),
    code_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    sent_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (email, purpose)
);
"""


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("CLUB_SECRET_KEY", "local-development-key-change-me"),
        DATABASE=os.environ.get("CLUB_DATABASE", str(Path(__file__).with_name("club.db"))),
        AI_API_KEY=os.environ.get("AI_API_KEY", ""),
        AI_BASE_URL=os.environ.get("AI_BASE_URL", "https://api.openai.com/v1"),
        AI_MODEL=os.environ.get("AI_MODEL", "gpt-4o-mini"),
        MAIL_SERVER=os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME", ""),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", ""),
        MAIL_FROM=os.environ.get("MAIL_FROM", os.environ.get("MAIL_USERNAME", "")),
    )
    if test_config:
        app.config.update(test_config)

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with app.app_context():
        init_db()

    def require_roles(*roles):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                user = current_user()
                if user is None:
                    return jsonify(error="Bạn cần đăng nhập."), 401
                if not user["email_verified"] and not (
                    request.path in ("/api/me", "/api/profile", "/api/departments", "/api/profile/verification/request", "/api/profile/verification/confirm")
                    or request.path == "/api/logout"
                ):
                    return jsonify(error="Hãy xác minh email trong trang thông tin cá nhân để tiếp tục."), 403
                if roles and user["role"] not in roles:
                    return jsonify(error="Bạn không có quyền thực hiện thao tác này."), 403
                return view(*args, **kwargs)

            return wrapped

        return decorator

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/api/login")
    def login():
        data = request.get_json(silent=True) or {}
        identity = required_text(data, "username").lower()
        password = data.get("password", "")
        if not identity or not isinstance(password, str) or not password:
            return jsonify(error="Hãy nhập đầy đủ tên đăng nhập/email và mật khẩu."), 400
        user = get_db().execute(
            "SELECT * FROM users WHERE lower(username) = ? OR lower(email) = ?",
            (identity, identity),
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return jsonify(error="Tên đăng nhập hoặc mật khẩu không đúng."), 401
        session.clear()
        session["user_id"] = user["id"]
        return jsonify(user_data(user))

    @app.post("/api/auth/register")
    def request_registration_code():
        data = request.get_json(silent=True) or {}
        full_name = required_text(data, "full_name")
        username = required_text(data, "username")
        email = normalize_email(data.get("email"))
        password = data.get("password", "")
        if not full_name or not username or not email or not isinstance(password, str):
            return jsonify(error="Hãy điền đầy đủ họ tên, tên đăng nhập, email và mật khẩu."), 400
        if not valid_email(email):
            return jsonify(error="Email không đúng định dạng."), 400
        if len(username) < 3 or len(username) > 40:
            return jsonify(error="Tên đăng nhập phải dài từ 3 đến 40 ký tự."), 400
        if len(password) < 8:
            return jsonify(error="Mật khẩu phải có ít nhất 8 ký tự."), 400

        db = get_db()
        existing = db.execute(
            "SELECT 1 FROM users WHERE lower(username) = ? OR lower(email) = ?",
            (username.lower(), email),
        ).fetchone()
        if existing:
            return jsonify(error="Tên đăng nhập hoặc email đã được sử dụng."), 409

        payload = json.dumps(
            {
                "full_name": full_name,
                "username": username,
                "password_hash": generate_password_hash(password),
            }
        )
        try:
            issue_email_code(app.config, db, email, "register", payload)
        except ValueError as exc:
            return jsonify(error=str(exc)), 503
        except TimeoutError as exc:
            return jsonify(error=str(exc)), 429
        except (OSError, smtplib.SMTPException) as exc:
            app.logger.warning("Registration email delivery failed: %s", exc)
            return jsonify(error="Không gửi được email xác minh. Kiểm tra cấu hình Gmail SMTP."), 502
        return jsonify(message="Mã xác minh đã được gửi đến email nếu địa chỉ này nhận được thư.")

    @app.post("/api/auth/register/verify")
    def verify_registration_code():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        code = required_text(data, "code")
        if not valid_email(email) or not re.fullmatch(r"\d{6}", code):
            return jsonify(error="Email hoặc mã xác minh không hợp lệ."), 400

        db = get_db()
        challenge = valid_email_code(db, email, "register", code)
        if challenge is None:
            return jsonify(error="Mã xác minh không đúng, đã hết hạn hoặc vượt số lần thử."), 400
        payload = json.loads(challenge["payload_json"])
        try:
            cursor = db.execute(
                """INSERT INTO users
                   (username, password_hash, full_name, email, email_verified, role)
                   VALUES (?, ?, ?, ?, 1, 'member')""",
                (payload["username"], payload["password_hash"], payload["full_name"], email),
            )
        except sqlite3.IntegrityError:
            db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = 'register'", (email,))
            db.commit()
            return jsonify(error="Tên đăng nhập hoặc email đã được sử dụng."), 409
        db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = 'register'", (email,))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        session.clear()
        session["user_id"] = user["id"]
        return jsonify(user_data(user))

    @app.post("/api/auth/forgot-password")
    def request_password_reset():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        if not valid_email(email):
            return jsonify(error="Email không đúng định dạng."), 400
        user = get_db().execute(
            "SELECT id FROM users WHERE lower(email) = ?", (email,)
        ).fetchone()
        if user:
            try:
                issue_email_code(app.config, get_db(), email, "reset")
            except ValueError as exc:
                return jsonify(error=str(exc)), 503
            except TimeoutError as exc:
                return jsonify(error=str(exc)), 429
            except (OSError, smtplib.SMTPException) as exc:
                app.logger.warning("Password reset email delivery failed: %s", exc)
                return jsonify(error="Không gửi được email xác minh. Kiểm tra cấu hình Gmail SMTP."), 502
        return jsonify(message="Nếu email thuộc một tài khoản, mã xác nhận sẽ được gửi đến hộp thư đó.")

    @app.post("/api/auth/reset-password")
    def reset_password():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        code = required_text(data, "code")
        password = data.get("new_password", "")
        if not valid_email(email) or not re.fullmatch(r"\d{6}", code):
            return jsonify(error="Email hoặc mã xác minh không hợp lệ."), 400
        if not isinstance(password, str) or len(password) < 8:
            return jsonify(error="Mật khẩu mới phải có ít nhất 8 ký tự."), 400
        db = get_db()
        challenge = valid_email_code(db, email, "reset", code)
        if challenge is None:
            return jsonify(error="Mã xác minh không đúng, đã hết hạn hoặc vượt số lần thử."), 400
        db.execute(
            "UPDATE users SET password_hash = ? WHERE lower(email) = ?",
            (generate_password_hash(password), email),
        )
        db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = 'reset'", (email,))
        db.commit()
        return jsonify(ok=True, message="Đặt lại mật khẩu thành công. Hãy đăng nhập bằng mật khẩu mới.")

    @app.post("/api/auth/verify-email")
    def request_account_email_code():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        if not valid_email(email):
            return jsonify(error="Email không đúng định dạng."), 400
        user = get_db().execute(
            "SELECT id FROM users WHERE lower(email) = ? AND email_verified = 0",
            (email,),
        ).fetchone()
        if user:
            try:
                issue_email_code(
                    app.config,
                    get_db(),
                    email,
                    "account_verify",
                    json.dumps({"user_id": user["id"]}),
                )
            except ValueError as exc:
                return jsonify(error=str(exc)), 503
            except TimeoutError as exc:
                return jsonify(error=str(exc)), 429
            except (OSError, smtplib.SMTPException) as exc:
                app.logger.warning("Account verification email delivery failed: %s", exc)
                return jsonify(error="Không gửi được email xác minh. Kiểm tra cấu hình Gmail SMTP."), 502
        return jsonify(message="Nếu email thuộc tài khoản chưa xác minh, mã sẽ được gửi đến hộp thư.")

    @app.post("/api/auth/verify-email/confirm")
    def verify_account_email():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        code = required_text(data, "code")
        if not valid_email(email) or not re.fullmatch(r"\d{6}", code):
            return jsonify(error="Email hoặc mã xác minh không hợp lệ."), 400
        db = get_db()
        challenge = valid_email_code(db, email, "account_verify", code)
        if challenge is None:
            return jsonify(error="Mã xác minh không đúng, đã hết hạn hoặc vượt số lần thử."), 400
        user_id = json.loads(challenge["payload_json"]).get("user_id")
        db.execute("UPDATE users SET email_verified = 1 WHERE id = ? AND lower(email) = ?", (user_id, email))
        db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = 'account_verify'", (email,))
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            return jsonify(error="Không tìm thấy tài khoản cần xác minh."), 404
        session.clear()
        session["user_id"] = user["id"]
        return jsonify(user_data(user))

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    def me():
        user = current_user()
        return (jsonify(user_data(user)) if user else jsonify(error="Chưa đăng nhập."), 200 if user else 401)

    @app.get("/api/profile")
    @require_roles()
    def get_profile():
        user = current_user()
        row = get_db().execute(
            """SELECT d.name AS department_name FROM users u
               LEFT JOIN departments d ON d.id = u.department_id WHERE u.id = ?""",
            (user["id"],),
        ).fetchone()
        return jsonify(**user_data(user), department_name=row["department_name"])

    @app.post("/api/profile/email/request")
    @require_roles()
    def request_profile_email_change():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        user = current_user()
        if not valid_email(email):
            return jsonify(error="Email không đúng định dạng."), 400
        if email == user["email"].lower():
            return jsonify(error="Đây đã là email hiện tại của bạn."), 400
        if get_db().execute(
            "SELECT 1 FROM users WHERE lower(email) = ?", (email,)
        ).fetchone():
            return jsonify(error="Email này đã được tài khoản khác sử dụng."), 409
        try:
            issue_email_code(
                app.config,
                get_db(),
                email,
                "email_change",
                json.dumps({"user_id": user["id"]}),
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 503
        except TimeoutError as exc:
            return jsonify(error=str(exc)), 429
        except (OSError, smtplib.SMTPException) as exc:
            app.logger.warning("Profile email verification failed: %s", exc)
            return jsonify(error="Không gửi được email xác minh. Kiểm tra cấu hình Gmail SMTP."), 502
        return jsonify(message="Mã xác minh đã được gửi đến email mới.")

    @app.post("/api/profile/verification/request")
    @require_roles()
    def request_current_email_verification():
        user = current_user()
        if user["email_verified"]:
            return jsonify(error="Email tài khoản đã được xác minh."), 400
        try:
            issue_email_code(
                app.config,
                get_db(),
                user["email"],
                "account_verify",
                json.dumps({"user_id": user["id"]}),
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 503
        except TimeoutError as exc:
            return jsonify(error=str(exc)), 429
        except (OSError, smtplib.SMTPException) as exc:
            app.logger.warning("Profile email verification failed: %s", exc)
            return jsonify(error="Không gửi được email xác minh. Kiểm tra cấu hình Gmail SMTP."), 502
        return jsonify(message="Mã xác minh đã được gửi đến email tài khoản.")

    @app.post("/api/profile/verification/confirm")
    @require_roles()
    def verify_current_email():
        data = request.get_json(silent=True) or {}
        user = current_user()
        code = required_text(data, "code")
        db = get_db()
        challenge = valid_email_code(db, user["email"], "account_verify", code)
        if challenge is None:
            return jsonify(error="Mã xác minh không đúng, đã hết hạn hoặc vượt số lần thử."), 400
        payload = json.loads(challenge["payload_json"])
        if payload.get("user_id") != user["id"]:
            return jsonify(error="Mã xác minh không thuộc tài khoản này."), 403
        db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))
        db.execute(
            "DELETE FROM email_codes WHERE email = ? AND purpose = 'account_verify'",
            (user["email"],),
        )
        db.commit()
        updated_user = current_user()
        return jsonify(**user_data(updated_user))

    @app.post("/api/profile/email/verify")
    @require_roles()
    def verify_profile_email_change():
        data = request.get_json(silent=True) or {}
        email = normalize_email(data.get("email"))
        code = required_text(data, "code")
        if not valid_email(email) or not re.fullmatch(r"\d{6}", code):
            return jsonify(error="Email hoặc mã xác minh không hợp lệ."), 400
        db = get_db()
        challenge = valid_email_code(db, email, "email_change", code)
        if challenge is None:
            return jsonify(error="Mã xác minh không đúng, đã hết hạn hoặc vượt số lần thử."), 400
        if json.loads(challenge["payload_json"]).get("user_id") != session["user_id"]:
            return jsonify(error="Mã này không thuộc tài khoản đang đăng nhập."), 403
        try:
            db.execute(
                "UPDATE users SET email = ?, email_verified = 1 WHERE id = ?",
                (email, session["user_id"]),
            )
        except sqlite3.IntegrityError:
            return jsonify(error="Email này đã được tài khoản khác sử dụng."), 409
        db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = 'email_change'", (email,))
        db.commit()
        return jsonify(email=email)

    @app.patch("/api/profile")
    @require_roles()
    def update_profile():
        data = request.get_json(silent=True) or {}
        user = current_user()
        updates = {}

        if "full_name" in data:
            full_name = required_text(data, "full_name")
            if not full_name:
                return jsonify(error="Họ và tên không được để trống."), 400
            updates["full_name"] = full_name

        if "email" in data:
            return jsonify(error="Hãy xác minh email mới trước khi thay đổi địa chỉ email."), 400

        for field in ("skills", "availability"):
            if field in data:
                value = data[field]
                if not isinstance(value, str):
                    return jsonify(error="Thông tin hồ sơ không hợp lệ."), 400
                updates[field] = value.strip()

        if "department_id" in data:
            raw_department_id = data["department_id"]
            try:
                updates["department_id"] = (
                    int(raw_department_id) if raw_department_id not in ("", None) else None
                )
            except (TypeError, ValueError):
                return jsonify(error="Ban chuyên môn không hợp lệ."), 400

        new_password = data.get("new_password", "")
        if new_password:
            current_password = data.get("current_password", "")
            if not isinstance(current_password, str) or not check_password_hash(
                user["password_hash"], current_password
            ):
                return jsonify(error="Mật khẩu hiện tại không đúng."), 400
            if not isinstance(new_password, str) or len(new_password) < 8:
                return jsonify(error="Mật khẩu mới phải có ít nhất 8 ký tự."), 400
            updates["password_hash"] = generate_password_hash(new_password)

        if not updates:
            return jsonify(error="Không có thông tin nào để cập nhật."), 400

        fields = ", ".join(f"{field} = ?" for field in updates)
        try:
            db = get_db()
            db.execute(
                f"UPDATE users SET {fields} WHERE id = ?",
                (*updates.values(), user["id"]),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify(error="Ban chuyên môn được chọn không tồn tại."), 400

        updated_user = current_user()
        department = get_db().execute(
            "SELECT name FROM departments WHERE id = ?", (updated_user["department_id"],)
        ).fetchone()
        return jsonify(
            **user_data(updated_user),
            department_name=department["name"] if department else None,
        )

    @app.get("/api/dashboard")
    @require_roles()
    def dashboard():
        db = get_db()
        totals = {
            "members": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "activities": db.execute("SELECT COUNT(*) FROM activities").fetchone()[0],
            "open_tasks": db.execute("SELECT COUNT(*) FROM tasks WHERE status != 'done'").fetchone()[0],
            "announcements": db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0],
        }
        recent = db.execute(
            "SELECT id, title, starts_at, status FROM activities ORDER BY id DESC LIMIT 5"
        ).fetchall()
        return jsonify(totals=totals, recent=[dict(row) for row in recent])

    @app.get("/api/departments")
    @require_roles()
    def list_departments():
        rows = get_db().execute("SELECT * FROM departments ORDER BY name").fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/departments")
    @require_roles("president")
    def create_department():
        data = request.get_json(silent=True) or {}
        name = required_text(data, "name")
        if not name:
            return jsonify(error="Tên ban là bắt buộc."), 400
        try:
            cursor = get_db().execute(
                "INSERT INTO departments (name, description) VALUES (?, ?)",
                (name, data.get("description", "").strip()),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            return jsonify(error="Tên ban đã tồn tại."), 409
        return jsonify(id=cursor.lastrowid, name=name), 201

    @app.get("/api/members")
    @require_roles()
    def list_members():
        rows = get_db().execute(
            """SELECT u.id, u.username, u.full_name, u.email, u.role, u.department_id,
                      u.skills, u.availability, d.name AS department_name
               FROM users u LEFT JOIN departments d ON d.id = u.department_id
               ORDER BY u.full_name"""
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/members")
    @require_roles("president")
    def create_member():
        data = request.get_json(silent=True) or {}
        required = ("username", "password", "full_name", "role", "email")
        if any(not isinstance(data.get(key), str) or not data[key].strip() for key in required):
            return jsonify(error="Cần nhập đầy đủ tên đăng nhập, mật khẩu, họ tên, email và vai trò."), 400
        email = normalize_email(data["email"])
        if not valid_email(email):
            return jsonify(error="Email không đúng định dạng."), 400
        if len(data["password"]) < 8:
            return jsonify(error="Mật khẩu phải có ít nhất 8 ký tự."), 400
        if data["role"] not in ("president", "lead", "member"):
            return jsonify(error="Vai trò không hợp lệ."), 400
        try:
            cursor = get_db().execute(
                """INSERT INTO users
                   (username, password_hash, full_name, email, email_verified, role, department_id, skills, availability)
                   VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)""",
                (
                    data["username"].strip(),
                    generate_password_hash(data["password"]),
                    data["full_name"].strip(),
                    email,
                    data["role"],
                    data.get("department_id") or None,
                    data.get("skills", "").strip(),
                    data.get("availability", "").strip(),
                ),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            return jsonify(error="Tên đăng nhập đã tồn tại hoặc ban không hợp lệ."), 409
        try:
            issue_email_code(
                app.config,
                get_db(),
                email,
                "account_verify",
                json.dumps({"user_id": cursor.lastrowid}),
            )
        except ValueError as exc:
            return jsonify(id=cursor.lastrowid, message=f"Đã tạo tài khoản nhưng chưa gửi được mã: {exc}"), 201
        except TimeoutError as exc:
            return jsonify(id=cursor.lastrowid, message=f"Đã tạo tài khoản; hãy đợi trước khi gửi mã: {exc}"), 201
        except (OSError, smtplib.SMTPException):
            app.logger.exception("Member created but verification email could not be sent")
            return jsonify(id=cursor.lastrowid, message="Đã tạo tài khoản nhưng gửi email xác minh thất bại. Có thể gửi lại mã sau khi cấu hình SMTP."), 201
        return jsonify(id=cursor.lastrowid, message="Đã tạo tài khoản; mã xác minh email đã được gửi."), 201

    @app.get("/api/members/<int:member_id>/history")
    @require_roles()
    def member_history(member_id):
        rows = get_db().execute(
            """SELECT a.id, a.title, a.starts_at, at.status AS attendance_status
               FROM attendance at JOIN activities a ON a.id = at.activity_id
               WHERE at.user_id = ? ORDER BY a.starts_at DESC, a.id DESC""",
            (member_id,),
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/my-activities")
    @require_roles()
    def my_activities():
        rows = get_db().execute(
            """SELECT a.id, a.title, a.description, a.starts_at, a.location, a.status,
                      at.status AS attendance_status, at.checked_at
               FROM activities a
               LEFT JOIN attendance at
                 ON at.activity_id = a.id AND at.user_id = ?
               ORDER BY a.starts_at DESC, a.id DESC""",
            (session["user_id"],),
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/activities")
    @require_roles()
    def list_activities():
        rows = get_db().execute(
            """SELECT a.*, u.full_name AS creator_name,
                      (SELECT COUNT(*) FROM attendance at WHERE at.activity_id = a.id) AS attendee_count
               FROM activities a LEFT JOIN users u ON u.id = a.created_by
               ORDER BY a.starts_at DESC, a.id DESC"""
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/activities")
    @require_roles("president", "lead")
    def create_activity():
        data = request.get_json(silent=True) or {}
        title = required_text(data, "title")
        if not title:
            return jsonify(error="Tên hoạt động là bắt buộc."), 400
        cursor = get_db().execute(
            """INSERT INTO activities (title, description, starts_at, location, created_by)
               VALUES (?, ?, ?, ?, ?)""",
            (
                title,
                data.get("description", "").strip(),
                data.get("starts_at", "").strip(),
                data.get("location", "").strip(),
                session["user_id"],
            ),
        )
        get_db().commit()
        return jsonify(id=cursor.lastrowid), 201

    @app.patch("/api/activities/<int:activity_id>")
    @require_roles("president", "lead")
    def update_activity(activity_id):
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        if status not in ("planned", "ongoing", "completed", "cancelled"):
            return jsonify(error="Trạng thái hoạt động không hợp lệ."), 400
        db = get_db()
        cursor = db.execute(
            "UPDATE activities SET status = ? WHERE id = ?", (status, activity_id)
        )
        if cursor.rowcount == 0:
            return jsonify(error="Không tìm thấy hoạt động."), 404
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/activities/<int:activity_id>/attendance")
    @require_roles()
    def mark_attendance(activity_id):
        data = request.get_json(silent=True) or {}
        target_id = data.get("user_id") or session["user_id"]
        user = current_user()
        if user["role"] == "member" and target_id != user["id"]:
            return jsonify(error="Thành viên chỉ có thể tự điểm danh."), 403
        status = data.get("status", "present")
        if status not in ("present", "absent", "excused"):
            return jsonify(error="Trạng thái điểm danh không hợp lệ."), 400
        db = get_db()
        if not db.execute("SELECT 1 FROM activities WHERE id = ?", (activity_id,)).fetchone():
            return jsonify(error="Không tìm thấy hoạt động."), 404
        if not db.execute("SELECT 1 FROM users WHERE id = ?", (target_id,)).fetchone():
            return jsonify(error="Không tìm thấy thành viên."), 404
        db.execute(
            """INSERT INTO attendance (activity_id, user_id, status)
               VALUES (?, ?, ?)
               ON CONFLICT(activity_id, user_id) DO UPDATE SET
                 status = excluded.status, checked_at = CURRENT_TIMESTAMP""",
            (activity_id, target_id, status),
        )
        db.commit()
        return jsonify(ok=True)

    @app.get("/api/tasks")
    @require_roles()
    def list_tasks():
        user = current_user()
        query = """SELECT t.*, u.full_name AS assignee_name, d.name AS department_name
                   FROM tasks t LEFT JOIN users u ON u.id = t.assigned_to
                   LEFT JOIN departments d ON d.id = t.department_id"""
        params = ()
        if user["role"] == "member":
            query += " WHERE t.assigned_to = ?"
            params = (user["id"],)
        query += " ORDER BY t.due_date, t.id DESC"
        return jsonify([dict(row) for row in get_db().execute(query, params).fetchall()])

    @app.post("/api/tasks")
    @require_roles("president", "lead")
    def create_task():
        data = request.get_json(silent=True) or {}
        title = required_text(data, "title")
        if not title:
            return jsonify(error="Tên nhiệm vụ là bắt buộc."), 400
        priority = data.get("priority", "normal")
        if priority not in ("normal", "important", "urgent"):
            return jsonify(error="Mức độ ưu tiên không hợp lệ."), 400
        try:
            cursor = get_db().execute(
                """INSERT INTO tasks
                   (title, description, assigned_to, department_id, due_date, priority, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    title,
                    data.get("description", "").strip(),
                    data.get("assigned_to") or None,
                    data.get("department_id") or None,
                    data.get("due_date", "").strip(),
                    priority,
                    session["user_id"],
                ),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            return jsonify(error="Thành viên hoặc ban được chọn không hợp lệ."), 400
        return jsonify(id=cursor.lastrowid), 201

    @app.patch("/api/tasks/<int:task_id>")
    @require_roles()
    def update_task(task_id):
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        if status is not None and status not in ("todo", "in_progress", "done"):
            return jsonify(error="Trạng thái nhiệm vụ không hợp lệ."), 400
        priority = data.get("priority")
        if priority is not None and priority not in ("normal", "important", "urgent"):
            return jsonify(error="Mức độ ưu tiên không hợp lệ."), 400
        if status is None and priority is None:
            return jsonify(error="Không có thay đổi để cập nhật."), 400
        db = get_db()
        task = db.execute("SELECT assigned_to FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return jsonify(error="Không tìm thấy nhiệm vụ."), 404
        user = current_user()
        if user["role"] == "member" and (
            task["assigned_to"] != user["id"] or priority is not None
        ):
            return jsonify(error="Bạn chỉ có thể cập nhật trạng thái nhiệm vụ được giao cho mình."), 403
        updates = []
        values = []
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if priority is not None:
            updates.append("priority = ?")
            values.append(priority)
        db.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
            (*values, task_id),
        )
        db.commit()
        return jsonify(ok=True)

    @app.get("/api/announcements")
    @require_roles()
    def list_announcements():
        rows = get_db().execute(
            """SELECT a.*, u.full_name AS creator_name FROM announcements a
               LEFT JOIN users u ON u.id = a.created_by ORDER BY a.id DESC"""
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/announcements")
    @require_roles("president", "lead")
    def create_announcement():
        data = request.get_json(silent=True) or {}
        title, content = required_text(data, "title"), required_text(data, "content")
        if not title or not content:
            return jsonify(error="Tiêu đề và nội dung thông báo là bắt buộc."), 400
        cursor = get_db().execute(
            "INSERT INTO announcements (title, content, created_by) VALUES (?, ?, ?)",
            (title, content, session["user_id"]),
        )
        get_db().commit()
        return jsonify(id=cursor.lastrowid), 201

    @app.post("/api/ai/<string:action>")
    @require_roles("president", "lead")
    def ai_assist(action):
        data = request.get_json(silent=True) or {}
        if action == "announcement":
            if not required_text(data, "activity"):
                return jsonify(error="Hãy nhập thông tin hoạt động."), 400
            prompt = (
                "Viết thông báo hoạt động ngắn gọn, thân thiện bằng tiếng Việt. "
                "Chỉ dùng thông tin được cung cấp, không tự thêm thông tin.\n"
                f"Thông tin hoạt động: {required_text(data, 'activity')}"
            )
        elif action == "summary":
            if not required_text(data, "notes") and not required_text(data, "feedback"):
                return jsonify(error="Hãy nhập ghi chú hoặc phản hồi hoạt động."), 400
            prompt = (
                "Tóm tắt ngắn gọn kết quả hoạt động bằng tiếng Việt, tách ý rõ ràng. "
                "Không suy diễn ngoài dữ liệu.\n"
                f"Ghi chú: {required_text(data, 'notes')}\nPhản hồi: {required_text(data, 'feedback')}"
            )
        elif action == "assignment":
            if not required_text(data, "activity"):
                return jsonify(error="Hãy nhập mô tả hoạt động hoặc nhiệm vụ."), 400
            members = get_db().execute(
                """SELECT u.full_name, u.skills, u.availability, d.name AS department
                   FROM users u LEFT JOIN departments d ON d.id = u.department_id
                   WHERE u.role != 'president' ORDER BY u.full_name"""
            ).fetchall()
            prompt = (
                "Bạn là trợ lý quản lý câu lạc bộ sinh viên. Gợi ý phân công nhiệm vụ ngắn gọn "
                "dựa trên ban, kỹ năng và lịch rảnh. Không tự thêm thông tin chưa có. "
                "Nếu thiếu dữ liệu, hãy nêu rõ.\n"
                f"Hoạt động: {required_text(data, 'activity')}\n"
                f"Thành viên: {[dict(row) for row in members]}"
            )
        else:
            return jsonify(error="Tác vụ AI không hợp lệ."), 404
        try:
            result = call_ai(app.config, prompt)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            app.logger.warning("AI request failed: %s", exc)
            return jsonify(error=f"Không thể gọi dịch vụ AI: {exc}"), 502
        return jsonify(result=result)

    return app


def call_ai(config, prompt):
    api_key = config.get("AI_API_KEY")
    if not api_key:
        raise ValueError(
            "Chưa cấu hình OpenAI API key. Hãy đặt AI_API_KEY trong PowerShell "
            "rồi khởi động lại ứng dụng."
        )
    base_url = config.get("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    payload = json.dumps(
        {
            "model": config.get("AI_MODEL", "gpt-4o-mini"),
            "messages": [
                {
                    "role": "system",
                    "content": "Bạn là trợ lý quản lý câu lạc bộ sinh viên. Viết ngắn gọn, thân thiện, không tự thêm thông tin chưa có.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read(1000).decode("utf-8", errors="replace")
        raise ValueError(f"Nhà cung cấp AI trả lỗi HTTP {exc.code}: {body}") from exc
    choices = result.get("choices", [])
    if not choices or not choices[0].get("message", {}).get("content"):
        raise ValueError("Nhà cung cấp AI trả về kết quả không hợp lệ.")
    return choices[0]["message"]["content"].strip()


def required_text(data, key):
    value = data.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def normalize_email(value):
    return value.strip().lower() if isinstance(value, str) else ""


def valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def issue_email_code(config, db, email, purpose, payload="{}"):
    if config.get("MAIL_SUPPRESS_SEND"):
        code = f"{secrets.randbelow(1_000_000):06d}"
        config.setdefault("TEST_EMAIL_CODES", []).append((email, purpose, code))
    else:
        username, password = config.get("MAIL_USERNAME"), config.get("MAIL_PASSWORD")
        sender = config.get("MAIL_FROM") or username
        if not username or not password or not sender:
            raise ValueError("Email chưa được cấu hình. Hãy thiết lập Gmail SMTP trong biến môi trường.")
        code = f"{secrets.randbelow(1_000_000):06d}"

    now = int(time())
    previous = db.execute(
        "SELECT sent_at FROM email_codes WHERE email = ? AND purpose = ?",
        (email, purpose),
    ).fetchone()
    if previous and now - previous["sent_at"] < 60:
        raise TimeoutError("Vui lòng đợi 60 giây trước khi yêu cầu gửi mã mới.")
    db.execute(
        """INSERT INTO email_codes
           (email, purpose, code_hash, expires_at, attempts, sent_at, payload_json)
           VALUES (?, ?, ?, ?, 0, ?, ?)
           ON CONFLICT(email, purpose) DO UPDATE SET
             code_hash = excluded.code_hash, expires_at = excluded.expires_at,
             attempts = 0, sent_at = excluded.sent_at, payload_json = excluded.payload_json""",
        (email, purpose, generate_password_hash(code), now + 600, now, payload),
    )
    db.commit()

    if not config.get("MAIL_SUPPRESS_SEND"):
        message = EmailMessage()
        message["Subject"] = "Mã xác nhận ClubSpace"
        message["From"] = config.get("MAIL_FROM") or config["MAIL_USERNAME"]
        message["To"] = email
        message.set_content(
            f"Mã xác nhận ClubSpace của bạn là: {code}\n"
            "Mã có hiệu lực trong 10 phút. Không chia sẻ mã này với người khác."
        )
        try:
            with smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=20) as smtp:
                smtp.starttls()
                smtp.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = ?", (email, purpose))
            db.commit()
            raise


def valid_email_code(db, email, purpose, code):
    challenge = db.execute(
        "SELECT * FROM email_codes WHERE email = ? AND purpose = ?",
        (email, purpose),
    ).fetchone()
    if challenge is None or challenge["expires_at"] < int(time()) or challenge["attempts"] >= 5:
        db.execute("DELETE FROM email_codes WHERE email = ? AND purpose = ?", (email, purpose))
        db.commit()
        return None
    if not check_password_hash(challenge["code_hash"], code):
        db.execute(
            "UPDATE email_codes SET attempts = attempts + 1 WHERE email = ? AND purpose = ?",
            (email, purpose),
        )
        db.commit()
        return None
    return challenge


def user_data(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "email_verified": bool(user["email_verified"]),
        "role": user["role"],
        "department_id": user["department_id"],
        "skills": user["skills"],
        "availability": user["availability"],
    }


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app_config_database())
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def current_app_config_database():
    from flask import current_app

    return current_app.config["DATABASE"]


def init_db():
    db = sqlite3.connect(current_app_config_database())
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if "email_verified" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1")
    task_columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
    if "priority" not in task_columns:
        db.execute(
            """ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'
               CHECK (priority IN ('normal', 'important', 'urgent'))"""
        )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(lower(email)) WHERE email <> ''"
    )
    legacy_demo_lead = db.execute(
        "SELECT id FROM users WHERE username = 'lead' AND email = 'lead@club.local'"
    ).fetchone()
    demo_member = db.execute(
        "SELECT id FROM users WHERE username = 'member'"
    ).fetchone()
    if legacy_demo_lead and demo_member:
        db.execute(
            """UPDATE tasks SET assigned_to = ?
               WHERE assigned_to = ? AND title = 'Chuẩn bị nội dung giới thiệu'""",
            (demo_member[0], legacy_demo_lead[0]),
        )
        db.execute("DELETE FROM users WHERE id = ?", (legacy_demo_lead[0],))
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO departments (name, description) VALUES (?, ?)",
            [
                ("Truyền thông", "Nội dung, hình ảnh và truyền thông sự kiện"),
                ("Sự kiện", "Tổ chức và điều phối hoạt động"),
                ("Kỹ thuật", "Hỗ trợ kỹ thuật và hậu cần"),
            ],
        )
        db.executemany(
            """INSERT INTO users
               (username, password_hash, full_name, email, role, department_id, skills, availability)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("admin", generate_password_hash("admin123"), "Chủ nhiệm CLB", "admin@club.local", "president", None, "quản lý", "linh hoạt"),
                ("member", generate_password_hash("member123"), "Trần Gia Bảo", "member@club.local", "member", 2, "hậu cần, chụp ảnh", "cuối tuần"),
            ],
        )
        db.execute(
            """INSERT INTO activities (title, description, starts_at, location, status, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("Sinh hoạt CLB đầu năm", "Gặp mặt thành viên và giới thiệu kế hoạch", "2026-10-15T15:00", "Phòng A1", "planned", 1),
        )
        db.execute(
            """INSERT INTO tasks (title, description, assigned_to, department_id, due_date, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("Chuẩn bị nội dung giới thiệu", "Soạn nội dung cho buổi sinh hoạt", 2, 1, "2026-10-12", 1),
        )
    ensure_demo_content(db)
    db.commit()
    db.close()


def ensure_demo_content(db):
    departments = {
        row[1]: row[0] for row in db.execute("SELECT id, name FROM departments").fetchall()
    }
    department_specs = [
        ("Truyền thông", "Nội dung, hình ảnh và truyền thông sự kiện"),
        ("Sự kiện", "Tổ chức và điều phối hoạt động"),
        ("Kỹ thuật", "Hỗ trợ kỹ thuật và hậu cần"),
    ]
    for name, description in department_specs:
        db.execute(
            "INSERT OR IGNORE INTO departments (name, description) VALUES (?, ?)",
            (name, description),
        )
    departments = {
        row[1]: row[0] for row in db.execute("SELECT id, name FROM departments").fetchall()
    }

    member_specs = [
        ("linh", "Nguyễn Ngọc Linh", "linh@club.local", "thiết kế, chụp ảnh", "buổi tối", "Truyền thông"),
        ("minh", "Phạm Quang Minh", "minh@club.local", "âm thanh, hậu cần", "cuối tuần", "Kỹ thuật"),
        ("trang", "Lê Thu Trang", "trang@club.local", "viết nội dung, MC", "buổi chiều", "Sự kiện"),
    ]
    for username, full_name, email, skills, availability, department_name in member_specs:
        db.execute(
            """INSERT OR IGNORE INTO users
               (username, password_hash, full_name, email, email_verified, role,
                department_id, skills, availability)
               VALUES (?, ?, ?, ?, 1, 'member', ?, ?, ?)""",
            (
                username,
                generate_password_hash(secrets.token_urlsafe(32)),
                full_name,
                email,
                departments[department_name],
                skills,
                availability,
            ),
        )

    users = {
        row[1]: row[0] for row in db.execute("SELECT id, username FROM users").fetchall()
    }
    activity_specs = [
        (
            "Buổi định hướng thành viên mới",
            "Làm quen, giới thiệu các ban và kế hoạch học kỳ.",
            "2026-09-12T14:00",
            "Hội trường thư viện cũ",
            "completed",
        ),
        (
            "Ngày hội tuyển thành viên",
            "Gian hàng giới thiệu câu lạc bộ và hoạt động trải nghiệm.",
            "2026-09-20T08:00",
            "Quảng trường ICTU",
            "completed",
        ),
        (
            "Workshop kỹ năng truyền thông",
            "Thực hành viết nội dung và chụp ảnh sự kiện.",
            "2026-09-27T15:00",
            "Phòng C203",
            "completed",
        ),
        (
            "Sinh hoạt CLB đầu năm",
            "Gặp mặt thành viên và giới thiệu kế hoạch.",
            "2026-10-15T15:00",
            "C2.103",
            "planned",
        ),
        (
            "Ngày hội sẻ chia",
            "Chuẩn bị hoạt động thiện nguyện và quyên góp sách.",
            "2026-10-24T08:00",
            "Nhà văn hóa sinh viên",
            "planned",
        ),
        (
            "Cuộc thi ý tưởng sáng tạo",
            "Các ban phối hợp tổ chức vòng trình bày ý tưởng.",
            "2026-11-07T13:30",
            "Hội trường A",
            "planned",
        ),
        (
            "Tổng kết hoạt động học kỳ",
            "Nhìn lại kết quả, ghi nhận đóng góp và đề xuất kế hoạch.",
            "2026-11-21T15:00",
            "Phòng hội thảo 2",
            "planned",
        ),
    ]
    activity_ids = {}
    for title, description, starts_at, location, status in activity_specs:
        existing = db.execute(
            "SELECT id FROM activities WHERE title = ?", (title,)
        ).fetchone()
        if existing:
            activity_id = existing[0]
        else:
            cursor = db.execute(
                """INSERT INTO activities
                   (title, description, starts_at, location, status, created_by)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    title,
                    description,
                    starts_at,
                    location,
                    status,
                    users.get("admin"),
                ),
            )
            activity_id = cursor.lastrowid
        activity_ids[title] = activity_id

    for title, location in (
        ("Buổi định hướng thành viên mới", "Hội trường thư viện cũ"),
        ("Ngày hội tuyển thành viên", "Quảng trường ICTU"),
        ("Sinh hoạt CLB đầu năm", "C2.103"),
    ):
        db.execute("UPDATE activities SET location = ? WHERE title = ?", (location, title))

    if "member" in users:
        history = [
            ("Buổi định hướng thành viên mới", "present", "2026-09-12 16:10:00"),
            ("Ngày hội tuyển thành viên", "present", "2026-09-20 12:15:00"),
            ("Workshop kỹ năng truyền thông", "absent", "2026-09-27 15:05:00"),
        ]
        for title, attendance_status, checked_at in history:
            db.execute(
                """INSERT OR IGNORE INTO attendance
                   (activity_id, user_id, status, checked_at)
                   VALUES (?, ?, ?, ?)""",
                (activity_ids[title], users["member"], attendance_status, checked_at),
            )
    if "linh" in users:
        db.execute(
            """INSERT OR IGNORE INTO attendance
               (activity_id, user_id, status, checked_at)
               VALUES (?, ?, 'present', '2026-09-20 12:20:00')""",
            (activity_ids["Ngày hội tuyển thành viên"], users["linh"]),
        )

    task_specs = [
        (
            "Thiết kế poster Ngày hội sẻ chia",
            "Chuẩn bị poster số và bản in cho truyền thông.",
            "linh",
            "Truyền thông",
            "2026-10-12",
            "urgent",
        ),
        (
            "Hoàn thiện danh sách tình nguyện viên",
            "Tổng hợp đăng ký và chia nhóm trực.",
            "trang",
            "Sự kiện",
            "2026-10-18",
            "important",
        ),
        (
            "Kiểm tra thiết bị âm thanh",
            "Thử micro, loa và dây kết nối trước sự kiện.",
            "minh",
            "Kỹ thuật",
            "2026-10-22",
            "important",
        ),
        (
            "Soạn nội dung giới thiệu câu lạc bộ",
            "Cập nhật phần giới thiệu cho buổi sinh hoạt.",
            "member",
            "Truyền thông",
            "2026-10-12",
            "normal",
        ),
        (
            "Gửi thư cảm ơn đối tác",
            "Soạn và gửi lời cảm ơn sau ngày hội tuyển thành viên.",
            "member",
            "Sự kiện",
            "2026-10-05",
            "normal",
        ),
        (
            "Lên ý tưởng trò chơi khởi động",
            "Đề xuất trò chơi ngắn cho buổi sinh hoạt CLB.",
            "trang",
            "Sự kiện",
            "2026-10-13",
            "normal",
        ),
    ]
    for title, description, username, department_name, due_date, priority in task_specs:
        if username not in users:
            continue
        existing_task = db.execute(
            "SELECT 1 FROM tasks WHERE title = ? AND assigned_to = ?",
            (title, users[username]),
        ).fetchone()
        if existing_task:
            continue
        db.execute(
            """INSERT INTO tasks
               (title, description, assigned_to, department_id, due_date, priority, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                description,
                users[username],
                departments[department_name],
                due_date,
                priority,
                users.get("admin"),
            ),
        )


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
