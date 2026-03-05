"""
main.py  —  FoxMIDI
Single entry point. Starts the MIDI engine, system tray icon, and GUI.

Usage:
    python  main.py             ← start with GUI open
    pythonw main.py             ← start with GUI open (no console window)
    pythonw main.py --silent    ← start in background, no GUI window

If an instance is already running:
    python  main.py             ← tells the running instance to show its GUI, then exits
    python  main.py --silent    ← exits immediately, does nothing
"""
import sys
import argparse
import logging
import os
import ctypes
import tempfile
import time
import threading

# Add src/ to path so `foxmidi` package is importable by name
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

MUTEX_NAME   = "FoxMIDI_SingleInstance"
SIGNAL_FILE  = os.path.join(tempfile.gettempdir(), "FoxMIDI_show_gui.signal")


def _create_mutex():
    """Create a named mutex. Returns (handle, already_existed)."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    already_existed = (ctypes.windll.kernel32.GetLastError() == 183)  # ERROR_ALREADY_EXISTS
    return handle, already_existed


def _watch_signal_file(app):
    """Poll for the signal file in a daemon thread; open GUI when seen."""
    def watch():
        while True:
            try:
                if os.path.exists(SIGNAL_FILE):
                    os.remove(SIGNAL_FILE)
                    app.root.after(0, lambda: (app.root.deiconify(), app.root.lift()))
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=watch, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(description="FoxMIDI")
    parser.add_argument("--silent", action="store_true", help="Start in background without opening GUI")
    args = parser.parse_args()

    _mutex_handle, already_running = _create_mutex()

    if already_running:
        if not args.silent:
            # Signal the running instance to show its window
            print("FoxMIDI already running — opening window...")
            try:
                with open(SIGNAL_FILE, "w") as f:
                    f.write("show")
            except Exception:
                pass
        sys.exit(0)

    from foxmidi.gui import App
    app = App(start_hidden=args.silent)
    _watch_signal_file(app)
    app.run()


if __name__ == "__main__":
    main()