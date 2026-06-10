from ai_service import generate_task_name

files = [
    "start_tracker.py",
    "email_sender.py",
    "report_generator.py",
    "dashboard.py"
]

for file in files:
    print(f"\nFile: {file}")
    print("AI Task:", generate_task_name(file))