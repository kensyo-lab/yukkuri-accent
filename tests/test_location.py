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

# 試聴で読む所（うっかり改行や記号だけを選んでいたら全体を読む）
from accent_core import preview_text
WHOLE = "ぶ'んしょうです。\nこれわ/て_スと"
m = 0
for sel, want in [
    (None, ("ぶ'んしょうです。これわ/て_スと", False)),
    ("こ'れわ", ("こ'れわ", True)),
    ("\n", ("ぶ'んしょうです。これわ/て_スと", False)),      # 改行だけ → 全体
    ("。", ("ぶ'んしょうです。これわ/て_スと", False)),      # 記号だけ → 全体
    ("  ", ("ぶ'んしょうです。これわ/て_スと", False)),      # 空白だけ → 全体
]:
    got = preview_text(sel, WHOLE)
    assert got == want, (sel, got)
    m += 1
assert preview_text(None, "") == ("", False)
assert preview_text("。", "、。") == ("", False)                # 全体にも仮名がなければ空
assert preview_text(None, "<NUMK VAL=3>") == ("", False)        # タグだけも読めない
print(f"試聴で読む所 {m + 3} 件 OK")

# 他の辞書を取り込んでも、作者の使用回数・登録日は持ち込まない
import datetime as _dt
from accent_core import Dictionary
src = Dictionary(); src.upsert("てすと", "て'すと"); src.entries[0].hits, src.entries[0].added = 5, "2020-01-01"
mine = Dictionary()
assert mine.merge(src) == (1, 0)
e = mine.entries[0]
assert (e.hits, e.added) == (0, _dt.date.today().isoformat()), (e.hits, e.added)
assert (src.entries[0].hits, src.entries[0].added) == (5, "2020-01-01")   # 取り込み元は書き換えない
# 同梱のサンプル辞書にも、使用回数・登録日は入れない
import json
sample = json.load(open(os.path.join(os.path.dirname(__file__), "..", "dictionaries", "kensyo.json"), encoding="utf-8"))
assert not any("hits" in x or "added" in x for x in sample["entries"])
print("辞書の取り込み 2 件 OK")
