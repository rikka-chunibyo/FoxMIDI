"""
gui.py  —  FoxMIDI setup GUI
Run:  python gui.py
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import json
import sys
import os
import threading
import queue

from foxmidi.config import (
    load_config, save_config, new_mapping_id,
    default_settings_for, MAPPING_SETTING_DEFAULTS
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

try:
    from foxmidi.shortcut_lib import (
        create_start_menu_shortcut,
        create_startup_shortcut,
        remove_startup_shortcut,
        startup_shortcut_exists,
    )
    _shortcuts_ok = True
except Exception:
    _shortcuts_ok = False


# ═══════════════════════════════════════════════════════
#  THEME
# ═══════════════════════════════════════════════════════
C = {
    "bg":      "#111214",
    "sidebar": "#0d0e10",
    "card":    "#1a1c1f",
    "card2":   "#222428",
    "border":  "#2a2c30",
    "accent":  "#4f9eff",
    "accent2": "#ff7043",
    "green":   "#69db7c",
    "yellow":  "#ffd43b",
    "text":    "#d4d6da",
    "dim":     "#5c6068",
    "white":   "#f0f2f5",
    "danger":  "#e03e3e",
}

FN  = ("Segoe UI",  9)
FNB = ("Segoe UI",  9, "bold")
FM  = ("Consolas",  9)
FT  = ("Segoe UI", 11, "bold")

INPUT_TYPES = ["pad/button", "continuous"]
MSG_TYPES   = ["cc", "note_on", "note_off"]

# "continuous" covers both knob/fader and slider/trackpad
ACTION_TYPES_PAD        = ["key", "type_text", "mouse_click", "scroll", "application", "script"]
ACTION_TYPES_CONTINUOUS = ["mouse_move", "volume", "zoom", "key", "type_text", "mouse_click", "scroll", "application", "script"]

# Legacy aliases
ACTION_TYPES_ANY  = ACTION_TYPES_PAD
ACTION_TYPES_KNOB = ACTION_TYPES_CONTINUOUS
ACTION_TYPES_TPAD = ACTION_TYPES_CONTINUOUS

VALUE_CONDITIONS = [
    "any value", "exact value", "value increasing", "value decreasing",
    "value unchanged", "value in range", "value above", "value below",
]


# ═══════════════════════════════════════════════════════
#  WIDGET HELPERS
# ═══════════════════════════════════════════════════════

def styled_button(parent, text, command, color=None, fg=None, **kw):
    return tk.Button(
        parent, text=text, command=command,
        bg=color or C["card2"], fg=fg or C["text"],
        activebackground=C["border"], activeforeground=C["white"],
        relief="flat", cursor="hand2", font=FN,
        padx=12, pady=5, **kw
    )

def styled_entry(parent, textvariable=None, width=24, **kw):
    return tk.Entry(
        parent, textvariable=textvariable, width=width,
        bg=C["card2"], fg=C["text"], insertbackground=C["accent"],
        relief="flat", font=FM,
        highlightthickness=1, highlightcolor=C["accent"],
        highlightbackground=C["border"], **kw
    )

def section_lbl(parent, text, bg=None):
    return tk.Label(parent, text=text.upper(),
                    bg=bg or C["bg"], fg=C["dim"],
                    font=("Segoe UI", 7, "bold"))

def hdiv(parent, bg=None, padx=0):
    f = tk.Frame(parent, bg=bg or C["border"], height=1)
    f.pack(fill="x", padx=padx)
    return f

def make_cb(parent, var, values, width=18, state="readonly"):
    cb = ttk.Combobox(parent, textvariable=var, values=values,
                      state=state, width=width)
    cb.bind("<FocusIn>",  lambda e: cb.configure(style="Focused.TCombobox"))
    cb.bind("<FocusOut>", lambda e: cb.configure(style="TCombobox"))
    return cb

def actions_summary(actions):
    """Summarise a list of action steps for the sidebar."""
    if not actions:
        return ""
    parts = []
    for step in actions[:3]:
        a = step.get("action", {})
        t = a.get("type", "")
        if t == "key":         parts.append(f"⌨ {a.get('key','')}")
        elif t == "type_text":
            txt = (a.get("text") or "").replace("\n", " ")
            parts.append(f"T  {txt[:20]}{'…' if len(txt)>20 else ''}")
        elif t == "scroll":    parts.append(f"↕ {a.get('ticks',1):+}")
        elif t == "application": parts.append(f"▶ {os.path.basename(a.get('path','') or '')}")
        elif t == "script":    parts.append("⚡ script")
        elif t == "volume":    parts.append("🔊 vol")
        elif t == "zoom":      parts.append("🔍 zoom")
        elif t == "mouse_move":parts.append("🖱 move")
        elif t == "mouse_click":parts.append(f"🖱 {a.get('button','left')}-click")
        else:                  parts.append(t)
    tail = f"  +{len(actions)-3} more" if len(actions) > 3 else ""
    return "  →  ".join(parts) + tail

def action_summary_single(action):
    if not action:
        return ""
    t = action.get("type", "")
    if t == "key":         return f"⌨  {action.get('key','')}"
    if t == "scroll":      return f"↕  scroll {action.get('ticks', 1):+}"
    if t == "application": return f"▶  {os.path.basename(action.get('path', '') or '')}"
    if t == "script":
        c = (action.get("code") or "").strip()
        return f"⚡  {c[:28]}{'…' if len(c)>28 else ''}"
    if t == "volume":      return "🔊  volume"
    if t == "zoom":        return "🔍  zoom"
    if t == "mouse_move":  return "🖱  mouse"
    return t


# ═══════════════════════════════════════════════════════
#  MIDI LEARN DIALOG
# ═══════════════════════════════════════════════════════

class MidiLearnDialog(tk.Toplevel):
    def __init__(self, parent, midi_manager):
        super().__init__(parent)
        self.title("MIDI Learn")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.grab_set()
        self.result = None   # (msg_type, number, value)
        self._midi = midi_manager
        self._original_cb = midi_manager._callback

        f = tk.Frame(self, bg=C["bg"])
        f.pack(padx=36, pady=28)
        tk.Label(f, text="Waiting for MIDI input…",
                 bg=C["bg"], fg=C["white"],
                 font=("Segoe UI", 12, "bold")).pack()
        tk.Label(f, text="Press a pad, move a knob, or touch the trackpad.",
                 bg=C["bg"], fg=C["dim"], font=FN).pack(pady=(6, 20))
        self._status = tk.Label(f, text="", bg=C["bg"], fg=C["green"], font=FM)
        self._status.pack()
        styled_button(f, "Cancel", self._cancel).pack(pady=(20, 0))

        def tap(device, msg_type, number, value):
            if self.result is not None:
                return
            self.result = (msg_type, number, value)
            label = {"cc": "CC", "note_on": "Note On", "note_off": "Note Off"}.get(msg_type, msg_type)
            self.after(0, lambda: self._status.configure(
                text=f"{label}  #{number}  value {value}  from {device}"))
            self.after(600, self._restore_and_close)

        midi_manager.set_callback(tap)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.wait_window()

    def _restore_and_close(self):
        self._midi.set_callback(self._original_cb)
        self.destroy()

    def _cancel(self):
        self.result = None
        self._midi.set_callback(self._original_cb)
        self.destroy()


# ═══════════════════════════════════════════════════════
#  ACTION EDITOR (single action, no delay)
# ═══════════════════════════════════════════════════════

class ActionEditorFrame(tk.Frame):
    def __init__(self, parent, action_types, action=None, bg=None, **kw):
        super().__init__(parent, bg=bg or C["card"], **kw)
        self._types = action_types
        self._action = dict(action) if action else {}
        self._bg = bg or C["card"]
        self._fields = {}
        self._build()

    def _build(self):
        row = tk.Frame(self, bg=self._bg)
        row.pack(fill="x", pady=(0, 6))
        section_lbl(row, "Action type", bg=self._bg).pack(side="left", padx=(0, 8))
        self._type_var = tk.StringVar(value=self._action.get("type", self._types[0]))
        cb = make_cb(row, self._type_var, self._types, width=16)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        self._ff = tk.Frame(self, bg=self._bg)
        self._ff.pack(fill="x")
        self._refresh()

    def _refresh(self):
        for w in self._ff.winfo_children():
            w.destroy()
        self._fields = {}
        t = self._type_var.get()
        ex = self._action if self._action.get("type") == t else {}
        bg = self._bg

        def entry_row(label, key, default="", width=28):
            r = tk.Frame(self._ff, bg=bg)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=label, bg=bg, fg=C["dim"], font=FN,
                     width=13, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(ex.get(key, default)))
            styled_entry(r, textvariable=var, width=width).pack(
                side="left", fill="x", expand=True)
            self._fields[key] = ("strvar", var)

        if t == "key":
            entry_row("Key combo", "key", ex.get("key", ""))
            tk.Label(self._ff,
                     text="e.g.  ctrl+z    play/pause media    windows+r    f5",
                     bg=bg, fg=C["dim"], font=("Consolas", 8)).pack(anchor="w")
        elif t == "scroll":
            entry_row("Ticks", "ticks", str(ex.get("ticks", 3)), width=8)
            tk.Label(self._ff,
                     text="positive = up / zoom in     negative = down / zoom out",
                     bg=bg, fg=C["dim"], font=("Consolas", 8)).pack(anchor="w")
        elif t == "mouse_click":
            r = tk.Frame(self._ff, bg=bg)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="Button", bg=bg, fg=C["dim"], font=FN,
                     width=13, anchor="w").pack(side="left")
            var = tk.StringVar(value=ex.get("button", "left"))
            make_cb(r, var, ["left", "right", "middle"], width=10).pack(side="left")
            self._fields["button"] = ("strvar", var)
        elif t == "application":
            r = tk.Frame(self._ff, bg=bg)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="Path", bg=bg, fg=C["dim"], font=FN,
                     width=13, anchor="w").pack(side="left")
            var = tk.StringVar(value=ex.get("path", ""))
            styled_entry(r, textvariable=var, width=28).pack(
                side="left", fill="x", expand=True)
            self._fields["path"] = ("strvar", var)
            def browse(v=var):
                p = filedialog.askopenfilename(
                    filetypes=[("Executables", "*.exe"), ("All", "*.*")])
                if p:
                    v.set(p)
            styled_button(r, "…", browse).pack(side="left", padx=(4, 0))
        elif t == "script":
            tk.Label(self._ff,
                     text="Python  (locals: value, mouse, volume, mapping)",
                     bg=bg, fg=C["dim"], font=("Consolas", 8)).pack(anchor="w", pady=(0, 2))
            box = scrolledtext.ScrolledText(
                self._ff, width=36, height=4,
                bg=C["card2"], fg=C["accent"],
                insertbackground=C["accent"], font=FM, relief="flat")
            box.pack(fill="x")
            box.insert("1.0", ex.get("code", ""))
            self._fields["code"] = ("widget", box)
        elif t == "type_text":
            tk.Label(self._ff, text="Text to type:",
                     bg=bg, fg=C["dim"], font=FN).pack(anchor="w", pady=(0, 2))
            box = scrolledtext.ScrolledText(
                self._ff, width=36, height=3,
                bg=C["card2"], fg=C["text"],
                insertbackground=C["accent"], font=FM, relief="flat")
            box.pack(fill="x")
            box.insert("1.0", ex.get("text", ""))
            self._fields["text"] = ("widget", box)

            r = tk.Frame(self._ff, bg=bg)
            r.pack(fill="x", pady=(6, 0))
            tk.Label(r, text="Delay between chars:", bg=bg, fg=C["dim"], font=FN).pack(side="left")
            var = tk.StringVar(value=str(ex.get("char_delay_ms", 30)))
            tk.Spinbox(r, from_=0, to=1000, increment=5,
                       textvariable=var, width=6,
                       bg=C["card2"], fg=C["text"], insertbackground=C["accent"],
                       relief="flat", font=FM,
                       highlightthickness=1, highlightcolor=C["accent"],
                       highlightbackground=C["border"]).pack(side="left", padx=(6, 2))
            tk.Label(r, text="ms", bg=bg, fg=C["dim"], font=FN).pack(side="left")
            self._fields["char_delay_ms"] = ("strvar", var)

        elif t in ("volume", "zoom"):
            tk.Label(self._ff, text="No extra parameters.",
                     bg=bg, fg=C["dim"], font=FN).pack(anchor="w", pady=6)

        elif t == "mouse_move":
            r = tk.Frame(self._ff, bg=bg)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="Axis", bg=bg, fg=C["dim"], font=FN,
                     width=13, anchor="w").pack(side="left")
            var_axis = tk.StringVar(value=ex.get("axis", "x"))
            make_cb(r, var_axis, ["x", "y"], width=6).pack(side="left")
            self._fields["axis"] = ("strvar", var_axis)

            r2 = tk.Frame(self._ff, bg=bg)
            r2.pack(fill="x", pady=2)
            tk.Label(r2, text="Invert", bg=bg, fg=C["dim"], font=FN,
                     width=13, anchor="w").pack(side="left")
            var_inv = tk.BooleanVar(value=bool(ex.get("invert", False)))
            tk.Checkbutton(r2, variable=var_inv,
                           bg=bg, fg=C["text"], selectcolor=C["card2"],
                           activebackground=bg, relief="flat").pack(side="left")
            self._fields["invert"] = ("boolvar", var_inv)

    def get_action(self):
        t = self._type_var.get()
        action = {"type": t}
        for key, (kind, w) in self._fields.items():
            if kind == "boolvar":
                action[key] = bool(w.get())
            elif kind == "strvar":
                val = w.get().strip()
                if key == "ticks":
                    try:
                        val = int(val)
                    except ValueError:
                        val = 3
                if key == "char_delay_ms":
                    try:
                        val = int(val)
                    except ValueError:
                        val = 30
                action[key] = val
            else:
                action[key] = w.get("1.0", "end-1c")
        return action

    def set_action(self, action):
        self._action = dict(action) if action else {}
        self._type_var.set(self._action.get("type", self._types[0]))
        self._refresh()


# ═══════════════════════════════════════════════════════
#  ACTION STEP ROW  (one step in the action sequence)
# ═══════════════════════════════════════════════════════

class ActionStepRow(tk.Frame):
    """
    One step in a multi-action sequence.
    data = { "action": {...}, "delay_ms": 0, "condition": {...},
             "fire": "release", "stop_if_skipped": False }
    """
    def __init__(self, parent, action_types, index, data=None,
                 on_remove=None, on_move=None, bg=None, is_pad=False, **kw):
        super().__init__(parent, bg=bg or C["bg"], **kw)
        self._action_types  = action_types
        self._on_remove     = on_remove
        self._on_move       = on_move
        self._bg            = bg or C["bg"]
        self._index         = index
        self._is_pad        = is_pad
        data = data or {"action": {"type": action_types[0]}, "delay_ms": 0}
        self._delay_var        = tk.IntVar(value=int(data.get("delay_ms", 0)))
        _fire_stored           = data.get("fire", "release")
        self._fire_var         = tk.StringVar(value="on press" if _fire_stored == "press" else "on release")
        self._stop_skip_var    = tk.BooleanVar(value=bool(data.get("stop_if_skipped", False)))
        self._action_data      = data.get("action", {})
        self._condition_data   = data.get("condition")
        self._editor           = None
        self._cond_editor      = None
        self._build()

    def _build(self):
        card_bg = C["card"]
        border  = tk.Frame(self, bg=C["border"], padx=1, pady=1)
        border.pack(fill="x")
        outer = tk.Frame(border, bg=card_bg)
        outer.pack(fill="x")
        tk.Frame(outer, bg=C["accent"], width=4).pack(side="left", fill="y")
        card = tk.Frame(outer, bg=card_bg, padx=12, pady=8)
        card.pack(side="left", fill="x", expand=True)

        # ── Header row ────────────────────────────────────────
        hdr = tk.Frame(card, bg=card_bg)
        hdr.pack(fill="x", pady=(0, 4))
        self._step_lbl = tk.Label(hdr, text=f"Step {self._index + 1}",
                                   bg=card_bg, fg=C["accent"], font=FNB)
        self._step_lbl.pack(side="left")
        tk.Label(hdr, text="  delay after:", bg=card_bg, fg=C["dim"], font=FN).pack(side="left")
        tk.Spinbox(hdr, from_=0, to=10000, increment=50,
                   textvariable=self._delay_var, width=6,
                   bg=C["card2"], fg=C["text"], insertbackground=C["accent"],
                   relief="flat", font=FM, highlightthickness=1,
                   highlightcolor=C["accent"],
                   highlightbackground=C["border"]).pack(side="left", padx=(4, 2))
        tk.Label(hdr, text="ms", bg=card_bg, fg=C["dim"], font=FN).pack(side="left")
        if self._is_pad:
            tk.Label(hdr, text="  fire:", bg=card_bg, fg=C["dim"], font=FN).pack(side="left")
            make_cb(hdr, self._fire_var, ["on press", "on release"],
                    width=10).pack(side="left", padx=(4, 12))
            tk.Checkbutton(hdr, text="stop if skipped",
                           variable=self._stop_skip_var,
                           bg=card_bg, fg=C["dim"], selectcolor=C["card2"],
                           activebackground=card_bg, font=FN,
                           relief="flat").pack(side="left")
        btn_frame = tk.Frame(hdr, bg=card_bg)
        btn_frame.pack(side="right")
        tk.Button(btn_frame, text="▲", bg=card_bg, fg=C["dim"],
                  relief="flat", font=FN, cursor="hand2", padx=4, pady=2,
                  command=lambda: self._on_move and self._on_move(self, -1)
                  ).pack(side="left")
        tk.Button(btn_frame, text="▼", bg=card_bg, fg=C["dim"],
                  relief="flat", font=FN, cursor="hand2", padx=4, pady=2,
                  command=lambda: self._on_move and self._on_move(self, +1)
                  ).pack(side="left")
        tk.Button(btn_frame, text="✕", bg=card_bg, fg=C["danger"],
                  relief="flat", font=FN, cursor="hand2", padx=6, pady=2,
                  command=lambda: self._on_remove and self._on_remove(self)
                  ).pack(side="left", padx=(4, 0))

        self._cond_editor = InlineConditionRow(
            card, condition=self._condition_data, bg=card_bg, label="If value:")
        self._cond_editor.pack(fill="x", pady=(0, 6))

        self._editor = ActionEditorFrame(
            card, self._action_types, action=self._action_data, bg=card_bg)
        self._editor.pack(fill="x")

    def set_index(self, i):
        self._index = i
        self._step_lbl.configure(text=f"Step {i + 1}")

    def get_data(self):
        try:
            delay = int(self._delay_var.get())
        except (ValueError, tk.TclError):
            delay = 0
        # Map display label back to internal value
        fire_raw = self._fire_var.get()
        fire = "press" if fire_raw == "on press" else "release"
        d = {
            "action":   self._editor.get_action(),
            "delay_ms": max(0, delay),
            "fire":     fire,
        }
        if self._stop_skip_var.get():
            d["stop_if_skipped"] = True
        cond = self._cond_editor.get_condition()
        if cond:
            d["condition"] = cond
        return d


# ═══════════════════════════════════════════════════════
#  ACTION SEQUENCE EDITOR
# ═══════════════════════════════════════════════════════

class ActionSequenceEditor(tk.Frame):
    """
    Editor for an ordered list of action steps.
    allow_empty: if True, zero steps is permitted (pad hold-only mappings)
    """
    def __init__(self, parent, action_types, actions=None, allow_empty=False,
                 bg=None, is_pad=False, **kw):
        super().__init__(parent, bg=bg or C["card"], **kw)
        self._types       = action_types
        self._bg          = bg or C["card"]
        self._rows        = []
        self._allow_empty = allow_empty
        self._is_pad      = is_pad
        self._build(actions or [])

    def _build(self, actions):
        bg = self._bg
        hdr = tk.Frame(self, bg=bg)
        hdr.pack(fill="x", pady=(0, 8))
        section_lbl(hdr, "Actions  (executed in order)", bg=bg).pack(side="left")
        styled_button(hdr, "+ Add step", self._add_step,
                       color=C["card2"]).pack(side="right")

        self._rows_frame = tk.Frame(self, bg=bg)
        self._rows_frame.pack(fill="x")

        if actions:
            for step in actions:
                self._add_step(step)
        elif not self._allow_empty:
            self._add_step()

    def _add_step(self, data=None):
        idx = len(self._rows)
        row = ActionStepRow(
            self._rows_frame,
            action_types=self._types,
            index=idx,
            data=data,
            on_remove=self._remove_row,
            on_move=self._move_row,
            bg=self._bg,
            is_pad=self._is_pad,
        )
        row.pack(fill="x", pady=(0, 2))
        self._rows.append(row)
        self._renumber()

    def _remove_row(self, row):
        if not self._allow_empty and len(self._rows) == 1:
            messagebox.showinfo("Can't remove",
                                "A mapping must have at least one action step.\n"
                                "(Pad/button mappings can have zero steps for hold-only use.)",
                                parent=self)
            return
        self._rows.remove(row)
        row.pack_forget()
        row.destroy()
        self._renumber()

    def _move_row(self, row, direction):
        idx = self._rows.index(row)
        new_idx = idx + direction
        if not (0 <= new_idx < len(self._rows)):
            return
        self._rows[idx], self._rows[new_idx] = self._rows[new_idx], self._rows[idx]
        self._repack()

    def _repack(self):
        for r in self._rows:
            r.pack_forget()
        for r in self._rows:
            r.pack(fill="x", pady=(0, 2))
        self._renumber()

    def _renumber(self):
        for i, r in enumerate(self._rows):
            r.set_index(i)

    def get_actions(self):
        return [r.get_data() for r in self._rows]


# ═══════════════════════════════════════════════════════
#  VALUE CONDITION EDITOR
# ═══════════════════════════════════════════════════════

class ValueConditionFrame(tk.Frame):
    def __init__(self, parent, condition=None, bg=None, **kw):
        super().__init__(parent, bg=bg or C["card"], **kw)
        self._bg = bg or C["card"]
        self._condition = dict(condition) if condition else {"type": "any value"}
        self._params = {}
        self._build()

    def _build(self):
        bg = self._bg
        row = tk.Frame(self, bg=bg)
        row.pack(fill="x", pady=(0, 4))
        section_lbl(row, "Trigger condition", bg=bg).pack(side="left", padx=(0, 8))
        self._ctype_var = tk.StringVar(value=self._condition.get("type", "any value"))
        cb = make_cb(row, self._ctype_var, VALUE_CONDITIONS, width=18)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_params())
        self._pf = tk.Frame(self, bg=bg)
        self._pf.pack(fill="x")
        self._refresh_params()

    def _refresh_params(self):
        for w in self._pf.winfo_children():
            w.destroy()
        self._params = {}
        ct = self._ctype_var.get()
        bg = self._bg
        ex = self._condition

        def spin(label, key, default, lo=0, hi=127):
            col = tk.Frame(self._pf, bg=bg)
            col.pack(side="left", padx=(0, 16))
            tk.Label(col, text=label, bg=bg, fg=C["dim"], font=FN).pack(anchor="w")
            var = tk.IntVar(value=int(ex.get(key, default)))
            tk.Spinbox(col, from_=lo, to=hi, textvariable=var, width=5,
                       bg=C["card2"], fg=C["text"],
                       insertbackground=C["accent"], relief="flat", font=FM,
                       highlightthickness=1, highlightcolor=C["accent"],
                       highlightbackground=C["border"]).pack(anchor="w")
            self._params[key] = var

        if ct == "exact value":
            spin("Value (0–127)", "value", ex.get("value", 127))
        elif ct == "value in range":
            spin("Min", "min", ex.get("min", 0))
            spin("Max", "max", ex.get("max", 127))
        elif ct in ("value above", "value below"):
            spin("Threshold", "threshold", ex.get("threshold", 64))

    def get_condition(self):
        cond = {"type": self._ctype_var.get()}
        for key, var in self._params.items():
            cond[key] = var.get()
        return cond


# ═══════════════════════════════════════════════════════
#  INLINE CONDITION ROW
# ═══════════════════════════════════════════════════════

class InlineConditionRow(tk.Frame):
    def __init__(self, parent, condition=None, bg=None, label="Condition:", **kw):
        super().__init__(parent, bg=bg or C["card"], **kw)
        self._bg        = bg or C["card"]
        self._condition = dict(condition) if condition else {"type": "any value"}
        self._params    = {}
        self._label     = label
        self._build()

    def _build(self):
        bg  = self._bg
        row = tk.Frame(self, bg=bg)
        row.pack(fill="x")
        tk.Label(row, text=self._label, bg=bg, fg=C["dim"], font=FN,
                 width=11, anchor="w").pack(side="left")
        self._ctype_var = tk.StringVar(value=self._condition.get("type", "any value"))
        cb = make_cb(row, self._ctype_var, VALUE_CONDITIONS, width=16)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._refresh_params())
        self._pf = tk.Frame(self, bg=bg)
        self._pf.pack(fill="x", padx=(80, 0))
        self._refresh_params()

    def _refresh_params(self):
        for w in self._pf.winfo_children():
            w.destroy()
        self._params = {}
        ct  = self._ctype_var.get()
        bg  = self._bg
        ex  = self._condition

        def spin(label, key, default, lo=0, hi=127):
            f = tk.Frame(self._pf, bg=bg)
            f.pack(side="left", padx=(0, 12))
            tk.Label(f, text=label, bg=bg, fg=C["dim"], font=FN).pack(side="left", padx=(0, 4))
            var = tk.IntVar(value=int(ex.get(key, default)))
            tk.Spinbox(f, from_=lo, to=hi, textvariable=var, width=4,
                       bg=C["card2"], fg=C["text"], insertbackground=C["accent"],
                       relief="flat", font=FM, highlightthickness=1,
                       highlightcolor=C["accent"],
                       highlightbackground=C["border"]).pack(side="left")
            self._params[key] = var

        if ct == "exact value":
            spin("=", "value", ex.get("value", 127))
        elif ct == "value in range":
            spin("min", "min", ex.get("min", 0))
            spin("max", "max", ex.get("max", 127))
        elif ct in ("value above", "value below"):
            spin(">=" if ct == "value above" else "<=", "threshold", ex.get("threshold", 64))

    def get_condition(self):
        ct = self._ctype_var.get()
        if ct == "any value":
            return None
        cond = {"type": ct}
        for key, var in self._params.items():
            cond[key] = var.get()
        return cond


class SettingsEditorFrame(tk.Frame):
    def __init__(self, parent, input_type, settings=None, bg=None, **kw):
        super().__init__(parent, bg=bg or C["card"], **kw)
        self._bg = bg or C["card"]
        self._itype = input_type
        self._settings = dict(settings or default_settings_for(input_type))
        self._vars = {}
        self._build()

    def _build(self):
        bg = self._bg
        defs = MAPPING_SETTING_DEFAULTS.get(self._itype, {})
        if not defs:
            tk.Label(self, text="No per-mapping settings for this input type.",
                     bg=bg, fg=C["dim"], font=FN).pack(anchor="w")
            return
        for key, default in defs.items():
            row = tk.Frame(self, bg=bg)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=key.replace("_", " "), bg=bg, fg=C["dim"],
                     font=FN, width=22, anchor="w").pack(side="left")
            val = self._settings.get(key, default)
            if key == "axis":
                var = tk.StringVar(value=str(val))
                make_cb(row, var, ["x", "y"], width=4).pack(side="left")
                self._vars[key] = ("str", var)
            elif isinstance(default, bool):
                var = tk.BooleanVar(value=bool(val))
                tk.Checkbutton(row, variable=var, bg=bg, fg=C["text"],
                               selectcolor=C["card2"], activebackground=bg,
                               relief="flat").pack(side="left")
                self._vars[key] = ("bool", var)
            elif isinstance(default, float):
                var = tk.DoubleVar(value=float(val))
                wrap = tk.Frame(row, bg=C["border"], padx=1, pady=1)
                wrap.pack(side="left")
                tk.Scale(wrap, variable=var, from_=0.0, to=1.0, resolution=0.01,
                          orient="horizontal", length=148, bg=bg, fg=C["dim"],
                          troughcolor=C["card2"], highlightthickness=0, bd=0,
                          activebackground=C["accent"], sliderrelief="flat",
                          relief="flat").pack()
                self._vars[key] = ("float", var)
            elif isinstance(default, int):
                lo = 1 if "sensitivity" in key else 0
                hi = 500 if "ms" in key else 32
                var = tk.IntVar(value=int(val))
                wrap = tk.Frame(row, bg=C["border"], padx=1, pady=1)
                wrap.pack(side="left")
                tk.Scale(wrap, variable=var, from_=lo, to=hi,
                          orient="horizontal", length=148, bg=bg, fg=C["dim"],
                          troughcolor=C["card2"], highlightthickness=0, bd=0,
                          activebackground=C["accent"], sliderrelief="flat",
                          relief="flat").pack()
                self._vars[key] = ("int", var)

    def get_settings(self):
        return {k: v.get() for k, (_, v) in self._vars.items()}


# ═══════════════════════════════════════════════════════
#  HOLD ACTION ROW
# ═══════════════════════════════════════════════════════

class HoldActionRow(tk.Frame):
    def __init__(self, parent, data=None, on_remove=None, on_move=None, bg=None, **kw):
        super().__init__(parent, bg=bg or C["bg"], **kw)
        self._on_remove      = on_remove
        self._on_move        = on_move
        self._bg             = bg or C["bg"]
        data = data or {"threshold_ms": 300, "action": {"type": "key", "key": ""}}
        self._threshold_var  = tk.IntVar(value=int(data.get("threshold_ms", 300)))
        _immed               = data.get("immediate", False)
        self._fire_var       = tk.StringVar(value="on reached" if _immed else "on release")
        self._stop_skip_var  = tk.BooleanVar(value=bool(data.get("stop_if_skipped", False)))
        self._action         = data.get("action")
        self._condition_data = data.get("condition")
        self._editor         = None
        self._cond_editor    = None
        self._build()

    def _build(self):
        card_bg = C["card"]
        border = tk.Frame(self, bg=C["border"], padx=1, pady=1)
        border.pack(fill="x")
        outer = tk.Frame(border, bg=card_bg)
        outer.pack(fill="x")
        tk.Frame(outer, bg=C["accent2"], width=4).pack(side="left", fill="y")
        card = tk.Frame(outer, bg=card_bg, padx=12, pady=10)
        card.pack(side="left", fill="x", expand=True)

        hdr = tk.Frame(card, bg=card_bg)
        hdr.pack(fill="x", pady=(0, 8))
        tk.Label(hdr, text="⏱  Hold ≥", bg=card_bg, fg=C["accent2"], font=FNB).pack(side="left")
        tk.Spinbox(hdr, from_=50, to=10000, increment=50,
                   textvariable=self._threshold_var, width=6,
                   bg=C["card2"], fg=C["text"], insertbackground=C["accent"],
                   relief="flat", font=FM,
                   highlightthickness=1, highlightcolor=C["accent2"],
                   highlightbackground=C["border"]).pack(side="left", padx=(4, 2))
        tk.Label(hdr, text="ms", bg=card_bg, fg=C["dim"], font=FN).pack(side="left")
        tk.Label(hdr, text="  fire:", bg=card_bg, fg=C["dim"], font=FN).pack(side="left", padx=(10, 4))
        make_cb(hdr, self._fire_var, ["on release", "on reached"],
                width=11).pack(side="left", padx=(0, 12))
        tk.Checkbutton(hdr, text="stop if skipped",
                       variable=self._stop_skip_var,
                       bg=card_bg, fg=C["dim"], selectcolor=C["card2"],
                       activebackground=card_bg, font=FN,
                       relief="flat").pack(side="left")
        btn_frame = tk.Frame(hdr, bg=card_bg)
        btn_frame.pack(side="right")
        tk.Button(btn_frame, text="▲", bg=card_bg, fg=C["dim"], relief="flat",
                  font=FN, cursor="hand2", padx=4, pady=2,
                  command=lambda: self._on_move and self._on_move(self, -1)
                  ).pack(side="left")
        tk.Button(btn_frame, text="▼", bg=card_bg, fg=C["dim"], relief="flat",
                  font=FN, cursor="hand2", padx=4, pady=2,
                  command=lambda: self._on_move and self._on_move(self, +1)
                  ).pack(side="left")
        tk.Button(btn_frame, text="✕", bg=card_bg, fg=C["danger"], relief="flat",
                  font=FN, cursor="hand2", padx=6, pady=2,
                  command=lambda: self._on_remove and self._on_remove(self)
                  ).pack(side="left", padx=(4, 0))

        self._cond_editor = InlineConditionRow(
            card, condition=self._condition_data, bg=card_bg, label="If value:")
        self._cond_editor.pack(fill="x", pady=(0, 6))

        self._editor = ActionEditorFrame(card, ACTION_TYPES_PAD, action=self._action, bg=card_bg)
        self._editor.pack(fill="x")

    def get_data(self):
        try:
            threshold = int(self._threshold_var.get())
        except (ValueError, tk.TclError):
            threshold = 300
        d = {"threshold_ms": max(1, threshold), "action": self._editor.get_action()}
        if self._fire_var.get() == "on reached":
            d["immediate"] = True
        if self._stop_skip_var.get():
            d["stop_if_skipped"] = True
        cond = self._cond_editor.get_condition()
        if cond:
            d["condition"] = cond
        return d


# ═══════════════════════════════════════════════════════
#  HOLD ACTIONS SECTION
# ═══════════════════════════════════════════════════════

class HoldActionsEditor(tk.Frame):
    def __init__(self, parent, hold_actions=None, bg=None, **kw):
        super().__init__(parent, bg=bg or C["bg"], **kw)
        self._bg = bg or C["bg"]
        self._rows = []
        self._build(hold_actions or [])

    def _build(self, hold_actions):
        bg = self._bg
        hdr = tk.Frame(self, bg=bg)
        hdr.pack(fill="x", pady=(0, 8))
        section_lbl(hdr, "Hold actions  (longest threshold wins)", bg=bg).pack(side="left")
        styled_button(hdr, "+ Add hold", self._add_row, color=C["card2"]).pack(side="right")

        self._rows_frame = tk.Frame(self, bg=bg)
        self._rows_frame.pack(fill="x")

        for h in sorted(hold_actions, key=lambda x: x.get("threshold_ms", 300)):
            self._add_row(h)

    def _add_row(self, data=None):
        row = HoldActionRow(
            self._rows_frame, data=data,
            on_remove=self._remove_row,
            on_move=self._move_row,
            bg=self._bg
        )
        row.pack(fill="x", pady=(0, 4))
        self._rows.append(row)

    def _remove_row(self, row):
        self._rows.remove(row)
        row.pack_forget()
        row.destroy()

    def _move_row(self, row, direction):
        idx = self._rows.index(row)
        new_idx = idx + direction
        if 0 <= new_idx < len(self._rows):
            self._rows[idx], self._rows[new_idx] = self._rows[new_idx], self._rows[idx]
            self._repack()

    def _repack(self):
        for r in self._rows:
            r.pack_forget()
        for r in self._rows:
            r.pack(fill="x", pady=(0, 4))

    def get_hold_actions(self):
        return [r.get_data() for r in self._rows]


# ═══════════════════════════════════════════════════════
#  MAPPING EDIT PANEL
# ═══════════════════════════════════════════════════════

class MappingEditPanel(tk.Frame):
    def __init__(self, parent, mapping, on_save, on_delete, midi_manager=None, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self._mapping = dict(mapping)
        self._on_save = on_save
        self._on_delete = on_delete
        self._midi = midi_manager
        self._sequence_editor = None
        self._hold_editor = None
        self._settings_editor = None
        self._condition_editor = None
        self._settings_section = None
        self._canvas = None
        self._build()

    def _build(self):
        bg   = C["bg"]
        card = C["card"]

        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._body = tk.Frame(self._canvas, bg=bg)
        self._win = self._canvas.create_window((0, 0), window=self._body, anchor="nw")

        self._body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._build_body()

    def _on_body_configure(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._win, width=e.width)

    def _on_mousewheel(self, e):
        self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _section(self, label):
        f = tk.Frame(self._body, bg=C["bg"])
        f.pack(fill="x", padx=24, pady=(14, 0))
        section_lbl(f, label, bg=C["bg"]).pack(anchor="w")
        return f

    def _card_frame(self, parent=None):
        p = parent if parent is not None else self._body
        f = tk.Frame(p, bg=C["card"], padx=14, pady=10)
        f.pack(fill="x", padx=24, pady=(4, 0))
        return f

    def _build_body(self):
        bg   = C["bg"]
        card = C["card"]

        # ── Name ──────────────────────────────────────────────────
        self._section("Mapping name")
        name_card = self._card_frame()
        self._name_var = tk.StringVar(value=self._mapping.get("name", ""))
        styled_entry(name_card, textvariable=self._name_var, width=38).pack(anchor="w")
        hdiv(self._body, padx=24)

        # ── Input ─────────────────────────────────────────────────
        self._section("Input")
        in_card = self._card_frame()
        row_in  = tk.Frame(in_card, bg=card)
        row_in.pack(fill="x")

        cc_col = tk.Frame(row_in, bg=card)
        cc_col.pack(side="left", padx=(0, 16))
        tk.Label(cc_col, text="CC / Note #", bg=card, fg=C["dim"], font=FN).pack(anchor="w")
        self._cc_var = tk.StringVar(value=str(self._mapping.get("cc", "")))
        styled_entry(cc_col, textvariable=self._cc_var, width=6).pack(anchor="w", pady=(3, 0))

        mtype_col = tk.Frame(row_in, bg=card)
        mtype_col.pack(side="left", padx=(0, 16))
        tk.Label(mtype_col, text="Msg type", bg=card, fg=C["dim"], font=FN).pack(anchor="w")
        self._mtype_var = tk.StringVar(value=self._mapping.get("msg_type", "cc"))
        mtype_cb = make_cb(mtype_col, self._mtype_var, MSG_TYPES, width=10)
        mtype_cb.pack(anchor="w", pady=(3, 0))
        mtype_cb.bind("<<ComboboxSelected>>", lambda e: self._rebuild_hold_section())

        itype_col = tk.Frame(row_in, bg=card)
        itype_col.pack(side="left", padx=(0, 16))
        tk.Label(itype_col, text="Input type", bg=card, fg=C["dim"], font=FN).pack(anchor="w")
        raw_itype = self._mapping.get("input_type", "pad/button")
        raw_itype = {
            "any": "pad/button", "pad": "pad/button",
            "knob": "continuous", "knob/fader": "continuous",
            "trackpad_x": "continuous", "trackpad_y": "continuous",
            "slider": "continuous", "slider/trackpad": "continuous",
        }.get(raw_itype, raw_itype)
        self._itype_var = tk.StringVar(value=raw_itype)
        itype_cb = make_cb(itype_col, self._itype_var, INPUT_TYPES, width=14)
        itype_cb.pack(anchor="w", pady=(3, 0))
        itype_cb.bind("<<ComboboxSelected>>", lambda e: self._on_itype_change())

        learn_col = tk.Frame(row_in, bg=card)
        learn_col.pack(side="left")
        tk.Label(learn_col, text=" ", bg=card, font=FN).pack(anchor="w")
        if self._midi:
            styled_button(learn_col, "⊙  MIDI Learn", self._midi_learn,
                          color=C["accent"], fg=C["white"]).pack(anchor="w", pady=(3, 0))
        else:
            tk.Label(learn_col, text="(no device — Devices page first)",
                     bg=card, fg=C["dim"], font=FN).pack(anchor="w", pady=(8, 0))

        self._learn_lbl = tk.Label(in_card, text="", bg=card, fg=C["green"], font=FM)
        self._learn_lbl.pack(anchor="w", pady=(6, 0))
        hdiv(self._body, padx=24)

        # ── Value condition ───────────────────────────────────────
        self._section("Value condition")
        cond_card = self._card_frame()
        self._condition_editor = ValueConditionFrame(
            cond_card, condition=self._mapping.get("condition"), bg=card)
        self._condition_editor.pack(fill="x")
        hdiv(self._body, padx=24)

        # ── Actions ───────────────────────────────────────────────
        self._section("Actions")
        self._seq_card = self._card_frame()
        self._rebuild_sequence_editor()
        hdiv(self._body, padx=24)

        # ── Hold actions ──────────────────────────────────────────
        self._hold_outer = tk.Frame(self._body, bg=C["bg"])
        # don't pack here — _rebuild_hold_section manages pack/pack_forget
        self._hold_divider = tk.Frame(self._body, bg=C["border"], height=1)
        # don't pack here either
        self._rebuild_hold_section()

        # ── Per-mapping settings ──────────────────────────────────
        self._settings_section = self._section("Per-mapping settings")  # save reference
        self._settings_card = self._card_frame()
        self._rebuild_settings_editor()   # populate immediately

        # ── Footer ────────────────────────────────────────────────
        foot = tk.Frame(self._body, bg=bg)
        foot.pack(fill="x", padx=24, pady=14)
        styled_button(foot, "Save mapping", self._save,
                      color=C["accent"], fg=C["white"]).pack(side="left", padx=(0, 8))
        styled_button(foot, "Delete", self._delete,
                      color=C["danger"], fg=C["white"]).pack(side="left")

    # ── rebuild helpers ───────────────────────────────────────────

    def _action_types_for(self, itype):
        if itype == "continuous":
            return ACTION_TYPES_CONTINUOUS
        return ACTION_TYPES_PAD

    def _cfg_itype(self, itype):
        return {
            "pad/button": "pad", "continuous": "continuous",
            "knob/fader": "continuous", "slider/trackpad": "continuous",
            "any": "pad", "knob": "continuous", "slider": "continuous",
            "trackpad_x": "continuous", "trackpad_y": "continuous",
        }.get(itype, "pad")

    def _is_pad(self):
        return self._itype_var.get() == "pad/button"

    def _rebuild_sequence_editor(self):
        for w in self._seq_card.winfo_children():
            w.destroy()
        itype  = self._itype_var.get()
        atypes = self._action_types_for(itype)
        existing = self._mapping.get("actions")
        if not existing:
            old = self._mapping.get("action")
            existing = [{"action": old, "delay_ms": 0}] if old else []
        self._sequence_editor = ActionSequenceEditor(
            self._seq_card, atypes, actions=existing,
            allow_empty=self._is_pad(), is_pad=self._is_pad(), bg=C["card"])
        self._sequence_editor.pack(fill="x")
        self._refresh_scroll()

    def _rebuild_hold_section(self):
        for w in self._hold_outer.winfo_children():
            w.destroy()
        self._hold_editor = None

        show = self._is_pad() and self._mtype_var.get() != "note_off"

        if show:
            bg   = C["bg"]
            card = C["card"]
            lbl_frame = tk.Frame(self._hold_outer, bg=bg)
            lbl_frame.pack(fill="x", padx=24, pady=(14, 0))
            section_lbl(lbl_frame, "Hold actions", bg=bg).pack(anchor="w")
            hold_card = tk.Frame(self._hold_outer, bg=card, padx=14, pady=10)
            hold_card.pack(fill="x", padx=24, pady=(4, 0))
            existing = self._mapping.get("hold_actions", [])
            if not existing:
                old = self._mapping.get("on_hold", {})
                if old.get("enabled") and old.get("action"):
                    existing = [{"threshold_ms": 300, "action": old["action"]}]
            self._hold_editor = HoldActionsEditor(hold_card, hold_actions=existing, bg=card)
            self._hold_editor.pack(fill="x")

            self._hold_outer.pack(fill="x", **({"before": self._settings_section} if self._settings_section else {}))
            self._hold_divider.pack(fill="x", padx=24, **({"before": self._settings_section} if self._settings_section else {}))
        else:
            self._hold_outer.pack_forget()
            self._hold_divider.pack_forget()

        self._refresh_scroll()

    def _rebuild_settings_editor(self):
        for w in self._settings_card.winfo_children():
            w.destroy()
        self._settings_editor = None
        cfg = self._cfg_itype(self._itype_var.get())
        if not MAPPING_SETTING_DEFAULTS.get(cfg):
            tk.Label(self._settings_card,
                     text="No per-mapping settings for this input type.",
                     bg=C["card"], fg=C["dim"], font=FN).pack(anchor="w")
            return
        self._settings_editor = SettingsEditorFrame(
            self._settings_card, cfg,
            settings=self._mapping.get("settings"), bg=C["card"])
        self._settings_editor.pack(fill="x")
        self._refresh_scroll()

    def _refresh_scroll(self):
        """Force the canvas scroll region to update after any layout change."""
        self._body.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_itype_change(self):
        self._rebuild_sequence_editor()
        self._rebuild_hold_section()
        self._rebuild_settings_editor()

    # ── MIDI learn ────────────────────────────────────────────────

    def _midi_learn(self):
        if not self._midi or not self._midi.connected_devices:
            messagebox.showinfo("MIDI Learn",
                                "No MIDI device connected.\n"
                                "Go to the Devices page and select one first.",
                                parent=self)
            return
        dlg = MidiLearnDialog(self, self._midi)
        if dlg.result:
            msg_type, number, value = dlg.result
            self._cc_var.set(str(number))
            self._mtype_var.set(msg_type)
            label = {"cc": "CC", "note_on": "Note On",
                     "note_off": "Note Off"}.get(msg_type, msg_type)
            self._learn_lbl.configure(
                text=f"Learned  {label} #{number}  value {value}")
            self._rebuild_hold_section()

    # ── collect / save / delete ───────────────────────────────────

    def _collect(self):
        m = dict(self._mapping)
        m["name"]       = self._name_var.get().strip()
        m["input_type"] = self._itype_var.get()
        m["msg_type"]   = self._mtype_var.get()
        try:
            m["cc"] = int(self._cc_var.get())
        except ValueError:
            messagebox.showerror("Invalid number", "CC / Note # must be 0–127.", parent=self)
            return None
        if not (0 <= m["cc"] <= 127):
            messagebox.showerror("Invalid number", "CC / Note # must be 0–127.", parent=self)
            return None
        m["condition"] = self._condition_editor.get_condition()
        m["actions"]   = self._sequence_editor.get_actions()
        m.pop("action", None)
        m["settings"]  = self._settings_editor.get_settings() \
                         if self._settings_editor else {}
        if self._hold_editor is not None:
            holds = self._hold_editor.get_hold_actions()
            m["hold_actions"] = holds if holds else []
        else:
            m.pop("hold_actions", None)
        m.pop("on_hold", None)
        return m

    def _save(self):
        m = self._collect()
        if m:
            self._mapping = m
            self._on_save(m)

    def _delete(self):
        name = self._mapping.get("name") or f"CC {self._mapping.get('cc', '')}"
        if messagebox.askyesno("Delete mapping", f"Delete '{name}'?", parent=self):
            self._on_delete(self._mapping["id"])


# ═══════════════════════════════════════════════════════
#  MAPPINGS PAGE
# ═══════════════════════════════════════════════════════

class MappingsPage(tk.Frame):
    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self._app = app
        self._selected_id = None
        self._edit_panel = None
        self._build()

    def _build(self):
        self._list_panel = tk.Frame(self, bg=C["sidebar"], width=230)
        self._list_panel.pack(side="left", fill="y")
        self._list_panel.pack_propagate(False)

        hdr = tk.Frame(self._list_panel, bg=C["sidebar"])
        hdr.pack(fill="x", padx=12, pady=10)
        tk.Label(hdr, text="Mappings", bg=C["sidebar"], fg=C["white"], font=FT).pack(side="left")
        styled_button(hdr, "+ New", self._new_mapping,
                      color=C["accent"], fg=C["white"]).pack(side="right")
        hdiv(self._list_panel, bg=C["border"])

        lc = tk.Canvas(self._list_panel, bg=C["sidebar"], highlightthickness=0)
        lsb = ttk.Scrollbar(self._list_panel, orient="vertical", command=lc.yview)
        lc.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        lc.pack(fill="both", expand=True)

        self._list_inner = tk.Frame(lc, bg=C["sidebar"])
        win = lc.create_window((0, 0), window=self._list_inner, anchor="nw")
        self._list_inner.bind("<Configure>",
            lambda e: lc.configure(scrollregion=lc.bbox("all")))
        lc.bind("<Configure>", lambda e: lc.itemconfig(win, width=e.width))

        self._right = tk.Frame(self, bg=C["bg"])
        self._right.pack(side="left", fill="both", expand=True)

        self._empty_lbl = tk.Label(
            self._right,
            text="Select a mapping  or  click  + New",
            bg=C["bg"], fg=C["dim"], font=("Segoe UI", 11))
        self._empty_lbl.place(relx=0.5, rely=0.5, anchor="center")

        self._edit_container = tk.Frame(self._right, bg=C["bg"])
        self._edit_container.place(x=0, y=0, relwidth=1, relheight=1)
        self._edit_container.lower()

        self._edit_panel = None
        self._refresh_list()

    def _show_edit(self, mapping):
        if self._edit_panel:
            self._edit_panel.destroy()
            self._edit_panel = None
        self._edit_panel = MappingEditPanel(
            self._edit_container, mapping,
            on_save=self._on_save,
            on_delete=self._on_delete,
            midi_manager=self._app.midi)
        self._edit_panel.pack(fill="both", expand=True)
        self._edit_container.lift()
        self._empty_lbl.lower()

    def _on_delete(self, mid):
        self._app.config["mappings"] = [
            m for m in self._app.config["mappings"] if m["id"] != mid]
        self._app.save()
        self._selected_id = None
        if self._edit_panel:
            self._edit_panel.destroy()
            self._edit_panel = None
        self._edit_container.lower()
        self._empty_lbl.lift()
        self._refresh_list()

    def _refresh_list(self, rebuild_panel=True):
        for w in self._list_inner.winfo_children():
            w.destroy()
        mappings = self._app.config.get("mappings", [])
        if not mappings:
            tk.Label(self._list_inner, text="No mappings yet.",
                     bg=C["sidebar"], fg=C["dim"], font=FN).pack(pady=14, padx=12)
            return

        badge_colors = {
            "pad/button": C["accent"],
            "continuous":  C["green"],
            "knob/fader": C["green"], "slider/trackpad": C["green"],
            "trackpad_x": C["green"], "trackpad_y": C["green"], "any": C["dim"],
        }

        for m in mappings:
            mid   = m.get("id", "")
            sel   = (mid == self._selected_id)
            bg    = C["card"] if sel else C["sidebar"]
            itype = m.get("input_type", "")
            cc    = m.get("cc", "?")
            mtype = m.get("msg_type", "cc")
            name  = m.get("name") or f"CC {cc}"

            bar_color = badge_colors.get(itype, C["dim"])
            row_outer = tk.Frame(self._list_inner, bg=bg, cursor="hand2")
            row_outer.pack(fill="x")
            tk.Frame(row_outer, bg=bar_color, width=3).pack(side="left", fill="y")

            if mtype == "note_on":
                badge_txt = f"N↑{cc}"
            elif mtype == "note_off":
                badge_txt = f"N↓{cc}"
            else:
                badge_txt = f"CC{cc}"

            step_actions = m.get("actions", [])
            if not step_actions and m.get("action"):
                step_actions = [{"action": m["action"]}]
            sub = actions_summary(step_actions)
            cond = m.get("condition", {})
            if cond.get("type") and cond["type"] != "any value":
                sub = (sub + "  " + cond["type"]) if sub else cond["type"]
            hold_count = len(m.get("hold_actions", []))
            if hold_count:
                hold_hint = f"  +{hold_count} hold{'s' if hold_count > 1 else ''}"
                sub = (sub + hold_hint) if sub else hold_hint

            tk.Label(row_outer, text=f" {badge_txt} ",
                     bg=badge_colors.get(itype, C["dim"]), fg=C["white"],
                     font=("Consolas", 7, "bold")).pack(side="left", padx=(4, 6), pady=8)

            info = tk.Frame(row_outer, bg=bg)
            info.pack(side="left", fill="x", expand=True, pady=8)
            tk.Label(info, text=name, bg=bg,
                     fg=C["white"] if sel else C["text"],
                     font=FNB, anchor="w").pack(anchor="w")
            if sub:
                tk.Label(info, text=sub, bg=bg, fg=C["dim"],
                          font=("Consolas", 8), anchor="w").pack(anchor="w")

            nav = tk.Frame(row_outer, bg=bg)
            nav.pack(side="right", padx=4)
            tk.Button(nav, text="▲", bg=bg, fg=C["dim"], relief="flat",
                      font=FN, cursor="hand2", padx=3, pady=1,
                      command=lambda m=m: self._move_mapping(m["id"], -1)
                      ).pack()
            tk.Button(nav, text="▼", bg=bg, fg=C["dim"], relief="flat",
                      font=FN, cursor="hand2", padx=3, pady=1,
                      command=lambda m=m: self._move_mapping(m["id"], +1)
                      ).pack()

            def click(e, mid=mid):
                self._select(mid)

            for w in (row_outer, info) + tuple(info.winfo_children()):
                w.bind("<Button-1>", click)

            hdiv(self._list_inner, bg=C["border"])

    def _move_mapping(self, mid, direction):
        mappings = self._app.config["mappings"]
        idx = next((i for i, m in enumerate(mappings) if m["id"] == mid), None)
        if idx is None:
            return
        new_idx = idx + direction
        if not (0 <= new_idx < len(mappings)):
            return
        mappings[idx], mappings[new_idx] = mappings[new_idx], mappings[idx]
        self._app.save()
        self._refresh_list()

    def _select(self, mid):
        self._selected_id = mid
        self._refresh_list()
        if self._edit_panel and getattr(self._edit_panel, '_mapping', {}).get('id') == mid:
            return  # already showing this mapping, don't rebuild
        m = next((x for x in self._app.config["mappings"] if x["id"] == mid), None)
        if m:
            self._show_edit(m)

    def _on_save(self, updated):
        for i, m in enumerate(self._app.config["mappings"]):
            if m["id"] == updated["id"]:
                self._app.config["mappings"][i] = updated
                break
        self._app.save()
        self._refresh_list(rebuild_panel=False)
        # no panel rebuild — it stays exactly as-is

    def _new_mapping(self):
        m = {
            "id":         new_mapping_id(),
            "name":       "",
            "cc":         0,
            "msg_type":   "cc",
            "input_type": "pad/button",
            "condition":  {"type": "any value"},
            "actions":    [],
            "settings":   {},
        }
        self._app.config["mappings"].append(m)
        self._app.save()
        self._select(m["id"])

    def on_show(self):
        self._refresh_list()


# ═══════════════════════════════════════════════════════
#  DEVICES PAGE
# ═══════════════════════════════════════════════════════

class DevicesPage(tk.Frame):
    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self._app = app
        self._checks = {}
        self._build()

    def _build(self):
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=40, pady=30)
        tk.Label(wrap, text="MIDI Devices", bg=C["bg"], fg=C["white"], font=FT).pack(anchor="w")
        tk.Label(wrap,
                 text="Select the MIDI devices the engine should listen to. "
                      "Devices are watched automatically — plug/unplug without restarting.",
                 bg=C["bg"], fg=C["dim"], font=FN).pack(anchor="w", pady=(4, 20))
        section_lbl(wrap, "Available MIDI inputs", bg=C["bg"]).pack(anchor="w")
        self._check_card = tk.Frame(wrap, bg=C["card"], padx=16, pady=12)
        self._check_card.pack(fill="x", pady=(4, 4), ipadx=4)
        self._check_inner = tk.Frame(self._check_card, bg=C["card"])
        self._check_inner.pack(fill="x")
        self._status_lbl = tk.Label(wrap, text="", bg=C["bg"], fg=C["green"], font=FM)
        self._status_lbl.pack(anchor="w", pady=(4, 12))
        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(anchor="w")
        styled_button(btns, "↻  Refresh", self._refresh_devices).pack(side="left", padx=(0, 8))
        styled_button(btns, "Save", self._save,
                       color=C["accent"], fg=C["white"]).pack(side="left")
        self._refresh_devices()

    def _refresh_devices(self):
        for w in self._check_inner.winfo_children():
            w.destroy()
        self._checks = {}
        devices   = MidiManager.list_inputs() if _midi_ok else []
        selected  = self._app.config.get("devices", [])
        connected = self._app.midi.connected_devices if self._app.midi else []
        if not devices:
            tk.Label(self._check_inner, text="No MIDI devices found.",
                     bg=C["card"], fg=C["dim"], font=FN).pack(anchor="w")
        else:
            for name in devices:
                row = tk.Frame(self._check_inner, bg=C["card"])
                row.pack(fill="x", pady=2)
                var = tk.BooleanVar(value=(name in selected))
                tk.Checkbutton(row, text=name, variable=var,
                    bg=C["card"], fg=C["text"], selectcolor=C["card2"],
                    activebackground=C["card"], activeforeground=C["white"],
                    font=FM, relief="flat").pack(side="left")
                dot_color = C["green"] if name in connected else C["dim"]
                tk.Label(row, text="●" if name in connected else "○",
                         bg=C["card"], fg=dot_color, font=FM).pack(side="left", padx=(6, 0))
                self._checks[name] = var
        if connected:
            self._status_lbl.configure(text=f"Connected: {', '.join(connected)}", fg=C["green"])
        else:
            self._status_lbl.configure(text="No devices connected.", fg=C["dim"])

    def _save(self):
        selected = [n for n, v in self._checks.items() if v.get()]
        self._app.config["devices"] = selected
        self._app.save()
        if self._app.midi:
            for name in selected:
                if name not in self._app.midi.connected_devices:
                    self._app.midi.open_device(name)

    def notify_device_change(self):
        try:
            self._refresh_devices()
        except Exception:
            pass

    def on_show(self):
        self._refresh_devices()


# ═══════════════════════════════════════════════════════
#  MIDI MONITOR WINDOW
# ═══════════════════════════════════════════════════════

class MidiMonitorWindow(tk.Toplevel):
    def __init__(self, parent, midi_manager):
        super().__init__(parent)
        self.title("MIDI Monitor")
        self.configure(bg=C["bg"])
        self.geometry("560x400")
        self._midi    = midi_manager
        self._q       = queue.Queue()
        self._orig_cb = None
        self._build()
        self._install_tap()
        self._poll()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        hdr = tk.Frame(self, bg=C["bg"])
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(hdr, text="MIDI Monitor", bg=C["bg"], fg=C["white"], font=FNB).pack(side="left")
        styled_button(hdr, "Clear", self._clear).pack(side="right")
        tk.Label(hdr,
                 text="Live raw MIDI — type, number, value",
                 bg=C["bg"], fg=C["dim"], font=FN).pack(side="left", padx=(12, 0))
        self._pause_var = tk.BooleanVar(value=True)
        tk.Checkbutton(hdr, text="Pause actions while open",
                       variable=self._pause_var,
                       bg=C["bg"], fg=C["dim"], selectcolor=C["card2"],
                       activebackground=C["bg"], activeforeground=C["text"],
                       font=FN, relief="flat",
                       command=self._on_pause_toggle).pack(side="right", padx=(0, 8))
        self._box = scrolledtext.ScrolledText(
            self, bg=C["sidebar"], fg=C["green"], font=FM,
            state="disabled", relief="flat")
        self._box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _install_tap(self):
        if not self._midi:
            return
        self._orig_cb = self._midi._callback
        def tap(device, msg_type, number, value):
            label = {"cc": "CC ", "note_on": "ON ", "note_off": "OFF"}.get(msg_type, msg_type[:3])
            self._q.put(f"{device[:26]:<26}  {label}  #{number:>3}  val {value:>3}\n")
            if not self._pause_var.get() and self._orig_cb:
                self._orig_cb(device, msg_type, number, value)
        self._midi.set_callback(tap)

    def _on_pause_toggle(self):
        pass

    def _poll(self):
        try:
            while True:
                line = self._q.get_nowait()
                self._box.configure(state="normal")
                self._box.insert("end", line)
                self._box.see("end")
                n = int(self._box.index("end-1c").split(".")[0])
                if n > 600:
                    self._box.delete("1.0", f"{n-500}.0")
                self._box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(40, self._poll)

    def _clear(self):
        self._box.configure(state="normal")
        self._box.delete("1.0", "end")
        self._box.configure(state="disabled")

    def _on_close(self):
        if self._midi and self._orig_cb is not None:
            self._midi.set_callback(self._orig_cb)
        self.destroy()


# ═══════════════════════════════════════════════════════
#  SETTINGS PAGE
# ═══════════════════════════════════════════════════════

class SettingsPage(tk.Frame):
    def __init__(self, parent, app, **kw):
        super().__init__(parent, bg=C["bg"], **kw)
        self._app = app
        self._build()

    def _build(self):
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True, padx=40, pady=30)

        tk.Label(wrap, text="Settings", bg=C["bg"], fg=C["white"], font=FT).pack(anchor="w")
        tk.Label(wrap, text="Application settings and Windows integration.",
                 bg=C["bg"], fg=C["dim"], font=FN).pack(anchor="w", pady=(4, 24))

        # ── Windows integration ──────────────────────────────────
        section_lbl(wrap, "Windows Integration", bg=C["bg"]).pack(anchor="w")
        integ_card = tk.Frame(wrap, bg=C["card"], padx=16, pady=14)
        integ_card.pack(fill="x", pady=(4, 20))

        self._shortcut_status = tk.StringVar(value="")

        if not _shortcuts_ok:
            tk.Label(integ_card,
                     text="pywin32 not installed — run:  pip install pywin32",
                     bg=C["card"], fg=C["yellow"], font=FM).pack(anchor="w")
        else:
            btn_row = tk.Frame(integ_card, bg=C["card"])
            btn_row.pack(anchor="w")

            styled_button(btn_row, "☰  Add to Start Menu",
                          self._add_start_menu,
                          color=C["card2"]).pack(side="left", padx=(0, 8))

            self._startup_btn = styled_button(btn_row, "",
                                              self._toggle_startup,
                                              color=C["card2"])
            self._startup_btn.pack(side="left")
            self._refresh_startup_btn()

            tk.Label(integ_card, textvariable=self._shortcut_status,
                     bg=C["card"], fg=C["green"], font=FM,
                     wraplength=500, justify="left").pack(anchor="w", pady=(8, 0))

        # ── Running the engine ───────────────────────────────────
        section_lbl(wrap, "Running the engine", bg=C["bg"]).pack(anchor="w", pady=(10, 0))
        run_card = tk.Frame(wrap, bg=C["card"], padx=16, pady=14)
        run_card.pack(fill="x", pady=(4, 20))
        info = (
            "  main.py is the single entry point. It starts the engine,\n"
            "  the system tray icon, and this GUI.\n\n"
            "  Left-click the tray icon to open this window.\n"
            "  Right-click for enable/disable, MIDI Monitor, and Exit.\n\n"
            "    pythonw main.py          ← background (no console window)\n"
            "    python  main.py          ← background with console\n"
            "    python  main.py --gui    ← open GUI window immediately\n"
            "    python  main.py --console← print MIDI activity to stdout"
        )
        tk.Label(run_card, text=info, bg=C["card"], fg=C["text"],
                 font=("Consolas", 9), justify="left").pack(anchor="w")

        # ── Config file ──────────────────────────────────────────
        section_lbl(wrap, "Config file", bg=C["bg"]).pack(anchor="w", pady=(10, 0))
        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(anchor="w", pady=(6, 0))
        styled_button(btns, "Export config.json…", self._export).pack(side="left", padx=(0, 8))
        styled_button(btns, "View raw JSON", self._view_json).pack(side="left")

    # ── shortcut helpers ─────────────────────────────────────────

    def _refresh_startup_btn(self):
        if not _shortcuts_ok:
            return
        if startup_shortcut_exists():
            self._startup_btn.configure(text="✕  Remove from Startup")
        else:
            self._startup_btn.configure(text="⏻  Add to Startup")

    def _add_start_menu(self):
        msg = create_start_menu_shortcut()
        self._shortcut_status.set(msg)

    def _toggle_startup(self):
        if startup_shortcut_exists():
            msg = remove_startup_shortcut()
        else:
            msg = create_startup_shortcut()
        self._shortcut_status.set(msg)
        self._refresh_startup_btn()

    # ── config helpers ───────────────────────────────────────────

    def _export(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
            initialfile="config.json")
        if path:
            with open(path, "w") as f:
                json.dump(self._app.config, f, indent=4)

    def _view_json(self):
        win = tk.Toplevel(self._app.root)
        win.title("config.json")
        win.configure(bg=C["bg"])
        box = scrolledtext.ScrolledText(win, width=72, height=36,
                                          bg=C["card"], fg=C["accent"], font=FM)
        box.pack(padx=12, pady=12, fill="both", expand=True)
        box.insert("1.0", json.dumps(self._app.config, indent=4))
        box.configure(state="disabled")

    def on_show(self):
        if _shortcuts_ok:
            self._refresh_startup_btn()


# ═══════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════

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
        # Set window / taskbar icon
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

    def _make_icon_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#4f9eff")
        d.ellipse([18, 18, 46, 46], fill="#111214")
        return img

    def _get_icon_path(self):
        """Return path to foxmidi.ico — works both as script and frozen exe."""
        if getattr(sys, "frozen", False):
            # Bundled assets extracted to _MEIPASS at runtime
            base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        else:
            # assets/ lives next to main.py, one level above foxmidi/ package
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
            pystray.MenuItem("Open GUI", show_gui, default=True),
            pystray.MenuItem("MIDI Monitor",   show_monitor),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",           quit_app),
        )
        self._tray = pystray.Icon("FoxMIDI", self._make_icon_image(), "FoxMIDI", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def open_monitor(self):
        if self._monitor_win and self._monitor_win.winfo_exists():
            self._monitor_win.lift()
            return
        self._monitor_win = MidiMonitorWindow(self.root, self.midi)

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

            # Dropdown popup list colors — kill the white border
            self.root.option_add("*TCombobox*Listbox.background", C["card"])
            self.root.option_add("*TCombobox*Listbox.foreground", C["white"])
            self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
            self.root.option_add("*TCombobox*Listbox.selectForeground", C["white"])
            self.root.option_add("*TCombobox*Listbox.relief", "flat")
            self.root.option_add("*TCombobox*Listbox.borderWidth", "0")
            self.root.option_add("*TCombobox*Listbox.highlightThickness", "0")

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
        y_mid  = canvas_height // 2
        fox_id = canvas.create_text(0, y_mid, text="Fox", fill=C["accent"], font=font, anchor="w")
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

        # All pages use place so switching is instantaneous — no pack/unpack flash
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
        self._pages[pid].on_show()  # rebuild while still hidden
        self._pages[pid].lift()     # then reveal fully built

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