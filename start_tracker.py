import time
import csv
import os
import re
import atexit
import signal
import sys
import subprocess
import webbrowser
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from tracemalloc import start

import pyautogui
from pynput import keyboard, mouse
import threading

# -----------------------------------------
# IMPORT MODULES
# -----------------------------------------
from tray_app import run_tray
from activity_store import (
    MAX_RECORDED_IDLE_SECONDS,
    get_active_tracker_user,
    log_tracker_db,
    save_tracked_activity,
    should_ignore_idle_activity,
)

# -----------------------------------------
# OPTIONAL ACTIVE WINDOW DETECTION
# -----------------------------------------
try:
    import win32gui
except ImportError:
    win32gui = None

# -----------------------------------------
# CONFIG
# -----------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "activity_log.csv")
PID_FILE = os.path.join(BASE_DIR, "tracker.pid")
STOP_REQUEST_FILE = os.path.join(BASE_DIR, "tracker.stop")

running = True
tracking_paused = False
last_window = None
start_time = None
last_loop_time = None

last_activity_time = datetime.now()

IDLE_THRESHOLD = 60  # seconds

shutdown_done = False
keyboard_listener = None
mouse_listener = None
last_logged_active_window = None
last_active_coding_task = None


def write_tracker_pid():
    try:
        with open(PID_FILE, "w", encoding="utf-8") as file:
            file.write(str(os.getpid()))
    except OSError as error:
        print(f"Unable to write tracker PID file: {error}")


def clear_tracker_pid():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError as error:
        print(f"Unable to remove tracker PID file: {error}")


def stop_requested():
    return os.path.exists(STOP_REQUEST_FILE)


def require_authenticated_user():
    active_user = get_active_tracker_user()
    if active_user:
        role = str(active_user.get("role") or "").strip().lower()
        if role != "employee":
            log_tracker_db(
                f"Tracker not started: active user role is not employee "
                f"(user_id={active_user.get('user_id')}, role={role})."
            )
            return False
        log_tracker_db(
            f"Tracker authenticated at startup: user_id={active_user.get('user_id')}, "
            f"employee_id={active_user.get('employee_id')}, "
            f"updated_at={active_user.get('updated_at')}."
        )
        return True

    print("Tracker not started: no authenticated dashboard session found.")
    return False

# -----------------------------------------
# UPDATE USER ACTIVITY
# -----------------------------------------
def update_activity(*args):

    global last_activity_time

    last_activity_time = datetime.now()

# -----------------------------------------
# GET ACTIVE WINDOW
# -----------------------------------------
def get_active_window():
    global last_logged_active_window

    if win32gui:

        window = win32gui.GetWindowText(

            win32gui.GetForegroundWindow()

        )

        if not window.strip():

            if last_logged_active_window != "Unknown Window":
                log_tracker_db("Active window detected: Unknown Window (blank foreground title).")
                last_logged_active_window = "Unknown Window"
            return "Unknown Window"

        if last_logged_active_window != window:
            log_tracker_db(f"Active window detected: {window!r}")
            last_logged_active_window = window
        return window

    if last_logged_active_window != "Unknown Window":
        log_tracker_db("Active window detected: Unknown Window (win32gui unavailable).")
        last_logged_active_window = "Unknown Window"
    return "Unknown Window"

# -----------------------------------------
# PROJECT CLASSIFICATION
# -----------------------------------------
CODING_TOOLS = [
    "visual studio code",
    "visual studio code insiders",
    "code - insiders",
    "vscode insiders",
    "vs code insiders",
    "vs code",
    "vscodium",
    "windsurf",
    "antigravity ide",
    "antigravity",
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

UNASSIGNED_ACTIVITY_KEYWORDS = [
    "snipping tool overlay",
    "snipping tool",
    "task switching",
    "file explorer",
    "windows explorer",
    "settings",
    "calculator",
    "program manager",
    "start menu",
    "search",
    "notification center",
    "action center",
    "desktop",
    "system tray overflow window",
    "unknown window",
    "unknown task",
    "unknown activity",
]

IDLE_WINDOW_KEYWORDS = [
    "system idle",
    "idle",
    "shut down windows",
    "lockapp",
    "windows default lock screen",
    "sign in",
]

SUPPORT_BROWSER_KEYWORDS = [
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
]

STANDALONE_FEATURE_KEYWORDS = [
    "task scheduler auto start",
    "auto start",
    "autostart",
    "startup",
]

UNRELATED_BROWSER_KEYWORDS = [
    "youtube",
    "netflix",
    "instagram",
    "facebook",
    "shopping",
    "amazon",
    "flipkart",
    "spotify",
]


def normalize_window_title(window_title):

    return (
        str(window_title)
        .replace("Ã¢â€”Â ", "")
        .replace("Ã¢â‚¬â€¹", "")
        .replace("\u200b", "")
        .strip()
    )


def is_file_name(value):

    _, ext = os.path.splitext(value.strip())

    return bool(ext)


def is_unknown_activity(value):
    normalized = normalize_window_title(value).lower().strip(" .")
    exact = {
        "unknown window",
        "unknown task",
        "unknown activity",
        "task switching",
        "file explorer",
        "windows explorer",
        "settings",
        "calculator",
        "search",
        "desktop",
        "",
    }
    contains = {"system tray overflow window", "snipping tool"}
    return normalized in exact or any(keyword in normalized for keyword in contains)


def project_name_from_path(value):
    text = normalize_window_title(value).strip().strip('"')
    match = re.search(r"[A-Za-z]:\\[^|<>?*\n\r]+", text)
    if not match:
        return None

    path = match.group(0).split(" - ", 1)[0].strip()
    basename = os.path.basename(path)
    if is_file_name(basename):
        return os.path.basename(os.path.dirname(path)) or None
    return basename or None


def is_ide_name(value):
    normalized = str(value or "").lower()
    return any(tool in normalized for tool in CODING_TOOLS)


def clean_project_candidate(value):
    candidate = normalize_window_title(value)
    candidate = re.sub(r"\[[^\]]+\]$", "", candidate).strip()
    if not candidate or is_file_name(candidate) or is_ide_name(candidate) or is_unknown_activity(candidate):
        return None
    if candidate.lower() in {"administrator", "personal", "professional", "community", "untitled"}:
        return None
    return candidate


def split_window_title(window_title):
    return [part.strip() for part in normalize_window_title(window_title).split(" - ") if part.strip()]


def extract_ide_title_parts(window_title):
    clean_title = normalize_window_title(window_title)
    path_project = project_name_from_path(clean_title)
    parts = split_window_title(clean_title)

    for index, part in enumerate(parts):
        if is_ide_name(part):
            file_name = ""
            project = path_project or ""
            if index >= 1 and is_file_name(parts[index - 1]):
                file_name = parts[index - 1]
            elif index >= 2 and is_file_name(parts[index - 2]):
                file_name = parts[index - 2]

            for candidate in reversed(parts[:index]):
                candidate_path_project = project_name_from_path(candidate)
                if candidate_path_project:
                    project = candidate_path_project
                    break
                cleaned_candidate = clean_project_candidate(candidate)
                if cleaned_candidate:
                    project = cleaned_candidate
                    break

            return project or "", file_name

    if any(tool in clean_title.lower() for tool in CODING_TOOLS):
        file_name = next((part for part in parts if is_file_name(part)), "")
        project = path_project or ""
        for candidate in reversed(parts):
            cleaned_candidate = clean_project_candidate(candidate)
            if cleaned_candidate:
                project = cleaned_candidate
                break
        return project or "", file_name

    return path_project or "", ""


def extract_coding_project(window_title):

    project, _ = extract_ide_title_parts(window_title)
    return clean_project_candidate(project) or None


def get_project(window_title):

    clean_title = normalize_window_title(window_title)
    title = clean_title.lower()

    if any(keyword in title for keyword in IDLE_WINDOW_KEYWORDS):
        return "IDLE"

    if is_unknown_activity(clean_title):
        return "Unassigned Activities"

    if any(keyword in title for keyword in UNASSIGNED_ACTIVITY_KEYWORDS):
        return "Unassigned Activities"

    if any(app in title for app in ["python.exe", "windows input experience", "widgets"]):
        return "Unassigned Activities"

    path_project = project_name_from_path(clean_title)
    if path_project:
        return path_project

    coding_project = extract_coding_project(clean_title)

    if coding_project:
        return coding_project

    if any(tool in title for tool in CODING_TOOLS):
        return "Unassigned Activities"

    if any(x in title for x in ["chrome", "google chrome", "edge", "microsoft edge", "chatgpt", "firefox", "gmail", "outlook", "github", "stackoverflow"]):
        return "Unassigned Activities"

    if any(x in title for x in ["youtube", "netflix", "spotify"]):
        return "Entertainment"

    if any(x in title for x in ["whatsapp", "teams", "mail"]):
        return "Communication"

    if any(x in title for x in ["excel", "word", "powerpoint"]):
        return "Office Work"

    if any(x in title for x in ["unknown window"]):
        return "Unassigned Activities"

    return "Unassigned Activities"

def extract_project_and_file(window_title):

    if is_unknown_activity(window_title):
        return "", "Unknown Window" if "unknown" in normalize_window_title(window_title).lower() else normalize_window_title(window_title)

    return extract_ide_title_parts(window_title)


def is_browser_window(window_title):
    title = normalize_window_title(window_title).lower()
    return any(marker in title for marker in ["chrome", "google chrome", "edge", "microsoft edge", "firefox"])


def is_unrelated_browser_window(window_title):
    title = normalize_window_title(window_title).lower()
    return any(marker in title for marker in UNRELATED_BROWSER_KEYWORDS)


def is_support_browser_window(window_title):
    title = normalize_window_title(window_title).lower()

    if not is_browser_window(title) or is_unrelated_browser_window(title):
        return False

    return any(marker in title for marker in SUPPORT_BROWSER_KEYWORDS)


def is_standalone_feature_window(window_title):
    title = normalize_window_title(window_title).lower()
    return any(marker in title for marker in STANDALONE_FEATURE_KEYWORDS)


def update_last_active_coding_task(project, file_name):
    global last_active_coding_task

    project = clean_project_candidate(project) or ""
    file_name = normalize_window_title(file_name)

    if project and file_name and is_file_name(file_name):
        last_active_coding_task = {
            "project": project,
            "file_name": file_name,
        }


def resolve_processed_tracking_context(project, window, csv_project, csv_file):
    if csv_project and csv_file and is_file_name(csv_file):
        update_last_active_coding_task(csv_project, csv_file)
        return project, csv_project, csv_file

    if is_support_browser_window(window) and last_active_coding_task:
        return (
            last_active_coding_task["project"],
            last_active_coding_task["project"],
            last_active_coding_task["file_name"],
        )

    if is_standalone_feature_window(window):
        fallback_project = (
            (last_active_coding_task or {}).get("project")
            or clean_project_candidate(project)
            or os.path.basename(os.path.dirname(os.path.abspath(__file__)))
        )
        return fallback_project, fallback_project, normalize_window_title(window)

    return project, csv_project, csv_file

# -----------------------------------------
# SAVE SESSION
# -----------------------------------------
def save_session(project, window, start, end):

    duration = end - start
    csv_project, csv_file = extract_project_and_file(window)
    project, csv_project, csv_file = resolve_processed_tracking_context(
        project,
        window,
        csv_project,
        csv_file,
    )
    active_user = get_active_tracker_user()
    log_tracker_db(
        f"Tracker save_session requested: bridge_user_id={(active_user or {}).get('user_id')}, "
        f"employee_id={(active_user or {}).get('employee_id')}, project={project!r}, "
        f"window={window!r}, start={start}, end={end}, duration={duration}."
    )
    # ignore very short sessions
    if duration.total_seconds() < 3:

        log_tracker_db(
            f"Tracker save_session skipped short duration: {duration.total_seconds()}s, "
            f"project={project!r}, window={window!r}."
        )
        return

    if should_ignore_idle_activity(project, csv_file or window, None, duration):
        log_tracker_db(
            f"Tracker save_session skipped long idle duration: {duration.total_seconds()}s "
            f"> {MAX_RECORDED_IDLE_SECONDS}s."
        )
        return

    file_exists = os.path.isfile(CSV_FILE)

    with open(

        CSV_FILE,
        "a",
        newline="",
        encoding="utf-8"

    ) as file:

        writer = csv.writer(file)

        # ---------------------------------
        # WRITE HEADER
        # ---------------------------------
        if not file_exists:

            writer.writerow([

                "Project Name",
                "App Name",
                "Project",
                "File Name",
                "Start Time",
                "End Time",
                "Duration"

        ])

        # ---------------------------------
        # WRITE DATA
        # ---------------------------------
        writer.writerow([

            project,
            window,
            csv_project,
            csv_file,
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            str(duration)

        ])

        file.flush()
        os.fsync(file.fileno())

    print("Calling PostgreSQL activity insert function")
    db_saved = save_tracked_activity(
        project_name=project,
        window_title=window,
        file_name=csv_file,
        start_time=start,
        end_time=end,
        duration=duration,
    )
    print(f"PostgreSQL activity insert: {'success' if db_saved else 'skipped/failed'}")
    log_tracker_db(
        f"Tracker PostgreSQL insert result: {'success' if db_saved else 'skipped/failed'}, "
        f"project={project!r}, window={window!r}."
    )

# -----------------------------------------
# SHUTDOWN POPUP
# -----------------------------------------
def shutdown_popup(exit_process=True):

    global shutdown_done
    global last_window
    global start_time

    # prevent duplicate execution
    if shutdown_done:

        return

    shutdown_done = True

    if last_window and start_time:

        project = get_project(last_window)

        if project:

            save_session(
                project,
                last_window,
                start_time,
                datetime.now()
            )

    clear_tracker_pid()

    print("\nTracker Closed Safely [OK]")

    # ---------------------------------
    # FORCE TERMINATE PROCESS
    # ---------------------------------
    if exit_process:

        os._exit(0)

# -----------------------------------------
# EXIT HANDLERS
# -----------------------------------------
atexit.register(shutdown_popup)

def handle_exit(signum, frame):

    global running

    running = False

    sys.exit()

if threading.current_thread() is threading.main_thread():

    signal.signal(signal.SIGINT, handle_exit)

    signal.signal(signal.SIGTERM, handle_exit)

def stop_tracker(exit_process=True):

    global running

    running = False

    shutdown_popup(exit_process=exit_process)


def pause_tracking():
    global tracking_paused
    tracking_paused = True
    log_tracker_db("Tracking paused from tray menu.")


def resume_tracking():
    global tracking_paused, start_time, last_window
    tracking_paused = False
    start_time = datetime.now()
    last_window = get_active_window()
    log_tracker_db("Tracking resumed from tray menu.")

def start_activity_listeners():
    global keyboard_listener
    global mouse_listener

    keyboard_listener = keyboard.Listener(on_press=update_activity)
    keyboard_listener.start()

    mouse_listener = mouse.Listener(
        on_move=update_activity,
        on_click=update_activity,
        on_scroll=update_activity,
    )
    mouse_listener.start()


def stop_activity_listeners():
    for listener in (keyboard_listener, mouse_listener):
        try:
            if listener:
                listener.stop()
        except Exception as error:
            print(f"Unable to stop activity listener: {error}")

# -----------------------------------------
# TRACKING ENGINE
# -----------------------------------------
def start_tracking():

    global last_window
    global start_time
    global last_loop_time

    if not require_authenticated_user():
        return

    write_tracker_pid()
    start_activity_listeners()

    print("TRACKER STARTED")
    # ---------------------------------
    # START TRAY APP
    # ---------------------------------
    tray_thread = threading.Thread(

        target=run_tray,

        args=(stop_tracker,),
        kwargs={"pause_handler": pause_tracking, "resume_handler": resume_tracking, "role": "employee"},

        daemon=True

    )

    tray_thread.start()

    print("CSV:", CSV_FILE)

    start_time = datetime.now()

    last_window = get_active_window()

    # FIX: initialize loop timer
    last_loop_time = datetime.now()

    while running and not stop_requested():
        if tracking_paused:
            last_loop_time = datetime.now()
            time.sleep(1)
            continue

        # ---------------------------------
        # DETECT SYSTEM SLEEP
        # ---------------------------------
        current_loop_time = datetime.now()

        # FIX: prevent NoneType error
        if last_loop_time is None:
            last_loop_time = current_loop_time

        time_gap = (

            current_loop_time - last_loop_time

        ).total_seconds()

        # ---------------------------------
        # SYSTEM WAS SUSPENDED
        # ---------------------------------
        if time_gap > 15:

            wake_time = datetime.now()

            sleep_duration = wake_time - last_loop_time

            save_session(
                "SLEEP",
                "System Sleep",
                last_loop_time,
                wake_time
            )

            # Sleep detected

            start_time = datetime.now()

            last_window = get_active_window()

        # ---------------------------------
        # UPDATE LOOP TIME
        # ---------------------------------
        last_loop_time = datetime.now()

        current_window = get_active_window()

        # ---------------------------------
        # CHECK USER IDLE TIME
        # ---------------------------------
        idle_duration = (

            datetime.now() - last_activity_time

        ).total_seconds()

        # ---------------------------------
        # USER IS IDLE
        # ---------------------------------
        if idle_duration >= IDLE_THRESHOLD and last_window != "IDLE":

            end_time = datetime.now()

            project = get_project(last_window)

            if project:

                save_session(

                    project,
                    last_window,
                    start_time,
                    end_time

                )

            # ---------------------------------
            # START IDLE SESSION
            # ---------------------------------
            start_time = datetime.now()

            last_window = "IDLE"

        # ---------------------------------
        # USER ACTIVE AGAIN
        # ---------------------------------
        elif idle_duration < IDLE_THRESHOLD and last_window == "IDLE":

            end_time = datetime.now()

            # ---------------------------------
            # SAVE IDLE SESSION
            # ---------------------------------
            save_session(

                "IDLE",
                "System Idle",
                start_time,
                end_time

            )

            # ---------------------------------
            # RESUME TRACKING
            # ---------------------------------
            start_time = datetime.now()

            last_window = current_window

        # ---------------------------------
        # WINDOW CHANGE DETECTED
        # ---------------------------------
        elif current_window != last_window and last_window != "IDLE":

            end_time = datetime.now()

            project = get_project(last_window)

            if project:

                save_session(

                    project,
                    last_window,
                    start_time,
                    end_time

                )

            start_time = datetime.now()

            last_window = current_window

        time.sleep(2)

    stop_activity_listeners()
    shutdown_popup(exit_process=False)

# -----------------------------------------
# MAIN
# -----------------------------------------
if __name__ == "__main__":

    start_tracking()
