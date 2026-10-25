# PyInstaller の設定（ADR-044）。Windows で次を実行すると dist/kokosimnew/ にできる。
#
#     pip install pyinstaller
#     pyinstaller --noconfirm kokosimnew.spec
#
# dist/kokosimnew/kokosimnew.exe を開く。セーブは同じフォルダの saves/ に置かれる。
from pathlib import Path

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "phase2_engine" / "screen" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "data"), "data"),
        (str(ROOT / "config"), "config"),
        (str(ROOT / "historical_data" / "koshien_records.csv"), "historical_data"),
        # 学校の評判の初期値（game_core/school_reputation.py）が読む
        (str(ROOT / "historical_data" / "koshien_entrants.csv"), "historical_data"),
        (str(ROOT / "historical_data" / "autumn_regional_entrants_2025.csv"), "historical_data"),
        (str(ROOT / "phase2_engine" / "screen" / "web"), "phase2_engine/screen/web"),
    ],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kokosimnew",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="kokosimnew")
