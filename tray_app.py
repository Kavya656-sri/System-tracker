import os
import sys
import threading
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from report_generator import generate_report
from dashboard import open_dashboard
from email_sender import send_email

# -----------------------------------------
# CREATE TRAY ICON IMAGE
# -----------------------------------------
def create_image():

    width = 64
    height = 64

    image = Image.new(

        "RGB",

        (width, height),

        color=(0, 102, 204)

    )

    draw = ImageDraw.Draw(image)

    draw.rectangle(

        (16, 16, 48, 48),

        fill="white"

    )

    return image

# -----------------------------------------
# OPEN DASHBOARD
# -----------------------------------------
def dashboard_action(icon, item):

    open_dashboard()

# -----------------------------------------
# GENERATE REPORT
# -----------------------------------------
def report_action(icon, item):

    generate_report()

# -----------------------------------------
# SEND EMAIL
# -----------------------------------------
def email_action(icon, item):

    send_email()

# -----------------------------------------
# EXIT APPLICATION
# -----------------------------------------
def exit_action(icon, item):

    print("\nStopping Tracker...")

    import start_tracker

    # ---------------------------------
    # STOP TRACKER LOOP
    # ---------------------------------
    start_tracker.running = False

    # ---------------------------------
    # STOP TRAY ICON
    # ---------------------------------
    icon.stop()

    print("Tracker Fully Closed ✔")

    # ---------------------------------
    # FORCE FULL EXIT
    # ---------------------------------
    os._exit(0)

# -----------------------------------------
# RUN TRAY ICON
# -----------------------------------------
def run_tray():

    icon = pystray.Icon(

        "Productivity Tracker",

        create_image(),

        "Productivity Tracker",

        menu=pystray.Menu(

            item("Open Dashboard", dashboard_action),

            item("Generate Report", report_action),

            item("Send Email", email_action),

            item("Exit Tracker", exit_action)

        )

    )

    icon.run()

# -----------------------------------------
# START TRAY APP
# -----------------------------------------
if __name__ == "__main__":

    tray_thread = threading.Thread(

        target=run_tray

    )

    tray_thread.start()