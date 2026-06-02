import time
import csv
import os
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
from report_generator import generate_report
from dashboard import open_dashboard
from tray_app import run_tray

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

running = True
last_window = None
start_time = None
last_loop_time = None

last_activity_time = datetime.now()

IDLE_THRESHOLD = 60  # seconds

shutdown_done = False

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

    if win32gui:

        window = win32gui.GetWindowText(

            win32gui.GetForegroundWindow()

        )

        if not window.strip():

            return "Unknown Window"

        return window

    return "Unknown Window"

# -----------------------------------------
# PROJECT CLASSIFICATION
# -----------------------------------------
CODING_TOOLS = [
    "visual studio code",
    "antigravity ide",
    "cursor",
    "codex",
    "firo",
    "vscode",
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


def extract_coding_project(window_title):

    clean_title = normalize_window_title(window_title)
    parts = [part.strip() for part in clean_title.split(" - ") if part.strip()]

    for index, part in enumerate(parts):
        if any(tool in part.lower() for tool in CODING_TOOLS):
            for candidate in reversed(parts[:index]):
                if not is_file_name(candidate):
                    return candidate

            return None

    if any(tool in clean_title.lower() for tool in CODING_TOOLS):
        for candidate in reversed(parts[:-1]):
            if not is_file_name(candidate):
                return candidate

        return None

    return None


def get_project(window_title):

    if window_title.startswith("C:\\"):
        return None

    clean_title = normalize_window_title(window_title)
    title = clean_title.lower()

    ignored_apps = [
        "python.exe",
        "windows input experience",
        "lockapp",
        "widgets",
    ]

    if any(app in title for app in ignored_apps):
        return None

    if any(x in title for x in ["chrome", "google chrome"]):
        return "Google Chrome"

    if any(x in title for x in ["edge", "microsoft edge"]):
        return "Microsoft Edge"

    coding_project = extract_coding_project(clean_title)

    if coding_project:
        return coding_project

    if any(tool in title for tool in CODING_TOOLS):
        return None

    if any(x in title for x in ["chatgpt", "firefox", "gmail", "outlook", "github", "stackoverflow"]):
        return "Browser Work"

    if any(x in title for x in ["youtube", "netflix", "spotify"]):
        return "Entertainment"

    if any(x in title for x in ["whatsapp", "teams", "mail"]):
        return "Communication"

    if any(x in title for x in ["excel", "word", "powerpoint"]):
        return "Office Work"

    if any(x in title for x in ["shut down windows", "lockapp", "windows default lock screen", "sign in"]):
        return "IDLE"
    
    if any(x in title for x in ["unknown window", "program manager"]):
        return "SLEEP"

    return "Other"

# -----------------------------------------
# SAVE SESSION
# -----------------------------------------
def save_session(project, window, start, end):

    duration = end - start

    # ignore very short sessions
    if duration.total_seconds() < 3:

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
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            str(duration)

        ])

        file.flush()
        os.fsync(file.fileno())

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

    root = tk.Tk()

    root.withdraw()

    # ---------------------------------
    # ASK GENERATE REPORT
    # ---------------------------------
    generate_result = messagebox.askyesno(

        "Tracker Shutdown",

        "Generate Report?"

    )

    # ---------------------------------
    # GENERATE REPORT
    # ---------------------------------
    if generate_result:

        print("\nGenerating Report...")

        report_data = generate_report()

        if report_data:

            print("Report Generated Successfully [OK]")

            print("Opening Dashboard...")

            open_dashboard()
            # open_dashboard handles launching Flask if not running and opening browser

        else:

            print("Report generation failed [ERROR]")

    if last_window and start_time:

        project = get_project(last_window)

        if project:

            save_session(
                project,
                last_window,
                start_time,
                datetime.now()
            )

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

# -----------------------------------------
# START KEYBOARD LISTENER
# -----------------------------------------
keyboard_listener = keyboard.Listener(

    on_press=update_activity

)

keyboard_listener.start()

# -----------------------------------------
# START MOUSE LISTENER
# -----------------------------------------
mouse_listener = mouse.Listener(

    on_move=update_activity,
    on_click=update_activity,
    on_scroll=update_activity

)

mouse_listener.start()

# -----------------------------------------
# TRACKING ENGINE
# -----------------------------------------
def start_tracking():

    global last_window
    global start_time
    global last_loop_time

    print("TRACKER STARTED")
    # ---------------------------------
    # START TRAY APP
    # ---------------------------------
    tray_thread = threading.Thread(

        target=run_tray,

        args=(stop_tracker,),

        daemon=True

    )

    tray_thread.start()

    print("CSV:", CSV_FILE)

    start_time = datetime.now()

    last_window = get_active_window()

    # FIX: initialize loop timer
    last_loop_time = datetime.now()

    while running:

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

# -----------------------------------------
# MAIN
# -----------------------------------------
if __name__ == "__main__":

    start_tracking()
