import json
import os
import re
import traceback
import uuid
from datetime import datetime, timedelta

import pandas as pd

import database
from database import Activity, Project, Task, User, get_db_session


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACTIVE_TRACKER_USER_FILE = os.path.join(BASE_DIR, "active_tracker_user.json")
TRACKER_DB_LOG_FILE = os.path.join(BASE_DIR, "tracker_activity_db.log")
_DATABASE_IMPORT_LOGGED = False
MAX_RECORDED_IDLE_SECONDS = 5 * 60

ACTIVITY_COLUMNS = [
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
    "Email Sent",
    "Sent At",
    "Start Time",
    "End Time",
    "Duration",
]

UNASSIGNED_ACTIVITY_KEYWORDS = {
    "snipping tool overlay",
    "snipping tool",
    "task switching",
    "file explorer",
    "windows explorer",
    "settings",
    "calculator",
    "program manager",
    "default ime",
    "lock screen",
    "windows default lock screen",
    "start menu",
    "search",
    "notification center",
    "action center",
    "desktop",
    "windows shell",
    "system tray overflow window",
    "unknown window",
    "unknown task",
    "unknown activity",
    "empty title",
    "none",
    "null",
}

GENERATED_TASK_SUFFIXES = (
    " enhancement",
    " optimization",
    " improvement",
    " development",
    " task",
)

PROCESSED_TASK_RULES = [
    (
        ("overview dashboard", "live dashboard", "dashboard development"),
        "Dashboard Development",
    ),
    (
        ("email verification", "email_verification"),
        "Email Verification Module",
    ),
    (
        ("email sender", "email_sender", "outlook", "inbox", "gmail"),
        "Email Automation Module",
    ),
    (
        ("task scheduler auto start", "auto start", "autostart", "startup"),
        "Auto Start Feature",
    ),
]

PROCESSED_TASK_NAMES = {task_name for _, task_name in PROCESSED_TASK_RULES}
GENERIC_BROWSER_PROJECTS = {
    "browser work",
    "chrome work",
    "edge work",
    "unknown project",
}

CANONICAL_ACTIVITY_NAMES = {
    "calculator": "Calculator",
    "file explorer": "File Explorer",
    "settings": "Settings",
    "snipping tool": "Snipping Tool",
    "snipping tool overlay": "Snipping Tool Overlay",
    "system idle": "System Idle",
    "system tray overflow window": "System Tray Overflow Window",
    "task switching": "Task Switching",
    "unknown window": "Unknown Window",
    "unknown task": "Unknown Window",
    "unknown activity": "Unknown Window",
    "empty title": "Unknown Window",
    "program manager": "Program Manager",
    "default ime": "Default IME",
    "windows default lock screen": "Windows Default Lock Screen",
    "lock screen": "Lock Screen",
    "windows shell": "Windows Shell",
}

MEANINGLESS_ACTIVITY_LABELS = {
    "",
    "none",
    "null",
    "nan",
    "nat",
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

INVALID_PROJECT_LABELS = MEANINGLESS_ACTIVITY_LABELS | {
    "browser work",
    "chrome",
    "google chrome",
    "microsoft edge",
    "edge",
    "codex",
    "pgadmin",
    "pgadmin 4",
    "office work",
    "communication",
    "entertainment",
    "development",
    "visual studio code",
    "vs code",
    "vscode",
    "cursor",
    "antigravity",
    "windsurf",
    "pycharm",
    "intellij",
    "snipping tool overlay",
    "snipping tool",
    "task switching",
    "file explorer",
    "windows explorer",
    "settings",
    "calculator",
    "windows shell",
    "idle",
    "system idle",
    "unassigned activities",
    "other",
}


def log_tracker_db(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with open(TRACKER_DB_LOG_FILE, "a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError as error:
        print(f"Unable to write tracker DB log: {error}")


def log_database_import_once():
    global _DATABASE_IMPORT_LOGGED
    if _DATABASE_IMPORT_LOGGED:
        return
    _DATABASE_IMPORT_LOGGED = True
    log_tracker_db(f"Tracker PostgreSQL module loaded: database.py={database.__file__}")


def _atomic_write_json(path, data):
    temp_path = f"{path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=True, indent=2)
    try:
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def set_active_tracker_user(user_data):
    """Expose the current dashboard user to the independent tracker process."""
    if not user_data or not user_data.get("id"):
        clear_active_tracker_user()
        return
    if str(user_data.get("role") or "").strip().lower() != "employee":
        log_tracker_db(
            f"Active tracker user not set for non-employee role: "
            f"user_id={user_data.get('id')}, role={user_data.get('role', '')}."
        )
        clear_active_tracker_user()
        return

    _atomic_write_json(
        ACTIVE_TRACKER_USER_FILE,
        {
            "user_id": int(user_data["id"]),
            "employee_id": user_data.get("employee_id", ""),
            "employee_name": user_data.get("employee_name", ""),
            "login_email": user_data.get("login_email", ""),
            "role": user_data.get("role", "employee"),
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
    )
    log_tracker_db(
        f"Active tracker user set: user_id={int(user_data['id'])}, "
        f"employee_id={user_data.get('employee_id', '')}"
    )


def clear_active_tracker_user():
    try:
        if os.path.exists(ACTIVE_TRACKER_USER_FILE):
            os.remove(ACTIVE_TRACKER_USER_FILE)
            log_tracker_db("Active tracker user cleared.")
    except OSError as error:
        log_tracker_db(f"Unable to clear active tracker user: {error}")


def get_active_tracker_user():
    try:
        with open(ACTIVE_TRACKER_USER_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        log_tracker_db(
            "No active tracker user found. Login to the dashboard before starting tracker."
        )
        return None

    user_id = data.get("user_id")
    if not user_id:
        log_tracker_db("Active tracker user file exists but does not contain user_id.")
        return None

    try:
        data["user_id"] = int(user_id)
    except (TypeError, ValueError):
        log_tracker_db(f"Invalid active tracker user_id value: {user_id}")
        return None

    return data


def _seconds_from_duration(duration):
    if duration is None:
        return 0
    if isinstance(duration, timedelta):
        return max(0, int(duration.total_seconds()))
    try:
        return max(0, int(float(duration)))
    except (TypeError, ValueError):
        try:
            return max(0, int(pd.to_timedelta(str(duration)).total_seconds()))
        except (TypeError, ValueError):
            return 0


def should_ignore_idle_activity(project_name, file_name="", ai_task_name="", duration_seconds=0):
    """Long idle sessions are not reportable work and should be ignored."""
    normalized_project = normalize_project_name_for_storage(project_name, file_name, ai_task_name)
    return normalized_project == "IDLE" and _seconds_from_duration(duration_seconds) > MAX_RECORDED_IDLE_SECONDS


def _clean_name(value):
    return str(value or "").replace("\u200b", "").strip()


def _project_key(value):
    return _clean_name(value).lower().strip(" .")


def is_valid_project_label(project_name):
    return bool(_project_key(project_name)) and _project_key(project_name) not in INVALID_PROJECT_LABELS


def _is_unassigned_activity(project_name, file_name="", ai_task_name=""):
    labels = " ".join([
        _clean_name(project_name),
        _clean_name(file_name),
        _clean_name(ai_task_name),
    ]).lower()
    exact_labels = {
        label
        for label in {
            _clean_name(project_name).lower().strip(" ."),
            _clean_name(file_name).lower().strip(" ."),
            _clean_name(ai_task_name).lower().strip(" ."),
        }
        if label
    }
    if exact_labels & MEANINGLESS_ACTIVITY_LABELS:
        return True
    return (
        _clean_name(project_name).lower() in {"other", "unassigned activities"}
        and any(keyword in labels for keyword in UNASSIGNED_ACTIVITY_KEYWORDS)
    ) or _clean_name(project_name).lower() == "unassigned activities"


def normalize_project_name_for_storage(project_name, file_name="", ai_task_name=""):
    project_name = _clean_name(project_name) or "Unassigned Activities"
    processed_task = _processed_task_name_from_text(project_name, file_name, ai_task_name)
    if project_name.lower().strip(" .") in {*GENERIC_BROWSER_PROJECTS, "unassigned activities"} and processed_task:
        return os.path.basename(BASE_DIR) or "productivity Tracker"
    if project_name.upper() in {"IDLE", "SYSTEM IDLE"}:
        return "IDLE"
    if _is_unassigned_activity(project_name, file_name, ai_task_name):
        return "Unassigned Activities"
    if project_name.lower().strip(" .") in {"other", "sleep", "system sleep", "unknown", *MEANINGLESS_ACTIVITY_LABELS}:
        return "Unassigned Activities"
    return project_name


def calculate_duration_seconds(start_time, end_time, stored_duration=0):
    try:
        if start_time and end_time:
            seconds = int((end_time - start_time).total_seconds())
            if seconds > 0:
                return seconds
    except Exception:
        pass
    try:
        return max(0, int(stored_duration or 0))
    except (TypeError, ValueError):
        return 0


def classify_activity_category(project_name, file_name="", ai_task_name=""):
    normalized = normalize_project_name_for_storage(project_name, file_name, ai_task_name)
    if normalized == "IDLE":
        return "IDLE"
    if normalized == "Unassigned Activities":
        return "Unassigned Activities"
    return "Project Work"


def _task_name_from_file(file_name, fallback):
    source = _clean_name(file_name) or _clean_name(fallback)
    if not source:
        return ""

    source = os.path.basename(source)
    source = os.path.splitext(source)[0]
    source = re.sub(r"[_\.-]+", " ", source)
    source = re.sub(r"\s+", " ", source).strip()
    return source.title() if source else ""


def _processed_task_name_from_text(*values):
    text = " ".join(str(value or "") for value in values).lower()

    for keywords, task_name in PROCESSED_TASK_RULES:
        if any(keyword in text for keyword in keywords):
            return task_name

    return None


def _processed_task_name_from_file(file_name, fallback=""):
    processed_name = _processed_task_name_from_text(file_name, fallback)

    if processed_name:
        return processed_name

    task_name = _task_name_from_file(file_name, fallback)

    if not task_name:
        return ""

    if task_name.lower().endswith(" module"):
        return task_name

    return f"{task_name} Module"


def derive_processed_task_name(project_name, window_title="", file_name="", ai_task_name=""):
    project = normalize_project_name_for_storage(project_name, file_name or window_title, ai_task_name)

    if project in {"IDLE", "Unassigned Activities"}:
        return normalize_task_name_for_storage(project, window_title, file_name, ai_task_name)

    processed_name = _processed_task_name_from_text(window_title, file_name, ai_task_name)

    if processed_name:
        return processed_name

    return _processed_task_name_from_file(file_name or ai_task_name or window_title, window_title)


def _display_activity_name(value):
    name = _clean_name(value)
    name = re.sub(r"\s+", " ", name).strip(" .")
    canonical_key = name.lower().strip(" .")
    if canonical_key in CANONICAL_ACTIVITY_NAMES:
        return CANONICAL_ACTIVITY_NAMES[canonical_key]
    return name or "Unknown Window"


def _strip_generated_task_suffix(task_name):
    cleaned = _display_activity_name(task_name)
    lowered = cleaned.lower()
    for suffix in GENERATED_TASK_SUFFIXES:
        if lowered.endswith(suffix):
            return cleaned[: -len(suffix)].strip(" .") or cleaned
    return cleaned


def normalize_task_name_for_storage(project_name, window_title="", file_name="", ai_task_name=""):
    project = normalize_project_name_for_storage(project_name, file_name or window_title, ai_task_name)
    if project == "IDLE":
        return "System Idle"
    if project == "Unassigned Activities":
        source = file_name or window_title or ai_task_name
        if str(source or "").strip().lower().strip(" .") in {"unknown task", "unknown activity"}:
            source = "Unknown Window"
        return _display_activity_name(source)
    processed_name = _processed_task_name_from_text(window_title, file_name, ai_task_name)
    if processed_name:
        return processed_name
    return _processed_task_name_from_file(
        file_name or _strip_generated_task_suffix(ai_task_name) or window_title,
        window_title,
    )


def _status_for_project(project_name):
    normalized = _clean_name(project_name).upper()
    if normalized in {"IDLE", "SLEEP", "SYSTEM IDLE"}:
        return "Idle"
    return "In Progress"


def _get_or_create_project(db_session, user_id, project_name):
    project = (
        db_session.query(Project)
        .filter(Project.user_id == int(user_id), Project.project_name == project_name)
        .first()
    )
    if project:
        return project

    project = Project(user_id=int(user_id), project_name=project_name)
    db_session.add(project)
    db_session.flush()
    return project


def _get_or_create_task(db_session, user_id, project_id, task_name, status):
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
        if status:
            task.status = status
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


def save_tracked_activity(
    project_name,
    window_title,
    file_name,
    start_time,
    end_time,
    duration,
    user_id=None,
    ai_task_name=None,
    status=None,
):
    """Persist one tracker session to PostgreSQL for the active dashboard user."""
    log_database_import_once()
    active_user = None if user_id else get_active_tracker_user()
    resolved_user_id = user_id or (active_user or {}).get("user_id")
    if active_user:
        log_tracker_db(
            f"Activity save resolved active bridge: user_id={active_user.get('user_id')}, "
            f"employee_id={active_user.get('employee_id')}, "
            f"updated_at={active_user.get('updated_at')}."
        )
    if not resolved_user_id:
        log_tracker_db(
            f"Activity DB insert skipped: no user_id for project={project_name!r}, "
            f"window={window_title!r}."
        )
        return False

    duration_seconds = _seconds_from_duration(duration)
    if duration_seconds < 3:
        log_tracker_db(
            f"Activity DB insert skipped: duration below 3 seconds "
            f"({duration_seconds}s) for user_id={resolved_user_id}."
        )
        return False

    file_name = _clean_name(file_name) or _clean_name(window_title)
    project_name = normalize_project_name_for_storage(project_name, file_name, ai_task_name)
    ai_task_name = normalize_task_name_for_storage(project_name, window_title, file_name, ai_task_name)
    status = _clean_name(status) or _status_for_project(project_name)
    if should_ignore_idle_activity(project_name, file_name, ai_task_name, duration_seconds):
        log_tracker_db(
            f"Activity DB insert skipped: idle duration exceeds "
            f"{MAX_RECORDED_IDLE_SECONDS}s ({duration_seconds}s) for user_id={resolved_user_id}."
        )
        return False

    try:
        log_tracker_db(
            f"Attempting PostgreSQL activity insert: user_id={resolved_user_id}, "
            f"project_name={project_name!r}, file_name={file_name!r}, "
            f"ai_task_name={ai_task_name!r}, status={status!r}, "
            f"start_time={start_time}, end_time={end_time}, duration={duration_seconds}s."
        )
        with get_db_session() as db_session:
            user = db_session.get(User, int(resolved_user_id))
            if not user:
                log_tracker_db(
                    f"Activity DB insert skipped: user_id={resolved_user_id} does not exist."
                )
                return False
            if str(user.role or "").strip().lower() != "employee":
                log_tracker_db(
                    f"Activity DB insert skipped: user_id={resolved_user_id} "
                    f"role={user.role!r} is not employee."
                )
                return False
            log_tracker_db(
                f"PostgreSQL insert owner verified: user_id={user.id}, "
                f"employee_id={user.employee_id}, login_email={user.login_email}."
            )
            activity = Activity(
                user_id=int(resolved_user_id),
                project_name=project_name,
                file_name=file_name,
                ai_task_name=ai_task_name,
                status=status,
                is_assigned=False,
                start_time=start_time,
                end_time=end_time,
                duration=duration_seconds,
            )
            db_session.add(activity)
            db_session.commit()
            log_tracker_db(
                f"Activity inserted successfully: activity_id={activity.id}, "
                f"user_id={resolved_user_id}, project={project_name!r}, "
                f"task={ai_task_name!r}, duration={duration_seconds}s."
            )
        return True
    except Exception as error:
        log_tracker_db(
            f"Activity insert failed with exception: user_id={resolved_user_id}, "
            f"project={project_name!r}, error={error}"
        )
        traceback.print_exc()
        return False


def _empty_activity_dataframe():
    return pd.DataFrame(columns=ACTIVITY_COLUMNS)


def load_user_activities_dataframe(user_id=None, include_all=False, include_sent=False):
    if not include_all and not user_id:
        return _empty_activity_dataframe()

    try:
        with get_db_session() as db_session:
            query = db_session.query(Activity)
            if not include_all:
                log_tracker_db(f"Dashboard activity query: WHERE user_id = {int(user_id)}")
                query = query.filter(Activity.user_id == int(user_id))
                if not include_sent:
                    log_tracker_db("Dashboard activity query: WHERE email_sent = FALSE")
                    query = query.filter(Activity.email_sent.is_(False))
            else:
                log_tracker_db("Dashboard activity query: manager include_all=True")
            activities = query.order_by(Activity.start_time.desc(), Activity.id.desc()).all()
            project_rows = db_session.query(Project.user_id, Project.project_name).all()
    except Exception as error:
        print(f"Activity database read failed: {error}")
        return None

    valid_projects_by_user = {}
    for project_user_id, project_name in project_rows:
        if is_valid_project_label(project_name):
            valid_projects_by_user.setdefault(int(project_user_id), set()).add(_project_key(project_name))

    rows = []
    for activity in activities:
        project_name = normalize_project_name_for_storage(
            activity.project_name,
            activity.file_name,
            activity.ai_task_name,
        )
        task_label = normalize_task_name_for_storage(
            project_name,
            activity.file_name,
            activity.file_name,
            activity.ai_task_name,
        )
        mapped_project_work = (
            project_name not in {"IDLE", "Unassigned Activities"}
            and task_label in PROCESSED_TASK_NAMES
            and is_valid_project_label(project_name)
        )
        valid_project = (
            mapped_project_work
            or bool(getattr(activity, "is_assigned", False))
            and is_valid_project_label(project_name)
            and _project_key(project_name) in valid_projects_by_user.get(int(activity.user_id), set())
        )
        duration_seconds = calculate_duration_seconds(
            activity.start_time,
            activity.end_time,
            activity.duration,
        )
        if should_ignore_idle_activity(project_name, activity.file_name, activity.ai_task_name, duration_seconds):
            continue
        rows.append(
            {
                "Activity ID": activity.id,
                "Project Name": project_name,
                "Activity Category": (
                    classify_activity_category(project_name, activity.file_name, activity.ai_task_name)
                    if valid_project
                    else "Unassigned Activities"
                ),
                "App Name": task_label,
                "Project": project_name,
                "File Name": activity.file_name or "",
                "AI Task Name": task_label,
                "Status": activity.status or "",
                "Is Assigned": bool(getattr(activity, "is_assigned", False)) or mapped_project_work,
                "Valid Project": valid_project,
                "Email Sent": bool(getattr(activity, "email_sent", False)),
                "Sent At": getattr(activity, "sent_at", None),
                "Start Time": activity.start_time,
                "End Time": activity.end_time,
                "Duration": duration_seconds,
            }
        )

    df = pd.DataFrame(rows, columns=ACTIVITY_COLUMNS)
    if not df.empty:
        df["Start Time"] = pd.to_datetime(df["Start Time"], errors="coerce")
        df["End Time"] = pd.to_datetime(df["End Time"], errors="coerce")
        df["Sent At"] = pd.to_datetime(df["Sent At"], errors="coerce")
        df["Duration"] = pd.to_numeric(df["Duration"], errors="coerce").fillna(0)
    return df


def normalize_existing_activity_projects():
    """Bring older activity rows in line with the current categorization model."""
    updated = 0
    try:
        with get_db_session() as db_session:
            project_rows = db_session.query(Project.user_id, Project.project_name).all()
            valid_projects_by_user = {}
            for project_user_id, project_name in project_rows:
                if is_valid_project_label(project_name):
                    valid_projects_by_user.setdefault(int(project_user_id), set()).add(_project_key(project_name))

            activities = db_session.query(Activity).all()
            for activity in activities:
                normalized_project = normalize_project_name_for_storage(
                    activity.project_name,
                    activity.file_name,
                    activity.ai_task_name,
                )
                normalized_task = normalize_task_name_for_storage(
                    normalized_project,
                    activity.file_name,
                    activity.file_name,
                    activity.ai_task_name,
                )
                if normalized_project != activity.project_name:
                    activity.project_name = normalized_project
                    updated += 1
                if normalized_task and normalized_task != activity.ai_task_name:
                    activity.ai_task_name = normalized_task
                    updated += 1
                has_valid_project = (
                    is_valid_project_label(activity.project_name)
                    and _project_key(activity.project_name) in valid_projects_by_user.get(int(activity.user_id), set())
                )
                if bool(getattr(activity, "is_assigned", False)) and not has_valid_project:
                    activity.is_assigned = False
                    updated += 1
            tasks = db_session.query(Task).join(Project, Task.project_id == Project.id).all()
            for task in tasks:
                normalized_task = normalize_task_name_for_storage(
                    task.project.project_name if task.project else "",
                    task.task_name,
                    task.task_name,
                    task.task_name,
                )
                if normalized_task and normalized_task != task.task_name:
                    task.task_name = normalized_task
                    updated += 1
            if updated:
                db_session.commit()
                log_tracker_db(f"Normalized existing activity/task labels: updated={updated}.")
    except Exception as error:
        log_tracker_db(f"Existing activity normalization failed: {error}")
        traceback.print_exc()
    return updated
