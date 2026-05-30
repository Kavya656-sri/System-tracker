import time
import csv
import os
import atexit
import signal
import sys
import tkinter as tk
from tkinter import messagebox
from datetime import datetime

import pyautogui
from pynput import keyboard, mouse

# -----------------------------------------
# IMPORT MODULES
# -----------------------------------------
from report_generator import generate_report
from dashboard import open_dashboard
from tray_app import run_tray
import threading

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
def get_project(window_title):

    if window_title.startswith("C:\\"):
        return None

    title = window_title.lower()

    ignored_apps = [

        "python.exe",
        "task scheduler",
        "windows input experience",
        "search",
        "start",
        "lockapp",
        "widgets",

    ]

    if any(app in title for app in ignored_apps):

        return None

    # ---------------------------------
    # DEVELOPMENT
    # ---------------------------------
    if any(x in title for x in [

        "vscode",
        "visual studio",
        "pycharm",
        ".py"
        "cmd.exe",
        "powershell",
        "terminal"

    ]):

        return "Development"

    # ---------------------------------
    # BROWSER
    # ---------------------------------
    if any(x in title for x in [

        "chrome",
        "google chrome",
        "chatgpt",
        "edge",
        "microsoft edge",
        "firefox",
        "gmail",
        "outlook",
        "github",
        "stackoverflow"

    ]):

        return "Browser Work"

    # ---------------------------------
    # ENTERTAINMENT
    # ---------------------------------
    if any(x in title for x in [

        "youtube",
        "netflix",
        "spotify"

    ]):

        return "Entertainment"

    # ---------------------------------
    # COMMUNICATION
    # ---------------------------------
    if any(x in title for x in [

        "whatsapp",
        "teams",
        "mail",
        "outlook"

    ]):

        return "Communication"

    # ---------------------------------
    # OFFICE
    # ---------------------------------
    if any(x in title for x in [

        "excel",
        "word",
        "powerpoint"

    ]):

        return "Office Work"

    # ---------------------------------
    # SHUTDOWN / LOCK / SLEEP
    # ---------------------------------
    if any(x in title for x in [

        "shut down windows",
        "lockapp",
        "windows default lock screen",
        "sign in"

    ]):

        return "IDLE"
    
    if any(x in title for x in [
        "unknown window",
        "program manager"
    ]):
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
def shutdown_popup():

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

            print("Report Generated Successfully ✔")

            # ---------------------------------
            # ASK OPEN DASHBOARD
            # ---------------------------------
            dashboard_result = messagebox.askyesno(

                "Open Dashboard",

                "Do you want to open dashboard?"

            )

            # ---------------------------------
            # OPEN DASHBOARD
            # ---------------------------------
            if dashboard_result:

                print("Opening Dashboard...")

                open_dashboard(report_data)

        else:

            print("Report generation failed ❌")

    if last_window and start_time:

        project = get_project(last_window)

        if project:

            save_session(
                project,
                last_window,
                start_time,
                datetime.now()
            )

    print("\nTracker Closed Safely ✔")

    # ---------------------------------
    # FORCE TERMINATE PROCESS
    # ---------------------------------
    os._exit(0)

# -----------------------------------------
# EXIT HANDLERS
# -----------------------------------------
atexit.register(shutdown_popup)

def handle_exit(signum, frame):

    global running

    running = False

    sys.exit()

signal.signal(signal.SIGINT, handle_exit)

signal.signal(signal.SIGTERM, handle_exit)

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

    print("====================================")
    print("TRACKER STARTED")
    print("====================================")
    # ---------------------------------
    # START TRAY APP
    # ---------------------------------
    tray_thread = threading.Thread(

        target=run_tray,

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

            print(
                f"Sleep detected: {sleep_duration}"
            )

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
        if current_window != last_window and last_window != "IDLE":

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