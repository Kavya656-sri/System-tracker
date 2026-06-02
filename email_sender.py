import csv
import html
import json
import os
from datetime import datetime

import pandas as pd
import yagmail

# -----------------------------------------
# EMAIL CONFIG
# -----------------------------------------
SENDER_EMAIL = "kavyakanagaraj2@gmail.com"
APP_PASSWORD = "bwtl ngcf pbei cftg"
RECEIVER_EMAIL = "23cb023@drngpit.ac.in"


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

CODING_TOOLS = [
    "visual studio code",
    "antigravity ide",
    "cursor",
    "codex",
    "firo",
    "vscode",
]


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


def normalize_title(value):

    return (
        str(value)
        .replace("â— ", "")
        .replace("â€‹", "")
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

    df = pd.read_csv("activity_log.csv")
    df.columns = df.columns.str.strip()
    df["Duration"] = pd.to_timedelta(df["Duration"])

    totals = {}

    for _, row in df.iterrows():
        title = normalize_title(row["App Name"])
        duration = row["Duration"]

        if any(keyword.lower() in title.lower() for keyword in IDLE_KEYWORDS):
            folder = "Idle Time"
        elif is_google_chrome(title):
            folder = "Google Chrome"
        elif is_microsoft_edge(title):
            folder = "Microsoft Edge"
        else:
            editor_folder = extract_editor_folder(title)
            saved_project_folder = get_saved_project_folder(row)

            if editor_folder:
                folder = editor_folder
            elif saved_project_folder:
                folder = saved_project_folder
            elif is_coding_tool(title):
                continue
            else:
                folder = "Others"

        totals[folder] = totals.get(folder, pd.Timedelta(0)) + duration

    chrome_total = totals.pop("Google Chrome", pd.Timedelta(0))
    edge_total = totals.pop("Microsoft Edge", pd.Timedelta(0))
    idle_total = totals.pop("Idle Time", pd.Timedelta(0))
    others_total = totals.pop("Others", pd.Timedelta(0))

    rows = []

    for folder_name, duration in sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        rows.append((folder_name, format_duration(duration)))

    if chrome_total.total_seconds() > 0:
        rows.append(("Google Chrome", format_duration(chrome_total)))
    if edge_total.total_seconds() > 0:
        rows.append(("Microsoft Edge", format_duration(edge_total)))
    if idle_total.total_seconds() > 0:
        rows.append(("Idle Time", format_duration(idle_total)))

    rows.append(("Others", format_duration(others_total)))

    return rows


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
        return render_summary_table(build_summary_rows())
    except Exception as error:
        print("Failed to generate timesheet:", error)
        return render_summary_table([("Others", "00:00:00")])


def build_email_body():

    table = generate_timesheet()

    return f"""<html>
<body>
{table}
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
def send_email(subject=None, body=None, report_data=None):

    print("USING NEW EMAIL_SENDER.PY")
    print("\n====================================")
    print("SENDING EMAIL")
    print("====================================")

    try:
        if not subject:
            subject = f"Daily Productivity Report - {get_today_date()}"

        body = build_email_body()

        print("\n===== TIMESHEET REPORT =====")
        print(generate_timesheet())
        print("===========================\n")

        yag = yagmail.SMTP(
            user=SENDER_EMAIL,
            password=APP_PASSWORD,
        )

        yag.send(
            to=RECEIVER_EMAIL,
            subject=subject,
            contents=yagmail.raw(body),
        )

        print("====================================")
        print("EMAIL SENT SUCCESSFULLY")
        print("====================================")

        try:
            status_data = {
                "last_status": "success",
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error_message": None,
            }
            with open("email_status.json", "w") as status_file:
                json.dump(status_data, status_file)
        except Exception as status_error:
            print("Failed to save success status to email_status.json:", status_error)

        clear_activity_log()

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
            with open("email_status.json", "w") as status_file:
                json.dump(status_data, status_file)
        except Exception as status_error:
            print("Failed to save failed status to email_status.json:", status_error)

        return False
