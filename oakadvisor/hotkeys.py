"""Global hotkeys (work while the game has focus) via the Win32 RegisterHotKey API."""
from __future__ import annotations
import ctypes
import sys

from PySide6.QtCore import QThread, Signal

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
VK = {f"F{i}": 0x6F + i for i in range(1, 13)}  # F1=0x70 ... F12=0x7B


class HotkeyThread(QThread):
    pressed = Signal(str)
    failed = Signal(str)

    def __init__(self, keys: dict):
        """keys: {"scan": "F8", "learn": "F9", "overlay": "F10"}"""
        super().__init__()
        self.keys = keys
        self._tid = None

    def run(self):
        if sys.platform != "win32":
            return
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._tid = kernel32.GetCurrentThreadId()
        ids = {}
        for n, (action, key) in enumerate(self.keys.items(), start=1):
            vk = VK.get(key.upper())
            if vk is None:
                self.failed.emit(f"Unknown key {key}")
                continue
            if user32.RegisterHotKey(None, n, MOD_NOREPEAT, vk):
                ids[n] = action
            else:
                self.failed.emit(f"{key} is already used by another program")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.pressed.emit(ids[msg.wParam])
        for n in ids:
            user32.UnregisterHotKey(None, n)

    def stop(self):
        if sys.platform == "win32" and self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self.wait(1000)
