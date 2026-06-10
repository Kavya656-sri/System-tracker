import os
import subprocess
import sys
import time
import webbrowser
import socket
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from activity_store import get_active_tracker_user


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(BASE_DIR, "app.py")
APP_URL = "http://127.0.0.1:5000"

tracker_stop_callback = None
pause_callback = None
resume_callback = None


def create_image():
    image = Image.new("RGB", (64, 64), color=(17, 24, 39))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((14, 14, 50, 50), radius=8, fill=(255, 255, 255))
    draw.rectangle((22, 24, 42, 29), fill=(37, 99, 235))
    draw.rectangle((22, 34, 42, 39), fill=(20, 184, 166))
    return image


def port_is_open(port=5000):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ensure_dashboard_server():
    if not port_is_open(5000):
        subprocess.Popen([sys.executable, APP_PATH], cwd=BASE_DIR)
        time.sleep(3)


def open_url(path):
    ensure_dashboard_server()
    webbrowser.open(APP_URL + path)


def get_tray_user():
    active_user = get_active_tracker_user() or {}
    role = os.getenv("TRAY_USER_ROLE") or active_user.get("role") or "employee"
    return {
        "role": str(role or "employee").strip().lower(),
        "user_id": os.getenv("TRAY_USER_ID") or active_user.get("user_id"),
        "employee_name": os.getenv("TRAY_USER_NAME") or active_user.get("employee_name") or "",
    }


def open_employee_dashboard(icon=None, menu_item=None):
    open_url("/dashboard")


def open_today_activity(icon=None, menu_item=None):
    open_url("/activity-log")


def open_weekly_report(icon=None, menu_item=None):
    open_url("/reports")


def open_productivity_summary(icon=None, menu_item=None):
    open_url("/productivity")


def open_manager_dashboard(icon=None, menu_item=None):
    open_url("/manager")


def open_employee_reports(icon=None, menu_item=None):
    open_url("/reports")


def open_team_summary(icon=None, menu_item=None):
    open_url("/analytics/team")


def pause_tracking(icon=None, menu_item=None):
    if pause_callback:
        pause_callback()


def resume_tracking(icon=None, menu_item=None):
    if resume_callback:
        resume_callback()


def exit_action(icon, menu_item):
    print("\nStopping tray application...")
    if tracker_stop_callback:
        tracker_stop_callback(exit_process=False)
    icon.stop()
    print("Tray application closed.")
    os._exit(0)


def build_employee_menu():
    return pystray.Menu(
        item("Open Dashboard", open_employee_dashboard),
        item("My Today's Activity", open_today_activity),
        item("My Weekly Report", open_weekly_report),
        item("My Productivity Summary", open_productivity_summary),
        pystray.Menu.SEPARATOR,
        item("Pause Tracking", pause_tracking),
        item("Resume Tracking", resume_tracking),
        pystray.Menu.SEPARATOR,
        item("Exit", exit_action),
    )


def build_manager_menu():
    return pystray.Menu(
        item("Open Manager Dashboard", open_manager_dashboard),
        item("Employee Reports", open_employee_reports),
        item("Team Summary", open_team_summary),
        pystray.Menu.SEPARATOR,
        item("Exit", exit_action),
    )


def run_tray(stop_callback=None, pause_handler=None, resume_handler=None, role=None):
    global tracker_stop_callback, pause_callback, resume_callback
    tracker_stop_callback = stop_callback
    pause_callback = pause_handler
    resume_callback = resume_handler

    user = get_tray_user()
    role = str(role or user["role"] or "employee").strip().lower()
    menu = build_manager_menu() if role == "manager" else build_employee_menu()
    title = "Manager Productivity Console" if role == "manager" else "Productivity Tracker"

    icon = pystray.Icon("Productivity Tracker", create_image(), title, menu=menu)
    icon.run()


if __name__ == "__main__":
    cli_role = None
    if "--role" in sys.argv:
        index = sys.argv.index("--role")
        if index + 1 < len(sys.argv):
            cli_role = sys.argv[index + 1]
    run_tray(role=cli_role)
