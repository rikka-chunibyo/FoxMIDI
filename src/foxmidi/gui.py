"""
gui.py  —  FoxMIDI
Entry point: the App class wires together the window, sidebar, pages,
system tray, MIDI engine, and device watcher.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from foxmidi.config import load_config, save_config
from foxmidi.gui_theme import C, FN, FM, styled_button, hdiv
from foxmidi.gui_panels import (
    MappingsPage, DevicesPage, SettingsPage, MidiMonitorWindow,
)

try:
    from foxmidi.midi_lib import MidiManager, DeviceWatcher
    _midi_ok = True
except Exception:
    _midi_ok = False

try:
    import pystray
    from PIL import Image, ImageDraw
    _tray_ok = True
except ImportError:
    _tray_ok = False


class App:
    PAGES = [
        ("Mappings", "mappings"),
        ("Devices",  "devices"),
        ("Settings", "settings"),
    ]

    def __init__(self, start_hidden=False):
        self.config   = load_config()
        self._enabled = True
        self._engine  = None
        self._monitor_win = None
        self.midi = self._init_midi()
        self.root = tk.Tk()
        self.root.title("FoxMIDI")
        self.root.configure(bg=C["bg"])
        self.root.geometry("1080x720")
        self.root.minsize(840, 540)
        self._pages = {}
        self._sidebar_btns = {}
        self._current_page = None
        self._apply_style()
        self.root.update_idletasks()
        self._build()
        if _tray_ok:
            ico = self._get_icon_path()
            if ico:
                try:
                    self.root.iconbitmap(ico)
                except Exception:
                    pass
        self.root.update_idletasks()
        self._show_page("mappings")
        self._start_watcher()
        if _tray_ok:
            self._start_tray()
        else:
            start_hidden = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if start_hidden:
            self.root.withdraw()

    # ── MIDI / engine init ────────────────────────────────────────

    def _init_midi(self):
        if not _midi_ok:
            return None
        try:
            from foxmidi.engine import MappingEngine
            m = MidiManager()
            self._engine = MappingEngine(self.config)
            m.set_callback(self._engine.handle_midi)
            for name in self.config.get("devices", []):
                m.open_device(name)
            return m
        except Exception:
            return None

    def _start_watcher(self):
        if not _midi_ok or not self.midi:
            return
        def on_connect(name):
            self.midi.open_device(name)
            self.root.after(0, self._on_device_change)
        def on_disconnect(name):
            self.root.after(0, self._on_device_change)
        self._watcher = DeviceWatcher(
            get_target_devices=lambda: self.config.get("devices", []),
            on_connect=on_connect,
            on_disconnect=on_disconnect,
            poll_interval=2.0,
        )
        self._watcher.start()

    def _on_device_change(self):
        dev_page = self._pages.get("devices")
        if dev_page:
            dev_page.notify_device_change()

    # ── System tray ───────────────────────────────────────────────

    def _make_icon_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#4f9eff")
        d.ellipse([18, 18, 46, 46], fill="#111214")
        return img

    def _get_icon_path(self):
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ico = os.path.join(base, "assets", "foxmidi.ico")
        return ico if os.path.exists(ico) else None

    def _start_tray(self):
        def toggle(icon, item):
            self._enabled = not self._enabled
            if self._engine and self.midi:
                self.midi.set_callback(
                    self._engine.handle_midi if self._enabled else lambda *a: None)
            icon.update_menu()

        def show_gui(icon, item):
            self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

        def show_monitor(icon, item):
            self.root.after(0, self.open_monitor)

        def quit_app(icon, item):
            icon.stop()
            self.root.after(0, self._shutdown)

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: "● Enabled" if self._enabled else "○ Disabled",
                toggle, checked=lambda item: self._enabled),
            pystray.MenuItem("Open GUI",      show_gui, default=True),
            pystray.MenuItem("MIDI Monitor",  show_monitor),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",          quit_app),
        )
        self._tray = pystray.Icon("FoxMIDI", self._make_icon_image(), "FoxMIDI", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def open_monitor(self):
        if self._monitor_win and self._monitor_win.winfo_exists():
            self._monitor_win.lift()
            return
        self._monitor_win = MidiMonitorWindow(self.root, self.midi)

    # ── Tkinter style ─────────────────────────────────────────────

    def _apply_style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        cb_common = dict(
            fieldbackground=C["card2"], background=C["card2"],
            foreground=C["text"], selectbackground=C["card2"],
            selectforeground=C["accent"],
            arrowcolor=C["dim"], arrowsize=12,
            bordercolor=C["card2"], lightcolor=C["card2"],
            darkcolor=C["card2"], troughcolor=C["card2"],
            relief="flat", borderwidth=0, padding=(6, 4),
        )
        s.configure("TCombobox", **cb_common)
        s.configure("Focused.TCombobox", **{**cb_common, "bordercolor": C["accent"]})
        s.map("TCombobox",
              fieldbackground=[("readonly", C["card2"])],
              background=[("active", C["card2"]), ("!active", C["card2"])],
              bordercolor=[("focus", C["card2"]), ("!focus", C["card2"])],
              lightcolor=[("focus", C["card2"]), ("!focus", C["card2"])],
              darkcolor=[("focus", C["card2"]), ("!focus", C["card2"])],
              arrowcolor=[("disabled", C["dim"]), ("!disabled", C["dim"])])
        s.map("Focused.TCombobox",
              fieldbackground=[("readonly", C["card2"])],
              bordercolor=[("focus", C["accent"]), ("!focus", C["accent"])])
        s.configure("TScrollbar",
                background=C["card2"], troughcolor=C["card"],
                arrowcolor=C["dim"], bordercolor=C["card"],
                lightcolor=C["card2"], darkcolor=C["card2"])
        self.root.option_add("*TCombobox*Listbox.background",        C["card"])
        self.root.option_add("*TCombobox*Listbox.foreground",        C["white"])
        self.root.option_add("*TCombobox*Listbox.selectBackground",  C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground",  C["white"])
        self.root.option_add("*TCombobox*Listbox.relief",            "flat")
        self.root.option_add("*TCombobox*Listbox.borderWidth",       "0")
        self.root.option_add("*TCombobox*Listbox.highlightThickness","0")

    # ── Layout ────────────────────────────────────────────────────

    def _build(self):
        sb = tk.Frame(self.root, bg=C["sidebar"], width=180)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        logo = tk.Frame(sb, bg=C["sidebar"])
        logo.pack(fill="x", padx=16, pady=24)
        LOGO_SIZE = 20
        font = ("Consolas", LOGO_SIZE, "bold")
        canvas_height = int(LOGO_SIZE * 1.9)
        canvas = tk.Canvas(logo, bg=C["sidebar"], highlightthickness=0, bd=0, height=canvas_height)
        canvas.pack(anchor="w")
        y_mid     = canvas_height // 2
        fox_id    = canvas.create_text(0, y_mid, text="Fox", fill=C["accent"], font=font, anchor="w")
        fox_bbox  = canvas.bbox(fox_id)
        fox_width = fox_bbox[2] - fox_bbox[0]
        canvas.create_text(fox_width - int(LOGO_SIZE * 0.28), y_mid,
                           text="MIDI", fill=C["white"], font=font, anchor="w")

        hdiv(sb, bg=C["border"])
        for label, pid in self.PAGES:
            btn = tk.Button(
                sb, text=label, anchor="w",
                bg=C["sidebar"], fg=C["dim"],
                activebackground=C["card"], activeforeground=C["white"],
                relief="flat", font=FN, padx=20, pady=10, cursor="hand2",
                command=lambda p=pid: self._show_page(p))
            btn.pack(fill="x")
            self._sidebar_btns[pid] = btn

        tk.Frame(sb, bg=C["sidebar"]).pack(fill="both", expand=True)
        hdiv(sb, bg=C["border"])
        styled_button(sb, "⎍  MIDI Monitor", self.open_monitor).pack(fill="x", pady=(6, 2))
        tk.Label(sb, text="v2.1", bg=C["sidebar"],
                 fg=C["dim"], font=("Consolas", 8)).pack(pady=(2, 10))

        self._container = tk.Frame(self.root, bg=C["bg"])
        self._container.pack(side="left", fill="both", expand=True)

        self._pages["mappings"] = MappingsPage(self._container, self)
        self._pages["devices"]  = DevicesPage(self._container, self)
        self._pages["settings"] = SettingsPage(self._container, self)
        for page in self._pages.values():
            page.place(x=0, y=0, relwidth=1, relheight=1)
            page.lower()

    def _show_page(self, pid):
        if self._current_page:
            self._pages[self._current_page].lower()
            self._sidebar_btns[self._current_page].configure(
                bg=C["sidebar"], fg=C["dim"])
        self._current_page = pid
        self._sidebar_btns[pid].configure(bg=C["card"], fg=C["white"])
        self._pages[pid].on_show()
        self._pages[pid].lift()

    # ── Save / lifecycle ──────────────────────────────────────────

    def save(self):
        save_config(self.config)
        if self._engine:
            self._engine.reload_config(self.config)

    def _on_close(self):
        if _tray_ok:
            self.root.withdraw()
        else:
            if messagebox.askyesno("Quit", "Exit FoxMIDI?"):
                self._shutdown()

    def _shutdown(self):
        try:
            if hasattr(self, "_watcher"):
                self._watcher.stop()
            if self.midi:
                self.midi.close_all()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()