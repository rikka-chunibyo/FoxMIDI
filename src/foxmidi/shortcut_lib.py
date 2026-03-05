"""
shortcut_lib.py  —  FoxMIDI
Creates / removes Windows shortcuts for Start Menu and Startup.
Requires pywin32  (pip install pywin32).
"""
import os
import sys


def _is_frozen():
    return getattr(sys, "frozen", False)


def _app_dir():
    """Project root — contains main.py when running as script, or the .exe when frozen."""
    if _is_frozen():
        return os.path.dirname(sys.executable)
    # foxmidi/shortcut_lib.py → go up one level to project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get_target():
    """Executable to launch — the .exe when frozen, pythonw.exe otherwise."""
    if _is_frozen():
        return sys.executable
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def _get_script():
    """Returns the main.py path — only used when not frozen."""
    return os.path.join(_app_dir(), "main.py")


def _get_icon_path():
    ico = os.path.join(_app_dir(), "assets", "foxmidi.ico")
    return ico if os.path.exists(ico) else None


def _write_shortcut(lnk_path, args, description):
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortCut(lnk_path)
    sc.TargetPath = _get_target()
    sc.Arguments = args if _is_frozen() else f'"{_get_script()}" {args}'.strip()
    sc.WorkingDirectory = _app_dir()
    sc.Description = description
    icon = _get_icon_path()
    if icon:
        sc.IconLocation = f"{icon}, 0"
    sc.save()


# ── public API ────────────────────────────────────────────────────

def create_start_menu_shortcut() -> str:
    try:
        folder = os.path.join(
            os.environ["APPDATA"],
            r"Microsoft\Windows\Start Menu\Programs"
        )
        lnk = os.path.join(folder, "FoxMIDI.lnk")
        _write_shortcut(lnk, "--gui", "FoxMIDI")
        return "Start Menu shortcut created."
    except Exception as e:
        return f"Failed: {e}"


def create_startup_shortcut() -> str:
    try:
        folder = os.path.join(
            os.environ["APPDATA"],
            r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        lnk = os.path.join(folder, "FoxMIDI.lnk")
        _write_shortcut(lnk, "", "FoxMIDI – run on login")
        return "Startup shortcut created."
    except Exception as e:
        return f"Failed: {e}"


def remove_startup_shortcut() -> str:
    try:
        folder = os.path.join(
            os.environ["APPDATA"],
            r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        lnk = os.path.join(folder, "FoxMIDI.lnk")
        if os.path.exists(lnk):
            os.remove(lnk)
            return "Startup shortcut removed."
        return "No startup shortcut found."
    except Exception as e:
        return f"Failed: {e}"


def startup_shortcut_exists() -> bool:
    folder = os.path.join(
        os.environ.get("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs\Startup"
    )
    return os.path.exists(os.path.join(folder, "FoxMIDI.lnk"))