"""
TrintzPOS Launcher — entry point for the packaged (PyInstaller) build.

Runs Flask in a background thread in the SAME PROCESS so no .py files
are ever written to disk or accessible as source. The GUI window acts as
the process sentinel: closing it stops the server.
"""

import os
import sys
import time
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, simpledialog


def resource_path(relative_path: str) -> str:
    """Resolve a path inside the PyInstaller bundle or the dev directory."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)


# ── License check ──────────────────────────────────────────────────────────────

def check_or_prompt_license(root: tk.Tk) -> bool:
    sys.path.insert(0, resource_path("."))
    from license_manager import check_license, activate_license

    status = check_license()
    if status["valid"]:
        if status.get("days_remaining", 999) <= 7:
            messagebox.showwarning(
                "License Expiring Soon",
                f"Your license expires in {status['days_remaining']} day(s).\n"
                "Please contact support@trintzlabs.com to renew.",
            )
        return True

    while True:
        key = simpledialog.askstring(
            "License Activation",
            f"TrintzPOS is not activated.\n{status['message']}\n\nEnter your license key:",
            parent=root,
        )
        if key is None:
            return False

        result = activate_license(key.strip())
        if result["success"]:
            messagebox.showinfo(
                "Activated",
                f"License activated!\n"
                f"Customer : {result.get('customer', '')}\n"
                f"Type     : {result['license_type']}\n"
                f"Expires  : {result['expiry_date']}  ({result['days_remaining']} days)",
            )
            return True

        if not messagebox.askretrycancel("Activation Failed", result["message"]):
            return False


# ── Flask server (runs in-process on a daemon thread) ─────────────────────────

_server_ready = threading.Event()
_flask_error: str | None = None


def _run_flask():
    global _flask_error
    try:
        # Set base dir so send_from_directory works from the bundle
        os.environ.setdefault("TRINTZ_BASE_DIR", resource_path("."))

        from app import create_app
        flask_app = create_app()

        # Signal readiness before blocking on serve_forever
        _server_ready.set()

        from werkzeug.serving import make_server
        srv = make_server("127.0.0.1", 5001, flask_app)
        srv.serve_forever()
    except Exception as exc:
        _flask_error = str(exc)
        _server_ready.set()


def start_flask_thread() -> bool:
    t = threading.Thread(target=_run_flask, daemon=True)
    t.start()
    _server_ready.wait(timeout=15)
    return _flask_error is None


# ── GUI ────────────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.title("TrintzPOS")
    root.geometry("440x230")
    root.resizable(False, False)

    tk.Label(root, text="TrintzPOS", font=("Segoe UI", 20, "bold")).pack(pady=12)
    status_lbl = tk.Label(root, text="Checking license...", font=("Segoe UI", 11))
    status_lbl.pack(pady=4)
    tk.Label(root, text="The POS will open in your default browser.", font=("Segoe UI", 10), fg="#555").pack(pady=2)
    tk.Label(root, text="Keep this window open while using the app.", font=("Segoe UI", 10), fg="#555").pack(pady=2)
    root.update()

    if not check_or_prompt_license(root):
        root.destroy()
        return

    status_lbl.config(text="Starting server...")
    root.update()

    if not start_flask_thread():
        messagebox.showerror("Error", f"Failed to start server:\n{_flask_error}")
        root.destroy()
        return

    status_lbl.config(text="Server running at http://localhost:5001")
    root.update()

    threading.Thread(
        target=lambda: (time.sleep(2), webbrowser.open("http://localhost:5001")),
        daemon=True,
    ).start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
