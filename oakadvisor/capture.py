"""Finding the game window and grabbing its picture (Windows)."""
from __future__ import annotations
import ctypes
import sys
from dataclasses import dataclass

import numpy as np

IS_WIN = sys.platform == "win32"
GAME_TITLE = "Oaken Tower"


@dataclass
class GameArea:
    x: int      # physical screen pixels of the 16:9 area the game draws
    y: int
    w: int
    h: int
    source: str  # "window" or "monitor"


def make_dpi_aware():
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware: real pixels
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _find_window(title_part: str):
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value
            if title_part.lower() in t.lower() and "advisor" not in t.lower():
                found.append((t.strip().lower() != title_part.lower(), len(t), hwnd))
        return True

    user32.EnumWindows(cb, 0)
    found.sort()  # exact title first (a browser tab named "Oaken Tower guide" loses)
    return found[0][2] if found else None


def _client_rect(hwnd):
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def fit_16_9(x, y, w, h):
    """The game keeps a 16:9 picture centred in its window (bars on ultrawide)."""
    if w <= 0 or h <= 0:
        return x, y, w, h
    if w / h > 16 / 9:
        gw = round(h * 16 / 9)
        return x + (w - gw) // 2, y, gw, h
    gh = round(w * 9 / 16)
    return x, y + (h - gh) // 2, w, gh


def locate(cfg) -> GameArea | None:
    """Window first; otherwise the monitor chosen in settings."""
    if cfg.get("manual_area"):
        x, y, w, h = cfg["manual_area"]
        return GameArea(x, y, w, h, "manual")
    if IS_WIN:
        hwnd = _find_window(cfg.get("window_title", GAME_TITLE))
        if hwnd:
            x, y, w, h = _client_rect(hwnd)
            if w > 200 and h > 200:
                return GameArea(*fit_16_9(x, y, w, h), "window")
    import mss
    with mss.mss() as s:
        mons = s.monitors[1:]
        idx = min(max(int(cfg.get("monitor", 1)), 1), len(mons)) - 1
        m = mons[idx]
        return GameArea(*fit_16_9(m["left"], m["top"], m["width"], m["height"]), "monitor")


def grab(area: GameArea) -> np.ndarray:
    import mss
    with mss.mss() as s:
        shot = s.grab({"left": area.x, "top": area.y, "width": area.w, "height": area.h})
        img = np.asarray(shot)[:, :, :3]  # BGRA -> BGR
        return np.ascontiguousarray(img)


def cursor_pos():
    if not IS_WIN:
        return None
    from ctypes import wintypes
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def to_frame_coords(area: GameArea, sx: int, sy: int, fw=2560, fh=1440):
    return (sx - area.x) * fw / area.w, (sy - area.y) * fh / area.h
