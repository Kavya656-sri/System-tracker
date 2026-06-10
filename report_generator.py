import os
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd

from email_sender import load_review_tasks, parse_review_duration


REPORTS_FOLDER = "reports"
CHARTS_FOLDER = "charts"


def _duration_to_seconds(duration):
    return parse_review_duration(duration) * 60


def _processed_tasks_dataframe():
    tasks = load_review_tasks()
    rows = []

    for task in tasks:
        rows.append({
            "Date": task.get("date", ""),
            "Project": task.get("project", ""),
            "Task": task.get("task", ""),
            "Status": task.get("status", ""),
            "Duration": task.get("duration", "00:00"),
            "Duration Seconds": _duration_to_seconds(task.get("duration", "00:00")),
        })

    return pd.DataFrame(rows)


def _format_processed_tasks(df):
    if df.empty:
        return "No processed tasks available."

    return df[["Date", "Project", "Task", "Status", "Duration"]].to_string(index=False)


def _save_chart(series, path, title, kind):
    plt.figure(figsize=(8, 6))

    if not series.empty:
        if kind == "pie":
            series.plot(kind="pie", autopct="%1.1f%%")
            plt.ylabel("")
        else:
            series.plot(kind="bar")
            plt.xlabel("")
            plt.ylabel("Duration Seconds")
            plt.xticks(rotation=45, ha="right")

    plt.title(title)
    plt.tight_layout()
    plt.savefig(path)
    plt.close()


def generate_report():
    print("\n====================================")
    print("GENERATING PROCESSED REPORT")
    print("====================================")

    try:
        os.makedirs(REPORTS_FOLDER, exist_ok=True)
        os.makedirs(CHARTS_FOLDER, exist_ok=True)

        current_date = datetime.now().strftime("%Y-%m-%d")
        processed_df = _processed_tasks_dataframe()

        total_tasks = len(processed_df)
        total_seconds = int(processed_df["Duration Seconds"].sum()) if not processed_df.empty else 0

        if processed_df.empty:
            project_stats = pd.Series(dtype="float64")
            task_stats = pd.Series(dtype="float64")
        else:
            project_stats = processed_df.groupby("Project")["Duration Seconds"].sum()
            task_stats = processed_df.groupby("Task")["Duration Seconds"].sum()

        report_content = f"""
================ DAILY REPORT ================

Date: {current_date}

Processed Tasks : {total_tasks}
Total Duration  : {total_seconds // 3600:02d}:{(total_seconds % 3600) // 60:02d}

----------------------------------------------
PROCESSED TASKS
----------------------------------------------

{_format_processed_tasks(processed_df)}

----------------------------------------------
PROJECT BREAKDOWN
----------------------------------------------

{project_stats.to_string()}

==============================================
"""

        print(report_content)

        text_report_path = os.path.join(REPORTS_FOLDER, f"daily_report_{current_date}.txt")
        with open(text_report_path, "w", encoding="utf-8") as file:
            file.write(report_content)

        excel_report_path = os.path.join(REPORTS_FOLDER, f"daily_report_{current_date}.xlsx")
        processed_df.to_excel(excel_report_path, index=False)

        pie_chart_path = os.path.join(CHARTS_FOLDER, f"project_pie_chart_{current_date}.png")
        _save_chart(project_stats, pie_chart_path, "Project Distribution", "pie")

        bar_chart_path = os.path.join(CHARTS_FOLDER, f"app_usage_chart_{current_date}.png")
        _save_chart(task_stats, bar_chart_path, "Processed Task Duration", "bar")

        return {
            "summary": {
                "date": current_date,
                "total_sessions": total_tasks,
                "productive_sessions": total_tasks,
                "entertainment_sessions": 0,
                "idle_sessions": 0,
                "productivity_score": 100 if total_tasks else 0,
            },
            "text_report": text_report_path,
            "excel_report": excel_report_path,
            "pie_chart": pie_chart_path,
            "bar_chart": bar_chart_path,
            "project_stats": project_stats.to_dict(),
            "app_stats": task_stats.to_dict(),
        }

    except Exception as error:
        print("\nREPORT GENERATION FAILED")
        print(error)
        return None
