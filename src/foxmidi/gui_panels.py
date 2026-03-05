"""
gui_panels.py  —  FoxMIDI
Page-level composites: MappingEditPanel, MappingsPage, DevicesPage,
MidiMonitorWindow, SettingsPage.
These hold references to the App object and own full-page layout.
"""
import json
import queue
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

from foxmidi.config import new_mapping_id, MAPPING_SETTING_DEFAULTS
from foxmidi.gui_theme import (
    C, FN, FNB, FM, FT,
    INPUT_TYPES, MSG_TYPES, ACTION_TYPES_PAD, ACTION_TYPES_CONTINUOUS,
    styled_button, styled_entry, section_lbl, hdiv, make_cb,
    actions_summary,
)
from foxmidi.gui_widgets import (
    MidiLearnDialog,
    ActionSequenceEditor,
    ValueConditionFrame,
    SettingsEditorFrame,
    HoldActionsEditor,
)

try:
    from foxmidi.midi_lib import MidiManager
    _midi_ok = True
except Exception:
    _midi_ok = False

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
        bg = C["bg"]

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
        self._hold_divider = tk.Frame(self._body, bg=C["border"], height=1)
        self._rebuild_hold_section()

        # ── Per-mapping settings ──────────────────────────────────
        self._settings_section = self._section("Per-mapping settings")
        self._settings_card = self._card_frame()
        self._rebuild_settings_editor()

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
            return
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
            "    pythonw main.py             ← open GUI (no console window)\n"
            "    python  main.py             ← open GUI with console\n"
            "    pythonw main.py --silent    ← start in background, no GUI"
        )
        tk.Label(run_card, text=info, bg=C["card"], fg=C["text"],
                 font=("Consolas", 9), justify="left").pack(anchor="w")

        # ── Config file ──────────────────────────────────────────
        section_lbl(wrap, "Config file", bg=C["bg"]).pack(anchor="w", pady=(10, 0))
        btns = tk.Frame(wrap, bg=C["bg"])
        btns.pack(anchor="w", pady=(6, 0))
        styled_button(btns, "Export config.json…", self._export).pack(side="left", padx=(0, 8))
        styled_button(btns, "View raw JSON", self._view_json).pack(side="left")

    def _refresh_startup_btn(self):
        if not _shortcuts_ok:
            return
        if startup_shortcut_exists():
            self._startup_btn.configure(text="✕  Remove from Startup")
        else:
            self._startup_btn.configure(text="⏻  Add to Startup")

    def _add_start_menu(self):
        self._shortcut_status.set(create_start_menu_shortcut())

    def _toggle_startup(self):
        if startup_shortcut_exists():
            msg = remove_startup_shortcut()
        else:
            msg = create_startup_shortcut()
        self._shortcut_status.set(msg)
        self._refresh_startup_btn()

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