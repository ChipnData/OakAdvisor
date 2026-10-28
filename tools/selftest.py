"""Quick check that screen reading works (run by the build, or by hand)."""
import os
import sys
import tempfile

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from oakadvisor.icons import IconLibrary  # noqa: E402
from oakadvisor.vision import Reader  # noqa: E402

lib = IconLibrary(tempfile.mkdtemp())
r = Reader(lib)
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {want!r})"))


st = r.read(cv2.imread(os.path.join(HERE, "..", "tests", "sample_day7.png")))
check("gold", st.gold, 67)
check("day", st.day, 7)
check("wins", st.wins, 4)
check("hearts", (st.hearts, st.hearts_max), (6, 10))
check("xp", (st.xp, st.xp_need), (4, 60))
check("costs", (st.reroll_cost, st.level_cost), (1, 4))
check("prices", [s.price for s in st.shop], [35, 35, 20, 20, 35, 25, 25])
check("tags", [s.packs for s in st.shop],
      [["Arcane", "Witch"], ["Witch"], ["Dragon"], ["Vampire"], ["Moon"], ["Arcane"], ["Crystal", "Frosty"]])
check("upgrade glow", [s.upgrade_glow for s in st.shop], [False, True, False, False, False, False, False])
check("tower tiers", [o.tier for o in st.tower], [2, 1, 2, 1, 2, 2])

st = r.read(cv2.imread(os.path.join(HERE, "..", "tests", "sample_day8_sale.png")))
check("sale prices", [(s.price, s.sale) for s in st.shop],
      [(15, True), (10, True), (15, True), (8, True), (None, False), (12, True), (18, True)])
check("tower tiers day 8", [o.tier for o in st.tower], [2, 1, 2, 1, 3, 2])
sys.exit(1 if fails else 0)
