# import time
# from datetime import datetime
# import win32gui
# import csv
# import os
# import ctypes


# # ==========================================
# # IDLE TIME DETECTION
# # ==========================================

# class LASTINPUTINFO(ctypes.Structure):

#     _fields_ = [
#         ('cbSize', ctypes.c_uint),
#         ('dwTime', ctypes.c_uint),
#     ]


# def get_idle_time():

#     last_input_info = LASTINPUTINFO()

#     last_input_info.cbSize = ctypes.sizeof(LASTINPUTINFO)

#     ctypes.windll.user32.GetLastInputInfo(
#         ctypes.byref(last_input_info)
#     )

#     millis = (
#         ctypes.windll.kernel32.GetTickCount()
#         - last_input_info.dwTime
#     )

#     return millis / 1000.0


# # ==========================================
# # PROJECT DETECTION
# # ==========================================

# def detect_project(window_title):

#     title = window_title.lower()

#     if "leetcode" in title:
#         return "Learning"

#     elif "portfolio" in title:
#         return "Portfolio Website"

#     elif "xerox" in title:
#         return "Xerox Automation"

#     elif "visual studio code" in title:
#         return "Development"

#     elif "chrome" in title:
#         return "Browser Work"

#     elif "outlook" in title:
#         return "Communication"

#     elif "excel" in title:
#         return "Excel Work"

#     elif "word" in title:
#         return "Documentation"

#     else:
#         return "Other"


# # ==========================================
# # CONFIGURATION
# # ==========================================

# current_window = ""

# start_time = datetime.now()

# csv_file = "activity_log.csv"

# # Idle limit in seconds
# IDLE_LIMIT = 10

# is_idle = False
# idle_start_time = None


# # ==========================================
# # CREATE CSV FILE
# # ==========================================

# if not os.path.exists(csv_file):

#     with open(csv_file,
#               mode="w",
#               newline="",
#               encoding="utf-8") as file:

#         writer = csv.writer(
#             file,
#             quoting=csv.QUOTE_ALL
#         )

#         writer.writerow([
#             "Project Name",
#             "App Name",
#             "Start Time",
#             "End Time",
#             "Duration"
#         ])


# print("Tracker Started...\n")


# # ==========================================
# # MAIN TRACKING LOOP
# # ==========================================

# while True:

#     idle_time = get_idle_time()

#     # ==========================================
#     # USER IS IDLE
#     # ==========================================

#     if idle_time > IDLE_LIMIT:

#         # First time entering idle state
#         if not is_idle:

#             is_idle = True

#             idle_start_time = datetime.now()

#             print("\nUser is IDLE")

#         time.sleep(1)

#         continue

#     # ==========================================
#     # USER RETURNED FROM IDLE
#     # ==========================================

#     else:

#         if is_idle:

#             idle_end_time = datetime.now()

#             idle_duration = idle_end_time - idle_start_time

#             print("\nUser became ACTIVE")

#             print("Idle Start :", idle_start_time.strftime("%H:%M:%S"))
#             print("Idle End   :", idle_end_time.strftime("%H:%M:%S"))
#             print("Idle Time  :", idle_duration)

#             # Save idle session into CSV
#             with open(csv_file,
#                       mode="a",
#                       newline="",
#                       encoding="utf-8") as file:

#                 writer = csv.writer(
#                     file,
#                     quoting=csv.QUOTE_ALL
#                 )

#                 writer.writerow([
#                     "IDLE",
#                     "No Application",
#                     idle_start_time.strftime("%H:%M:%S"),
#                     idle_end_time.strftime("%H:%M:%S"),
#                     str(idle_duration)
#                 ])

#             is_idle = False

#     # ==========================================
#     # ACTIVE WINDOW TRACKING
#     # ==========================================

#     hwnd = win32gui.GetForegroundWindow()

#     window_title = win32gui.GetWindowText(hwnd)

#     # Ignore empty window titles
#     if window_title.strip() == "":

#         time.sleep(1)

#         continue

#     # Detect window switch
#     if window_title != current_window:

#         end_time = datetime.now()

#         # Save previous session
#         if current_window != "":

#             duration = end_time - start_time

#             project_name = detect_project(current_window)

#             print("\n--------------------------")
#             print("Project Name   :", project_name)
#             print("Previous Window:", current_window)
#             print("Start Time     :", start_time.strftime("%H:%M:%S"))
#             print("End Time       :", end_time.strftime("%H:%M:%S"))
#             print("Duration       :", duration)

#             # Save into CSV
#             with open(csv_file,
#                       mode="a",
#                       newline="",
#                       encoding="utf-8") as file:

#                 writer = csv.writer(
#                     file,
#                     quoting=csv.QUOTE_ALL
#                 )

#                 writer.writerow([
#                     project_name,
#                     current_window,
#                     start_time.strftime("%H:%M:%S"),
#                     end_time.strftime("%H:%M:%S"),
#                     str(duration)
#                 ])

#         # Start tracking new window
#         current_window = window_title

#         start_time = datetime.now()

#         current_project = detect_project(current_window)

#         print("\nNow Tracking ->", current_window)
#         print("Project Name ->", current_project)

#     time.sleep(1)


import time
from datetime import datetime
import win32gui
import csv
import os
import ctypes


# ==========================================
# IDLE TIME DETECTION
# ==========================================

class LASTINPUTINFO(ctypes.Structure):

    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint)
    ]


def get_idle_time():

    last_input_info = LASTINPUTINFO()

    last_input_info.cbSize = ctypes.sizeof(LASTINPUTINFO)

    ctypes.windll.user32.GetLastInputInfo(
        ctypes.byref(last_input_info)
    )

    millis = (
        ctypes.windll.kernel32.GetTickCount64()
        - last_input_info.dwTime
    )

    return millis / 1000.0


# ==========================================
# PROJECT DETECTION
# ==========================================
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


def detect_project(window_title):

    clean_title = normalize_window_title(window_title)
    title = clean_title.lower()

    if "leetcode" in title:
        return "Learning"

    elif "portfolio" in title:
        return "Portfolio Website"

    elif "xerox" in title:
        return "Xerox Automation"

    elif "chrome" in title:
        return "Google Chrome"

    elif "edge" in title:
        return "Microsoft Edge"

    coding_project = extract_coding_project(clean_title)

    if coding_project:
        return coding_project

    if any(tool in title for tool in CODING_TOOLS):
        return None

    if "outlook" in title:
        return "Communication"

    if "excel" in title:
        return "Excel Work"

    if "word" in title:
        return "Documentation"

    return "Other"


# ==========================================
# CONFIGURATION
# ==========================================

current_window = ""

start_time = datetime.now()

csv_file = "activity_log.csv"

IDLE_LIMIT = 5

is_idle = False
idle_start_time = None


# ==========================================
# CREATE CSV FILE
# ==========================================

if (
    not os.path.exists(csv_file)
    or os.path.getsize(csv_file) == 0
):

    with open(
        csv_file,
        mode="w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(
            file,
            quoting=csv.QUOTE_ALL
        )

        writer.writerow([
            "Project Name",
            "App Name",
            "Start Time",
            "End Time",
            "Duration"
        ])


print("====================================")
print("TRACKER STARTED")
print("====================================")

print("CSV File Path:")
print(os.path.abspath(csv_file))


# ==========================================
# MAIN LOOP
# ==========================================

while True:

    try:

        # ==========================================
        # CHECK IDLE TIME
        # ==========================================

        idle_time = get_idle_time()

        # ==========================================
        # USER IS IDLE
        # ==========================================

        if idle_time > IDLE_LIMIT:

            if not is_idle:

                is_idle = True

                idle_start_time = datetime.now()

                # User is idle

                # SAVE CURRENT SESSION BEFORE IDLE
                if current_window != "":

                    idle_start = datetime.now()

                    duration = idle_start - start_time

                    project_name = detect_project(
                        current_window
                    )

                    with open(
                        csv_file,
                        mode="a",
                        newline="",
                        encoding="utf-8"
                    ) as file:

                        writer = csv.writer(
                            file,
                            quoting=csv.QUOTE_ALL
                        )

                        writer.writerow([
                            project_name,
                            current_window,
                            start_time.strftime("%H:%M:%S"),
                            idle_start.strftime("%H:%M:%S"),
                            str(duration)
                        ])



            time.sleep(1)

            continue

        # ==========================================
        # USER BECAME ACTIVE
        # ==========================================

        else:

            if is_idle:

                idle_end_time = datetime.now()

                idle_duration = (
                    idle_end_time - idle_start_time
                )

                # User became active

                # SAVE IDLE SESSION
                with open(
                    csv_file,
                    mode="a",
                    newline="",
                    encoding="utf-8"
                ) as file:

                    writer = csv.writer(
                        file,
                        quoting=csv.QUOTE_ALL
                    )

                    writer.writerow([
                        "IDLE",
                        "No Application",
                        idle_start_time.strftime("%H:%M:%S"),
                        idle_end_time.strftime("%H:%M:%S"),
                        str(idle_duration)
                    ])



                is_idle = False

                start_time = datetime.now()

        # ==========================================
        # GET ACTIVE WINDOW
        # ==========================================

        hwnd = win32gui.GetForegroundWindow()

        window_title = win32gui.GetWindowText(hwnd)

        # Ignore empty window titles
        if window_title.strip() == "":

            time.sleep(1)

            continue

        # ==========================================
        # WINDOW SWITCH DETECTED
        # ==========================================

        if window_title != current_window:

            end_time = datetime.now()

            # SAVE PREVIOUS WINDOW
            if current_window != "":

                duration = end_time - start_time

                project_name = detect_project(
                    current_window
                )

                # Session window changed

                with open(
                    csv_file,
                    mode="a",
                    newline="",
                    encoding="utf-8"
                ) as file:

                    writer = csv.writer(
                        file,
                        quoting=csv.QUOTE_ALL
                    )

                    writer.writerow([
                        project_name,
                        current_window,
                        start_time.strftime("%H:%M:%S"),
                        end_time.strftime("%H:%M:%S"),
                        str(duration)
                    ])



            # START NEW SESSION
            current_window = window_title

            start_time = datetime.now()

            current_project = detect_project(
                current_window
            )

            # Now tracking new window

        time.sleep(1)

    # ==========================================
    # STOP TRACKER SAFELY
    # ==========================================

    except KeyboardInterrupt:

        print("\n====================================")
        print("STOPPING TRACKER")
        print("====================================")

        # SAVE FINAL SESSION
        if current_window != "":

            end_time = datetime.now()

            duration = end_time - start_time

            project_name = detect_project(
                current_window
            )

            with open(
                csv_file,
                mode="a",
                newline="",
                encoding="utf-8"
            ) as file:

                writer = csv.writer(
                    file,
                    quoting=csv.QUOTE_ALL
                )

                writer.writerow([
                    project_name,
                    current_window,
                    start_time.strftime("%H:%M:%S"),
                    end_time.strftime("%H:%M:%S"),
                    str(duration)
                ])

                print("Final Session Saved")

        break

    # ==========================================
    # HANDLE ERRORS
    # ==========================================

    except Exception as e:

        print("\nERROR :", e)

        time.sleep(1)
