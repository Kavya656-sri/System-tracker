import tkinter as tk
import subprocess
import webbrowser
import time
from tkinter import messagebox
import json
from datetime import datetime

def save_notes():
    work_summary = summary_text.get("1.0", tk.END).strip()
    pending_tasks = pending_text.get("1.0", tk.END).strip()

    data = {
        "date": str(datetime.now()),
        "work_summary": work_summary,
        "pending_tasks": pending_tasks
    }

    with open("shutdown_notes.json", "w") as file:
        json.dump(data, file, indent=4)

    messagebox.showinfo("Saved", "Work summary saved successfully!")

    # Start Flask Dashboard
    subprocess.Popen(["python", "app.py"])

    # Wait for Flask to start
    time.sleep(3)

    # Open Dashboard
    webbrowser.open("http://127.0.0.1:5000")

    root.destroy()

# Main Window
root = tk.Tk()
root.title("Daily Work Summary")
root.geometry("500x400")

# Work Summary Label
tk.Label(root, text="What did you work on today?").pack(pady=5)

summary_text = tk.Text(root, height=8, width=55)
summary_text.pack()

# Pending Tasks Label
tk.Label(root, text="Pending tasks for tomorrow").pack(pady=5)

pending_text = tk.Text(root, height=6, width=55)
pending_text.pack()

# Submit Button
submit_btn = tk.Button(root, text="Submit", command=save_notes)
submit_btn.pack(pady=20)

root.mainloop()