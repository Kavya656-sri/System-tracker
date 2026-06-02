import subprocess
import sys
import os
import time
import webbrowser
import socket

# Path to the Flask application entry point
APP_PATH = os.path.join(os.path.dirname(__file__), "app.py")


def _is_port_in_use(port: int) -> bool:
    """Return True if a TCP port on localhost is open (i.e., Flask is already running)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def open_dashboard(report_data=None):
    """Launch the Flask dashboard if it is not already running and open it in the browser.

    The optional *report_data* argument is kept for compatibility with previous calls but is unused.
    """
    # If the Flask app is not listening on the default port, start it.
    if not _is_port_in_use(5000):
        # Use the same Python executable that runs this script.
        subprocess.Popen([sys.executable, APP_PATH])
        # Give Flask a moment to start up.
        time.sleep(3)
    # Open the dashboard in the default web browser.
    webbrowser.open("http://127.0.0.1:5000")

# When this module is executed directly (e.g., `python dashboard.py`) we simply open the dashboard.
if __name__ == "__main__":
    open_dashboard()