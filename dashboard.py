import streamlit as st
import pandas as pd
import os
import subprocess
import sys

from email_sender import send_email

# ---------------------------------
# OPEN DASHBOARD FROM TRACKER
# ---------------------------------
def open_dashboard(report_data=None):

    subprocess.Popen(

        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "dashboard.py"
        ]

    )

# ---------------------------------
# PAGE CONFIG
# ---------------------------------
st.set_page_config(

    page_title="Productivity Dashboard",
    layout="wide"

)

# ---------------------------------
# TITLE
# ---------------------------------
st.title("🚀 Productivity Monitoring Dashboard")

# ---------------------------------
# SIDEBAR
# ---------------------------------
st.sidebar.title("⚙️ Navigation")

page = st.sidebar.radio(

    "Go To",

    [

        "Dashboard",
        "Analytics",
        "Reports"

    ]

)

# ---------------------------------
# PAGE SELECTION
# ---------------------------------
if page == "Dashboard":

    st.header("📊 Live Dashboard")

elif page == "Analytics":

    st.header("📈 Productivity Analytics")

elif page == "Reports":

    st.header("📁 Generated Reports")

# ---------------------------------
# REFRESH BUTTON
# ---------------------------------
if st.button("🔄 Refresh Data"):

    st.rerun()

# ---------------------------------
# CHECK CSV
# ---------------------------------
CSV_FILE = "activity_log.csv"

if not os.path.exists(CSV_FILE):

    st.error("activity_log.csv not found ❌")

    st.stop()

# ---------------------------------
# READ CSV
# ---------------------------------
df = pd.read_csv(CSV_FILE)

df.columns = df.columns.str.strip()

# ---------------------------------
# CONVERT DURATION
# ---------------------------------
df["Duration"] = pd.to_timedelta(

    df["Duration"]

)

# ---------------------------------
# SHOW DATA
# ---------------------------------
st.subheader("📋 Activity Log")

edited_df = st.data_editor(

    df,

    use_container_width=True,
    num_rows="dynamic"

)

# ---------------------------------
# SAVE CHANGES
# ---------------------------------
if st.button("💾 Save Changes"):

    edited_df.to_csv(

        CSV_FILE,
        index=False

    )

    st.success("Changes Saved Successfully ✔")

# ---------------------------------
# METRICS
# ---------------------------------
total_sessions = len(df)

productive_sessions = df[

    df["Project Name"].isin([

        "Development",
        "Browser Work",
        "Communication",
        "Office Work"

    ])

].shape[0]

idle_sessions = df[

    df["Project Name"] == "IDLE"

].shape[0]

# ---------------------------------
# PRODUCTIVITY SCORE
# ---------------------------------
if total_sessions > 0:

    productivity_score = round(

        (productive_sessions / total_sessions) * 100,
        2

    )

else:

    productivity_score = 0

# ---------------------------------
# DISPLAY METRICS
# ---------------------------------
col1, col2, col3, col4 = st.columns(4)

col1.metric(

    "Total Sessions",
    total_sessions

)

col2.metric(

    "Productive Sessions",
    productive_sessions

)

col3.metric(

    "Idle Sessions",
    idle_sessions

)

col4.metric(

    "Productivity Score",
    f"{productivity_score}%"

)

# ---------------------------------
# PROJECT DISTRIBUTION
# ---------------------------------
st.subheader("📊 Project Distribution")

project_table = df.groupby(

    "Project Name"

)["Duration"].sum().reset_index()

project_table.columns = [

    "Project Name",
    "Total Time Worked"

]

project_table = project_table.sort_values(

    by="Total Time Worked",
    ascending=False

)

edited_project_table = st.data_editor(

    project_table,

    use_container_width=True,
    num_rows="dynamic"

)

# ---------------------------------
# APPLICATION WORK DURATION
# ---------------------------------
st.subheader("🖥️ Application Work Duration")
app_duration = df.groupby(

    "App Name"

)["Duration"].sum().reset_index()

app_duration.columns = [

    "Application Name",
    "Total Time Worked"

]

app_duration = app_duration.sort_values(

    by="Total Time Worked",
    ascending=False

)

# ---------------------------------
# EMAIL TIMESHEET PREVIEW
# ---------------------------------
st.subheader("📧 Email Timesheet Preview")

email_table = pd.DataFrame(
    columns=[
        "Application",
        "Work Done",
        "Duration"
    ]
)

for _, row in app_duration.iterrows():

    title = str(row["Application Name"])

    duration = str(
        row["Total Time Worked"]
    ).split(".")[0]

    app_name = "Other"
    work_done = title

    if " - Google Chrome" in title:

        app_name = "Google Chrome"
        work_done = title.replace(
            " - Google Chrome",
            ""
        )

    elif " - Visual Studio Code" in title:

        app_name = "VS Code"
        work_done = title.replace(
            " - Visual Studio Code",
            ""
        )

    elif " - Microsoft Edge" in title:

        app_name = "Microsoft Edge"
        work_done = title.replace(
            " - Microsoft Edge",
            ""
        )

    email_table.loc[len(email_table)] = [

        app_name,
        work_done,
        duration

    ]

edited_email_table = st.data_editor(

    email_table,

    use_container_width=True,

    num_rows="dynamic"

)

if st.button("💾 Save Email Timesheet"):

    edited_email_table.to_csv(

        "email_timesheet.csv",

        index=False

    )

    st.success(
        "Email Timesheet Saved ✔"
    )


edited_app_duration = st.data_editor(

    app_duration,

    use_container_width=True,
    num_rows="dynamic"

)

# ---------------------------------
# SAVE APPLICATION DURATION CHANGES
# ---------------------------------
if st.button("💾 Save Application Duration Changes"):

    edited_app_duration.to_csv(

        "application_work_duration.csv",
        index=False

    )

    st.success(

        "Application Duration Changes Saved ✔"

    )

# ---------------------------------
# SEND EMAIL SECTION
# ---------------------------------
st.divider()

st.subheader("📧 Send Report")

st.write(

    "Click the button below to send the latest productivity report via email."

)

if st.button("📨 SEND EMAIL"):

    try:

        send_email()

        st.success(

            "Email Sent Successfully ✔"

        )

    except Exception as e:

        st.error(

            f"Failed to send email ❌\n\n{e}"

        )

# ---------------------------------
# GENERATED REPORTS SECTION
# ---------------------------------
st.divider()

st.subheader("📁 Generated Reports")

reports_folder = "reports"

if os.path.exists(reports_folder):

    report_files = os.listdir(reports_folder)

    if report_files:

        for file in report_files:

            st.write(f"📄 {file}")

    else:

        st.info(

            "No reports generated yet."

        )

else:

    st.info(

        "Reports folder not found."

    )

# ---------------------------------
# FOOTER
# ---------------------------------
st.divider()

st.caption(

    "🚀 Productivity Monitoring System | Built with Streamlit"

)