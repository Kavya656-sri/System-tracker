import os
import pandas as pd
import matplotlib.pyplot as plt
import smtplib

from datetime import datetime

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# -----------------------------------------
# CONFIG
# -----------------------------------------
CSV_FILE = "activity_log.csv"

SENDER_EMAIL = "kavyakanagaraj2@gmail.com"

RECEIVER_EMAIL = "23cb023@drngpit.ac.in"

# USE YOUR GMAIL APP PASSWORD
PASSWORD = "bwtl ngcf pbei cftg"

# -----------------------------------------
# GENERATE REPORT
# -----------------------------------------
def generate_report():

    print("\n====================================")
    print("GENERATING DAILY REPORT")
    print("====================================")

    try:

        # ---------------------------------
        # CHECK CSV EXISTS
        # ---------------------------------
        if not os.path.exists(CSV_FILE):

            print("CSV file not found ❌")
            return None

        # ---------------------------------
        # READ CSV
        # ---------------------------------
        df = pd.read_csv(CSV_FILE)

        df.columns = df.columns.str.strip()

        if df.empty:

            print("CSV file is empty ❌")
            return None

        # ---------------------------------
        # PRODUCTIVITY ANALYSIS
        # ---------------------------------
        productive_categories = [

            "Development",
            "Browser Work",
            "Office Work",
            "Communication"

        ]

        productive_count = df[
            df["Project Name"].isin(
                productive_categories
            )
        ].shape[0]

        entertainment_count = df[
            df["Project Name"] == "Entertainment"
        ].shape[0]

        total_sessions = len(df)

        productivity_score = round(

            (productive_count / total_sessions) * 100,
            2

        )

        # ---------------------------------
        # PROJECT STATS
        # ---------------------------------
        project_stats = df[
            "Project Name"
        ].value_counts()

        app_stats = df[
            "App Name"
        ].value_counts()

        # ---------------------------------
        # REPORT CONTENT
        # ---------------------------------
        report_content = f"""
================ DAILY REPORT ================

Date: {datetime.now().strftime("%Y-%m-%d")}

Total Sessions: {total_sessions}

----------------------------------------------
PRODUCTIVITY ANALYSIS
----------------------------------------------

Productive Sessions     : {productive_count}

Entertainment Sessions  : {entertainment_count}

Productivity Score      : {productivity_score} %

----------------------------------------------
PROJECT BREAKDOWN
----------------------------------------------

{project_stats.to_string()}

----------------------------------------------
APPLICATION USAGE
----------------------------------------------

{app_stats.to_string()}

==============================================
"""

        print(report_content)

        # ---------------------------------
        # SAVE TXT REPORT
        # ---------------------------------
        with open(

            "daily_report.txt",
            "w",
            encoding="utf-8"

        ) as file:

            file.write(report_content)

        print("Text Report Saved ✔")

        # ---------------------------------
        # SAVE EXCEL REPORT
        # ---------------------------------
        df.to_excel(

            "daily_report.xlsx",
            index=False

        )

        print("Excel Report Saved ✔")

        # ---------------------------------
        # CREATE PIE CHART
        # ---------------------------------
        plt.figure(figsize=(7, 7))

        project_stats.plot(

            kind="pie",
            autopct="%1.1f%%"

        )

        plt.title("Project Distribution")

        plt.ylabel("")

        plt.savefig("project_pie_chart.png")

        plt.close()

        print("Pie Chart Saved ✔")

        # ---------------------------------
        # CREATE BAR CHART
        # ---------------------------------
        plt.figure(figsize=(10, 5))

        app_stats.plot(kind="bar")

        plt.title("Application Usage")

        plt.xlabel("Applications")

        plt.ylabel("Usage Count")

        plt.xticks(rotation=45)

        plt.tight_layout()

        plt.savefig("app_usage_chart.png")

        plt.close()

        print("Bar Chart Saved ✔")

        print("\nReport Generated Successfully ✔")

        return report_content

    except Exception as e:

        print("\nREPORT GENERATION FAILED ❌")
        print(e)

        return None

# -----------------------------------------
# SEND EMAIL
# -----------------------------------------
def send_email(report_content):

    print("\n====================================")
    print("SENDING EMAIL")
    print("====================================")

    try:

        # ---------------------------------
        # CREATE EMAIL
        # ---------------------------------
        msg = MIMEMultipart()

        msg["From"] = SENDER_EMAIL

        msg["To"] = RECEIVER_EMAIL

        msg["Subject"] = "Automated Daily Timesheet Report"

        msg.attach(

            MIMEText(report_content, "plain")

        )

        # ---------------------------------
        # ATTACH FILES
        # ---------------------------------
        attachments = [

            "daily_report.txt",
            "daily_report.xlsx",
            "project_pie_chart.png",
            "app_usage_chart.png"

        ]

        for file_name in attachments:

            if os.path.exists(file_name):

                with open(file_name, "rb") as attachment:

                    part = MIMEBase(

                        "application",
                        "octet-stream"

                    )

                    part.set_payload(
                        attachment.read()
                    )

                encoders.encode_base64(part)

                part.add_header(

                    "Content-Disposition",
                    f"attachment; filename={file_name}"

                )

                msg.attach(part)

                print(f"{file_name} Attached ✔")

        # ---------------------------------
        # CONNECT TO GMAIL SMTP
        # ---------------------------------
        print("Connecting to Gmail SMTP...")

        server = smtplib.SMTP(

            "smtp.gmail.com",
            587,
            timeout=20

        )

        server.starttls()

        print("Logging into Gmail...")

        server.login(

            SENDER_EMAIL,
            PASSWORD

        )

        print("Login Successful ✔")

        # ---------------------------------
        # SEND EMAIL
        # ---------------------------------
        print("Sending Email...")

        server.sendmail(

            SENDER_EMAIL,
            RECEIVER_EMAIL,
            msg.as_string()

        )

        server.quit()

        print("Email Sent Successfully ✔")

    except Exception as e:

        print("\nEMAIL FAILED ❌")
        print(e)

# -----------------------------------------
# MAIN
# -----------------------------------------
if __name__ == "__main__":

    report = generate_report()

    if report:

        send_email(report)