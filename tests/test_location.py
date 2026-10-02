"""起動時の置き場所の確認。python tests/test_location.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import check_location

ENV = {"OneDrive": r"C:\Users\masak\OneDrive", "ProgramFiles": r"C:\Program Files",
       "ProgramFiles(x86)": r"C:\Program Files (x86)"}
TEMP = r"C:\Users\masak\AppData\Local\Temp"
n = 0
for path, kw, want in [
    (r"C:\Users\masak\yukkuri-accent", {}, []),                                           # おすすめの場所
    (r"C:\Users\masak\OneDrive\デスクトップ\yukkuri-accent", {}, [("warn", "sync:OneDrive")]),
    (r"C:\Users\masak\OneDrive - 株式会社○○\Documents\ya", {}, [("warn", "sync:OneDrive")]),  # 法人の OneDrive
    (r"C:\Users\masak\OneDriveX\ya", {}, []),                                             # 似た名前は違う
    (r"D:\Dropbox\tools\ya", {}, [("warn", "sync:Dropbox")]),
    (r"G:\マイドライブ\ya", {}, [("warn", "sync:Google ドライブ")]),
    (TEMP + r"\Temp1_yukkuri-accent-v0.5.1-windows.zip\yukkuri-accent", {}, [("crit", "zip")]),
    (TEMP + r"\7zO1234\yukkuri-accent", {}, [("crit", "zip")]),                           # 一時フォルダ
    (r"C:\Program Files\yukkuri-accent", {"writable": False}, [("crit", "readonly"), ("warn", "programfiles")]),
    (r"C:\Program Files (x86)\ya", {}, [("warn", "programfiles")]),
]:
    got = check_location(path, ENV, TEMP, **kw)
    assert got == want, (path, got, want)
    n += 1
print(f"置き場所 {n} 件 OK")
