import ctypes
import time

user32 = ctypes.windll.user32

MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
VK_CONTROL = 0x11


def send_ctrl_wheel(ticks: int):
    if ticks == 0:
        return
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(WHEEL_DELTA * ticks), 0)
    user32.keybd_event(VK_CONTROL, 0, 2, 0)


class FastMouse:
    def __init__(self):
        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        self._last_x = -1
        self._last_y = -1
        self._last_time = 0.0

    def move_absolute(self, cc_x: int, cc_y: int, debounce: float = 0.0015):
        px = int((cc_x / 127) * self.screen_w)
        py = int(self.screen_h - (cc_y / 127) * self.screen_h)

        now = time.time()
        if now - self._last_time < debounce:
            return
        if px == self._last_x and py == self._last_y:
            return

        user32.SetCursorPos(px, py)
        self._last_x = px
        self._last_y = py
        self._last_time = now
