import os
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt

# -----------------------------------------
# CONFIG
# -----------------------------------------
CSV_FILE = "activity_log.csv"

REPORTS_FOLDER = "reports"

CHARTS_FOLDER = "charts"

# -----------------------------------------
# GENERATE REPORT FUNCTION
# -----------------------------------------
def generate_report():

    print("\n====================================")
    print("GENERATING REPORT")
    print("====================================")

    try:

        # ---------------------------------
        # CHECK CSV FILE
        # ---------------------------------
        if not os.path.exists(CSV_FILE):

            print("CSV file not found ❌")

            return None

        # ---------------------------------
        # CREATE FOLDERS
        # ---------------------------------
        os.makedirs(REPORTS_FOLDER, exist_ok=True)

        os.makedirs(CHARTS_FOLDER, exist_ok=True)

        # ---------------------------------
        # READ CSV
        # ---------------------------------
        df = pd.read_csv(CSV_FILE)

        df.columns = df.columns.str.strip()

        # ---------------------------------
        # CHECK EMPTY
        # ---------------------------------
        if df.empty:

            print("CSV file is empty ❌")

            return None

        # ---------------------------------
        # CONVERT DURATION
        # ---------------------------------
        df["Duration"] = pd.to_timedelta(

            df["Duration"]

        )

        # ---------------------------------
        # BASIC STATS
        # ---------------------------------
        total_sessions = len(df)

        project_stats = df["Project Name"].value_counts()

        app_stats = df["App Name"].value_counts()

        # ---------------------------------
        # PRODUCTIVITY ANALYSIS
        # ---------------------------------
        productive_categories = [

            "Development",
            "Browser Work",
            "Google Chrome",
            "Microsoft Edge",
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

        idle_count = df[

            df["Project Name"] == "IDLE"

        ].shape[0]

        # ---------------------------------
        # PRODUCTIVITY SCORE
        # ---------------------------------
        if total_sessions > 0:

            productivity_score = round(

                (productive_count / total_sessions) * 100,
                2

            )

        else:

            productivity_score = 0

        # ---------------------------------
        # CURRENT DATE
        # ---------------------------------
        current_date = datetime.now().strftime(
            "%Y-%m-%d"
        )

        # ---------------------------------
        # REPORT CONTENT
        # ---------------------------------
        report_content = f"""
================ DAILY REPORT ================

Date: {current_date}

Total Sessions: {total_sessions}

----------------------------------------------
PRODUCTIVITY ANALYSIS
----------------------------------------------

Productive Sessions   : {productive_count}
Entertainment Sessions: {entertainment_count}
Idle Sessions         : {idle_count}
Productivity Score    : {productivity_score} %

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
        # SAVE TEXT REPORT
        # ---------------------------------
        text_report_path = os.path.join(

            REPORTS_FOLDER,

            f"daily_report_{current_date}.txt"

        )

        with open(

            text_report_path,
            "w",
            encoding="utf-8"

        ) as file:

            file.write(report_content)

        print(f"Text Report Saved ✔")

        # ---------------------------------
        # SAVE EXCEL REPORT
        # ---------------------------------
        excel_report_path = os.path.join(

            REPORTS_FOLDER,

            f"daily_report_{current_date}.xlsx"

        )

        df.to_excel(

            excel_report_path,
            index=False

        )

        print(f"Excel Report Saved ✔")

        # ---------------------------------
        # PIE CHART
        # ---------------------------------
        pie_chart_path = os.path.join(

            CHARTS_FOLDER,

            f"project_pie_chart_{current_date}.png"

        )

        plt.figure(figsize=(7, 7))

        project_stats.plot(

            kind="pie",
            autopct="%1.1f%%"

        )

        plt.title("Project Distribution")

        plt.ylabel("")

        plt.tight_layout()

        plt.savefig(pie_chart_path)

        plt.close()

        print("Pie Chart Generated ✔")

        # ---------------------------------
        # BAR CHART
        # ---------------------------------
        bar_chart_path = os.path.join(

            CHARTS_FOLDER,

            f"app_usage_chart_{current_date}.png"

        )

        plt.figure(figsize=(10, 5))

        app_stats.plot(kind="bar")

        plt.title("Application Usage")

        plt.xlabel("Applications")

        plt.ylabel("Usage Count")

        plt.xticks(rotation=45)

        plt.tight_layout()

        plt.savefig(bar_chart_path)

        plt.close()

        print("Bar Chart Generated ✔")

        # ---------------------------------
        # SUMMARY DATA
        # ---------------------------------
        summary_data = {

            "date": current_date,

            "total_sessions": total_sessions,

            "productive_sessions": productive_count,

            "entertainment_sessions": entertainment_count,

            "idle_sessions": idle_count,

            "productivity_score": productivity_score

        }

        # ---------------------------------
        # FINAL REPORT DATA
        # ---------------------------------
        report_data = {

            "summary": summary_data,

            "text_report": text_report_path,

            "excel_report": excel_report_path,

            "pie_chart": pie_chart_path,

            "bar_chart": bar_chart_path,

            "project_stats": project_stats.to_dict(),

            "app_stats": app_stats.to_dict()

        }

        print("\n====================================")
        print("REPORT GENERATED SUCCESSFULLY ✔")
        print("====================================")

        return report_data

    except Exception as e:

        print("\n====================================")
        print("REPORT GENERATION FAILED ❌")
        print("====================================")

        print(e)

        return None