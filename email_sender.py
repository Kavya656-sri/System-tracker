import yagmail
import os
import csv
import pandas as pd
from datetime import datetime
from tabulate import tabulate
# -----------------------------------------
# EMAIL CONFIG
# -----------------------------------------
SENDER_EMAIL = "kavyakanagaraj2@gmail.com"

APP_PASSWORD = "bwtl ngcf pbei cftg"

RECEIVER_EMAIL = "23cb023@drngpit.ac.in"

# -----------------------------------------
# GET TODAY DATE
# -----------------------------------------
def get_today_date():

    return datetime.now().strftime("%Y-%m-%d")

# -----------------------------------------
# GET REPORT FILES
# -----------------------------------------
def get_report_files():

    date = get_today_date()

    # ---------------------------------
    # PIE CHART PATH
    # ---------------------------------
    pie_chart = f"charts/project_pie_chart_{date}.png"

    # ---------------------------------
    # ATTACHMENTS LIST
    # ---------------------------------
    attachments = []

    # ---------------------------------
    # ONLY ATTACH PIE CHART
    # ---------------------------------
    if os.path.exists(pie_chart):

        attachments.append(pie_chart)

    # CREATE EXCEL TIMESHEET AND ATTACH IF EXISTS
    timesheet_excel = create_timesheet_excel()
    if os.path.exists(timesheet_excel):
        attachments.append(timesheet_excel)

    return attachments



# -----------------------------------------
# FORMAT DURATION
# -----------------------------------------
def format_duration(duration):

    total_seconds = int(duration.total_seconds())

    hours = total_seconds // 3600

    minutes = (total_seconds % 3600) // 60

    seconds = total_seconds % 60

    return f"{hours:02}:{minutes:02}:{seconds:02}"

# -----------------------------------------
# FORMAT TASK NAME
# -----------------------------------------
def format_task_name(window_title):

    title = str(window_title)

    # ---------------------------------
    # GOOGLE CHROME
    # ---------------------------------
    if " - Google Chrome" in title:

        task = title.replace(
            " - Google Chrome",
            ""
        )

        return f"Google Chrome - {task}"

    # ---------------------------------
    # MICROSOFT EDGE
    # ---------------------------------
    if " - Microsoft Edge" in title:

        task = title.replace(
            " - Microsoft Edge",
            ""
        )

        return f"Microsoft Edge - {task}"

    # ---------------------------------
    # VISUAL STUDIO CODE
    # ---------------------------------
    if " - Visual Studio Code" in title:

        file_name = title.split(" - ")[0]

        return f"VS Code - {file_name}"

    # ---------------------------------
    # EXCEL
    # ---------------------------------
    if " - Excel" in title:

        task = title.replace(
            " - Excel",
            ""
        )

        return f"Excel - {task}"

    return title


# -----------------------------------------
# GENERATE TIMESHEET
# -----------------------------------------
def generate_timesheet():

    try:

        df = pd.read_csv("activity_log.csv")

        print(df["App Name"].tolist())

        df.columns = df.columns.str.strip()

        df["Duration"] = pd.to_timedelta(
            df["Duration"]
        )

        task_summary = df.groupby(
            "App Name"
        )["Duration"].sum().reset_index()

        task_summary = task_summary.sort_values(
            by="Duration",
            ascending=False
        )

        work_section = ""

        system_section = ""

        system_keywords = [

            "System Idle",
            "Tracker Shutdown",
            "Unknown Window",
            "Program Manager",
            "Shut Down Windows"

        ]

        for _, row in task_summary.iterrows():

            task_name = format_task_name(
                row["App Name"]
            )

            duration = format_duration(
                row["Duration"]
            )

            line = f"{task_name}\t{duration}\n"

            if any(

                keyword.lower() in task_name.lower()

                for keyword in system_keywords

            ):

                system_section += line

            else:

                work_section += line

        report = f"""
========================================
WORK TIMESHEET
========================================

{work_section}

========================================
SYSTEM ACTIVITY
========================================

{system_section}

========================================
"""

        return report

    except Exception as e:

        return f"Failed to generate timesheet\n{e}"



# -----------------------------------------
# CREATE EXCEL TIMESHEET
# -----------------------------------------
def create_timesheet_excel():

    if os.path.exists("email_timesheet.csv"):

        df = pd.read_csv("email_timesheet.csv")

    else:

        df = pd.read_csv("activity_log.csv")

    df.columns = df.columns.str.strip()

    df["Duration"] = pd.to_timedelta(df["Duration"])

    task_summary = df.groupby(
        "App Name"
    )["Duration"].sum().reset_index()

    rows = []

    for _, row in task_summary.iterrows():

        title = str(row["App Name"])

        duration = format_duration(
            row["Duration"]
        )

        app_name = "Other"
        work_name = title

        # Chrome
        if " - Google Chrome" in title:

            app_name = "Google Chrome"
            work_name = title.replace(
                " - Google Chrome",
                ""
            )

        # Edge
        elif " - Microsoft Edge" in title:

            app_name = "Microsoft Edge"
            work_name = title.replace(
                " - Microsoft Edge",
                ""
            )

        # VS Code
        elif " - Visual Studio Code" in title:

            app_name = "VS Code"
            work_name = title.replace(
                " - Visual Studio Code",
                ""
            )

        # Excel
        elif "Excel" in title:

            app_name = "Excel"
            work_name = title.replace(
                " - Excel",
                ""
            )

        # System Activities
        elif title in [
            "System Idle",
            "Unknown Window",
            "Program Manager",
            "Tracker Shutdown",
            "Shut Down Windows",
            "System Sleep"
        ]:

            app_name = "System"

        rows.append([
            app_name,
            work_name,
            duration
        ])

    report_df = pd.DataFrame(

        rows,

        columns=[
            "Application",
            "Work Done",
            "Duration"
        ]

    )

    os.makedirs("reports", exist_ok=True)

    file_name = (
        f"reports/timesheet_{get_today_date()}.xlsx"
    )

    report_df.to_excel(
        file_name,
        index=False
    )

    print("Timesheet Excel Created ✔")

    return file_name
# -----------------------------------------
# SEND EMAIL FUNCTION
# -----------------------------------------
# -----------------------------------------
# CLEAR ACTIVITY LOG
# -----------------------------------------
def clear_activity_log():

    try:

        with open(

            "activity_log.csv",

            "w",

            newline="",

            encoding="utf-8"

        ) as file:

            writer = csv.writer(file)

            # ---------------------------------
            # WRITE HEADER ONLY
            # ---------------------------------
            writer.writerow([

                "Project Name",
                "App Name",
                "Start Time",
                "End Time",
                "Duration"

            ])

        print("Activity log cleared ✔")

    except Exception as e:

        print("Failed to clear activity log ❌")

        print(e)
def send_email(report_data=None):

    print("USING NEW EMAIL_SENDER.PY")

    print("\n====================================")
    print("SENDING EMAIL")
    print("====================================")

    try:

        # ---------------------------------
        # GET ATTACHMENTS
        # ---------------------------------
        attachments = get_report_files()

        # ---------------------------------
        # EMAIL SUBJECT
        # ---------------------------------
        subject = f"Daily Productivity Report - {get_today_date()}"

        # ---------------------------------
        # SUMMARY DATA
        # ---------------------------------
        summary = ""

        if report_data and "summary" in report_data:

            s = report_data["summary"]

            summary = f"""
Daily Productivity Summary

Date: {s.get('date')}

Total Sessions         : {s.get('total_sessions')}
Productive Sessions    : {s.get('productive_sessions')}
Entertainment Sessions : {s.get('entertainment_sessions')}
Idle Sessions          : {s.get('idle_sessions')}
Productivity Score     : {s.get('productivity_score')} %
"""

        # ---------------------------------
        # GENERATE TIMESHEET
        # ---------------------------------
        timesheet_report = generate_timesheet()

        print("\n===== TIMESHEET REPORT =====")
        print(timesheet_report)
        print("===========================\n")

        # ---------------------------------
        # EMAIL BODY
        # ---------------------------------
        body = f"""
Hello Manager,

Please find below today's productivity summary.

{summary}

{timesheet_report}

Attached:
✔ Project Distribution Pie Chart

Regards,
Productivity Monitoring System
"""

        # ---------------------------------
        # CONNECT EMAIL SERVER
        # ---------------------------------
        yag = yagmail.SMTP(

            user=SENDER_EMAIL,

            password=APP_PASSWORD

        )

        # ---------------------------------
        # SEND EMAIL
        # ---------------------------------
        print(timesheet_report)

        yag.send(

            to=RECEIVER_EMAIL,

            subject=subject,

            contents=body,

            attachments=attachments

        )

        print("====================================")
        print("EMAIL SENT SUCCESSFULLY ✔")
        print("====================================")

        # ---------------------------------
        # CLEAR CSV AFTER EMAIL
# ---------------------------------
        clear_activity_log()

        return True

    except Exception as e:

        print("\n====================================")
        print("EMAIL FAILED ❌")
        print("====================================")

        print(e)

        return False