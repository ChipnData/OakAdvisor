"""Screen layout of Oaken Tower's shop phase.

All boxes are (x0, y0, x1, y1) in a 2560x1440 "game frame" — the 16:9 area the
game draws (on a 3440x1440 ultrawide it is centred with black bars).
Any capture is resized to this frame before reading, so other resolutions work
as long as the game keeps the same 16:9 layout.
"""

FRAME_W, FRAME_H = 2560, 1440

_SHOP_CENTRES = [(1200, 395), (1452, 395), (1704, 395), (1956, 395),
                 (1275, 760), (1578, 760), (1880, 760)]
_TAG_Y = [286, 286, 286, 286, 653, 653, 653]
_PRICE_Y = [532, 532, 532, 532, 898, 898, 898]

SHOP_ICON = [(cx - 115, cy - 95, cx + 115, cy + 95) for cx, cy in _SHOP_CENTRES]
SHOP_TAG = [(cx - 130, y - 18, cx + 130, y + 18) for (cx, _), y in zip(_SHOP_CENTRES, _TAG_Y)]
# price box is tall enough to hold a struck-through price plus the SALE price under it
SHOP_PRICE = [(cx - 110, y - 55, cx + 110, y + 115) for (cx, _), y in zip(_SHOP_CENTRES, _PRICE_Y)]
SHOP_OCR_REGION = (1040, 240, 2120, 700)  # one OCR pass here reads every pack tag

TOWER = [(x0, y0, x0 + 212, y0 + 212) for y0 in (336, 598, 860) for x0 in (196, 458)]
TOWER_INSET = (16, 24, 16, 36)  # left, top, right, bottom trimmed off a tile (frame, badges, stars)

GOLD = (965, 1160, 1105, 1218)
INCOME = (860, 1218, 1105, 1258)
LEVEL = (860, 1272, 1105, 1302)
XP = (890, 1302, 1100, 1362)
DAY = (1060, 22, 1140, 95)
TROPHIES = (1240, 22, 1385, 95)
HEARTS = (1490, 22, 1650, 95)
ODDS = (1705, 18, 2005, 72)
REROLL_COST = (2108, 1098, 2170, 1138)   # digits only, coin icon excluded
LEVEL_COST = (2455, 1098, 2520, 1138)
REROLL_BTN = (2065, 985, 2175, 1090)
FREEZE_BTN = (2238, 985, 2348, 1090)
LEVEL_BTN = (2412, 985, 2522, 1090)
LEAVE_BTN = (2180, 110, 2420, 310)
STORAGE = (1125, 1148, 2455, 1432)

PACKS = ["Dragon", "Witch", "Moon", "Dark", "Arcane", "Neutral", "Frosty", "Crystal",
         "Vampire", "Goblin", "Poison", "Burn", "Bleed", "Holy", "Nature"]
RARITIES = ["Common", "Rare", "Epic", "Legendary"]


def scale_box(box, sx: float, sy: float):
    x0, y0, x1, y1 = box
    return int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)


def tower_inner(i: int):
    x0, y0, x1, y1 = TOWER[i]
    l, t, r, b = TOWER_INSET
    return x0 + l, y0 + t, x1 - r, y1 - b


def which_slot(x: float, y: float):
    """Map a point in frame coords to ('shop', i) / ('tower', i) / ('storage', None)."""
    for i, (x0, y0, x1, y1) in enumerate(SHOP_ICON):
        if x0 - 20 <= x <= x1 + 20 and y0 - 40 <= y <= y1 + 60:
            return "shop", i
    for i, (x0, y0, x1, y1) in enumerate(TOWER):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return "tower", i
    x0, y0, x1, y1 = STORAGE
    if x0 <= x <= x1 and y0 <= y <= y1:
        return "storage", None
    return None, None
