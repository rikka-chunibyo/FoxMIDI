"""
gui_theme.py  —  FoxMIDI
Theme constants, font tuples, action-type lists, and stateless widget helpers.
"""
import os
import tkinter as tk
from tkinter import ttk, scrolledtext

# ═══════════════════════════════════════════════════════
#  COLOURS & FONTS
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

# ═══════════════════════════════════════════════════════
#  ACTION / INPUT LISTS
# ═══════════════════════════════════════════════════════
INPUT_TYPES = ["pad/button", "continuous"]
MSG_TYPES   = ["cc", "note_on", "note_off"]

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

# ═══════════════════════════════════════════════════════
#  ACTION SUMMARY HELPERS
# ═══════════════════════════════════════════════════════

def actions_summary(actions):
    """Summarise a list of action steps for the sidebar."""
    if not actions:
        return ""
    parts = []
    for step in actions[:3]:
        a = step.get("action", {})
        t = a.get("type", "")
        if t == "key":          parts.append(f"⌨ {a.get('key','')}")
        elif t == "type_text":
            txt = (a.get("text") or "").replace("\n", " ")
            parts.append(f"T  {txt[:20]}{'…' if len(txt)>20 else ''}")
        elif t == "scroll":     parts.append(f"↕ {a.get('ticks',1):+}")
        elif t == "application":parts.append(f"▶ {os.path.basename(a.get('path','') or '')}")
        elif t == "script":     parts.append("⚡ script")
        elif t == "volume":     parts.append("🔊 vol")
        elif t == "zoom":       parts.append("🔍 zoom")
        elif t == "mouse_move": parts.append("🖱 move")
        elif t == "mouse_click":parts.append(f"🖱 {a.get('button','left')}-click")
        else:                   parts.append(t)
    tail = f"  +{len(actions)-3} more" if len(actions) > 3 else ""
    return "  →  ".join(parts) + tail

def action_summary_single(action):
    if not action:
        return ""
    t = action.get("type", "")
    if t == "key":          return f"⌨  {action.get('key','')}"
    if t == "scroll":       return f"↕  scroll {action.get('ticks', 1):+}"
    if t == "application":  return f"▶  {os.path.basename(action.get('path', '') or '')}"
    if t == "script":
        c = (action.get("code") or "").strip()
        return f"⚡  {c[:28]}{'…' if len(c)>28 else ''}"
    if t == "volume":       return "🔊  volume"
    if t == "zoom":         return "🔍  zoom"
    if t == "mouse_move":   return "🖱  mouse"
    return t
