"""
gui_widgets.py  —  FoxMIDI
Reusable editor widgets: action editor, step/hold rows, condition editors,
settings editor, and the MIDI Learn dialog.
These have no knowledge of pages or the App object.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

from foxmidi.config import default_settings_for, MAPPING_SETTING_DEFAULTS
from foxmidi.gui_theme import (
    C, FN, FNB, FM,
    VALUE_CONDITIONS,
    styled_button, styled_entry, section_lbl, make_cb,
)


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
#  ACTION EDITOR  (single action, no delay)
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


# ═══════════════════════════════════════════════════════
#  SETTINGS EDITOR
# ═══════════════════════════════════════════════════════

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
            if isinstance(default, bool):
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
    allow_empty: if True, zero steps is permitted (pad hold-only mappings).
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

        # Hold actions only use pad action types
        from foxmidi.gui_theme import ACTION_TYPES_PAD
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
