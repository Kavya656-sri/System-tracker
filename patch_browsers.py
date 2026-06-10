import re
import os

base_dir = r"c:\Users\KAVYA SRI K\OneDrive\Desktop\task-1"

# 1. FIX tracker.py
tracker_path = os.path.join(base_dir, "tracker.py")
with open(tracker_path, "r", encoding="utf-8") as f:
    tracker_content = f.read()

# Replace chrome logic
tracker_content = re.sub(
    r'elif "chrome" in title:\s*return "Browser Work"',
    r'elif "chrome" in title:\n        return "Google Chrome"\n\n    elif "edge" in title:\n        return "Microsoft Edge"',
    tracker_content
)

with open(tracker_path, "w", encoding="utf-8") as f:
    f.write(tracker_content)
print("Updated tracker.py")

# 2. FIX start_tracker.py - Reconstruct the correct get_project function
start_tracker_path = os.path.join(base_dir, "start_tracker.py")
with open(start_tracker_path, "r", encoding="utf-8") as f:
    start_tracker_content = f.read()

def_idx = start_tracker_content.find("def get_project(window_title):")
end_idx = start_tracker_content.find("def save_session(", def_idx)

if def_idx != -1 and end_idx != -1:
    new_get_project = """def get_project(window_title):

    if window_title.startswith("C:\\\\"):
        return None

    title = window_title.lower()

    ignored_apps = [
        "python.exe",
        "windows input experience",
        "lockapp",
        "widgets",
    ]

    if any(app in title for app in ignored_apps):
        return None

    if any(x in title for x in ["vscode", "visual studio", "pycharm", ".py", "cmd.exe", "powershell", "terminal"]):
        return "Development"

    if any(x in title for x in ["chrome", "google chrome"]):
        return "Google Chrome"

    if any(x in title for x in ["edge", "microsoft edge"]):
        return "Microsoft Edge"

    if any(x in title for x in ["chatgpt", "firefox", "gmail", "outlook", "github", "stackoverflow"]):
        return "Browser Work"

    if any(x in title for x in ["youtube", "netflix", "spotify"]):
        return "Entertainment"

    if any(x in title for x in ["whatsapp", "teams", "mail"]):
        return "Communication"

    if any(x in title for x in ["excel", "word", "powerpoint"]):
        return "Office Work"

    if any(x in title for x in ["shut down windows", "lockapp", "windows default lock screen", "sign in"]):
        return "IDLE"
    
    if any(x in title for x in ["unknown window", "program manager"]):
        return "SLEEP"

    return "Other"

# -----------------------------------------
# SAVE SESSION
# -----------------------------------------
"""
    start_tracker_content = start_tracker_content[:def_idx] + new_get_project + start_tracker_content[end_idx + len("def save_session(\n") - 18:]

    with open(start_tracker_path, "w", encoding="utf-8") as f:
        f.write(start_tracker_content)
    print("Updated start_tracker.py")

# 3. FIX app.py
app_path = os.path.join(base_dir, "app.py")
with open(app_path, "r", encoding="utf-8") as f:
    app_content = f.read()

# Update productive categories in two places
app_content = app_content.replace(
    'productive_categories = ["Development", "Browser Work", "Office Work", "Communication"]',
    'productive_categories = ["Development", "Browser Work", "Google Chrome", "Microsoft Edge", "Office Work", "Communication"]'
)
app_content = app_content.replace(
    "productive_cats = ['Development', 'Browser Work', 'Office Work', 'Communication']",
    "productive_cats = ['Development', 'Browser Work', 'Google Chrome', 'Microsoft Edge', 'Office Work', 'Communication']"
)

# Fix Category in app_usage API
# cat = "Development" if row['Clean_App'] in ["Visual Studio Code", "Antigravity IDE"] else "Browser" if row['Clean_App'] in ["Google Chrome", "Microsoft Edge"] else "Communication" if row['Clean_App'] == "WhatsApp" else "Other"
app_content = app_content.replace(
    'cat = "Development" if row[\'Clean_App\'] in ["Visual Studio Code", "Antigravity IDE"] else "Browser" if row[\'Clean_App\'] in ["Google Chrome", "Microsoft Edge"] else "Communication" if row[\'Clean_App\'] == "WhatsApp" else "Other"',
    'cat = "Development" if row[\'Clean_App\'] in ["Visual Studio Code", "Antigravity IDE"] else "Google Chrome" if row[\'Clean_App\'] == "Google Chrome" else "Microsoft Edge" if row[\'Clean_App\'] == "Microsoft Edge" else "Communication" if row[\'Clean_App\'] == "WhatsApp" else "Other"'
)

with open(app_path, "w", encoding="utf-8") as f:
    f.write(app_content)
print("Updated app.py")
