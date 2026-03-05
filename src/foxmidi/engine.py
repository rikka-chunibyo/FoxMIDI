import time
import threading
import keyboard
import subprocess
import logging
import ctypes
from foxmidi.mouse_lib import send_ctrl_wheel, FastMouse
from foxmidi.volume_lib import VolumeController

log = logging.getLogger("engine")

_user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN   = 0x0002
MOUSEEVENTF_LEFTUP     = 0x0004
MOUSEEVENTF_RIGHTDOWN  = 0x0008
MOUSEEVENTF_RIGHTUP    = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP   = 0x0040

def check_condition(condition, value, last_value):
    if not condition:
        return True
    ct = condition.get("type", "any value")
    if ct == "any value":        return True
    if ct == "exact value":      return value == condition.get("value", 127)
    if ct == "value increasing": return value > last_value
    if ct == "value decreasing": return value < last_value
    if ct == "value unchanged":  return value == last_value
    if ct == "value in range":   return condition.get("min", 0) <= value <= condition.get("max", 127)
    if ct == "value above":      return value > condition.get("threshold", 64)
    if ct == "value below":      return value < condition.get("threshold", 64)
    return True


def _normalise_itype(itype):
    return {
        "any":             "pad/button",
        "pad":             "pad/button",
        "knob":            "continuous",
        "knob/fader":      "continuous",
        "slider/trackpad": "continuous",
        "trackpad_x":      "continuous",
        "trackpad_y":      "continuous",
        "slider":          "continuous",
    }.get(itype, itype)


class MappingEngine:
    def __init__(self, config):
        self.config = config
        self.mouse  = FastMouse()
        self.volume = VolumeController()

        # (mapped_msg_type, number) → (press_timestamp, press_value)
        self._pad_press     = {}
        self._knob_last_value = {}
        self._knob_remainder  = {}
        self._last_value      = {}   # (msg_type, number) → last value
        self._axis_pos        = {}
        self._pad_timers      = {}   # press_key → list of threading.Timer (immediate holds)

    def reload_config(self, config):
        self.config = config

    def handle_midi(self, device_name, msg_type, number, value):
        key  = (msg_type, number)
        last = self._last_value.get(key, value)

        for mapping in self.config.get("mappings", []):
            if mapping.get("cc") != number:
                continue

            mapped_mtype = mapping.get("msg_type", "cc")
            itype = _normalise_itype(mapping.get("input_type", "pad/button"))

            if itype == "pad/button":
                if mapped_mtype == "note_off":
                    # note_off mappings fire immediately on note_off — no hold concept
                    if msg_type == "note_off":
                        condition = mapping.get("condition")
                        if check_condition(condition, value, last):
                            self._run_sequence(mapping, mapped_mtype, number, value)

                elif mapped_mtype == "note_on":
                    # press on note_on, release/fire on paired note_off
                    if msg_type in ("note_on", "note_off"):
                        self._pad(mapping, msg_type, number, value)

                elif mapped_mtype == "cc":
                    if msg_type == "cc":
                        self._pad(mapping, msg_type, number, value)

            elif itype == "continuous":
                if msg_type != mapped_mtype:
                    continue
                condition = mapping.get("condition")
                if check_condition(condition, value, last):
                    self._continuous(mapping, number, value)

        self._last_value[key] = value

    def handle_cc(self, device_name, cc, value):
        self.handle_midi(device_name, "cc", cc, value)

    def _pad(self, mapping, msg_type, number, value):
        press_key    = (mapping.get("msg_type", "cc"), number)
        mapped_mtype = mapping.get("msg_type", "cc")

        # ── Press ──────────────────────────────────────────────
        is_press = (msg_type == "note_on") or (msg_type == "cc" and value != 0)
        if is_press:
            self._pad_press[press_key] = (time.time(), value)

            # Run steps marked fire="press" immediately
            steps = mapping.get("actions", [])
            press_steps = [s for s in steps if s.get("fire", "release") == "press"]
            if press_steps:
                condition = mapping.get("condition")
                last      = self._last_value.get((mapped_mtype, number), 0)
                if check_condition(condition, value, last):
                    self._run_steps(press_steps, mapping, mapped_mtype, number, value)

            # Schedule timers for immediate hold actions
            hold_actions   = mapping.get("hold_actions", [])
            immed_holds    = [h for h in hold_actions if h.get("immediate", False)]
            if immed_holds:
                timers = []
                for hold in immed_holds:
                    def _make_fire(h, v):
                        def _fire():
                            if check_condition(h.get("condition"), v, 0):
                                self._run_single(h.get("action"), mapping, v)
                            elif h.get("stop_if_skipped", False):
                                # Cancel all sibling timers that haven't fired yet
                                for t in self._pad_timers.pop(press_key, []):
                                    t.cancel()
                        return _fire
                    t = threading.Timer(
                        hold.get("threshold_ms", 300) / 1000.0,
                        _make_fire(hold, value))
                    t.daemon = True
                    timers.append(t)
                self._pad_timers[press_key] = timers
                for t in timers:
                    t.start()
            return

        # ── Release ────────────────────────────────────────────
        held_ms     = 0
        press_value = value
        if press_key in self._pad_press:
            press_time, press_value = self._pad_press.pop(press_key)
            held_ms = (time.time() - press_time) * 1000

        # Cancel any pending immediate hold timers (button released before threshold)
        for t in self._pad_timers.pop(press_key, []):
            t.cancel()

        trigger_value = press_value

        # Non-immediate holds: fire highest matched threshold on release
        hold_actions      = mapping.get("hold_actions", [])
        non_immed_holds   = [h for h in hold_actions if not h.get("immediate", False)]
        if non_immed_holds:
            for hold in sorted(non_immed_holds,
                               key=lambda h: h.get("threshold_ms", 0),
                               reverse=True):
                if held_ms >= hold.get("threshold_ms", 300):
                    if check_condition(hold.get("condition"), trigger_value, 0):
                        self._run_single(hold.get("action"), mapping, trigger_value)
                        return   # fired — hold consumed the release
                    elif hold.get("stop_if_skipped", False):
                        return   # condition failed but stop requested — block regular steps
                    # condition failed, stop_if_skipped=False — fall through to regular steps

        # Run steps marked fire="release" (or unmarked — default)
        steps = mapping.get("actions", [])
        if not steps:
            old = mapping.get("action")
            if old:
                steps = [{"action": old, "delay_ms": 0, "fire": "release"}]
        release_steps = [s for s in steps if s.get("fire", "release") == "release"]

        condition = mapping.get("condition")
        last      = self._last_value.get((mapped_mtype, number), 0)
        if check_condition(condition, trigger_value, last):
            self._run_steps(release_steps, mapping, mapped_mtype, number, trigger_value)

    def _continuous(self, mapping, number, value):
        settings = mapping.get("settings", {})

        action = self._first_action(mapping)
        atype  = (action or {}).get("type", "")

        if atype == "mouse_move":
            if (action or {}).get("invert", False):
                value = 127 - value
        else:
            if settings.get("invert", False):
                value = 127 - value

        if atype == "mouse_move":
            self._axis_pos[number] = value
            axis = (action or {}).get("axis", "x")
            x_val = y_val = 64
            for m in self.config.get("mappings", []):
                if m.get("id") == mapping.get("id"):
                    continue
                if _normalise_itype(m.get("input_type", "")) != "continuous":
                    continue
                fa = self._first_action(m)
                if not fa or fa.get("type") != "mouse_move":
                    continue
                other_axis = fa.get("axis", "x")
                if other_axis == axis:
                    continue
                other_val = self._axis_pos.get(m.get("cc"), 64)
                if axis == "x": x_val, y_val = value, other_val
                else:           x_val, y_val = other_val, value
                break
            else:
                if axis == "x": x_val, y_val = value, 64
                else:           x_val, y_val = 64, value
            debounce = settings.get("debounce_ms", 1.5) / 1000.0
            self.mouse.move_absolute(x_val, y_val, debounce)

        elif atype == "volume":
            self.volume.handle_cc(value, settings.get("smoothing", 0.3))

        elif atype == "zoom":
            sensitivity = settings.get("sensitivity", 8)
            last  = self._knob_last_value.get(number, value)
            delta = value - last
            self._knob_last_value[number] = value
            rem   = self._knob_remainder.get(number, 0.0) + delta
            ticks = round(rem / sensitivity)
            if ticks != 0:
                rem -= ticks * sensitivity
                send_ctrl_wheel(ticks)
            self._knob_remainder[number] = rem

        else:
            self._run_sequence(mapping, "cc", number, value)

    def _first_action(self, mapping):
        steps = mapping.get("actions")
        if steps:
            return steps[0].get("action")
        return mapping.get("action")

    def _run_sequence(self, mapping, msg_type, number, value=None):
        """Legacy entry-point: collects all steps and delegates to _run_steps."""
        steps = mapping.get("actions")
        if not steps:
            old = mapping.get("action")
            if old:
                steps = [{"action": old, "delay_ms": 0}]
        if not steps:
            return
        self._run_steps(steps, mapping, msg_type, number, value)

    def _run_steps(self, steps, mapping, msg_type, number, value=None):
        """Execute a list of step dicts, honouring delay_ms, per-step condition,
        and stop_if_skipped."""
        if not steps:
            return
        last = self._last_value.get((msg_type, number), value)

        if len(steps) == 1 and steps[0].get("delay_ms", 0) == 0:
            step = steps[0]
            if check_condition(step.get("condition"), value, last):
                self._run_single(step.get("action"), mapping, value)
            # stop_if_skipped on a lone step is a no-op
            return

        def run():
            for i, step in enumerate(steps):
                if check_condition(step.get("condition"), value, last):
                    self._run_single(step.get("action"), mapping, value)
                else:
                    if step.get("stop_if_skipped", False):
                        break
                delay = step.get("delay_ms", 0)
                if delay > 0 and i < len(steps) - 1:
                    time.sleep(delay / 1000.0)
        threading.Thread(target=run, daemon=True).start()

    def _run_single(self, action, mapping, value=None):
        if not action:
            return
        t = action.get("type", "")
        try:
            if t == "key":
                keyboard.send(action.get("key", ""))
            elif t == "type_text":
                text  = action.get("text", "")
                delay = action.get("char_delay_ms", 30) / 1000.0
                for ch in text:
                    keyboard.write(ch)
                    if delay > 0:
                        time.sleep(delay)
            elif t == "scroll":
                send_ctrl_wheel(action.get("ticks", 1))
            elif t == "mouse_click":
                btn = action.get("button", "left")
                if btn == "left":
                    _user32.mouse_event(MOUSEEVENTF_LEFTDOWN,   0, 0, 0, 0)
                    _user32.mouse_event(MOUSEEVENTF_LEFTUP,     0, 0, 0, 0)
                elif btn == "right":
                    _user32.mouse_event(MOUSEEVENTF_RIGHTDOWN,  0, 0, 0, 0)
                    _user32.mouse_event(MOUSEEVENTF_RIGHTUP,    0, 0, 0, 0)
                elif btn == "middle":
                    _user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
                    _user32.mouse_event(MOUSEEVENTF_MIDDLEUP,   0, 0, 0, 0)
            elif t == "application":
                path = (action.get("path") or "").strip()
                if path:
                    subprocess.Popen(path, shell=True)
            elif t == "script":
                code = (action.get("code") or "").strip()
                if code:
                    exec(code, {
                        "value": value, "mouse": self.mouse,
                        "volume": self.volume, "mapping": mapping,
                    })
            elif t == "mouse_move":
                if isinstance(value, dict):
                    self.mouse.move_absolute(value["x"], value["y"])
        except Exception as e:
            log.error(f"Action error [{t}]: {e}")