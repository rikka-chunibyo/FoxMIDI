import mido
import mido.backends.rtmidi  # explicit import so PyInstaller bundles it
import threading
import time
import logging

log = logging.getLogger("midi")

# Explicitly set backend — autodiscovery fails in frozen executables
mido.set_backend("mido.backends.rtmidi")

class MidiManager:
    def __init__(self):
        self._ports = {}        # name → mido port
        self._threads = {}      # name → thread
        self._callback = None

    @staticmethod
    def list_inputs():
        try:
            return mido.get_input_names()
        except Exception:
            return []

    def set_callback(self, callback):
        self._callback = callback

    def open_device(self, name):
        if name in self._ports:
            return True
        try:
            port = mido.open_input(name)
            self._ports[name] = port
            t = threading.Thread(target=self._listen, args=(name, port), daemon=True)
            self._threads[name] = t
            t.start()
            log.info(f"Opened MIDI device: {name}")
            return True
        except Exception as e:
            log.warning(f"Could not open '{name}': {e}")
            return False

    def close_device(self, name):
        port = self._ports.pop(name, None)
        if port:
            try:
                port.close()
            except Exception:
                pass
        self._threads.pop(name, None)

    def close_all(self):
        for name in list(self._ports.keys()):
            self.close_device(name)

    def _listen(self, name, port):
        try:
            for msg in port:
                if not self._callback:
                    continue
                if msg.type == "control_change":
                    self._callback(name, "cc", msg.control, msg.value)
                elif msg.type == "note_on":
                    # note_on with velocity 0 is a note_off by MIDI convention
                    if msg.velocity == 0:
                        self._callback(name, "note_off", msg.note, msg.velocity)
                    else:
                        self._callback(name, "note_on", msg.note, msg.velocity)
                elif msg.type == "note_off":
                    self._callback(name, "note_off", msg.note, msg.velocity)
        except Exception as e:
            log.warning(f"Device '{name}' disconnected: {e}")
        finally:
            self._ports.pop(name, None)
            self._threads.pop(name, None)

    @property
    def connected_devices(self):
        return list(self._ports.keys())


class DeviceWatcher:
    """
    Background thread that watches for configured devices to appear/disappear.
    Calls on_connect(name) / on_disconnect(name).
    """
    def __init__(self, get_target_devices, on_connect, on_disconnect, poll_interval=2.0):
        self._get_targets = get_target_devices
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._interval = poll_interval
        self._known = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                available = set(MidiManager.list_inputs())
                targets = set(self._get_targets())

                appeared = (available & targets) - self._known
                disappeared = self._known - available

                for name in appeared:
                    self._known.add(name)
                    self._on_connect(name)

                for name in disappeared:
                    self._known.discard(name)
                    self._on_disconnect(name)

            except Exception as e:
                log.warning(f"DeviceWatcher error: {e}")

            self._stop.wait(self._interval)