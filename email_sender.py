import csv
import html
import json
import os
import re
import smtplib
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText

import pandas as pd
from dotenv import load_dotenv
from activity_store import derive_processed_task_name, should_ignore_idle_activity

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
TASKS_FILE = os.path.join(os.path.dirname(__file__), "tasks.json")
AI_CACHE_FILE = os.path.join(os.path.dirname(__file__), "ai_cache.json")

UNICODE_EMAIL_REPLACEMENTS = {
    "\u25cf": "*",
    "\u2022": "*",
    "\u2713": "[OK]",
    "\u2714": "[OK]",
    "\u2717": "[X]",
    "\u2718": "[X]",
    "\u2705": "[OK]",
    "\u274c": "[X]",
}


# -----------------------------------------
# IDLE / SLEEP KEYWORDS
# -----------------------------------------
IDLE_KEYWORDS = [
    "System Idle",
    "Shut Down Windows",
    "Unknown Window",
    "Program Manager",
    "Tracker Shutdown",
    "System Sleep",
]

AUTO_MERGE_APPS = {
    "google chrome",
    "microsoft edge",
}


def get_system_email_credentials():
    load_dotenv(ENV_FILE)
    sender = os.getenv("SYSTEM_EMAIL", "").strip()
    password = os.getenv("SYSTEM_APP_PASSWORD", "").strip()

    if not sender or not password:
        raise ValueError("SYSTEM_EMAIL or SYSTEM_APP_PASSWORD is missing in .env.")

    return sender, password


def mask_secret(value, visible=2):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * (len(value) - visible * 2)}{value[-visible:]}"


def log_email_auth_debug(sender, password, recipient):
    print(f"SYSTEM_EMAIL loaded: {'YES' if sender else 'NO'}")
    print(f"SYSTEM_APP_PASSWORD loaded: {'YES' if password else 'NO'}")
    print(f"Using sender: {sender}")
    print("Credential source: .env")
    print(f"Recipient email: {recipient}")
    print(f"SYSTEM_APP_PASSWORD length: {len(password)}")
    print(f"SYSTEM_APP_PASSWORD masked: {mask_secret(password)}")


def sanitize_email_text(value):
    text = str(value or "")
    for source, replacement in UNICODE_EMAIL_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    return text


def debug_non_ascii_email_lines(label, value):
    text = str(value or "")
    found = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        chars = sorted({character for character in line if ord(character) > 127})
        if not chars:
            continue
        found = True
        char_summary = ", ".join(
            f"U+{ord(character):04X}" for character in chars
        )
        ascii_preview = line.encode("ascii", "backslashreplace").decode("ascii")
        print(
            f"EMAIL ENCODING DEBUG: {label} line {line_number} "
            f"contains {char_summary}: {ascii_preview}"
        )
    if not found:
        print(f"EMAIL ENCODING DEBUG: {label} has no non-ASCII characters.")

SUPPORT_BROWSER_KEYWORDS = {
    "chatgpt",
    "github",
    "stack overflow",
    "stackoverflow",
    "mdn",
    "docs",
    "documentation",
    "python docs",
    "microsoft docs",
    "postgresql",
    "outlook",
    "inbox",
    "email verification",
    "new tab",
}

UNRELATED_BROWSER_KEYWORDS = {
    "youtube",
    "netflix",
    "instagram",
    "facebook",
    "shopping",
    "amazon",
    "flipkart",
    "spotify",
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

CODING_TOOLS = [
    "visual studio code",
    "antigravity ide",
    "cursor",
    "codex",
    "firo",
    "vscode",
    "pycharm",
    "intellij idea",
    "intellij",
    "webstorm",
    "phpstorm",
    "rider",
    "android studio",
    "eclipse",
    "netbeans",
]


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

    text = normalize_title(value) if "normalize_title" in globals() else str(value).strip()

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


def log_skipped_invalid_row(row):

    try:
        row_data = row.to_dict()
    except AttributeError:
        row_data = row

    print("Skipped invalid row:", row_data)



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

    return derive_processed_task_name("", file_name, file_name, file_name)


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
    return derive_processed_task_name(project, raw_file_name, raw_file_name, raw_file_name)

# -----------------------------------------
# DATE / DURATION HELPERS
# -----------------------------------------

def get_today_date():

    return datetime.now().strftime("%Y-%m-%d")


def format_duration(duration):

    total_seconds = int(duration.total_seconds())

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    return f"{hours:02d}:{minutes:02d}"


def parse_review_duration(duration):

    parts = str(duration or "0:00").strip().split(":")
    try:
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except Exception:
        return 0


def format_review_duration(total_minutes):

    total_minutes = max(0, int(total_minutes))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def normalize_title(value):

    return (
        str(value)
        .replace("\u200b", "")
        .strip()
    )


def is_file_name(value):

    _, ext = os.path.splitext(value.strip())

    return bool(ext)


def is_google_chrome(title):

    return "google chrome" in normalize_title(title).lower()


def is_microsoft_edge(title):

    normalized = normalize_title(title).lower()

    return "microsoft edge" in normalized or (
        "microsoft" in normalized and "edge" in normalized
    )


def is_auto_merge_activity(title):

    normalized = normalize_title(title).lower()
    if not any(app in normalized for app in AUTO_MERGE_APPS):
        return False
    if any(keyword in normalized for keyword in UNRELATED_BROWSER_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in SUPPORT_BROWSER_KEYWORDS)


def is_standalone_processed_activity(title):
    normalized = normalize_title(title).lower()
    return any(keyword in normalized for keyword in {
        "task scheduler auto start",
        "auto start",
        "autostart",
        "startup",
    })


def is_ignored_task_file(task_name):

    return os.path.basename(str(task_name or "").strip()).lower() in IGNORE_FILES


def normalize_app_identity(app_name):

    normalized = str(app_name or "").strip().lower()
    for marker in (" - google chrome", " - microsoft edge"):
        if normalized.endswith(marker):
            normalized = marker.rsplit(" - ", 1)[1]
            break
    return normalized


def normalize_misc_app(app_name):

    normalized = normalize_app_identity(app_name)
    raw_name = normalize_title(app_name)
    if is_auto_merge_activity(raw_name):
        return None
    if any(app in normalized for app in AUTO_MERGE_APPS):
        return raw_name or "Browser Activity"
    return MANUAL_ASSIGN_APPS.get(normalized)


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


def is_coding_tool(title):

    normalized = normalize_title(title).lower()

    return any(tool in normalized for tool in CODING_TOOLS)


# -----------------------------------------
# REPORT / ATTACHMENT HOOKS DISABLED
# -----------------------------------------
def get_report_files():

    return []


def create_timesheet_excel():

    print("Timesheet Excel generation disabled")

    return None


# -----------------------------------------
# FOLDER EXTRACTION
# -----------------------------------------
def extract_editor_folder(title):

    clean_title = normalize_title(title)
    parts = [part.strip() for part in clean_title.split(" - ") if part.strip()]

    for index, part in enumerate(parts):
        if any(editor in part.lower() for editor in CODING_TOOLS):
            previous_parts = parts[:index]

            for candidate in reversed(previous_parts):
                if not is_file_name(candidate):
                    return candidate

            return None

    if is_coding_tool(clean_title):
        for candidate in reversed(parts[:-1]):
            if not is_file_name(candidate):
                return candidate

        return None

    return None


def get_saved_project_folder(row):

    project_name = normalize_title(row.get("Project Name", ""))

    non_folder_categories = {
        "",
        "browser work",
        "communication",
        "codex",
        "cursor",
        "development",
        "entertainment",
        "excel work",
        "firo",
        "idle",
        "learning",
        "microsoft edge",
        "office work",
        "other",
        "others",
        "sleep",
        "visual studio code",
        "vscode",
    }

    if project_name.lower() in non_folder_categories:
        return None

    return project_name


# -----------------------------------------
# SUMMARY TABLE
# -----------------------------------------
def build_summary_rows():

    df = pd.read_csv("activity_log.csv", encoding="utf-8-sig", encoding_errors="replace")
    df.columns = df.columns.str.strip()
    df["Duration"] = pd.to_timedelta(df["Duration"])

    totals = {}
    last_active_file = None
    idle_limit = pd.Timedelta(minutes=5)

    for _, row in df.iterrows():
        title = normalize_required_text(row.get("App Name", ""))
        duration = row["Duration"]
        if should_ignore_idle_activity(
            row.get("Project Name", "") or row.get("Project", ""),
            title,
            None,
            duration,
        ):
            continue

        raw_project = row.get("Project", "")
        raw_file_name = row.get("File Name", "")
        project = normalize_required_text(raw_project)
        file_name = normalize_required_text(raw_file_name)
        has_invalid_project_file = is_invalid_text_value(raw_project) or is_invalid_text_value(raw_file_name)
        is_development_row = (
            is_meaningful_project_and_task(project, file_name)
            and not is_ignored_task_file(file_name)
        )

        if is_development_row:
            last_active_file = (project, file_name)
            totals[last_active_file] = totals.get(last_active_file, pd.Timedelta(0)) + duration
            continue

        if is_standalone_processed_activity(title):
            standalone_project = project if is_meaningful_project_and_task(project, "Auto Start Feature") else "Productivity Tracker"
            standalone_key = (standalone_project, title)
            totals[standalone_key] = totals.get(standalone_key, pd.Timedelta(0)) + duration
            continue

        if last_active_file is None:
            if has_invalid_project_file or project or file_name:
                log_skipped_invalid_row(row)
            continue

        normalized_title = title.lower()
        should_auto_merge = any(app in normalized_title for app in AUTO_MERGE_APPS)
        if not should_auto_merge:
            if has_invalid_project_file or project or file_name:
                log_skipped_invalid_row(row)
            continue

        totals[last_active_file] = totals.get(last_active_file, pd.Timedelta(0)) + duration

    rows = []

    for (project, file_name), duration in sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        rows.append((f"{project} / {file_name}", format_duration(duration)))

    return rows


def load_saved_review_data():

    if not os.path.exists(TASKS_FILE):
        return {"tasks": [], "activity_merges": []}

    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as tasks_file:
            data = json.load(tasks_file)
            if isinstance(data, list):
                return {"tasks": data, "activity_merges": []}
            if isinstance(data, dict):
                return {
                    "tasks": data.get("tasks", []) if isinstance(data.get("tasks", []), list) else [],
                    "activity_merges": data.get("activity_merges", []) if isinstance(data.get("activity_merges", []), list) else [],
                }
            return {"tasks": [], "activity_merges": []}
    except Exception as error:
        print("Failed to load tasks.json:", error)
        return {"tasks": [], "activity_merges": []}


def normalize_review_tasks(tasks):

    normalized = []
    for task in tasks if isinstance(tasks, list) else []:
        date = normalize_required_text(task.get("date", ""))
        project = normalize_required_text(task.get("project", ""))
        task_name = normalize_required_text(task.get("task", ""))
        source_task = normalize_required_text(task.get("source_task") or task_name)
        duration = normalize_required_text(task.get("duration", ""))

        if not all([date, project, task_name, source_task, duration]):
            print("Skipped invalid row:", task)
            continue

        if is_ignored_task_file(task_name) or is_ignored_task_file(source_task):
            continue

        if is_auto_merge_activity(task_name):
            if normalized:
                add_duration_to_task(normalized[-1], duration)
            continue

        normalized.append({
            "date": date,
            "project": project,
            "task": task_name,
            "source_task": source_task,
            "status": normalize_required_text(task.get("status", "In Progress")) or "In Progress",
            "duration": duration,
        })

    return normalized


def normalize_activity_merges(raw_merges):

    normalized = []
    seen = set()
    for item in raw_merges if isinstance(raw_merges, list) else []:
        app = normalize_misc_app(item.get("app", ""))
        target_task = normalize_required_text(item.get("target_task", ""))
        if not app or not target_task or is_ignored_task_file(target_task):
            continue
        key = (app.lower(), target_task.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"app": app, "target_task": target_task})
    return normalized


def build_current_review_tasks():

    today = datetime.now().strftime("%d-%m-%Y")
    tasks = []
    ai_cache = load_ai_cache()
    for label, duration in build_summary_rows():
        if " / " in label:
            project, task_name = label.split(" / ", 1)
        else:
            project, task_name = "Project", label

        project = normalize_required_text(project)
        task_name = normalize_required_text(task_name)

        if not project or not task_name or is_ignored_task_file(task_name):
            print("Skipped invalid row:", {"project": project, "file_name": task_name, "duration": duration})
            continue

        ai_task_name = get_ai_task_name(project, task_name, ai_cache)
        tasks.append({
            "date": today,
            "project": project,
            "task": ai_task_name or task_name,
            "source_task": task_name,
            "status": "In Progress",
            "duration": duration,
        })
    return sort_review_tasks_by_project(normalize_review_tasks(tasks))


def build_current_unassigned_activities():

    try:
        df = pd.read_csv("activity_log.csv", encoding="utf-8-sig", encoding_errors="replace")
        df.columns = df.columns.str.strip()
        df["Duration"] = pd.to_timedelta(df["Duration"])
    except Exception:
        return []

    totals = {}
    for _, row in df.iterrows():
        if should_ignore_idle_activity(
            row.get("Project Name", "") or row.get("Project", ""),
            row.get("App Name", ""),
            None,
            row["Duration"],
        ):
            continue
        app = normalize_misc_app(row.get("App Name", ""))
        if not app:
            continue
        totals[app] = totals.get(app, pd.Timedelta(0)) + row["Duration"]

    return [
        {"app": app, "duration": format_duration(duration)}
        for app, duration in totals.items()
        if duration.total_seconds() > 0
    ]


def load_review_tasks():

    tasks = build_current_review_tasks()
    saved_data = load_saved_review_data()
    saved_tasks = normalize_review_tasks(saved_data.get("tasks", []))
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

    unassigned_by_app = {
        item["app"].lower(): item
        for item in build_current_unassigned_activities()
    }
    for merge in normalize_activity_merges(saved_data.get("activity_merges", [])):
        activity = unassigned_by_app.get(merge["app"].lower())
        target = find_task_by_name(tasks, merge["target_task"])
        if activity and target:
            add_duration_to_task(target, activity.get("duration"))

    return tasks


def render_tasks_table(tasks):

    table_rows = [
        '<tr>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Date</th>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Project</th>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Task</th>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Status</th>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Duration</th>'
        '</tr>'
    ]

    for task in tasks:
        table_rows.append(
            '<tr>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:center;">{html.escape(str(task.get("date", "")))}</td>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:left;">{html.escape(str(task.get("project", "")))}</td>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:left;">{html.escape(str(task.get("task", "")))}</td>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:center;">{html.escape(str(task.get("status", "")))}</td>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:center;">{html.escape(str(task.get("duration", "")))}</td>'
            '</tr>'
        )

    return (
        '<table border="1" cellspacing="0" cellpadding="0" '
        'style="border-collapse:collapse;width:90%;mso-table-lspace:0pt;mso-table-rspace:0pt;">'
        f"{''.join(table_rows)}"
        '</table>'
    )


def render_summary_table(rows):

    table_rows = [
        '<tr>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Folder / Activity</th>'
        '<th style="border:1px solid #000;padding:6px 10px;background-color:#f2f2f2;text-align:center;">Duration</th>'
        '</tr>'
    ]

    for label, duration in rows:
        table_rows.append(
            '<tr>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:left;">{html.escape(label)}</td>'
            f'<td style="border:1px solid #000;padding:6px 10px;text-align:center;">{html.escape(duration)}</td>'
            '</tr>'
        )

    return (
        '<table border="1" cellspacing="0" cellpadding="0" '
        'style="border-collapse:collapse;width:70%;mso-table-lspace:0pt;mso-table-rspace:0pt;">'
        f"{''.join(table_rows)}"
        '</table>'
    )


def generate_timesheet():

    try:
        tasks = load_review_tasks()
        if tasks:
            return render_tasks_table(tasks)

        return render_summary_table(build_summary_rows())
    except Exception as error:
        print("Failed to generate timesheet:", error)
        return render_tasks_table([])


def get_employee_name(employee_name=None):

    return str(employee_name or "User").strip() or "User"


def build_email_body(employee_name=None, employee_id=None):

    table = generate_timesheet()
    employee_name = html.escape(get_employee_name(employee_name))

    return f"""<html>
<body>
<p>Hello Manager,</p>
<p>Please find below my productivity report for today.</p>
<p>The report summarizes the activities completed, associated projects, task assignments, statuses, and durations recorded during today's work session.</p>
{table}
<p>Regards,</p>
<p>{employee_name}</p>
</body>
</html>
"""


# -----------------------------------------
# CLEAR ACTIVITY LOG
# -----------------------------------------
def clear_activity_log():

    try:
        with open(
            "activity_log.csv",
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.writer(file)
            writer.writerow([
                "Project Name",
                "App Name",
                "Project",
                "File Name",
                "Start Time",
                "End Time",
                "Duration",
            ])
        print("Activity log cleared")
    except Exception as error:
        print("Failed to clear activity log")
        print(error)
# -----------------------------------------
# SEND EMAIL FUNCTION
# -----------------------------------------
def send_email(
    subject=None,
    body=None,
    report_data=None,
    employee_name=None,
    employee_id=None,
    receiver_email=None,
    sender_email=None,
    app_password=None,
):

    print("USING NEW EMAIL_SENDER.PY")
    print("\n====================================")
    print("SENDING EMAIL")
    print("====================================")

    try:
        if not subject:
            safe_employee_name = get_employee_name(employee_name)
            subject = f"{safe_employee_name} - Daily Productivity Report - {get_today_date()}"

        if not body:
            body = build_email_body(employee_name=employee_name, employee_id=employee_id)
        recipient = str(receiver_email or "").strip()
        sender, password = get_system_email_credentials()
        if not recipient:
            raise ValueError("Employee manager email is missing.")
        if "Sent From:" not in body:
            body = f"Sent From: {sender}\n\n{body}"
        log_email_auth_debug(sender, password, recipient)
        debug_non_ascii_email_lines("subject before sanitize", subject)
        debug_non_ascii_email_lines("body before sanitize", body)
        subject = sanitize_email_text(subject)
        body = sanitize_email_text(body)
        debug_non_ascii_email_lines("subject after sanitize", subject)
        debug_non_ascii_email_lines("body after sanitize", body)

        print("\n===== TIMESHEET REPORT =====")
        print("Generated email body length:", len(body))
        print("===========================\n")

        message = MIMEText(body, "html", "utf-8")
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = recipient

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)

        print("====================================")
        print("EMAIL SENT SUCCESSFULLY")
        print("====================================")

        try:
            status_data = {
                "last_status": "success",
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error_message": None,
            }
            with open("email_status.json", "w", encoding="utf-8") as status_file:
                json.dump(status_data, status_file)
        except Exception as status_error:
            print("Failed to save success status to email_status.json:", status_error)

        return True

    except Exception as error:
        print("\n====================================")
        print("EMAIL FAILED")
        print("====================================")
        print(error)

        try:
            status_data = {
                "last_status": "failed",
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error_message": str(error),
            }
            with open("email_status.json", "w", encoding="utf-8") as status_file:
                json.dump(status_data, status_file)
        except Exception as status_error:
            print("Failed to save failed status to email_status.json:", status_error)

        return False








