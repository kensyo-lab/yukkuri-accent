"""高低の線（ピッチ）と、辞書のバックアップの確認。python tests/test_pitch_backup.py"""
import sys, os, tempfile, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import (split_phrases, Phrase, pitch_pattern, set_accent_edits,
                         backup_file, list_backups)

def ph(s):
    return [p for p in split_phrases(s) if isinstance(p, Phrase)][0]

def hl(s, high_start=False):
    """H/L の文字列で（拍でないものは ・）"""
    return "".join("・" if v is None else "HL"[1 - v] for v in pitch_pattern(ph(s), high_start))

n = 0
def check(got, want):
    global n
    assert got == want, f"\n got: {got}\nwant: {want}"
    n += 1

check(hl("これわ"), "LHH")                  # 平板
check(hl("ぶ'んしょうです"), "HLLLLL")      # 頭高（ぶ ん しょ う で す）
check(hl("えんしゅ'うりつ"), "LHHLLL")      # 中高（え ん しゅ ← ここまで高い）
check(hl("きゅ'ーに"), "HLL")               # 拗音は1拍、ー も拍
check(hl("おねがいしま'_ス"), "LHHHHHL")     # _ス は1拍
check(hl("あ<NUMK VAL=1>い"), "L・H")       # タグは拍に数えない
check(hl("これわ", high_start=True), "HHH")  # ; の後は高く始まる
check(hl("か'き", high_start=True), "HL")

# set_accent_edits: 付け外しを切り替えない
p = ph("ぶ'んしょう")
check(set_accent_edits(p, 0), ([], None))          # すでにそこ → 何もしない
check(set_accent_edits(p, None), ([1], None))      # 外す
check(set_accent_edits(p, 2), ([1], 5))           # しょ の後ろへ（元の文字列での位置）

# バックアップ
d = tempfile.mkdtemp()
src = os.path.join(d, "accent_dict.json")
bk = os.path.join(d, "backup")
t0 = dt.datetime(2026, 10, 2, 12, 0, 0)
open(src, "w").write("A")
check(bool(backup_file(src, bk, now=t0)), True)
check(backup_file(src, bk, now=t0 + dt.timedelta(seconds=1)), None)   # 中身が同じなら写さない
for i in range(25):
    open(src, "w").write(f"B{i}")
    backup_file(src, bk, keep=20, now=t0 + dt.timedelta(minutes=i + 1))
lst = list_backups(bk)
check(len(lst), 20)                                   # 古いものは消える
check(open(lst[0]).read(), "B24")                     # 新しい順
check(backup_file(os.path.join(d, "none.json"), bk), None)
print(f"{n} 件 OK")

# ショートカットキー
from accent_core import shortcut_from_keys, shortcut_label, shortcut_variants
m = 0
for args, seq, label in [
    (("V", True, True, False), "<Control-Shift-Key-V>", "Ctrl+Shift+V"),
    (("v", True, False, False), "<Control-Key-v>", "Ctrl+V"),
    (("Return", True, False, False), "<Control-Key-Return>", "Ctrl+Enter"),
    (("F5", False, False, False), "<Key-F5>", "F5"),
    (("Left", False, False, True), "<Alt-Key-Left>", "Alt+←"),
    (("1", True, False, False), "<Control-Key-1>", "Ctrl+1"),       # 数字も Key- 付き
    (("plus", True, True, False), "<Control-Shift-Key-plus>", "Ctrl+Shift++"),
]:
    got = shortcut_from_keys(*args)
    assert got == seq, (args, got)
    assert shortcut_label(got) == label, (got, shortcut_label(got))
    m += 1
assert shortcut_from_keys("a", False, False, False) is None      # 修飾キーなしの文字は不可（入力とぶつかる）
assert shortcut_from_keys("Control_L", True, False, False) is None
assert shortcut_label("") == "（なし）"
assert shortcut_variants("<Control-Shift-Key-V>") == ["<Control-Shift-Key-v>", "<Control-Shift-Key-V>"]
assert shortcut_variants("<Key-F5>") == ["<Key-F5>"]
print(f"ショートカット {m + 5} 件 OK")

# 点を動かしたときのアクセントの置き方
from accent_core import accent_for_pitch
def drag(s, text, up, high_start=False):
    p = ph(s)
    k = [u.text for u in p.units].index(text)
    ok, tgt = accent_for_pitch(p, k, up, high_start)
    if not ok:
        return "変えない"
    return "平板" if tgt is None else p.units[tgt].text
c = 0
for args, want in [
    (("ぶ'んしょうです", "しょ", True), "しょ"),     # 高低低低低低 → 低高高低低低
    (("ぶんしょうです", "で", False), "う"),          # 平板の「で」を下げる → 直前の「う」にアクセント
    (("えんしゅ'うりつ", "つ", True), "平板"),        # 最後を上げる → 平板
    (("か'きくけ", "か", False), "き"),               # 頭高の1拍目を下げる → 低高低低
    (("ぶ'んしょう", "ぶ", True), "変えない"),        # すでに高い
    (("これわ", "こ", True), "こ"),                   # 平板の1拍目を上げる → 頭高
    (("きゅーに", "ー", False), "きゅ"),              # ー を下げる → きゅ にアクセント（ー には置けない）
]:
    got = drag(*args)
    assert got == want, (args, got, want)
    c += 1
print(f"点のドラッグ {c} 件 OK")
