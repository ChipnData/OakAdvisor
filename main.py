"""Oak Advisor — shop helper for Oaken Tower. Run: python main.py

    OakAdvisor.exe --selftest screenshot.png   reads a screenshot and prints what it sees
"""
import sys


def selftest(path):
    import tempfile
    import cv2
    from oakadvisor import capture
    from oakadvisor.advisor import advise, Settings
    from oakadvisor.icons import IconLibrary
    from oakadvisor.vision import Reader
    img = cv2.imread(path)
    x, y, w, h = capture.fit_16_9(0, 0, img.shape[1], img.shape[0])
    st = Reader(IconLibrary(tempfile.mkdtemp())).read(img[y:y + h, x:x + w])
    print("gold", st.gold, "day", st.day, "wins", st.wins, "hearts", st.hearts,
          "prices", [s.price for s in st.shop], "tags", [s.packs for s in st.shop])
    print("warnings", st.warnings)
    print(advise(st, IconLibrary(tempfile.mkdtemp()), Settings()).steps)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    else:
        from oakadvisor.ui import run
        run()
