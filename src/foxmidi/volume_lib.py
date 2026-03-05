from ctypes import POINTER, cast
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import time


class VolumeController:
    def __init__(self):
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        self.volume = cast(interface, POINTER(IAudioEndpointVolume))
        self._current = 50.0
        self._last_time = 0.0

    def set_percent(self, percent: float):
        percent = max(0.0, min(100.0, percent))
        self.volume.SetMasterVolumeLevelScalar(percent / 100.0, None)

    def handle_cc(self, value: int, smoothing: float = 0.3):
        if value <= 5:
            target = 0.0
        elif value >= 122:
            target = 100.0
        else:
            target = ((value - 5) / 116) * 100.0

        if target <= 8:
            self._current = 0.0
        elif target >= 92:
            self._current = 100.0
        else:
            self._current = self._current * (1.0 - smoothing) + target * smoothing

        now = time.time()
        if now - self._last_time >= 0.016:
            self.set_percent(self._current)
            self._last_time = now
