from flask import Flask, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
import bcrypt
import html
import pandas as pd
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import io
import urllib.request
import unicodedata
from datetime import datetime, timedelta
from functools import wraps

from activity_store import (
    MAX_RECORDED_IDLE_SECONDS,
    clear_active_tracker_user,
    derive_processed_task_name,
    get_active_tracker_user,
    is_valid_project_label,
    load_user_activities_dataframe,
    normalize_existing_activity_projects,
    normalize_project_name_for_storage,
    save_tracked_activity,
    set_active_tracker_user,
    should_ignore_idle_activity,
)
from database import Activity, Project, Task, User, get_db_session, initialize_postgres_foundation

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_KEY_FILE = os.path.join(BASE_DIR, ".flask_secret_key")
TRACKER_SCRIPT = os.path.join(BASE_DIR, "start_tracker.py")
TRAY_SCRIPT = os.path.join(BASE_DIR, "tray_app.py")
TRACKER_PID_FILE = os.path.join(BASE_DIR, "tracker.pid")
MANAGER_TRAY_PID_FILE = os.path.join(BASE_DIR, "manager_tray.pid")
TRACKER_STOP_FILE = os.path.join(BASE_DIR, "tracker.stop")
TRACKER_LOG_FILE = os.path.join(BASE_DIR, "tracker_runtime.log")
AUTH_FLOW_LOG_FILE = os.path.join(BASE_DIR, "auth_tracker_flow.log")
EMAIL_REPORT_DEBUG_LOG_FILE = os.path.join(BASE_DIR, "email_report_debug.log")
EMAIL_REVIEW_DEBUG_LOG_FILE = os.path.join(BASE_DIR, "email_review_debug.log")
TRACKER_STOP_TIMEOUT_SECONDS = 8
_tracker_process = None


def load_persistent_secret_key():
    configured_key = os.getenv("SECRET_KEY", "").strip()
    if configured_key:
        return configured_key

    try:
        with open(SECRET_KEY_FILE, "r", encoding="utf-8") as file:
            saved_key = file.read().strip()
            if saved_key:
                return saved_key
    except OSError:
        pass

    generated_key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as file:
            file.write(generated_key)
    except OSError as error:
        print("Unable to persist Flask secret key:", error)

    return generated_key


def get_session_timeout_hours():
    try:
        return max(1, int(os.getenv("SESSION_TIMEOUT_HOURS", "12")))
    except ValueError:
        return 12


app = Flask(__name__)
app.secret_key = load_persistent_secret_key()
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=get_session_timeout_hours()),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    JSON_AS_ASCII=False,
)
app.json.ensure_ascii = False

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

DATA_FILE = os.path.join(BASE_DIR, 'activity_log.csv')
TASKS_FILE = os.path.join(BASE_DIR, 'tasks.json')
AI_CACHE_FILE = os.path.join(BASE_DIR, 'ai_cache.json')
EMPTY_ACTIVITY_COLUMNS = [
    "Activity ID",
    "Project Name",
    "Activity Category",
    "App Name",
    "Project",
    "File Name",
    "AI Task Name",
    "Status",
    "Is Assigned",
    "Valid Project",
    "Start Time",
    "End Time",
    "Duration",
]

AUTO_MERGE_APPS = {
    "google chrome",
    "microsoft edge",
}

IGNORE_FILES = {
    "activity_log.csv",
    "application_work_duration.csv",
    "email_status.json",
    "tasks.json",
}

MANUAL_ASSIGN_APPS = {
    "whatsapp": "WhatsApp",
    "notepad": "Notepad",
    "task scheduler": "Task Scheduler",
    "calculator": "Calculator",
    "camera": "Camera",
    "photos": "Photos",
    "settings": "Settings",
    "snipping tool overlay": "Snipping Tool Overlay",
    "snipping tool": "Snipping Tool",
    "file explorer": "File Explorer",
    "windows explorer": "File Explorer",
    "unknown window": "Unknown Window",
    "unknown task": "Unknown Window",
    "unknown activity": "Unknown Window",
    "empty title": "Unknown Window",
    "system tray overflow window": "System Tray Overflow Window",
    "program manager": "Program Manager",
    "default ime": "Default IME",
    "windows default lock screen": "Windows Default Lock Screen",
    "lock screen": "Lock Screen",
    "start menu": "Start Menu",
    "search": "Search",
    "notification center": "Windows Shell",
    "action center": "Windows Shell",
    "desktop": "Windows Shell",
    "task switching": "Task Switching",
}
initialize_postgres_foundation()
normalize_existing_activity_projects()

AUTH_EXEMPT_ENDPOINTS = {
    "login",
    "register",
    "health",
    "static",
    "api_tracker_login",
}


@app.after_request
def enforce_utf8_response(response):
    if response.mimetype in {"text/html", "text/plain", "text/csv", "application/json"}:
        response.headers["Content-Type"] = f"{response.mimetype}; charset=utf-8"
    return response


def normalize_login_email(value):
    return str(value or "").strip().lower()


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            str(password_hash or "").encode("utf-8"),
        )
    except ValueError:
        return False


def user_to_session(user):
    return {
        "id": user.id,
        "employee_name": user.employee_name,
        "employee_id": user.employee_id,
        "login_email": user.login_email,
        "role": user.role,
    }


def is_manager_user(user=None):
    user = user or g.get("current_user")
    return str(getattr(user, "role", "") or "").strip().lower() == "manager"


def get_role_home_url(user=None):
    return url_for("manager_dashboard") if is_manager_user(user) else url_for("dashboard")


def log_auth_flow(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(AUTH_FLOW_LOG_FILE, "a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError as error:
        print("Unable to write auth flow log:", error)


def read_tracker_pid():
    try:
        with open(TRACKER_PID_FILE, "r", encoding="utf-8") as file:
            return int(file.read().strip())
    except (OSError, TypeError, ValueError):
        return None


def process_is_running(pid):
    if not pid:
        return False

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return str(pid) in result.stdout
        except Exception:
            return False

    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def find_tracker_process_ids():
    if os.name != "nt":
        return []

    escaped_script = TRACKER_SCRIPT.replace("'", "''")
    command = (
        "$script = '" + escaped_script + "'; "
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
        "Where-Object { $_.CommandLine -like \"*$script*\" } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as error:
        log_auth_flow(f"Unable to inspect tracker processes: {error}")
        return []

    process_ids = []
    for line in result.stdout.splitlines():
        try:
            process_ids.append(int(line.strip()))
        except ValueError:
            pass
    return sorted(set(process_ids))


def tracker_is_running():
    global _tracker_process

    if _tracker_process is not None and _tracker_process.poll() is None:
        return True

    pid = read_tracker_pid()
    return process_is_running(pid) or bool(find_tracker_process_ids())


def clear_tracker_stop_request():
    try:
        if os.path.exists(TRACKER_STOP_FILE):
            os.remove(TRACKER_STOP_FILE)
    except OSError as error:
        print("Unable to clear tracker stop request:", error)


def read_manager_tray_pid():
    try:
        with open(MANAGER_TRAY_PID_FILE, "r", encoding="utf-8") as file:
            return int(file.read().strip())
    except (OSError, TypeError, ValueError):
        return None


def manager_tray_is_running():
    return process_is_running(read_manager_tray_pid())


def stop_manager_tray():
    pid = read_manager_tray_pid()
    if pid and process_is_running(pid):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            else:
                os.kill(int(pid), signal.SIGTERM)
        except Exception as error:
            print("Unable to terminate manager tray PID:", error)
    try:
        if os.path.exists(MANAGER_TRAY_PID_FILE):
            os.remove(MANAGER_TRAY_PID_FILE)
    except OSError as error:
        print("Unable to remove manager tray PID file:", error)


def start_manager_tray_for_user(user):
    if str(getattr(user, "role", "") or "").strip().lower() != "manager":
        return False
    if manager_tray_is_running():
        return True

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["TRAY_USER_ROLE"] = "manager"
    env["TRAY_USER_ID"] = str(user.id)
    env["TRAY_USER_NAME"] = user.employee_name
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

    try:
        process = subprocess.Popen(
            [sys.executable, TRAY_SCRIPT, "--role", "manager"],
            cwd=BASE_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        with open(MANAGER_TRAY_PID_FILE, "w", encoding="utf-8") as file:
            file.write(str(process.pid))
        log_auth_flow(f"Manager tray started: pid={process.pid}, user_id={user.id}.")
        return True
    except Exception as error:
        log_auth_flow(f"Manager tray start failed for user_id={user.id}: {error}")
        return False


def start_tracker_for_user(user, password=None):
    global _tracker_process

    requested_user = user_to_session(user)
    requested_role = str(requested_user.get("role") or "").strip().lower()
    if requested_role != "employee":
        log_auth_flow(
            f"Tracker start skipped: user_id={requested_user.get('id')}, "
            f"employee_id={requested_user.get('employee_id')}, role={requested_role}."
        )
        if tracker_is_running() or get_active_tracker_user():
            stop_tracker_safely()
        else:
            clear_active_tracker_user()
        return True

    active_user = get_active_tracker_user()
    tracker_pids = find_tracker_process_ids()
    active_user_id = (active_user or {}).get("user_id")
    requested_user_id = int(requested_user["id"])

    log_auth_flow(
        f"Tracker start requested: session_user_id={requested_user_id}, "
        f"employee_id={requested_user.get('employee_id')}, "
        f"active_bridge_user_id={active_user_id}, tracker_pids={tracker_pids}."
    )

    if tracker_is_running() and active_user_id and int(active_user_id) != requested_user_id:
        log_auth_flow(
            f"User switch detected. Stopping tracker for bridge user_id={active_user_id} "
            f"before starting user_id={requested_user_id}."
        )
        stop_tracker_safely(clear_bridge=False)

    tracker_pids = find_tracker_process_ids()
    if len(tracker_pids) > 1:
        log_auth_flow(f"Duplicate tracker processes detected: {tracker_pids}. Restarting singleton tracker.")
        stop_tracker_safely(clear_bridge=False, force_all=True)

    set_active_tracker_user(requested_user)

    if tracker_is_running():
        log_auth_flow(f"Tracker already running for user_id={requested_user_id}; not starting another instance.")
        return True

    clear_tracker_stop_request()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if password:
        env["TRACKER_PASSWORD"] = password
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

    try:
        log_file = open(TRACKER_LOG_FILE, "a", encoding="utf-8")
        _tracker_process = subprocess.Popen(
            [sys.executable, TRACKER_SCRIPT],
            cwd=BASE_DIR,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        with open(TRACKER_PID_FILE, "w", encoding="utf-8") as file:
            file.write(str(_tracker_process.pid))
        log_auth_flow(
            f"Tracker process started: pid={_tracker_process.pid}, "
            f"user_id={requested_user_id}, employee_id={requested_user.get('employee_id')}."
        )
        return True
    except Exception as error:
        log_auth_flow(f"Tracker auto-start failed for user_id={requested_user_id}: {error}")
        return False


def sync_active_tracker_user(user, reason="request"):
    user_data = user_to_session(user)
    role = str(user_data.get("role") or "").strip().lower()
    if role != "employee":
        if get_active_tracker_user() or tracker_is_running():
            log_auth_flow(
                f"Active tracker bridge cleared for non-employee request: "
                f"user_id={user_data.get('id')}, role={role}, reason={reason}."
            )
            stop_tracker_safely()
        return

    active_user = get_active_tracker_user()
    active_user_id = (active_user or {}).get("user_id")
    requested_user_id = int(user_data["id"])

    if active_user_id != requested_user_id:
        log_auth_flow(
            f"Active tracker bridge sync ({reason}): "
            f"{active_user_id} -> {requested_user_id}, employee_id={user_data.get('employee_id')}."
        )
        set_active_tracker_user(user_data)


def request_tracker_stop():
    try:
        with open(TRACKER_STOP_FILE, "w", encoding="utf-8") as file:
            file.write(datetime.utcnow().isoformat(timespec="seconds"))
    except OSError as error:
        print("Unable to request tracker stop:", error)


def terminate_tracker_process(pid=None):
    global _tracker_process

    try:
        if _tracker_process is not None and _tracker_process.poll() is None:
            _tracker_process.terminate()
            return
    except Exception as error:
        print("Unable to terminate tracker process:", error)

    pid = pid or read_tracker_pid()
    if not pid or not process_is_running(pid):
        return

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        else:
            os.kill(int(pid), signal.SIGTERM)
    except Exception as error:
        print("Unable to terminate tracker PID:", error)


def terminate_all_tracker_processes():
    for pid in find_tracker_process_ids():
        terminate_tracker_process(pid)


def stop_tracker_safely(clear_bridge=True, force_all=False):
    global _tracker_process

    tracker_pid = read_tracker_pid()
    active_user = get_active_tracker_user()
    log_auth_flow(
        f"Tracker stop requested: bridge_user_id={(active_user or {}).get('user_id')}, "
        f"employee_id={(active_user or {}).get('employee_id')}, "
        f"pid_file={tracker_pid}, tracker_pids={find_tracker_process_ids()}, "
        f"clear_bridge={clear_bridge}, force_all={force_all}."
    )
    request_tracker_stop()
    deadline = time.time() + TRACKER_STOP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if not tracker_is_running():
            break
        time.sleep(0.25)

    if tracker_is_running():
        if force_all:
            terminate_all_tracker_processes()
        else:
            terminate_tracker_process(tracker_pid)

    for path in (TRACKER_STOP_FILE, TRACKER_PID_FILE):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as error:
            print(f"Unable to remove {path}:", error)

    if clear_bridge:
        clear_active_tracker_user()

    _tracker_process = None
    log_auth_flow(f"Tracker stop completed. Remaining tracker_pids={find_tracker_process_ids()}.")


def get_session_user_id():
    try:
        return int(session.get("user_id"))
    except (TypeError, ValueError):
        return None


def empty_activity_dataframe():
    return pd.DataFrame(columns=EMPTY_ACTIVITY_COLUMNS)


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        with get_db_session() as db_session:
            return db_session.get(User, int(user_id))
    except Exception as error:
        print("Failed to load current user:", error)
        return None


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.get("current_user") is None:
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Login required."}), 401

            return redirect(url_for("login", next=request.full_path.rstrip("?")))

        return view(*args, **kwargs)

    return wrapped_view


def manager_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.get("current_user") is None:
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Login required."}), 401

            return redirect(url_for("login", next=request.full_path.rstrip("?")))

        if not is_manager_user():
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Manager access required."}), 403

            return redirect(url_for("dashboard"))

        return view(*args, **kwargs)

    return wrapped_view


def get_safe_next_url(default_endpoint="dashboard"):
    next_url = request.args.get("next", "")
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url

    return url_for(default_endpoint)


@app.before_request
def require_dashboard_login():
    g.current_user = get_current_user()

    if request.endpoint in AUTH_EXEMPT_ENDPOINTS or request.endpoint is None:
        return None

    if g.current_user is None:
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": "Login required."}), 401

        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    sync_active_tracker_user(g.current_user)
    return None


@app.context_processor
def inject_current_user():
    current_user = g.get("current_user")
    return {
        "current_user": user_to_session(current_user) if current_user else None
    }


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.get("current_user"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        employee_name = str(request.form.get("employee_name", "")).strip()
        employee_id = str(request.form.get("employee_id", "")).strip()
        login_email = normalize_login_email(request.form.get("login_email", ""))
        password = str(request.form.get("password", ""))
        confirm_password = str(request.form.get("confirm_password", ""))
        manager_email = normalize_login_email(request.form.get("manager_email", ""))

        required_fields = {
            "employee_name": employee_name,
            "employee_id": employee_id,
            "login_email": login_email,
            "password": password,
            "confirm_password": confirm_password,
            "manager_email": manager_email,
        }
        missing_fields = [
            field_name
            for field_name, field_value in required_fields.items()
            if not field_value
        ]

        if missing_fields:
            print("Registration missing required fields:", ", ".join(missing_fields))
            flash("All fields are required.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        try:
            with get_db_session() as db_session:
                email_exists = (
                    db_session.query(User)
                    .filter(User.login_email == login_email)
                    .first()
                    is not None
                )
                employee_id_exists = (
                    db_session.query(User)
                    .filter(User.employee_id == employee_id)
                    .first()
                    is not None
                )

                if email_exists:
                    flash("An account with this login email already exists.", "error")
                    return render_template("register.html")

                if employee_id_exists:
                    flash("An account with this employee ID already exists.", "error")
                    return render_template("register.html")

                user = User(
                    employee_name=employee_name,
                    employee_id=employee_id,
                    login_email=login_email,
                    password_hash=hash_password(password),
                    manager_email=manager_email,
                    role="employee",
                )
                db_session.add(user)
                db_session.commit()

        except Exception as error:
            print("Registration failed:", error)
            flash("Registration failed. Please check the database connection and try again.", "error")
            return render_template("register.html")

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.get("current_user"):
        return redirect(get_role_home_url(g.current_user))

    if request.method == "POST":
        login_email = normalize_login_email(request.form.get("login_email", ""))
        password = str(request.form.get("password", ""))

        if not login_email or not password:
            flash("Login email and password are required.", "error")
            return render_template("login.html")

        try:
            with get_db_session() as db_session:
                user = (
                    db_session.query(User)
                    .filter(User.login_email == login_email)
                    .first()
                )

                if not user:
                    flash("Invalid email.", "error")
                    return render_template("login.html")

                if not verify_password(password, user.password_hash):
                    flash("Invalid password.", "error")
                    return render_template("login.html")

                session.clear()
                session.permanent = True
                session["user_id"] = user.id
                session["user_name"] = user.employee_name
                session["employee_id"] = user.employee_id
                session["employee_name"] = user.employee_name
                session["login_email"] = user.login_email
                session["role"] = user.role
                log_auth_flow(
                    f"Login success: user_id={user.id}, employee_id={user.employee_id}, "
                    f"email={user.login_email}, role={user.role}."
                )
                if is_manager_user(user):
                    log_auth_flow(f"Manager login: tracker auto-start skipped for user_id={user.id}.")
                    stop_tracker_safely()
                    start_manager_tray_for_user(user)
                elif not start_tracker_for_user(user, password=password):
                    stop_manager_tray()
                    flash("Login succeeded, but the tracker could not be started automatically.", "error")
                else:
                    stop_manager_tray()

        except Exception as error:
            print("Login failed:", error)
            flash("Login failed. Please check the database connection and try again.", "error")
            return render_template("login.html")

        default_endpoint = "manager_dashboard" if is_manager_user(user) else "dashboard"
        return redirect(get_safe_next_url(default_endpoint))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session_role = str(session.get("role") or "").strip().lower()
    log_auth_flow(
        f"Logout requested: session_user_id={session.get('user_id')}, "
        f"employee_id={session.get('employee_id')}, role={session_role}."
    )
    if session_role == "employee":
        stop_tracker_safely()
    else:
        stop_manager_tray()
        clear_active_tracker_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


ZERO_WIDTH_CHARS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"), None)
MOJIBAKE_MARKERS = (
    "\u00c3",
    "\u00c2",
    "\u00e2\u20ac",
    "\u00e2\u20ac\u2122",
    "\u00e2\u20ac\u0153",
    "\u00e2\u20ac\u009d",
    "\u00e2\u20ac\u201c",
    "\u00e2\u20ac\u201d",
    "\ufffd",
)
MOJIBAKE_FRAGMENT_CHARS = (
    "\u00a2\u00a3\u00a5\u00a6\u00a7\u00a8\u00aa\u00ab\u00ac\u00ad\u00ae\u00af\u00b0"
    "\u00b4\u00b8\u00ba\u00bb\u00c2\u00c3\u00e2\u0192\u02c6\u02dc\u0152\u0153"
    "\u0160\u0161\u017d\u017e\u0178\u201a\u201e\u2020\u2021\u2022\u2030"
    "\u2039\u203a\u20ac\u2122"
)

INVALID_TEXT_VALUES = {"", "nan", "nat", "none", "null"}
UNASSIGNED_PROJECT_VALUES = {
    "unknown",
    "unassigned activities",
    "other",
    "sleep",
    "system sleep",
    "empty",
}
MEANINGLESS_ACTIVITY_VALUES = {
    "",
    "nan",
    "nat",
    "none",
    "null",
    "unknown",
    "unknown window",
    "unknown task",
    "unknown activity",
    "empty title",
    "system tray overflow window",
    "program manager",
    "default ime",
    "lock screen",
    "windows default lock screen",
    "start menu",
    "search",
}


def is_invalid_text_value(value):
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass

    return str(value).strip().lower() in INVALID_TEXT_VALUES


def normalize_required_text(value):
    if is_invalid_text_value(value):
        return ""

    text = clean_display_text(value)

    if is_invalid_text_value(text):
        return ""

    return text.strip()


def normalize_validation_label(value):
    return normalize_required_text(value).lower().strip(" .")


def is_meaningless_activity_label(value):
    label = normalize_validation_label(value)
    if label in MEANINGLESS_ACTIVITY_VALUES:
        return True
    return any(
        marker in label
        for marker in (
            "system tray overflow window",
            "windows default lock screen",
        )
    )


def is_meaningful_project_and_task(project_name, task_name):
    project = normalize_validation_label(project_name)
    task = normalize_validation_label(task_name)
    if not project or project in UNASSIGNED_PROJECT_VALUES or is_meaningless_activity_label(project):
        return False
    if not task or is_meaningless_activity_label(task):
        return False
    return True


def get_first_non_empty_series(df, column_names):
    values = pd.Series("", index=df.index, dtype="object")
    for column_name in column_names:
        if column_name not in df.columns:
            continue
        candidate = df[column_name].fillna("").astype(str).map(normalize_required_text)
        values = values.mask(values.eq(""), candidate)
    return values


def get_activity_project_series(df):
    return get_first_non_empty_series(df, ("Project Name", "Project"))


def get_activity_task_series(df):
    return get_first_non_empty_series(
        df,
        ("AI Task Name", "File Name", "Task Name", "Activity", "App Name"),
    )


def get_assigned_mask(df):
    if df.empty:
        return pd.Series(False, index=df.index)
    if "Is Assigned" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["Is Assigned"].fillna(False).map(
        lambda value: str(value).strip().lower() in {"true", "1", "yes", "y"}
        if isinstance(value, str)
        else bool(value)
    )


def get_valid_project_mask(df):
    if df.empty:
        return pd.Series(False, index=df.index)
    if "Valid Project" in df.columns:
        return df["Valid Project"].fillna(False).map(
            lambda value: str(value).strip().lower() in {"true", "1", "yes", "y"}
            if isinstance(value, str)
            else bool(value)
        )
    return pd.Series(False, index=df.index)


CLASSIFIED_TASK_NAMES = {
    "Dashboard Development",
    "Auto Start Feature",
    "Email Automation Module",
    "Email Verification Module",
}

GENERIC_PROJECT_LABELS = {
    "browser work",
    "chrome work",
    "edge work",
    "unknown project",
    "unassigned activities",
}


def normalize_classified_project_display(project_name, task_name):
    project = normalize_required_text(project_name)
    task = normalize_required_text(task_name)
    if task in CLASSIFIED_TASK_NAMES and normalize_validation_label(project) in GENERIC_PROJECT_LABELS:
        return os.path.basename(BASE_DIR) or "productivity Tracker"
    return project


def log_skipped_invalid_row(row):
    try:
        row_data = row.to_dict()
    except AttributeError:
        row_data = row

    print("Skipped invalid row:", row_data)



def _mojibake_score(value):
    value = str(value or "")
    return sum(value.count(marker) for marker in MOJIBAKE_MARKERS)


def _repair_mojibake(value):
    text = str(value or "")

    for _ in range(4):
        best_text = text
        best_score = _mojibake_score(text)

        for encoding in ("cp1252", "latin1"):
            try:
                candidate = text.encode(encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue

            candidate_score = _mojibake_score(candidate)
            if candidate_score < best_score:
                best_text = candidate
                best_score = candidate_score

        if best_text == text:
            break

        text = best_text

    return text


def clean_display_text(value):
    if is_invalid_text_value(value):
        return ""

    text = _repair_mojibake(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(ZERO_WIDTH_CHARS)
    text = text.replace("\ufffd", " ")
    text = "".join(
        " " if char in MOJIBAKE_FRAGMENT_CHARS else char
        for char in text
    )
    text = "".join(
        char if char.isprintable() and not unicodedata.category(char).startswith("C") else " "
        for char in text
    )
    text = re.sub(r"\s+", " ", text).strip()

    if not any(char.isalnum() for char in text):
        return ""

    return text


def clean_dataframe_text(df):
    df = df.copy()

    for column in df.select_dtypes(include=["object"]).columns:
        df[column] = df[column].apply(clean_display_text)

    return df



def load_env_file():

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def build_ai_cache_key(project_name, file_name):

    project = normalize_required_text(project_name)
    filename = os.path.basename(normalize_required_text(file_name))

    if not project or not filename:
        return ""

    return f"{project}|{filename}"


def resolve_project_file_path(project_name, file_name):

    filename = os.path.basename(normalize_required_text(file_name))
    if not filename:
        return None

    current_root = os.path.dirname(__file__)
    desktop_root = os.path.dirname(current_root)
    project = normalize_required_text(project_name)
    candidates = []

    if project:
        candidates.append(os.path.join(desktop_root, project, filename))

    candidates.append(os.path.join(current_root, filename))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    search_roots = []
    if project:
        project_root = os.path.join(desktop_root, project)
        if os.path.isdir(project_root):
            search_roots.append(project_root)
    search_roots.append(current_root)

    for search_root in search_roots:
        for dirpath, dirnames, filenames in os.walk(search_root):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in {".git", ".venv", "__pycache__", "build", "dist"}]
            if filename in filenames:
                return os.path.join(dirpath, filename)

    return None


def read_first_100_lines(project_name, file_name):

    file_path = resolve_project_file_path(project_name, file_name)
    if not file_path:
        return ""

    lines = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as source_file:
            for index, line in enumerate(source_file):
                if index >= 100:
                    break
                lines.append(line.rstrip("\n"))
    except OSError:
        return ""

    return "\n".join(lines).strip()


def build_ai_task_prompt(project_name, file_name, first_100_lines):

    project = normalize_required_text(project_name)
    filename = os.path.basename(normalize_required_text(file_name))
    code = first_100_lines.strip()

    if code:
        return f"""Generate a professional software development activity description suitable for a manager timesheet.

Project:
{project}

Filename:
{filename}

Code:
{code}

Rules:

* Maximum 4 words.
* Use business-friendly wording.
* Describe the actual development work.
* Avoid generic terms like "Enhancement" unless necessary.
* Return only the task name.
* No explanations."""

    return f"""Generate a professional software development activity description suitable for a manager timesheet.

Project:
{project}

Filename:
{filename}

Rules:

* Maximum 4 words.
* Use business-friendly wording.
* Describe the actual development work.
* Avoid generic terms like "Enhancement" unless necessary.
* Return only the task name.
* No explanations."""


def clean_ai_task_name(task_name, fallback):

    task_name = normalize_required_text(str(task_name or "").strip().strip('"').strip("'"))
    if not task_name:
        return fallback

    words = task_name.split()
    if len(words) > 4:
        task_name = " ".join(words[:4])

    return task_name

def load_ai_cache():
    if not os.path.exists(AI_CACHE_FILE):
        return {}
    try:
        with open(AI_CACHE_FILE, "r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
            return cache if isinstance(cache, dict) else {}
    except Exception:
        return {}


def save_ai_cache(cache):
    with open(AI_CACHE_FILE, "w", encoding="utf-8") as cache_file:
        json.dump(cache, cache_file, indent=2, ensure_ascii=False)


def title_case_words(words):
    small_words = {"and", "or", "for", "to", "of", "in", "on", "with"}
    titled = []
    for index, word in enumerate(words):
        word = str(word or "").strip().lower()
        if not word:
            continue
        if index > 0 and word in small_words:
            titled.append(word)
        else:
            titled.append(word.capitalize())
    return " ".join(titled)


def fallback_ai_task_name(file_name):
    if is_invalid_text_value(file_name):
        return ""

    return normalize_required_text(file_name)


def call_ai_task_name_service(project_name, file_name, first_100_lines=""):

    load_env_file()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=8000),
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_ai_task_prompt(project_name, file_name, first_100_lines),
    )

    fallback = fallback_ai_task_name(file_name)
    return clean_ai_task_name(response.text, fallback)


def get_ai_task_name(project_name, file_name, cache=None):

    if is_invalid_text_value(project_name) or is_invalid_text_value(file_name):
        return ""

    project = normalize_required_text(project_name)
    raw_file_name = os.path.basename(normalize_required_text(file_name))
    if is_invalid_text_value(project) or is_invalid_text_value(raw_file_name):
        return ""
    if project.upper() in {"IDLE", "SYSTEM IDLE"}:
        return "System Idle"
    return raw_file_name


def get_default_project_name():

    """Best-effort project name for task entries."""
    folder_name = os.path.basename(os.path.abspath(os.path.dirname(__file__))).strip()
    return folder_name or "task-1"


def normalize_review_project_name(project_name, task_name=""):
    project = normalize_required_text(project_name)
    normalized = normalize_validation_label(project)
    generic_projects = {
        "browser work",
        "chrome work",
        "edge work",
        "unknown project",
        "unassigned activities",
        "idle",
    }
    if normalized in generic_projects:
        task = normalize_required_text(task_name)
        return get_default_project_name() if task and task != "Unassigned Activity" else "Unassigned Activities"
    return project or get_default_project_name()


def empty_review_data():
    return {"tasks": [], "unassigned": [], "activity_merges": []}


def get_user_tasks_file():
    user_id = get_session_user_id()
    if not user_id:
        return TASKS_FILE

    tasks_dir = os.path.join(os.path.dirname(__file__), "user_tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    return os.path.join(tasks_dir, f"tasks_user_{user_id}.json")


def debug_email_review_flow(step, tasks=None, unassigned=None, target_task=None, activity_ids=None, extra=None):
    try:
        user_id = get_session_user_id()
    except Exception:
        user_id = None
    lines = [
        "",
        "========== EMAIL REVIEW FLOW DEBUG ==========",
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Step: {step}",
        f"User ID: {user_id}",
        f"Review task rows: {len(tasks or [])}",
        f"Unassigned activities: {len(unassigned or [])}",
        f"Target task ID/name: {target_task}",
        f"Activity IDs being merged: {activity_ids or []}",
    ]
    if extra is not None:
        lines.append(f"Extra: {extra}")
    lines.append("============================================")
    for line in lines:
        print(line)
    try:
        with open(EMAIL_REVIEW_DEBUG_LOG_FILE, "a", encoding="utf-8") as debug_file:
            for line in lines:
                debug_file.write(f"{line}\n")
    except OSError as error:
        print(f"Unable to write email review debug log: {error}")


def load_tasks_data():
    """Load persisted email review data for the current user."""
    tasks_file_path = get_user_tasks_file()
    if not os.path.exists(tasks_file_path):
        debug_email_review_flow(
            "load_tasks_data missing file",
            extra={"file": tasks_file_path},
        )
        return empty_review_data()

    try:
        with open(tasks_file_path, "r", encoding="utf-8") as task_file:
            data = json.load(task_file)
            if isinstance(data, list):
                debug_email_review_flow(
                    "load_tasks_data loaded legacy list",
                    tasks=data,
                    extra={"file": tasks_file_path},
                )
                return {"tasks": data, "unassigned": [], "activity_merges": []}
            if isinstance(data, dict):
                loaded_tasks = data.get("tasks", []) if isinstance(data.get("tasks", []), list) else []
                loaded_unassigned = data.get("unassigned", []) if isinstance(data.get("unassigned", []), list) else []
                debug_email_review_flow(
                    "load_tasks_data loaded dict",
                    tasks=loaded_tasks,
                    unassigned=loaded_unassigned,
                    extra={"file": tasks_file_path},
                )
                return {
                    "tasks": loaded_tasks,
                    "unassigned": loaded_unassigned,
                    "activity_merges": data.get("activity_merges", []) if isinstance(data.get("activity_merges", []), list) else [],
                }
            debug_email_review_flow(
                "load_tasks_data invalid payload",
                extra={"file": tasks_file_path, "payload_type": type(data).__name__},
            )
            return empty_review_data()
    except Exception as error:
        debug_email_review_flow(
            "load_tasks_data exception",
            extra={"file": tasks_file_path, "error": str(error)},
        )
        return empty_review_data()


def save_tasks_data(tasks, unassigned=None, activity_merges=None):
    """Persist review edits and manual merge selections for the current user."""
    payload = {
        "tasks": sanitize_saved_tasks(tasks),
        "unassigned": normalize_unassigned_activities(unassigned or []),
        "activity_merges": normalize_activity_merges(activity_merges or []),
    }
    tasks_file_path = get_user_tasks_file()
    debug_email_review_flow(
        "save_tasks_data before write",
        tasks=payload["tasks"],
        unassigned=payload["unassigned"],
        extra={"file": tasks_file_path, "activity_merges": len(payload["activity_merges"])},
    )
    with open(tasks_file_path, "w", encoding="utf-8") as task_file:
        json.dump(payload, task_file, indent=2, ensure_ascii=False)
    debug_email_review_flow(
        "save_tasks_data after write",
        tasks=payload["tasks"],
        unassigned=payload["unassigned"],
        extra={"file": tasks_file_path, "activity_merges": len(payload["activity_merges"])},
    )


def parse_review_duration(duration):
    parts = str(duration or "0:00").strip().split(":")
    try:
        if len(parts) >= 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) >= 2:
            return int(parts[0]) * 3600 + int(parts[1]) * 60
        return int(parts[0])
    except Exception:
        return 0


def format_review_duration(total_seconds):
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def normalize_app_identity(app_name):
    normalized = str(app_name or "").strip().lower()
    for marker in (" - google chrome", " - microsoft edge"):
        if normalized.endswith(marker):
            normalized = marker.rsplit(" - ", 1)[1]
            break
    return normalized


def normalize_misc_app(app_name):
    normalized = normalize_app_identity(app_name)
    if any(app in normalized for app in AUTO_MERGE_APPS):
        return None
    return MANUAL_ASSIGN_APPS.get(normalized)


def is_auto_merge_activity(activity_name):
    normalized = str(activity_name or "").strip().lower()
    return any(app in normalized for app in AUTO_MERGE_APPS)


def is_ignored_task_file(task_name):
    return os.path.basename(str(task_name or "").strip()).lower() in IGNORE_FILES


def task_identity(task):
    project = str(task.get("project", "")).strip().lower()
    source_task = str(task.get("source_task") or task.get("task") or "").strip().lower()
    return (project, source_task)


def sort_review_tasks_by_project(tasks):
    tasks = list(tasks or [])
    project_totals = {}

    for task in tasks:
        project = normalize_required_text(task.get("project", ""))
        project_totals[project] = project_totals.get(project, 0) + parse_review_duration(task.get("duration"))

    return sorted(
        tasks,
        key=lambda task: (
            -project_totals.get(normalize_required_text(task.get("project", "")), 0),
            normalize_required_text(task.get("project", "")).lower(),
            -parse_review_duration(task.get("duration")),
            normalize_required_text(task.get("task", "")).lower(),
        ),
    )


def add_duration_to_task(task, minutes):
    task["duration"] = format_review_duration(
        parse_review_duration(task.get("duration")) + parse_review_duration(minutes)
    )


def find_task_by_name(tasks, task_name):
    target = str(task_name or "").strip().lower()
    return next(
        (
            task for task in tasks
            if str(task.get("task", "")).strip().lower() == target
            or str(task.get("source_task", "")).strip().lower() == target
        ),
        None,
    )

def load_data():
    current_user_id = get_session_user_id()
    if current_user_id:
        db_df = load_user_activities_dataframe(
            user_id=current_user_id,
            include_all=is_manager_user(),
        )
        if db_df is not None:
            db_df = ensure_activity_category(db_df)
            if not is_manager_user():
                db_df = filter_activity_date(db_df)
            return db_df
        return empty_activity_dataframe()

    if not os.path.exists(DATA_FILE):
        return empty_activity_dataframe()

    df = pd.read_csv(DATA_FILE, encoding="utf-8-sig", encoding_errors="replace")
    # Clean column names
    df.columns = [clean_display_text(c).strip() for c in df.columns]
    df = clean_dataframe_text(df)
    # Parse datetime columns if present
    if 'Start Time' in df.columns:
        df['Start Time'] = pd.to_datetime(df['Start Time'], errors='coerce')
    if 'End Time' in df.columns:
        df['End Time'] = pd.to_datetime(df['End Time'], errors='coerce')
    # Convert duration to seconds if not already numeric
    if 'Duration' in df.columns:
        if not pd.api.types.is_numeric_dtype(df['Duration']):
            df['Duration'] = pd.to_timedelta(df['Duration']).dt.total_seconds()
    if {'Start Time', 'End Time'}.issubset(df.columns):
        calculated_duration = (df['End Time'] - df['Start Time']).dt.total_seconds()
        df['Duration'] = calculated_duration.where(calculated_duration > 0, df.get('Duration', 0)).fillna(0)
    if "Duration" in df.columns:
        project_names = df.get("Project Name", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
        app_names = df.get("App Name", pd.Series("", index=df.index)).fillna("").astype(str).str.upper()
        idle_mask = (
            project_names.isin({"IDLE", "SYSTEM IDLE"})
            | app_names.isin({"IDLE", "SYSTEM IDLE", "NO APPLICATION"})
            | app_names.str.contains("SYSTEM IDLE", na=False)
        )
        df = df.loc[~(idle_mask & (pd.to_numeric(df["Duration"], errors="coerce").fillna(0) > MAX_RECORDED_IDLE_SECONDS))].copy()
    return df


def get_idle_mask(df):
    """Detect idle rows from project or app labels in the activity data."""
    if df.empty:
        return pd.Series(False, index=df.index)

    project_names = (
        df.get('Project Name', pd.Series('', index=df.index))
        .fillna('')
        .astype(str)
        .str.strip()
        .str.upper()
    )
    app_names = (
        df.get('App Name', pd.Series('', index=df.index))
        .fillna('')
        .astype(str)
        .str.strip()
        .str.upper()
    )

    idle_labels = {'IDLE', 'SYSTEM IDLE', 'LOCK SCREEN', 'UNKNOWN WINDOW', 'NO ACTIVITY'}
    return (
        project_names.isin({'IDLE', 'SYSTEM IDLE'})
        | app_names.isin(idle_labels)
        | app_names.str.contains('SYSTEM IDLE', na=False)
    )


def get_unassigned_mask(df):
    if df.empty:
        return pd.Series(False, index=df.index)

    categories = (
        df.get('Activity Category', pd.Series('', index=df.index))
        .fillna('')
        .astype(str)
        .str.strip()
        .str.upper()
    )
    project_names = get_activity_project_series(df)
    task_names = get_activity_task_series(df)
    assigned_mask = get_assigned_mask(df)
    valid_project_mask = get_valid_project_mask(df)
    invalid_projects = project_names.map(
        lambda value: not is_meaningful_project_and_task(value, "placeholder.py")
    )
    invalid_tasks = task_names.map(
        lambda value: not normalize_validation_label(value) or is_meaningless_activity_label(value)
    )
    return categories.eq('UNASSIGNED ACTIVITIES') | ~assigned_mask | ~valid_project_mask | invalid_projects | invalid_tasks


def get_project_work_mask(df):
    if df.empty:
        return pd.Series(False, index=df.index)

    projects = get_activity_project_series(df)
    tasks = get_activity_task_series(df)
    meaningful_pairs = pd.Series(
        [
            is_meaningful_project_and_task(project, task)
            for project, task in zip(projects, tasks)
        ],
        index=df.index,
    )
    return get_assigned_mask(df) & get_valid_project_mask(df) & meaningful_pairs & ~(get_idle_mask(df) | get_unassigned_mask(df))


def ensure_activity_category(df):
    if df.empty:
        if "Activity Category" not in df.columns:
            df = df.copy()
            df["Activity Category"] = []
        return df

    df = df.copy()
    task_names = get_activity_task_series(df)
    project_names = get_activity_project_series(df)
    normalized_projects = [
        normalize_classified_project_display(project, task)
        for project, task in zip(project_names, task_names)
    ]
    if "Project Name" in df.columns:
        df["Project Name"] = normalized_projects
    if "Project" in df.columns:
        df["Project"] = normalized_projects
    classified_mask = task_names.isin(CLASSIFIED_TASK_NAMES) & pd.Series(
        [
            normalize_validation_label(project) not in {"", "idle"}
            for project in normalized_projects
        ],
        index=df.index,
    )
    if "Is Assigned" in df.columns:
        df.loc[classified_mask, "Is Assigned"] = True
    if "Valid Project" in df.columns:
        df.loc[classified_mask, "Valid Project"] = True

    idle_mask = get_idle_mask(df)
    unassigned_mask = get_unassigned_mask(df)
    project_work_mask = get_project_work_mask(df)
    df["Activity Category"] = "Unassigned Activities"
    df.loc[project_work_mask, "Activity Category"] = "Project Work"
    df.loc[unassigned_mask, "Activity Category"] = "Unassigned Activities"
    df.loc[idle_mask & ~unassigned_mask, "Activity Category"] = "IDLE"
    return df


def build_balanced_time_summary(total_seconds, productive_seconds):
    """Return minute-balanced seconds so displayed HH:MM cards add up."""
    total_seconds = max(0, float(total_seconds or 0))
    productive_seconds = max(0, min(float(productive_seconds or 0), total_seconds))

    total_minutes = max(0, int(round(total_seconds / 60)))
    productive_minutes = max(0, min(int(round(productive_seconds / 60)), total_minutes))
    idle_minutes = max(0, total_minutes - productive_minutes)

    return {
        'total_seconds': total_minutes * 60,
        'productive_seconds': productive_minutes * 60,
        'idle_seconds': idle_minutes * 60
    }


def get_session_category_masks(df):
    idle_mask = get_idle_mask(df)
    project_work_mask = get_project_work_mask(df) & ~idle_mask
    unassigned_mask = ~(project_work_mask | idle_mask)
    return project_work_mask, idle_mask, unassigned_mask


def filter_activity_date(df, target_date=None):
    if df.empty or "Start Time" not in df.columns:
        return df.copy()

    target_date = target_date or datetime.now().date()
    filtered = df.copy()
    start_times = pd.to_datetime(filtered["Start Time"], errors="coerce")
    return filtered.loc[start_times.dt.date == target_date].copy()


def build_consistent_activity_summary(df):
    if df.empty or "Duration" not in df.columns:
        return {
            "total_seconds": 0.0,
            "productive_seconds": 0.0,
            "idle_seconds": 0.0,
            "project_work_seconds": 0.0,
            "unassigned_seconds": 0.0,
            "total_sessions": 0,
            "productive_sessions": 0,
            "idle_sessions": 0,
            "unassigned_sessions": 0,
            "productivity_score": 0.0,
        }

    project_work_mask, idle_mask, unassigned_mask = get_session_category_masks(df)
    total_seconds = max(0, float(df["Duration"].sum() or 0))
    idle_seconds = max(0, float(df.loc[idle_mask, "Duration"].sum() or 0))
    project_work_seconds = max(0, float(df.loc[project_work_mask, "Duration"].sum() or 0))
    unassigned_seconds = max(0, float(df.loc[unassigned_mask, "Duration"].sum() or 0))
    productive_seconds = max(0, total_seconds - idle_seconds)

    total_sessions = int(len(df))
    idle_sessions = int(idle_mask.sum())
    project_work_sessions = int(project_work_mask.sum())
    unassigned_sessions = int(unassigned_mask.sum())
    productive_sessions = max(0, total_sessions - idle_sessions)

    return {
        "total_seconds": total_seconds,
        "productive_seconds": productive_seconds,
        "idle_seconds": idle_seconds,
        "project_work_seconds": project_work_seconds,
        "unassigned_seconds": unassigned_seconds,
        "total_sessions": total_sessions,
        "productive_sessions": productive_sessions,
        "project_work_sessions": project_work_sessions,
        "idle_sessions": idle_sessions,
        "unassigned_sessions": unassigned_sessions,
        "productivity_score": round((productive_seconds / total_seconds) * 100, 2) if total_seconds else 0.0,
    }


def debug_overview_session_counts(user_id, total_count, productive_count, idle_count, unassigned_count):
    lines = [
        "",
        "========== OVERVIEW SESSION COUNT DEBUG ==========",
        f"Current User ID: {user_id}",
        "Total Sessions Query:",
        f"SELECT COUNT(*) FROM activities WHERE user_id = {user_id} AND email_sent = FALSE;",
        "Productive Sessions Query:",
        f"SELECT COUNT(*) FROM activities WHERE user_id = {user_id} AND email_sent = FALSE AND category = 'Project Work';",
        "Idle Sessions Query:",
        f"SELECT COUNT(*) FROM activities WHERE user_id = {user_id} AND email_sent = FALSE AND category = 'IDLE';",
        "Unassigned Sessions Query:",
        f"SELECT COUNT(*) FROM activities WHERE user_id = {user_id} AND email_sent = FALSE AND category = 'Unassigned Activities';",
        f"Total: {total_count}",
        f"Productive: {productive_count}",
        f"Idle: {idle_count}",
        f"Unassigned: {unassigned_count}",
        f"Check: {productive_count} + {idle_count} + {unassigned_count} = {productive_count + idle_count + unassigned_count}",
        f"Matches Total: {total_count == productive_count + idle_count + unassigned_count}",
        "================================================",
    ]
    for line in lines:
        print(line)


def is_idle_activity_label(project_name, app_name=""):
    labels = {
        str(project_name or "").strip().upper(),
        str(app_name or "").strip().upper(),
    }
    return any(label in {"IDLE", "SYSTEM IDLE", "SLEEP"} for label in labels)


def is_unassigned_activity_label(project_name, app_name=""):
    labels = {
        str(project_name or "").strip().upper(),
        str(app_name or "").strip().upper(),
    }
    return "UNASSIGNED ACTIVITIES" in labels


def get_manager_date_range(args):
    period = str(args.get("period") or "today").strip().lower()
    now = datetime.now()
    today = now.date()
    start_date = None
    end_date = None

    if period == "today":
        start_date = today
        end_date = today + timedelta(days=1)
    elif period == "yesterday":
        start_date = today - timedelta(days=1)
        end_date = today
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = today + timedelta(days=1)
    elif period == "month":
        start_date = today.replace(day=1)
        end_date = today + timedelta(days=1)
    elif period == "custom":
        try:
            if args.get("start_date"):
                start_date = pd.to_datetime(args.get("start_date")).date()
            if args.get("end_date"):
                end_date = pd.to_datetime(args.get("end_date")).date() + timedelta(days=1)
        except Exception:
            start_date = today
            end_date = today + timedelta(days=1)

    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.min.time()) if end_date else None
    return start_dt, end_dt


def apply_manager_activity_filters(query, args):
    start_dt, end_dt = get_manager_date_range(args)
    try:
        employee_user_id = int(args.get("user_id") or 0)
    except (TypeError, ValueError):
        employee_user_id = 0
    if employee_user_id:
        query = query.filter(Activity.user_id == employee_user_id)
    if start_dt:
        query = query.filter(Activity.start_time >= start_dt)
    if end_dt:
        query = query.filter(Activity.start_time < end_dt)
    return query


def format_manager_datetime(value):
    if not value:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def manager_seconds_payload(seconds):
    seconds = max(0, int(seconds or 0))
    return {
        "seconds": seconds,
        "display": format_seconds_hms(seconds),
    }


def get_manager_activity_metrics(activity):
    project_name = normalize_project_name_for_storage(
        activity.project_name,
        activity.file_name,
        activity.ai_task_name,
    )
    task_name = derive_processed_task_name(
        project_name,
        activity.file_name or "",
        activity.file_name or "",
        activity.ai_task_name or "",
    )
    try:
        duration = int(((activity.end_time or activity.start_time) - activity.start_time).total_seconds()) if activity.start_time else int(activity.duration or 0)
        duration = duration if duration > 0 else int(activity.duration or 0)
    except Exception:
        duration = int(activity.duration or 0)

    is_idle = is_idle_activity_label(project_name, task_name)
    is_productive = (
        not is_idle
        and project_name not in {"IDLE", "Unassigned Activities"}
        and is_meaningful_project_and_task(project_name, task_name)
    )
    display_project = project_name if is_productive else ("IDLE" if is_idle else "Unassigned Activities")
    return display_project, task_name, duration, is_idle, is_productive


def is_reportable_manager_activity(activity):
    project_name, _, duration, _, _ = get_manager_activity_metrics(activity)
    return not should_ignore_idle_activity(
        project_name,
        activity.file_name,
        activity.ai_task_name,
        duration,
    )


def build_employee_metric_rows(db_session, args):
    employees = (
        db_session.query(User)
        .filter(User.role == "employee")
        .order_by(User.employee_name.asc())
        .all()
    )
    employee_ids = [employee.id for employee in employees]
    activities = []
    if employee_ids:
        query = db_session.query(Activity).filter(Activity.user_id.in_(employee_ids))
        activities = apply_manager_activity_filters(query, args).all()

    activity_totals = {
        employee.id: {
            "total_seconds": 0,
            "idle_seconds": 0,
            "productive_seconds": 0,
            "activity_count": 0,
        }
        for employee in employees
    }

    for activity in activities:
        if not is_reportable_manager_activity(activity):
            continue
        totals = activity_totals.get(activity.user_id)
        if totals is None:
            continue
        _, _, duration, is_idle, is_productive = get_manager_activity_metrics(activity)
        totals["total_seconds"] += duration
        totals["activity_count"] += 1
        if is_idle:
            totals["idle_seconds"] += duration
        elif is_productive:
            totals["productive_seconds"] += duration

    rows = []
    for employee in employees:
        totals = activity_totals[employee.id]
        total_seconds = totals["total_seconds"]
        productive_seconds = totals["productive_seconds"]
        productivity = round((productive_seconds / total_seconds) * 100, 2) if total_seconds else 0
        rows.append({
            "user_id": employee.id,
            "employee_name": employee.employee_name,
            "employee_id": employee.employee_id,
            "total_work_time": format_seconds_hms(total_seconds),
            "total_work_seconds": total_seconds,
            "productive_time": format_seconds_hms(productive_seconds),
            "productive_seconds": productive_seconds,
            "idle_time": format_seconds_hms(totals["idle_seconds"]),
            "idle_seconds": totals["idle_seconds"],
            "productivity_percentage": productivity,
            "total_activities": totals["activity_count"],
        })

    return rows, activities, employees


@app.route("/analytics/team")
@app.route("/admin")
@app.route("/manager")
@manager_required
def manager_dashboard():
    response = app.make_response(render_template("manager_dashboard.html"))
    response.headers["X-Template-Rendered"] = "manager_dashboard.html"
    return response


@app.route("/manager_dashboard.html")
@app.route("/templates/manager_dashboard.html")
def manager_dashboard_template_alias():
    return redirect(url_for("manager_dashboard"))


@app.route("/api/manager/overview")
@manager_required
def api_manager_overview():
    try:
        with get_db_session() as db_session:
            rows, activities, employees = build_employee_metric_rows(db_session, request.args)
            employee_ids = [employee.id for employee in employees]

            today_start = datetime.combine(datetime.now().date(), datetime.min.time())
            today_end = today_start + timedelta(days=1)
            active_today = 0
            if employee_ids:
                active_today = len({
                    user_id for (user_id,) in db_session.query(Activity.user_id)
                    .filter(
                        Activity.user_id.in_(employee_ids),
                        Activity.start_time >= today_start,
                        Activity.start_time < today_end,
                    )
                    .distinct()
                    .all()
                })

        total_productive = sum(row["productive_seconds"] for row in rows)
        total_idle = sum(row["idle_seconds"] for row in rows)
        scored_rows = [row for row in rows if row["total_work_seconds"] > 0]
        average_score = (
            round(sum(row["productivity_percentage"] for row in scored_rows) / len(scored_rows), 2)
            if scored_rows else 0
        )

        return jsonify({
            "success": True,
            "cards": {
                "total_employees": len(employees),
                "active_employees_today": active_today,
                "total_productive_time": manager_seconds_payload(total_productive),
                "total_idle_time": manager_seconds_payload(total_idle),
                "average_productivity_score": average_score,
            },
        })
    except Exception as error:
        print("Manager overview failed:", error)
        return jsonify({"success": False, "error": str(error)}), 500


@app.route("/api/manager/employees")
@manager_required
def api_manager_employees():
    try:
        with get_db_session() as db_session:
            rows, _, _ = build_employee_metric_rows(db_session, request.args)
        return jsonify({"success": True, "data": rows})
    except Exception as error:
        print("Manager employees failed:", error)
        return jsonify({"success": False, "error": str(error), "data": []}), 500


@app.route("/api/manager/employee-options")
@manager_required
def api_manager_employee_options():
    try:
        with get_db_session() as db_session:
            employees = (
                db_session.query(User)
                .filter(User.role == "employee")
                .order_by(User.employee_name.asc())
                .all()
            )

        return jsonify({
            "success": True,
            "data": [
                {
                    "user_id": employee.id,
                    "employee_name": employee.employee_name,
                    "employee_id": employee.employee_id,
                }
                for employee in employees
            ],
        })
    except Exception as error:
        print("Manager employee options failed:", error)
        return jsonify({"success": False, "error": str(error), "data": []}), 500


def build_activity_record_rows(activities):
    grouped = {}
    for activity in activities:
        if not is_reportable_manager_activity(activity):
            continue
        if not activity.start_time:
            continue

        key = (activity.user_id, activity.start_time.date().isoformat())
        row = grouped.setdefault(key, {
            "user_id": activity.user_id,
            "employee_name": activity.user.employee_name if activity.user else "",
            "employee_id": activity.user.employee_id if activity.user else "",
            "date": activity.start_time.date().isoformat(),
            "login_time_raw": activity.start_time,
            "logout_time_raw": activity.end_time or activity.start_time,
            "total_seconds": 0,
            "productive_seconds": 0,
            "idle_seconds": 0,
            "activity_count": 0,
            "projects": {},
        })

        project_name, _, duration, is_idle, is_productive = get_manager_activity_metrics(activity)
        row["total_seconds"] += duration
        row["activity_count"] += 1
        row["login_time_raw"] = min(row["login_time_raw"], activity.start_time)
        row["logout_time_raw"] = max(row["logout_time_raw"], activity.end_time or activity.start_time)

        project = row["projects"].setdefault(project_name, 0)
        row["projects"][project_name] = project + duration

        if is_idle:
            row["idle_seconds"] += duration
        elif is_productive:
            row["productive_seconds"] += duration

    rows = []
    for row in grouped.values():
        total_seconds = row["total_seconds"]
        productive_seconds = row["productive_seconds"]
        project_items = sorted(row["projects"].items(), key=lambda item: item[1], reverse=True)
        productive_project_names = [
            project
            for project, _ in project_items
            if normalize_validation_label(project) not in {"unassigned activities", "idle"}
        ]
        rows.append({
            "user_id": row["user_id"],
            "employee_name": row["employee_name"],
            "employee_id": row["employee_id"],
            "date": row["date"],
            "login_time": row["login_time_raw"].strftime("%H:%M:%S") if row["login_time_raw"] else "",
            "logout_time": row["logout_time_raw"].strftime("%H:%M:%S") if row["logout_time_raw"] else "",
            "total_work_time": format_seconds_hms(total_seconds),
            "total_work_seconds": total_seconds,
            "productive_time": format_seconds_hms(productive_seconds),
            "productive_seconds": productive_seconds,
            "idle_time": format_seconds_hms(row["idle_seconds"]),
            "idle_seconds": row["idle_seconds"],
            "productivity_percentage": round((productive_seconds / total_seconds) * 100, 2) if total_seconds else 0,
            "project_name": ", ".join(productive_project_names[:3]) or "Unassigned Activities",
            "activity_count": row["activity_count"],
        })

    rows.sort(key=lambda item: (item["date"], item["employee_name"]), reverse=True)
    return rows


@app.route("/api/manager/activity-records")
@manager_required
def api_manager_activity_records():
    try:
        with get_db_session() as db_session:
            query = (
                db_session.query(Activity)
                .join(User, Activity.user_id == User.id)
                .filter(User.role == "employee")
            )
            activities = (
                apply_manager_activity_filters(query, request.args)
                .order_by(Activity.start_time.desc(), Activity.id.desc())
                .all()
            )
            rows = build_activity_record_rows(activities)

        total_seconds = sum(row["total_work_seconds"] for row in rows)
        productive_seconds = sum(row["productive_seconds"] for row in rows)
        idle_seconds = sum(row["idle_seconds"] for row in rows)
        activity_count = sum(row["activity_count"] for row in rows)
        employee_count = len({row["user_id"] for row in rows})

        return jsonify({
            "success": True,
            "summary": {
                "employees_found": employee_count,
                "total_work_time": manager_seconds_payload(total_seconds),
                "productive_time": manager_seconds_payload(productive_seconds),
                "idle_time": manager_seconds_payload(idle_seconds),
                "activity_count": activity_count,
            },
            "data": rows,
        })
    except Exception as error:
        print("Manager activity records failed:", error)
        return jsonify({"success": False, "error": str(error), "summary": {}, "data": []}), 500


@app.route("/api/manager/activity-record-detail")
@manager_required
def api_manager_activity_record_detail():
    try:
        user_id = int(request.args.get("user_id") or 0)
        selected_date = pd.to_datetime(request.args.get("date")).date()
        start_dt = datetime.combine(selected_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)

        with get_db_session() as db_session:
            employee = (
                db_session.query(User)
                .filter(User.id == user_id, User.role == "employee")
                .first()
            )
            if not employee:
                return jsonify({"success": False, "error": "Employee not found."}), 404

            activities = (
                db_session.query(Activity)
                .filter(
                    Activity.user_id == user_id,
                    Activity.start_time >= start_dt,
                    Activity.start_time < end_dt,
                )
                .order_by(Activity.start_time.asc(), Activity.id.asc())
                .all()
            )

        project_totals = {}
        timeline = []
        for activity in activities:
            if not is_reportable_manager_activity(activity):
                continue
            project_name, task_name, duration, _, _ = get_manager_activity_metrics(activity)
            project_totals[project_name] = project_totals.get(project_name, 0) + duration
            timeline.append({
                "start_time": activity.start_time.strftime("%H:%M:%S") if activity.start_time else "",
                "end_time": activity.end_time.strftime("%H:%M:%S") if activity.end_time else "",
                "project": project_name,
                "activity": task_name or activity.ai_task_name or activity.file_name or project_name,
                "duration": format_seconds_hms(duration),
                "duration_seconds": duration,
            })

        total_project_seconds = sum(project_totals.values())
        projects = [
            {
                "project": project,
                "duration": format_seconds_hms(seconds),
                "duration_seconds": seconds,
                "percentage": round((seconds / total_project_seconds) * 100, 2) if total_project_seconds else 0,
            }
            for project, seconds in sorted(project_totals.items(), key=lambda item: item[1], reverse=True)
        ]

        return jsonify({
            "success": True,
            "employee": {
                "user_id": employee.id,
                "employee_name": employee.employee_name,
                "employee_id": employee.employee_id,
            },
            "date": selected_date.isoformat(),
            "projects": projects,
            "timeline": timeline,
        })
    except Exception as error:
        print("Manager activity record detail failed:", error)
        return jsonify({"success": False, "error": str(error)}), 500


@app.route("/api/manager/employee/<int:user_id>")
@manager_required
def api_manager_employee_details(user_id):
    try:
        with get_db_session() as db_session:
            employee = (
                db_session.query(User)
                .filter(User.id == user_id, User.role == "employee")
                .first()
            )
            if not employee:
                return jsonify({"success": False, "error": "Employee not found."}), 404

            activities_query = db_session.query(Activity).filter(Activity.user_id == user_id)
            activities = (
                apply_manager_activity_filters(activities_query, request.args)
                .order_by(Activity.start_time.desc(), Activity.id.desc())
                .all()
            )
            projects = (
                db_session.query(Project)
                .filter(Project.user_id == user_id)
                .order_by(Project.project_name.asc())
                .all()
            )
            tasks = (
                db_session.query(Task)
                .filter(Task.user_id == user_id)
                .order_by(Task.created_at.desc(), Task.id.desc())
                .all()
            )

        project_summary = {
            project.project_name: {
                "project": project.project_name,
                "total_seconds": 0,
                "activity_count": 0,
            }
            for project in projects
        }
        daily_summary = {}

        timeline = []
        for activity in activities:
            if not is_reportable_manager_activity(activity):
                continue
            duration = int(activity.duration or 0)
            project_name = (
                activity.project_name
                if bool(getattr(activity, "is_assigned", False))
                else "Unassigned Activities"
            ) or "Other"
            project = project_summary.setdefault(
                project_name,
                {"project": project_name, "total_seconds": 0, "activity_count": 0},
            )
            project["total_seconds"] += duration
            project["activity_count"] += 1

            day_key = activity.start_time.date().isoformat() if activity.start_time else "Unknown"
            daily = daily_summary.setdefault(
                day_key,
                {"date": day_key, "total_seconds": 0, "productive_seconds": 0, "idle_seconds": 0},
            )
            daily["total_seconds"] += duration
            if is_idle_activity_label(activity.project_name, activity.ai_task_name):
                daily["idle_seconds"] += duration
            elif (
                not bool(getattr(activity, "is_assigned", False))
                or is_unassigned_activity_label(activity.project_name, activity.ai_task_name)
            ):
                pass
            else:
                daily["productive_seconds"] += duration

            if len(timeline) < 100:
                timeline.append({
                    "project_name": project_name,
                    "task_name": activity.ai_task_name or activity.file_name or project_name,
                    "status": activity.status or "",
                    "start_time": format_manager_datetime(activity.start_time),
                    "end_time": format_manager_datetime(activity.end_time),
                    "duration": format_seconds_hms(duration),
                    "duration_seconds": duration,
                })

        project_rows = []
        for item in project_summary.values():
            project_rows.append({
                "project": item["project"],
                "duration": format_seconds_hms(item["total_seconds"]),
                "duration_seconds": item["total_seconds"],
                "activities": item["activity_count"],
            })
        project_rows.sort(key=lambda item: item["duration_seconds"], reverse=True)
        project_name_by_id = {project.id: project.project_name for project in projects}

        task_rows = [
            {
                "task": task.task_name,
                "project": project_name_by_id.get(task.project_id, ""),
                "status": task.status or "",
                "duration": format_seconds_hms(task.duration or 0),
                "duration_seconds": int(task.duration or 0),
            }
            for task in tasks
        ]

        daily_rows = []
        for day in sorted(daily_summary.values(), key=lambda item: item["date"]):
            productivity = (
                round((day["productive_seconds"] / day["total_seconds"]) * 100, 2)
                if day["total_seconds"] else 0
            )
            daily_rows.append({
                "date": day["date"],
                "total_time": format_seconds_hms(day["total_seconds"]),
                "productive_time": format_seconds_hms(day["productive_seconds"]),
                "idle_time": format_seconds_hms(day["idle_seconds"]),
                "productivity_percentage": productivity,
            })

        return jsonify({
            "success": True,
            "employee": {
                "user_id": employee.id,
                "employee_name": employee.employee_name,
                "employee_id": employee.employee_id,
                "login_email": employee.login_email,
            },
            "timeline": timeline,
            "project_summary": project_rows,
            "task_summary": task_rows,
            "daily_trend": daily_rows,
        })
    except Exception as error:
        print("Manager employee details failed:", error)
        return jsonify({"success": False, "error": str(error)}), 500


# Add health endpoint
@app.route('/health')
def health():
    return jsonify({"status": "OK"})

# Update overview route to compute accurate metrics
@app.route('/')
@app.route('/dashboard')
def dashboard():
    # Dashboard Loaded
    print("Dashboard Loaded")
    df = load_data()
    print("Dataframe Exists:", 'df' in locals())
    project_work_mask, idle_mask, unassigned_mask = get_session_category_masks(df)
    summary = build_consistent_activity_summary(df)
    total_seconds = summary["total_seconds"]
    idle_seconds = summary["idle_seconds"]
    productive_seconds = summary["productive_seconds"]
    # Debug prints (temporary)
    print('TOTAL:', total_seconds)
    print('IDLE:', idle_seconds)
    print('PRODUCTIVE:', productive_seconds)
    # Convert to hours for display
    total_work_hours = round(total_seconds / 3600, 2)
    productive_hours = round(productive_seconds / 3600, 2)
    idle_hours = round(idle_seconds / 3600, 2)
    # Productivity score
    productivity_score = round((productive_seconds / total_seconds) * 100, 2) if total_seconds else 0
    # Total sessions
    total_sessions = summary["total_sessions"]
    productive_sessions = summary["productive_sessions"]
    idle_sessions = summary["idle_sessions"]
    unassigned_sessions = summary["unassigned_sessions"]
    debug_overview_session_counts(
        get_session_user_id(),
        total_sessions,
        productive_sessions,
        idle_sessions,
        unassigned_sessions,
    )
    # Project breakdown
    project_counts = df.groupby('Project Name')['Duration'].sum()
    pie_labels = list(project_counts.keys())
    pie_values = [round(v / 3600, 2) for v in project_counts.values]  # hours for each category
    # Application usage (top 5 text list)
    app_durations = df.groupby('App Name')['Duration'].sum().sort_values(ascending=False).head(10)
    bar_full_labels = [clean_display_text(label) for label in app_durations.index]
    recent = df.sort_values('Start Time', ascending=False).head(10)
    recent['Start Time'] = recent['Start Time'].astype(str)
    recent_records = recent[['Activity Category', 'Project Name', 'App Name', 'Start Time', 'Duration']].to_dict(orient='records')
    return render_template('dashboard.html',
        total_sessions=total_sessions,
        productive_sessions=productive_sessions,
        idle_sessions=idle_sessions,
        unassigned_sessions=unassigned_sessions,
        productivity_score=productivity_score,
        total_work_hours=total_work_hours,
        productive_hours=productive_hours,
        idle_hours=idle_hours,
        pie_labels=json.dumps(pie_labels),
        pie_values=json.dumps(pie_values),
        bar_full_labels=json.dumps(bar_full_labels),
        recent_activities=json.dumps(recent_records)
    )

# ---------- Activity Log Page ----------
@app.route('/activity-log')
def activity_log_page():
    # Render page; data will be loaded via AJAX
    return render_template('activity_log.html')
# Alias route for sidebar navigation
@app.route('/overview')
def overview():
    return dashboard()


# Helper function to filter dataframe based on request arguments
def filter_dataframe(df, args):
    """Apply search, project, and date filters to the dataframe based on request args."""
    # Search term
    search = args.get('search[value]', '').strip().lower()
    if search:
        mask = (
            df['Project Name'].astype(str).str.lower().str.contains(search) |
            df['App Name'].astype(str).str.lower().str.contains(search) |
            df.get('Window Title', pd.Series([''])).astype(str).str.lower().str.contains(search) |
            df.apply(lambda row: ' '.join(row.astype(str)), axis=1).str.lower().str.contains(search)
        )
        df = df[mask]
    # Project filter
    project = args.get('project')
    if project and project != 'All':
        df = df[df['Project Name'] == project]
    # Date filter
    date_filter = args.get('date_filter')
    if date_filter:
        today = datetime.now().date()
        if date_filter == 'today':
            df = df[df['Start Time'].dt.date == today]
        elif date_filter == 'last7':
            df = df[df['Start Time'] >= today - timedelta(days=7)]
        elif date_filter == 'last30':
            df = df[df['Start Time'] >= today - timedelta(days=30)]
        elif date_filter == 'custom':
            start_str = args.get('date_start')
            end_str = args.get('date_end')
            if start_str and end_str:
                start_dt = pd.to_datetime(start_str)
                end_dt = pd.to_datetime(end_str)
                df = df[(df['Start Time'] >= start_dt) & (df['Start Time'] <= end_dt)]
    return df

@app.route('/api/activity-data')
def activity_data():
    df = load_data()
    # Apply filtering & searching
    filtered_df = filter_dataframe(df, request.args)
    summary = build_consistent_activity_summary(filtered_df)
    total_records = len(filtered_df)
    total_work_time = summary["total_seconds"]
    idle_time = summary["idle_seconds"]
    productive_time = summary["productive_seconds"]
    print('ACTIVITY TOTAL:', total_work_time)
    print('ACTIVITY IDLE:', idle_time)
    print('ACTIVITY PRODUCTIVE:', productive_time)

    records_filtered = len(filtered_df)

    # Sorting
    order_col_index = request.args.get('order[0][column]')
    order_dir = request.args.get('order[0][dir]', 'asc')
    columns = ['Activity Category', 'Project Name', 'App Name', 'File Name', 'Start Time', 'End Time', 'Duration']
    if order_col_index is not None and order_col_index.isdigit():
        col_name = columns[int(order_col_index)]
        filtered_df = filtered_df.sort_values(col_name, ascending=(order_dir == 'asc'))

    # Pagination
    start = int(request.args.get('start', 0))
    length = int(request.args.get('length', 10))
    page_df = filtered_df.iloc[start:start+length]

    # Convert datetime columns to string for JSON serialization
    df_page = page_df[columns].copy()
    for col in ['Start Time', 'End Time']:
        if col in df_page.columns:
            df_page[col] = df_page[col].astype(str)
    data = df_page.fillna('').to_dict(orient='records')

    return jsonify({
        'draw': int(request.args.get('draw', 1)),
        'recordsTotal': total_records,
        'recordsFiltered': records_filtered,
        'data': data,
        'summary': {
            'total_records': total_records,
            'total_work_time': total_work_time,
            'productive_time': productive_time,
            'idle_time': idle_time
        }
    })

@app.route('/export/activity')
def export_activity():
    df = load_data()
    filtered_df = filter_dataframe(df, request.args)
    fmt = request.args.get('format', 'csv')
    if fmt == 'excel':
        # Requires openpyxl; ensure it is installed
        output = io.BytesIO()
        filtered_df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        return send_file(output, as_attachment=True,
                         download_name='activity_log.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    else:
        csv_data = filtered_df.to_csv(index=False)
        return send_file(io.BytesIO(csv_data.encode('utf-8-sig')),
                         as_attachment=True,
                         download_name='activity_log.csv',
                         mimetype='text/csv; charset=utf-8')

# Productivity page route renders dashboard with page flag
@app.route('/productivity')
def productivity():
    # Render dashboard template with page identifier for conditional rendering
    return render_template('dashboard.html', page='productivity')

# API endpoint for productivity data aggregation
@app.route('/api/productivity')
def api_productivity():
    df = load_data()
    summary = build_consistent_activity_summary(df)
    # Summary calculations (seconds -> hours)
    total_work_seconds = summary["total_seconds"]
    idle_seconds = summary["idle_seconds"]
    productive_seconds = summary["productive_seconds"]
    # Debug prints (to be removed after verification)
    print('Total seconds:', total_work_seconds)
    print('Idle seconds:', idle_seconds)
    print('Productive seconds:', productive_seconds)
    total_work_hours = total_work_seconds / 3600
    productive_hours = productive_seconds / 3600
    unassigned_hours = 0
    idle_hours = idle_seconds / 3600
    productivity_score = summary["productivity_score"]
    # Project breakdown
    proj_group = df.groupby('Project Name')['Duration'].sum().reset_index()
    proj_group['Hours'] = proj_group['Duration'] / 3600
    proj_group['Percentage'] = round(proj_group['Hours'] / total_work_hours * 100, 2) if total_work_hours else 0
    proj_data = proj_group[['Project Name', 'Hours', 'Percentage']].to_dict(orient='records')
    # Top applications
    app_group = df.groupby('App Name')['Duration'].sum().reset_index()
    app_group = app_group.sort_values('Duration', ascending=False).head(10)
    app_group['Hours'] = app_group['Duration'] / 3600
    app_group['Percentage'] = round(app_group['Hours'] / total_work_hours * 100, 2) if total_work_hours else 0
    app_data = app_group[['App Name', 'Hours', 'Percentage']].to_dict(orient='records')
    return jsonify({
        'summary': {
            'productivity_score': productivity_score,
            'total_work_hours': total_work_hours,
            'productive_hours': productive_hours,
            'unassigned_hours': unassigned_hours,
            'idle_hours': idle_hours
        },
        'project_breakdown': proj_data,
        'top_apps': app_data
    })

def get_current_report_data():
    df = load_current_user_activity_dataframe()
    summary = build_consistent_activity_summary(df)
        
    return {
        "summary": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_sessions": summary["total_sessions"],
            "productive_sessions": summary["productive_sessions"],
            "entertainment_sessions": summary["unassigned_sessions"],
            "idle_sessions": summary["idle_sessions"],
            "productivity_score": summary["productivity_score"]
        }
    }


def format_seconds_hms(seconds):
    seconds = max(0, int(float(seconds or 0)))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_current_user_activity_dataframe():
    user_id = get_session_user_id()
    if not user_id:
        return empty_activity_dataframe()
    df = load_user_activities_dataframe(user_id=user_id, include_all=False, include_sent=False)
    if df is None:
        return empty_activity_dataframe()
    return filter_activity_date(ensure_activity_category(df))


def load_current_user_all_activity_dataframe():
    user_id = get_session_user_id()
    if not user_id:
        return empty_activity_dataframe()
    df = load_user_activities_dataframe(user_id=user_id, include_all=False, include_sent=False)
    if df is None:
        return empty_activity_dataframe()
    return filter_activity_date(ensure_activity_category(df))


def get_assigned_report_dataframe(df=None):
    df = load_current_user_activity_dataframe() if df is None else df
    if df.empty:
        return df.copy()
    filtered = df.loc[get_project_work_mask(df)].copy()
    if filtered.empty or "Start Time" not in filtered.columns:
        return filtered
    start_times = pd.to_datetime(filtered["Start Time"], errors="coerce")
    today = datetime.now().date()
    return filtered.loc[start_times.dt.date == today].copy()


def get_all_history_report_dataframe():
    return load_current_user_all_activity_dataframe()


def _email_debug_write(lines):
    if isinstance(lines, str):
        lines = [lines]
    for line in lines:
        print(line)
    try:
        with open(EMAIL_REPORT_DEBUG_LOG_FILE, "a", encoding="utf-8") as file:
            for line in lines:
                file.write(f"{line}\n")
    except OSError as error:
        print(f"Unable to write email debug log: {error}")


def _format_email_debug_rows(df, max_rows=5):
    if df is None or df.empty:
        return ["(no rows)"]
    preview_columns = [
        "Activity ID",
        "Project Name",
        "Activity Category",
        "App Name",
        "AI Task Name",
        "Status",
        "Is Assigned",
        "Valid Project",
        "Start Time",
        "Duration",
    ]
    existing_columns = [column for column in preview_columns if column in df.columns]
    preview = df[existing_columns].head(max_rows).copy()
    if "Start Time" in preview.columns:
        preview["Start Time"] = preview["Start Time"].astype(str)
    return preview.to_string(index=False).splitlines()


def debug_email_report_inputs(raw_df, filtered_df, tasks):
    today = datetime.now().date()
    user_id = get_session_user_id()
    current_user = getattr(g, "current_user", None)
    username = (
        getattr(current_user, "employee_name", None)
        or getattr(current_user, "login_email", None)
        or session.get("employee_name")
        or session.get("login_email")
        or "Unknown"
    )
    query_used = (
        "load_user_activities_dataframe(user_id="
        f"{user_id}, include_all=False) -> "
        f"SELECT activities WHERE Activity.user_id = {user_id} "
        "ORDER BY Activity.start_time DESC, Activity.id DESC"
    )

    raw_count = 0 if raw_df is None else len(raw_df)
    final_count = 0 if filtered_df is None else len(filtered_df)
    task_count = len(tasks or [])

    lines = [
        "",
        "========== EMAIL REPORT DEBUG ==========",
        f"Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Current User ID: {user_id}",
        f"Current Username: {username}",
        f"Today's Date: {today}",
        f"Query Used: {query_used}",
        "Filtering Conditions Applied:",
        "- user_id must match the logged-in session user",
        "- Is Assigned must be True",
        "- Valid Project must be True",
        "- Project Name and Task Name must be meaningful",
        "- Activity must not be Idle",
        "- Activity must not be Unassigned Activities",
        "- Start Time date must equal today's date",
        f"Activities Returned Before Filters: {raw_count}",
    ]

    if raw_df is not None and not raw_df.empty:
        assigned_count = int(get_assigned_mask(raw_df).sum())
        valid_project_count = int(get_valid_project_mask(raw_df).sum())
        project_work_count = int(get_project_work_mask(raw_df).sum())
        unassigned_count = int(get_unassigned_mask(raw_df).sum())
        idle_count = int(get_idle_mask(raw_df).sum())
        if "Start Time" in raw_df.columns:
            start_times = pd.to_datetime(raw_df["Start Time"], errors="coerce")
            today_count = int((start_times.dt.date == today).sum())
        else:
            today_count = 0
        lines.extend([
            f"Rows With Is Assigned=True: {assigned_count}",
            f"Rows With Valid Project=True: {valid_project_count}",
            f"Rows Passing Project Work Mask: {project_work_count}",
            f"Rows Marked Unassigned: {unassigned_count}",
            f"Rows Marked Idle: {idle_count}",
            f"Rows With Start Time Date Today: {today_count}",
        ])

    lines.extend([
        f"Activities Found After Email Filters: {final_count}",
        f"Email Body Task Rows Built: {task_count}",
        "First 5 Returned Rows:",
        *_format_email_debug_rows(raw_df),
        "First 5 Rows After Email Filters:",
        *_format_email_debug_rows(filtered_df),
    ])

    if raw_count == 0:
        lines.append(
            "Why count is 0: no Activity rows were returned for the current logged-in user id."
        )
    elif final_count == 0:
        lines.append("Why email table is empty: all returned rows were removed by the email filters above.")
        if raw_df is not None and not raw_df.empty:
            if int(get_assigned_mask(raw_df).sum()) == 0:
                lines.append("- No rows have Is Assigned=True.")
            if int(get_valid_project_mask(raw_df).sum()) == 0:
                lines.append("- No rows have Valid Project=True.")
            if int(get_project_work_mask(raw_df).sum()) == 0:
                lines.append("- No rows passed the project work mask.")
            if "Start Time" in raw_df.columns:
                start_times = pd.to_datetime(raw_df["Start Time"], errors="coerce")
                if int((start_times.dt.date == today).sum()) == 0:
                    lines.append("- No rows have Start Time equal to today's date.")

    lines.append("========================================")
    _email_debug_write(lines)


def build_user_report_text(df=None):
    df = load_current_user_activity_dataframe() if df is None else filter_activity_date(ensure_activity_category(df))
    summary = build_consistent_activity_summary(df)
    total_seconds = summary["total_seconds"]
    idle_seconds = summary["idle_seconds"]
    unassigned_seconds = summary["unassigned_seconds"]
    productive_seconds = summary["productive_seconds"]
    productivity_score = summary["productivity_score"]

    lines = [
        "================ DAILY PRODUCTIVITY REPORT ================",
        f"Employee: {session.get('employee_name', 'User')}",
        f"Employee ID: {session.get('employee_id', '')}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Total Sessions: {len(df)}",
        f"Total Work Time: {format_seconds_hms(total_seconds)}",
        f"Project Work Time: {format_seconds_hms(productive_seconds)}",
        f"Unassigned Time: {format_seconds_hms(unassigned_seconds)}",
        f"Idle Time: {format_seconds_hms(idle_seconds)}",
        f"Productivity Score: {productivity_score}%",
        "",
        "Recent Activities:",
    ]

    if df.empty:
        lines.append("No activity records found for this employee.")
    else:
        recent = df.sort_values("Start Time", ascending=False).head(20)
        for _, row in recent.iterrows():
            lines.append(
                " | ".join([
                    str(row.get("Project Name", "")),
                    str(row.get("App Name", "")),
                    str(row.get("Start Time", "")),
                    format_seconds_hms(row.get("Duration", 0)),
                ])
            )

    return "\n".join(lines)


def build_review_tasks_report_text(tasks):
    total_seconds = sum(parse_review_duration(task.get("duration")) for task in tasks)
    lines = [
        "================ DAILY PRODUCTIVITY REPORT ================",
        f"Employee: {session.get('employee_name', 'User')}",
        f"Employee ID: {session.get('employee_id', '')}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Total Tasks: {len(tasks)}",
        f"Total Work Time: {format_review_duration(total_seconds)}",
        "",
        "Recent Activities:",
    ]
    if not tasks:
        lines.append("No reviewed task rows found for this employee.")
    else:
        for task in tasks:
            lines.append(
                " | ".join([
                    str(task.get("project", "")),
                    str(task.get("task", "")),
                    str(task.get("date", "")),
                    str(task.get("duration", "")),
                ])
            )
    return "\n".join(lines)


def build_review_tasks_preview_dataframe(tasks):
    rows = []
    for task in tasks:
        rows.append({
            "Activity Category": "Project Work",
            "Project Name": task.get("project", ""),
            "App Name": task.get("task", ""),
            "Start Time": task.get("date", ""),
            "Duration": parse_review_duration(task.get("duration")),
        })
    return pd.DataFrame(rows, columns=["Activity Category", "Project Name", "App Name", "Start Time", "Duration"])


def build_history_activity_report_text(df):
    total_seconds = float(df["Duration"].sum()) if not df.empty and "Duration" in df.columns else 0
    lines = [
        "================ DAILY PRODUCTIVITY REPORT ================",
        f"Employee: {session.get('employee_name', 'User')}",
        f"Employee ID: {session.get('employee_id', '')}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"Total Sessions: {len(df)}",
        f"Total Work Time: {format_seconds_hms(total_seconds)}",
        "",
        "Recent Activities:",
    ]
    if df.empty:
        lines.append("No activity records found for this employee.")
    else:
        recent = df.sort_values("Start Time", ascending=False).head(50)
        for _, row in recent.iterrows():
            lines.append(
                " | ".join([
                    str(row.get("Project Name", "")),
                    str(row.get("App Name", "")),
                    str(row.get("Start Time", "")),
                    format_seconds_hms(row.get("Duration", 0)),
                    f"email_sent={bool(row.get('Email Sent', False))}",
                ])
            )
    return "\n".join(lines)


def build_user_reports_payload():
    df = get_all_history_report_dataframe()
    latest_name = f"daily_report_user_{session.get('user_id', 'current')}.txt"
    generated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    preview_columns = ["Activity Category", "Project Name", "App Name", "Start Time", "Duration"]
    preview_df = df[preview_columns].head(10).copy() if not df.empty else pd.DataFrame(columns=preview_columns)
    if "Start Time" in preview_df.columns:
        preview_df["Start Time"] = preview_df["Start Time"].astype(str)

    return {
        "reports": [
            {
                "filename": latest_name,
                "path": "",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "gen_time": generated_time,
                "type": "Text Report",
                "size": f"{len(build_history_activity_report_text(df).encode('utf-8'))} B",
                "raw_size": len(build_history_activity_report_text(df).encode("utf-8")),
                "raw_mtime": datetime.now().timestamp(),
            }
        ] if not df.empty else [],
        "stats": {
            "total_reports": 1 if not df.empty else 0,
            "unique_days": int(df["Start Time"].dt.date.nunique()) if not df.empty and "Start Time" in df.columns else 0,
            "last_generated_time": generated_time if not df.empty else "N/A",
            "status": "Active" if not df.empty else "No Reports",
        },
        "latest": {
            "filename": latest_name if not df.empty else "N/A",
            "date": datetime.now().strftime("%Y-%m-%d") if not df.empty else "N/A",
            "size": f"{len(build_history_activity_report_text(df).encode('utf-8'))} B" if not df.empty else "N/A",
            "type": "Text Report" if not df.empty else "N/A",
            "text_preview": build_history_activity_report_text(df),
            "excel_preview": preview_df.fillna("").to_dict(orient="records"),
        },
    }

@app.route('/email-verification')
@app.route('/email_verification')
def email_verification():
    return render_template('email_verification.html')


def build_csv_summary_rows():
    """Aggregate only manually assigned records for the main email review table."""
    df = get_assigned_report_dataframe()
    totals = {}

    if df.empty or "Duration" not in df.columns:
        return []

    assigned_df = df.loc[get_project_work_mask(df)].copy()
    if assigned_df.empty:
        return []

    for _, row in assigned_df.iterrows():
        project = normalize_required_text(row.get("Project Name", "") or row.get("Project", ""))
        task = normalize_required_text(row.get("AI Task Name", "") or row.get("File Name", "") or row.get("App Name", ""))
        if not is_meaningful_project_and_task(project, task) or is_ignored_task_file(task):
            log_skipped_invalid_row(row)
            continue
        totals[(project, task)] = totals.get((project, task), 0) + int(row.get("Duration", 0) or 0)

    return [
        (f"{project} / {task}", format_review_duration(seconds))
        for (project, task), seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        if seconds > 0
    ]


def build_default_email_tasks():
    """Create editable review rows from the current CSV aggregation."""
    today = datetime.now().strftime("%d-%m-%Y")
    tasks = []
    ai_cache = load_ai_cache()

    for label, duration in build_csv_summary_rows():
        if " / " in label:
            project, task = label.split(" / ", 1)
        else:
            project, task = get_default_project_name(), label

        project = normalize_required_text(project)
        task = normalize_required_text(task)

        if not is_meaningful_project_and_task(project, task) or is_ignored_task_file(task):
            print("Skipped invalid row:", {"project": project, "file_name": task, "duration": duration})
            continue

        ai_task_name = get_ai_task_name(project, task, ai_cache)
        tasks.append({
            "date": today,
            "project": project,
            "task": ai_task_name or task,
            "source_task": task,
            "status": "In Progress",
            "duration": duration,
        })

    return tasks


def build_default_unassigned_activities():
    """Collect all unassigned non-idle activities for manual review."""
    df = load_current_user_activity_dataframe()
    totals = {}

    if df.empty or "Duration" not in df.columns:
        return []

    review_df = df.loc[get_unassigned_mask(df)].copy()
    if not review_df.empty and "Start Time" in review_df.columns:
        start_times = pd.to_datetime(review_df["Start Time"], errors="coerce")
        today = datetime.now().date()
        review_df = review_df.loc[start_times.dt.date == today].copy()
    for _, row in review_df.iterrows():
        project = normalize_required_text(row.get("Project Name", "") or row.get("Project", ""))
        task = normalize_required_text(row.get("AI Task Name", "") or row.get("File Name", "") or row.get("App Name", ""))
        app = task or project or "Unknown Window"
        if not app:
            continue
        key = (project, task, app)
        item = totals.setdefault(
            key,
            {
                "app": app,
                "project": project,
                "task": task,
                "duration_seconds": 0,
                "activity_ids": [],
            },
        )
        item["duration_seconds"] += int(row.get("Duration", 0) or 0)
        activity_id = row.get("Activity ID")
        if activity_id not in ("", None):
            try:
                item["activity_ids"].append(int(activity_id))
            except (TypeError, ValueError):
                pass

    return [
        {
            "app": item["app"],
            "project": item["project"],
            "task": item["task"],
            "duration": format_review_duration(item["duration_seconds"]),
            "activity_ids": sorted(set(item["activity_ids"])),
        }
        for item in sorted(totals.values(), key=lambda value: (value["project"].lower(), value["app"].lower()))
        if item["duration_seconds"] > 0
    ]


def normalize_email_tasks(raw_tasks):
    """Keep email-review rows clean and absorb Chrome/Edge into the prior task."""
    normalized = []
    for item in raw_tasks if isinstance(raw_tasks, list) else []:
        status = normalize_required_text(item.get("status", "In Progress")) or "In Progress"
        if status not in {"Completed", "In Progress"}:
            status = "In Progress"

        date = normalize_required_text(item.get("date", ""))
        task = normalize_required_text(item.get("task", ""))
        project = normalize_review_project_name(item.get("project", ""), task)
        source_task = normalize_required_text(item.get("source_task") or task)
        duration = normalize_required_text(item.get("duration", ""))

        if not all([date, project, task, source_task, duration]):
            print("Skipped invalid row:", item)
            continue
        if is_ignored_task_file(task) or is_ignored_task_file(source_task):
            continue

        if is_auto_merge_activity(task):
            if normalized:
                normalized[-1]["duration"] = format_review_duration(
                    parse_review_duration(normalized[-1].get("duration"))
                    + parse_review_duration(duration)
                )
            continue
        if not is_meaningful_project_and_task(project, source_task):
            print("Skipped invalid row:", item)
            continue

        normalized.append({
            "date": date,
            "project": project,
            "task": task,
            "source_task": source_task,
            "status": status,
            "duration": duration,
        })

    return normalized


def sanitize_saved_tasks(raw_tasks):
    if not isinstance(raw_tasks, list):
        return []

    email_tasks = normalize_email_tasks(raw_tasks)
    if email_tasks:
        return email_tasks

    sanitized = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            continue
        task = normalize_required_text(item.get("task", ""))
        if not task or is_ignored_task_file(task) or is_auto_merge_activity(task):
            continue
        sanitized.append(item)
    return sanitized


def normalize_unassigned_activities(raw_items):
    normalized = []
    for item in raw_items if isinstance(raw_items, list) else []:
        app = normalize_required_text(item.get("app", ""))
        project = normalize_required_text(item.get("project", ""))
        task = normalize_required_text(item.get("task", ""))
        if not app:
            app = task or project or "Unknown Window"
        duration = str(item.get("duration", "")).strip()
        if not app or not duration:
            continue
        activity_ids = []
        for activity_id in item.get("activity_ids", []) if isinstance(item.get("activity_ids", []), list) else []:
            try:
                activity_ids.append(int(activity_id))
            except (TypeError, ValueError):
                pass
        normalized.append({
            "app": app,
            "project": project,
            "task": task,
            "duration": duration,
            "activity_ids": sorted(set(activity_ids)),
        })
    return normalized


def normalize_activity_merges(raw_merges):
    normalized = []
    seen = set()
    for item in raw_merges if isinstance(raw_merges, list) else []:
        app = normalize_required_text(item.get("app", ""))
        target_task = normalize_required_text(item.get("target_task", ""))
        if not app or not target_task or is_ignored_task_file(target_task):
            continue
        key = (app.lower(), target_task.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"app": app, "target_task": target_task})
    return normalized


def apply_saved_review_state(tasks, unassigned, saved_data):
    saved_tasks = normalize_email_tasks(saved_data.get("tasks", []))
    saved_by_identity = {task_identity(task): task for task in saved_tasks}

    for task in tasks:
        saved = saved_by_identity.get(task_identity(task))
        if not saved:
            continue
        task["date"] = saved.get("date") or task["date"]
        saved_task_name = normalize_required_text(saved.get("task", ""))
        saved_source_name = normalize_required_text(saved.get("source_task", ""))
        if saved_task_name and saved_task_name != saved_source_name:
            task["task"] = saved_task_name
        task["status"] = saved.get("status") or task["status"]

    activity_merges = normalize_activity_merges(saved_data.get("activity_merges", []))
    return tasks, unassigned, activity_merges


def build_email_review_rows(saved_data=None):
    debug_email_review_flow(
        "build_email_review_rows enter",
        tasks=saved_data.get("tasks", []) if isinstance(saved_data, dict) else [],
        unassigned=saved_data.get("unassigned", []) if isinstance(saved_data, dict) else [],
        extra={"has_saved_data": bool(saved_data)},
    )
    tasks = normalize_email_tasks(build_default_email_tasks())
    unassigned = normalize_unassigned_activities(build_default_unassigned_activities())
    debug_email_review_flow(
        "build_email_review_rows generated defaults",
        tasks=tasks,
        unassigned=unassigned,
    )
    if saved_data:
        saved_tasks = normalize_email_tasks(saved_data.get("tasks", []))
        if saved_tasks:
            saved_unassigned = normalize_unassigned_activities(saved_data.get("unassigned", []))
            debug_email_review_flow(
                "build_email_review_rows returning saved rows",
                tasks=saved_tasks,
                unassigned=saved_unassigned,
            )
            return sort_review_tasks_by_project(saved_tasks), saved_unassigned
        tasks, unassigned, _ = apply_saved_review_state(tasks, unassigned, saved_data)
        debug_email_review_flow(
            "build_email_review_rows applied saved state",
            tasks=tasks,
            unassigned=unassigned,
        )
    sorted_tasks = sort_review_tasks_by_project(tasks)
    debug_email_review_flow(
        "build_email_review_rows return",
        tasks=sorted_tasks,
        unassigned=unassigned,
    )
    return sorted_tasks, unassigned


def debug_email_task_rows(tasks, source):
    lines = [
        "",
        "========== EMAIL ROW SOURCE DEBUG ==========",
        f"Source: {source}",
        f"Rows for email = {len(tasks or [])}",
    ]
    for index, task in enumerate(tasks or [], start=1):
        lines.append(
            f"{index}. Project={task.get('project', '')} | "
            f"Task={task.get('task', '')} | "
            f"Duration={task.get('duration', '')}"
        )
    lines.append("============================================")
    _email_debug_write(lines)


def build_user_email_body(employee_name=None, tasks_override=None, source="saved review rows"):
    raw_df = load_current_user_activity_dataframe()
    filtered_df = get_assigned_report_dataframe(raw_df)
    if tasks_override is not None:
        tasks = normalize_email_tasks(tasks_override)
    else:
        tasks, _ = build_email_review_rows(load_tasks_data())
    debug_email_report_inputs(raw_df, filtered_df, tasks)
    debug_email_task_rows(tasks, source)
    table_rows = [
        "<tr>"
        "<th>Date</th><th>Project</th><th>AI Task Name</th><th>Status</th><th>Duration</th>"
        "</tr>"
    ]
    for task in tasks:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(str(task.get('date', '')))}</td>"
            f"<td>{html.escape(str(task.get('project', '')))}</td>"
            f"<td>{html.escape(str(task.get('task', '')))}</td>"
            f"<td>{html.escape(str(task.get('status', '')))}</td>"
            f"<td>{html.escape(str(task.get('duration', '')))}</td>"
            "</tr>"
        )

    table = (
        "<table border='1' cellspacing='0' cellpadding='6' "
        "style='border-collapse:collapse;width:90%;'>"
        f"{''.join(table_rows)}"
        "</table>"
    )
    safe_name = html.escape(str(employee_name or session.get("employee_name") or "User"))
    return f"""<html>
<body>
<p>Hello Manager,</p>
<p>Please find below my productivity report for today.</p>
<p>The report summarizes the activities completed, associated projects, task assignments, statuses, and durations recorded during today's work session.</p>
{table}
<p>Regards,</p>
<p>{safe_name}</p>
</body>
</html>"""


def mark_current_user_today_activities_emailed():
    user_id = get_session_user_id()
    if not user_id:
        return 0

    now = datetime.now()
    today_start = datetime.combine(now.date(), datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)

    with get_db_session() as db_session:
        activities = (
            db_session.query(Activity)
            .filter(
                Activity.user_id == int(user_id),
                Activity.email_sent.is_(False),
                Activity.start_time >= today_start,
                Activity.start_time < tomorrow_start,
            )
            .all()
        )
        for activity in activities:
            activity.email_sent = True
            activity.sent_at = now
        db_session.commit()
        return len(activities)


def get_existing_review_project(db_session, user_id, project_name):
    if not is_valid_project_label(project_name):
        return None
    target_key = normalize_validation_label(project_name)
    projects = (
        db_session.query(Project)
        .filter(Project.user_id == int(user_id))
        .all()
    )
    for project in projects:
        if is_valid_project_label(project.project_name) and normalize_validation_label(project.project_name) == target_key:
            return project
    return None


def get_or_create_review_task(db_session, user_id, project_id, task_name, status="In Progress"):
    task = (
        db_session.query(Task)
        .filter(
            Task.user_id == int(user_id),
            Task.project_id == int(project_id),
            Task.task_name == task_name,
        )
        .first()
    )
    if task:
        task.status = status or task.status
        return task
    task = Task(
        user_id=int(user_id),
        project_id=int(project_id),
        task_name=task_name,
        status=status,
        duration=0,
    )
    db_session.add(task)
    db_session.flush()
    return task


def merge_activity_ids_into_task(activity_ids, target_project, target_task, status="In Progress"):
    user_id = get_session_user_id()
    debug_email_review_flow(
        "merge_activity_ids_into_task enter",
        target_task=target_task,
        activity_ids=activity_ids,
        extra={"target_project": target_project, "status": status},
    )
    if not user_id:
        raise ValueError("Login required.")
    if not activity_ids:
        raise ValueError("No activity IDs were selected.")
    if not is_meaningful_project_and_task(target_project, target_task):
        raise ValueError("Select a meaningful project and task target.")

    updated = 0
    with get_db_session() as db_session:
        activities = (
            db_session.query(Activity)
            .filter(Activity.user_id == int(user_id), Activity.id.in_(activity_ids))
            .all()
        )
        debug_email_review_flow(
            "merge_activity_ids_into_task selected activities",
            target_task=target_task,
            activity_ids=[activity.id for activity in activities],
            extra={
                "activity_count": len(activities),
                "durations": [int(activity.duration or 0) for activity in activities],
            },
        )
        project = get_existing_review_project(db_session, user_id, target_project)
        if not project:
            raise ValueError("Target project does not exist in the projects table.")
        target_project = project.project_name
        task = get_or_create_review_task(db_session, user_id, project.id, target_task, status)
        task.duration = int(task.duration or 0)
        debug_email_review_flow(
            "merge_activity_ids_into_task target before update",
            target_task=f"{task.id}:{task.task_name}",
            activity_ids=activity_ids,
            extra={
                "project_id": project.id,
                "project_name": target_project,
                "task_duration_before": task.duration,
            },
        )

        for activity in activities:
            if bool(getattr(activity, "is_assigned", False)):
                debug_email_review_flow(
                    "merge_activity_ids_into_task skip assigned activity",
                    target_task=f"{task.id}:{task.task_name}",
                    activity_ids=[activity.id],
                    extra={"activity_duration": int(activity.duration or 0)},
                )
                continue
            duration = int(activity.duration or 0)
            before_duration = task.duration
            activity.project_name = target_project
            activity.file_name = target_task
            activity.ai_task_name = target_task
            activity.status = status
            activity.is_assigned = True
            task.duration += duration
            debug_email_review_flow(
                "merge_activity_ids_into_task added activity",
                target_task=f"{task.id}:{task.task_name}",
                activity_ids=[activity.id],
                extra={
                    "activity_duration": duration,
                    "task_duration_before": before_duration,
                    "task_duration_after": task.duration,
                },
            )
            updated += 1

        debug_email_review_flow(
            "merge_activity_ids_into_task before commit",
            target_task=f"{task.id}:{task.task_name}",
            activity_ids=activity_ids,
            extra={"updated_count": updated, "task_duration_before_commit": task.duration},
        )
        db_session.commit()
        debug_email_review_flow(
            "merge_activity_ids_into_task after commit",
            target_task=f"{task.id}:{task.task_name}",
            activity_ids=activity_ids,
            extra={"updated_count": updated, "task_duration_after_commit": task.duration},
        )

    return updated


@app.route('/api/email-tasks')
def api_email_tasks():
    try:
        use_saved = request.args.get("saved") == "1" and request.args.get("fresh") != "1"
        debug_email_review_flow(
            "api_email_tasks enter",
            extra={
                "use_saved": use_saved,
                "fresh": request.args.get("fresh"),
                "saved": request.args.get("saved"),
            },
        )
        saved_data = load_tasks_data() if use_saved else empty_review_data()
        tasks, unassigned = build_email_review_rows(saved_data if use_saved else None)
        debug_email_review_flow(
            "api_email_tasks return",
            tasks=tasks,
            unassigned=unassigned,
            extra={"use_saved": use_saved},
        )
        return jsonify({"success": True, "tasks": tasks, "unassigned": unassigned})
    except Exception as e:
        print("EMAIL TASKS ERROR:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/save-tasks', methods=['POST'])
def api_save_tasks():
    try:
        data = request.get_json(silent=True) or {}
        saved_data = load_tasks_data()
        tasks = normalize_email_tasks(data.get("tasks", []))
        unassigned = normalize_unassigned_activities(data.get("unassigned", []))
        debug_email_review_flow(
            "api_save_tasks request",
            tasks=tasks,
            unassigned=unassigned,
        )
        activity_merges = normalize_activity_merges(
            data.get("activity_merges", saved_data.get("activity_merges", []))
        )
        tasks = sort_review_tasks_by_project(tasks)
        debug_email_review_flow(
            "api_save_tasks before save_tasks_data",
            tasks=tasks,
            unassigned=unassigned,
            extra={"activity_merges": len(activity_merges)},
        )
        save_tasks_data(tasks, unassigned, activity_merges)
        debug_email_review_flow(
            "api_save_tasks response",
            tasks=tasks,
            unassigned=unassigned,
            extra={"activity_merges": len(activity_merges)},
        )
        return jsonify({"success": True, "tasks": tasks, "unassigned": unassigned})
    except Exception as e:
        print("SAVE TASKS ERROR:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/merge-unassigned', methods=['POST'])
def api_merge_unassigned():
    try:
        data = request.get_json(silent=True) or {}
        tasks = normalize_email_tasks(data.get("tasks", []))
        unassigned = normalize_unassigned_activities(data.get("unassigned", []))
        debug_email_review_flow(
            "api_merge_unassigned request",
            tasks=tasks,
            unassigned=unassigned,
            target_task=data.get("target_task", ""),
            activity_ids=data.get("activity_ids", []),
            extra={
                "selected_indexes": data.get("selected_indexes", []),
                "target_project": data.get("target_project", ""),
            },
        )
        selected_indexes = set()
        for index in data.get("selected_indexes", []) if isinstance(data.get("selected_indexes", []), list) else []:
            try:
                selected_indexes.add(int(index))
            except (TypeError, ValueError):
                pass
        target_task = normalize_required_text(data.get("target_task", ""))
        target_project = normalize_required_text(data.get("target_project", ""))

        if "|||" in target_task:
            target_project, target_task = [
                normalize_required_text(part)
                for part in target_task.split("|||", 1)
            ]

        selected_items = [
            item for index, item in enumerate(unassigned)
            if index in selected_indexes
        ]

        activity_ids = []
        for activity_id in data.get("activity_ids", []) if isinstance(data.get("activity_ids", []), list) else []:
            try:
                activity_ids.append(int(activity_id))
            except (TypeError, ValueError):
                pass
        for item in selected_items:
            activity_ids.extend(item.get("activity_ids", []))
        parsed_activity_ids = []
        for activity_id in activity_ids:
            try:
                parsed_activity_ids.append(int(activity_id))
            except (TypeError, ValueError):
                pass
        activity_ids = sorted(set(parsed_activity_ids))
        debug_email_review_flow(
            "api_merge_unassigned parsed selection",
            tasks=tasks,
            unassigned=unassigned,
            target_task=target_task,
            activity_ids=activity_ids,
            extra={
                "selected_indexes": sorted(selected_indexes),
                "selected_items": len(selected_items),
                "target_project": target_project,
            },
        )

        if not selected_indexes and not activity_ids:
            return jsonify({"success": False, "error": "Select at least one activity."}), 400
        if not target_task:
            return jsonify({"success": False, "error": "Select a target task."}), 400

        target = find_task_by_name(tasks, target_task)
        if target is not None and not target_project:
            target_project = normalize_required_text(target.get("project", ""))
        debug_email_review_flow(
            "api_merge_unassigned target resolved",
            tasks=tasks,
            unassigned=unassigned,
            target_task=target_task,
            activity_ids=activity_ids,
            extra={
                "target_found": target is not None,
                "target_project": target_project,
                "target_row_duration": target.get("duration") if target else None,
            },
        )

        if not target_project and selected_items:
            candidate = selected_items[0]
            target_project = normalize_required_text(candidate.get("project", ""))
            target_task = normalize_required_text(candidate.get("task", "") or candidate.get("app", ""))

        if not is_meaningful_project_and_task(target_project, target_task):
            return jsonify({"success": False, "error": "Target task was not found."}), 400

        updated_count = merge_activity_ids_into_task(
            activity_ids,
            target_project,
            target_task,
            target.get("status", "In Progress") if target else "In Progress",
        )
        debug_email_review_flow(
            "api_merge_unassigned after db merge",
            tasks=tasks,
            unassigned=unassigned,
            target_task=target_task,
            activity_ids=activity_ids,
            extra={"updated_count": updated_count},
        )
        if updated_count <= 0:
            return jsonify({"success": False, "error": "No unassigned database records were updated."}), 400

        regenerated_tasks, regenerated_remaining = build_email_review_rows()
        debug_email_review_flow(
            "api_merge_unassigned regenerated rows",
            tasks=regenerated_tasks,
            unassigned=regenerated_remaining,
            target_task=target_task,
            activity_ids=activity_ids,
        )
        response_tasks = regenerated_tasks if regenerated_tasks else tasks
        response_unassigned = regenerated_remaining
        if not regenerated_tasks:
            selected_activity_ids = set(activity_ids)
            response_unassigned = [
                item for item in unassigned
                if not selected_activity_ids.intersection(
                    {
                        int(activity_id)
                        for activity_id in item.get("activity_ids", [])
                        if str(activity_id).isdigit()
                    }
                )
            ]
        debug_email_review_flow(
            "api_merge_unassigned before save_tasks_data",
            tasks=response_tasks,
            unassigned=response_unassigned,
            target_task=target_task,
            activity_ids=activity_ids,
            extra={"used_regenerated_tasks": bool(regenerated_tasks)},
        )
        save_tasks_data(response_tasks, response_unassigned, [])
        debug_email_review_flow(
            "api_merge_unassigned response",
            tasks=response_tasks,
            unassigned=response_unassigned,
            target_task=target_task,
            activity_ids=activity_ids,
        )
        return jsonify({"success": True, "tasks": response_tasks, "unassigned": response_unassigned})
    except Exception as e:
        print("MERGE UNASSIGNED ERROR:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/email-data')
def api_email_data():
    df = load_current_user_activity_dataframe()
    summary = build_consistent_activity_summary(df)
    
    total_apps = int(df['App Name'].nunique()) if not df.empty else 0
    total_projects = int(df['Project Name'].nunique()) if not df.empty else 0
    total_work_seconds = summary["total_seconds"]
    
    hours = int(total_work_seconds // 3600)
    minutes = int((total_work_seconds % 3600) // 60)
    seconds = int(total_work_seconds % 60)
    total_work_duration = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    # Read email status
    status_file = 'email_status.json'
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as sf:
                last_status_data = json.load(sf)
        except Exception:
            last_status_data = {
                "last_status": "never",
                "last_run": "Never",
                "error_message": None
            }
    else:
        last_status_data = {
            "last_status": "never",
            "last_run": "Never",
            "error_message": None
        }

    if df.empty:
        work_timesheet = []
        system_activity = []
    else:
        idle_mask = get_idle_mask(df)
        app_totals = df.groupby('App Name')['Duration'].sum().sort_values(ascending=False)
        work_timesheet = [
            {'Application Name': str(app), 'Duration': format_seconds_hms(seconds)}
            for app, seconds in app_totals.items()
        ]
        system_activity = [
            {
                'Application Name': str(row.get('App Name', '')),
                'Duration': format_seconds_hms(row.get('Duration', 0)),
            }
            for _, row in df.loc[idle_mask].iterrows()
        ]

    return jsonify({
        "summary": {
            "total_applications": total_apps,
            "total_projects": total_projects,
            "total_work_duration": total_work_duration,
            "last_status": last_status_data.get("last_status", "never"),
            "last_run": last_status_data.get("last_run", "Never"),
            "error_message": last_status_data.get("error_message")
        },
        "work_timesheet": work_timesheet,
        "system_activity": system_activity
    })

@app.route('/api/email-content')
def api_email_content():
    """Return the auto-generated subject and body so the frontend can load them into the editor."""
    try:
        employee_name = str(g.current_user.employee_name or "User").strip() or "User"
        report_date = datetime.now().strftime("%d-%m-%Y")
        subject = _repair_mojibake(f"{employee_name} - Daily Productivity Report - {report_date}")
        body = _repair_mojibake(build_user_email_body(employee_name=g.current_user.employee_name))
        return jsonify({"success": True, "subject": subject, "body": body})
    except Exception as e:
        print("EMAIL CONTENT ERROR:", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/send-email', methods=['POST'])
def trigger_send_email():
    print("================ DEBUG INFO ================")
    print("CWD:", os.getcwd())
    print("activity_log.csv exists:", os.path.exists("activity_log.csv"))
    print("============================================")

    try:
        # Accept JSON or form data
        data = request.get_json(silent=True) or {}
        employee_name = str(g.current_user.employee_name or "User").strip() or "User"
        report_date = datetime.now().strftime("%d-%m-%Y")
        custom_subject = f"{employee_name} - Daily Productivity Report - {report_date}"
        request_tasks = normalize_email_tasks(data.get("tasks", []))
        email_tasks = request_tasks
        email_source = "Email Verification visible table"
        if not email_tasks:
            email_tasks, _ = build_email_review_rows(load_tasks_data())
            email_source = "saved review rows fallback"
        custom_body = build_user_email_body(
            employee_name=g.current_user.employee_name,
            tasks_override=email_tasks,
            source=email_source,
        )

        if not g.current_user.manager_email:
            return jsonify({"success": False, "error_message": "Manager email is missing for this employee."}), 400

        from email_sender import send_email
        success = send_email(
            subject=custom_subject,
            body=custom_body,
            employee_name=g.current_user.employee_name,
            receiver_email=g.current_user.manager_email,
        )
        if success:
            archived_count = mark_current_user_today_activities_emailed() if email_tasks else 0
            debug_email_review_flow(
                "trigger_send_email before clearing saved review data",
                tasks=[],
                unassigned=[],
                extra={"archived_count": archived_count},
            )
            save_tasks_data([], [], [])
            debug_email_review_flow(
                "trigger_send_email after clearing saved review data",
                tasks=[],
                unassigned=[],
                extra={"archived_count": archived_count},
            )
            print(f"POST EMAIL ARCHIVE: archived {archived_count} activities for user {get_session_user_id()}")
            return jsonify({"success": True, "message": "Email Sent Successfully"})
        else:
            error_message = "Unknown error occurred"
            if os.path.exists("email_status.json"):
                try:
                    with open("email_status.json", "r", encoding="utf-8") as sf:
                        status_data = json.load(sf)
                        error_message = status_data.get("error_message") or error_message
                except Exception:
                    pass
            return jsonify({"success": False, "error_message": error_message})
    except Exception as e:
        print("EMAIL ERROR:", str(e))
        return jsonify({"success": False, "error_message": str(e)})


@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/download/excel')
def download_excel():
    df = get_all_history_report_dataframe()
    output = io.BytesIO()
    df.to_excel(output, index=False, engine='openpyxl')
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"daily_report_user_{session.get('user_id')}.xlsx",
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

@app.route('/download/text')
def download_text():
    report_text = build_history_activity_report_text(get_all_history_report_dataframe())
    return send_file(
        io.BytesIO(report_text.encode('utf-8')),
        as_attachment=True,
        download_name=f"daily_report_user_{session.get('user_id')}.txt",
        mimetype='text/plain',
    )

@app.route('/download/activity-log')
def download_activity_log():
    csv_data = get_all_history_report_dataframe().to_csv(index=False)
    return send_file(
        io.BytesIO(csv_data.encode('utf-8-sig')),
        as_attachment=True,
        download_name=f"activity_log_user_{session.get('user_id')}.csv",
        mimetype='text/csv; charset=utf-8',
    )

@app.route('/download/app-usage')
def download_app_usage():
    df = get_all_history_report_dataframe()
    if df.empty:
        usage_df = pd.DataFrame(columns=["App Name", "Duration"])
    else:
        usage_df = df.groupby("App Name", as_index=False)["Duration"].sum().sort_values("Duration", ascending=False)
    return send_file(
        io.BytesIO(usage_df.to_csv(index=False).encode('utf-8-sig')),
        as_attachment=True,
        download_name=f"application_work_duration_user_{session.get('user_id')}.csv",
        mimetype='text/csv; charset=utf-8',
    )

@app.route('/api/generate-report', methods=['POST'])
def api_generate_report():
    try:
        df = get_all_history_report_dataframe()
        return jsonify({
            'success': True,
            'message': 'Report Generated Successfully',
            'summary': get_current_report_data().get('summary'),
            'record_count': int(len(df)),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports-list')
def api_reports_list():
    try:
        return jsonify(build_user_reports_payload())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports-data')
def api_reports_data():
    df = get_all_history_report_dataframe()
    if df.empty:
        return jsonify({'error': 'No data found'})

    def fmt(s):
        h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    total_sessions = len(df)
    project_work_mask = get_project_work_mask(df)
    unassigned_mask = get_unassigned_mask(df)
    idle_mask = get_idle_mask(df)
    summary = build_consistent_activity_summary(df)
    productive_sessions = summary["productive_sessions"]
    unassigned_sessions = summary["unassigned_sessions"]
    idle_sessions = summary["idle_sessions"]
    total_secs = summary["total_seconds"]
    prod_secs = summary["productive_seconds"]
    unassigned_secs = summary["unassigned_seconds"]
    idle_secs = summary["idle_seconds"]
    score = summary["productivity_score"]

    # Daily productivity
    df['Date'] = df['Start Time'].dt.date.astype(str)
    daily = df.groupby('Date').agg(
        total_seconds=('Duration', 'sum'),
        session_count=('App Name', 'count')
    ).reset_index()
    daily_report = [{'date': str(r['Date']), 'hours': round(float(r['total_seconds']) / 3600, 2), 'sessions': int(r['session_count'])} for _, r in daily.iterrows()]

    # Project summary
    proj_group = df.groupby('Project Name').agg(
        total_seconds=('Duration', 'sum'),
        session_count=('App Name', 'count')
    ).reset_index().sort_values('total_seconds', ascending=False)
    project_report = [{
        'project': r['Project Name'],
        'duration': fmt(r['total_seconds']),
        'seconds': float(r['total_seconds']),
        'sessions': int(r['session_count']),
        'percentage': round((float(r['total_seconds']) / total_secs) * 100, 2) if total_secs else 0
    } for _, r in proj_group.iterrows()]

    # Top apps summary
    app_group = df.groupby('App Name')['Duration'].sum().reset_index().sort_values('Duration', ascending=False).head(15)
    app_report = [{
        'app': r['App Name'],
        'duration': fmt(r['Duration']),
        'seconds': float(r['Duration']),
        'percentage': round((float(r['Duration']) / total_secs) * 100, 2) if total_secs else 0
    } for _, r in app_group.iterrows()]

    return jsonify({
        'summary': {
            'total_sessions': total_sessions,
            'productive_sessions': productive_sessions,
            'unassigned_sessions': unassigned_sessions,
            'idle_sessions': idle_sessions,
            'total_duration': fmt(total_secs),
            'productive_duration': fmt(prod_secs),
            'unassigned_duration': fmt(unassigned_secs),
            'idle_duration': fmt(idle_secs),
            'productivity_score': score,
            'date_range': {'start': daily_report[0]['date'] if daily_report else 'N/A', 'end': daily_report[-1]['date'] if daily_report else 'N/A'}
        },
        'daily': daily_report,
        'projects': project_report,
        'apps': app_report
    })
def parse_datetime(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    clean_val = val.rstrip("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(clean_val, fmt)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    return None


@app.route("/api/tracker/login", methods=["POST"])
def api_tracker_login():
    try:
        data = request.get_json(silent=True) or {}
        login_email = normalize_login_email(data.get("login_email", ""))
        password = str(data.get("password", ""))

        if not login_email or not password:
            return jsonify({"success": False, "error": "Login email and password are required."}), 400

        with get_db_session() as db_session:
            user = (
                db_session.query(User)
                .filter(User.login_email == login_email)
                .first()
            )

            if not user:
                return jsonify({"success": False, "error": "Invalid email."}), 401

            if not verify_password(password, user.password_hash):
                return jsonify({"success": False, "error": "Invalid password."}), 401

            if str(user.role or "").strip().lower() != "employee":
                return jsonify({"success": False, "error": "Access restricted to employees."}), 403

            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            session["user_name"] = user.employee_name
            session["employee_id"] = user.employee_id
            session["employee_name"] = user.employee_name
            session["login_email"] = user.login_email
            session["role"] = user.role
            
            # Sync active tracker user info locally
            sync_active_tracker_user(user, reason="api_login")

            log_auth_flow(
                f"API Tracker Login success: user_id={user.id}, employee_id={user.employee_id}, "
                f"email={user.login_email}, role={user.role}."
            )

            return jsonify({
                "success": True,
                "user": {
                    "id": user.id,
                    "employee_name": user.employee_name,
                    "employee_id": user.employee_id,
                    "login_email": user.login_email,
                    "role": user.role
                }
            })
    except Exception as error:
        print("API Tracker Login failed:", error)
        return jsonify({"success": False, "error": "Server error during login."}), 500


@app.route("/api/tracker/activity", methods=["POST"])
@login_required
def api_tracker_activity():
    try:
        # Enforce that logged in user is an employee
        if str(g.current_user.role or "").strip().lower() != "employee":
            return jsonify({"success": False, "error": "Access restricted to employees."}), 403

        data = request.get_json(silent=True) or {}
        project_name = data.get("project_name")
        window_title = data.get("window_title")
        file_name = data.get("file_name", "")
        start_time_str = data.get("start_time")
        end_time_str = data.get("end_time")
        duration_val = data.get("duration")

        if not project_name or not window_title:
            return jsonify({"success": False, "error": "project_name and window_title are required."}), 400

        start_time = parse_datetime(start_time_str)
        end_time = parse_datetime(end_time_str)

        if not start_time or not end_time:
            return jsonify({"success": False, "error": "Invalid start_time or end_time format."}), 400

        if duration_val is not None:
            try:
                duration = timedelta(seconds=float(duration_val))
            except (ValueError, TypeError):
                duration = end_time - start_time
        else:
            duration = end_time - start_time

        db_saved = save_tracked_activity(
            project_name=project_name,
            window_title=window_title,
            file_name=file_name,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            user_id=g.current_user.id
        )

        return jsonify({"success": True, "saved": db_saved})

    except Exception as error:
        print("API Tracker Activity save failed:", error)
        return jsonify({"success": False, "error": "Server error during activity save."}), 500


@app.route("/api/tracker/heartbeat", methods=["POST"])
@login_required
def api_tracker_heartbeat():
    try:
        # Enforce that logged in user is an employee
        if str(g.current_user.role or "").strip().lower() != "employee":
            return jsonify({"success": False, "error": "Access restricted to employees."}), 403

        data = request.get_json(silent=True) or {}
        client_status = data.get("status", "active")
        client_version = data.get("version", "unknown")

        print(f"Tracker heartbeat received: user_id={g.current_user.id}, status={client_status}, version={client_version}")

        return jsonify({
            "success": True,
            "status": "active",
            "server_time": datetime.utcnow().isoformat()
        })
    except Exception as error:
        print("API Tracker Heartbeat failed:", error)
        return jsonify({"success": False, "error": "Server error during heartbeat."}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0', use_reloader=False)















