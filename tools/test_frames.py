"""Run the screen reader + advisor on saved screenshots (no game needed).

    python tools/test_frames.py path/to/screenshot.png [more.png ...]

Screenshots can be full-monitor captures (3440x1440 etc.) or just the game area."""
import os
import sys
import tempfile

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from oakadvisor import capture, config  # noqa: E402
from oakadvisor.advisor import advise, RunTracker  # noqa: E402
from oakadvisor.icons import IconLibrary  # noqa: E402
from oakadvisor.vision import Reader  # noqa: E402


def main(paths):
    cfg, adv = config.load()
    root = config.data_dir() if "--mylib" in paths else tempfile.mkdtemp()
    if root != config.data_dir():
        config.seed_library(root)
    lib = IconLibrary(root)
    reader = Reader(lib)
    tracker = RunTracker()
    for p in [p for p in paths if not p.startswith("--")]:
        img = cv2.imread(p)
        x, y, w, h = capture.fit_16_9(0, 0, img.shape[1], img.shape[0])
        st = reader.read(img[y:y + h, x:x + w])
        tracker.update(st)
        a = advise(st, lib, adv, tracker)
        print(f"\n=== {os.path.basename(p)}")
        print(f"day {st.day} wins {st.wins} hearts {st.hearts}/{st.hearts_max} gold {st.gold} income {st.income} "
              f"level {st.level} xp {st.xp}/{st.xp_need} reroll {st.reroll_cost} xp-cost {st.level_cost} odds {st.odds}")
        for s in st.shop:
            if not s.empty:
                sa = a.slots.get(s.index)
                print(f"  shop {s.index}: {s.name or '?':18s} {'/'.join(s.packs):16s} {s.price}g"
                      f"{' SALE' if s.sale else ''}{' UPGRADE' if s.upgrade_glow else ''}  -> {sa.action if sa else ''} {sa.score if sa else ''}")
        print("  tower:", [(o.index, o.name, o.tier) for o in st.tower])
        print("  storage items:", len(st.storage))
        for s in a.steps:
            print("  >", s)
        for n in a.notes:
            print("  *", n)


if __name__ == "__main__":
    main(sys.argv[1:])
