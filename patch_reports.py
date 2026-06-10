import os

base_dir = r"c:\Users\KAVYA SRI K\OneDrive\Desktop\task-1"

for filename in ["report_generator.py", "daily_report_sender.py"]:
    filepath = os.path.join(base_dir, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace the list formatting
        content = content.replace(
            '"Development",\n            "Browser Work",\n            "Office Work",\n            "Communication"',
            '"Development",\n            "Browser Work",\n            "Google Chrome",\n            "Microsoft Edge",\n            "Office Work",\n            "Communication"'
        )
        # Also try one line format just in case
        content = content.replace(
            '["Development", "Browser Work", "Office Work", "Communication"]',
            '["Development", "Browser Work", "Google Chrome", "Microsoft Edge", "Office Work", "Communication"]'
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {filename}")
