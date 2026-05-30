import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# Read the existing CSV with error handling
try:
    df = pd.read_csv("activity_log.csv", on_bad_lines='skip')
except:
    df = pd.read_csv("activity_log.csv", engine='python', on_bad_lines='skip')

# Ensure only 5 columns
if "Ideal Time Met" in df.columns:
    df = df[["Project Name", "App Name", "Start Time", "End Time", "Duration"]]
else:
    if len(df.columns) > 5:
        df = df.iloc[:, :5]
    df.columns = ["Project Name", "App Name", "Start Time", "End Time", "Duration"]

# Function to show ideal time duration (only for sessions >= 120 seconds)
def show_ideal_time(duration_str):
    try:
        parts = str(duration_str).split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        total_seconds = hours * 3600 + minutes * 60 + seconds
        
        if total_seconds >= 120:
            return duration_str  # Show the duration if it meets ideal time
        else:
            return ""  # Empty if doesn't meet ideal time
    except:
        return ""

# Add the new column
df["Ideal Time"] = df["Duration"].apply(show_ideal_time)

# Save back
df.to_csv("activity_log.csv", index=False)

print("✔ CSV updated with 'Ideal Time' column")
print(f"Total records: {len(df)}")
print(f"\nSample data (showing Sessions with Ideal Time >= 120 seconds):")
ideal_sessions = df[df["Ideal Time"] != ""][["Project Name", "Duration", "Ideal Time"]].head(10)
print(ideal_sessions.to_string())
print(f"\nTotal sessions with Ideal Time (>= 120 seconds): {len(df[df['Ideal Time'] != ''])}")
print(f"Total sessions without Ideal Time (< 120 seconds): {len(df[df['Ideal Time'] == ''])}")
