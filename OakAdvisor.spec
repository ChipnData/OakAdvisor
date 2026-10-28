# PyInstaller build file — used by the GitHub Actions workflow (or run: pyinstaller OakAdvisor.spec)
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

EXCLUDES = ["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtPdf",
            "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtLocation",
            "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
            "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSpatialAudio", "PySide6.QtVirtualKeyboard"]

datas = [("oakadvisor/assets", "oakadvisor/assets")]
datas += collect_data_files("rapidocr_onnxruntime")
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(["main.py"], pathex=["."], datas=datas, binaries=binaries,
             hiddenimports=collect_submodules("rapidocr_onnxruntime"), excludes=EXCLUDES)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OakAdvisor",
          console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="OakAdvisor")
