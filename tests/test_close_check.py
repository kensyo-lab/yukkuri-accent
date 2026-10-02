"""終了するときの確認（辞書に入っていない変更が残っていないか）。python tests/test_close_check.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import unregistered_changes, Candidate

n = 0
def check(got, want):
    global n
    assert got == want, f"\n got: {got}\nwant: {want}"
    n += 1

def st(now, conv="", sent=None, cands=()):
    return unregistered_changes(now, conv, sent, list(cands))

# 何もしていない／変換しただけ → 確認しない
check(st(""), {"edited": False, "pending": 0})
check(st("これわ/てすとです", "これわ/てすとです"), {"edited": False, "pending": 0})
# 手直しした → 確認する
check(st("これわ/て'すとです", "これわ/てすとです")["edited"], True)
# 手直しを学習タブへ送った → その分は確認しない
check(st("これわ/て'すとです", "これわ/てすとです", "これわ/て'すとです")["edited"], False)
# 送ったあとにさらに手直し → 確認する
check(st("これ'わ/て'すとです", "これわ/てすとです", "これわ/て'すとです")["edited"], True)
# 全角の記号を打っただけ（そろえると同じ）なら手直しとみなさない
check(st("これわ／てすとです", "これわ/てすとです")["edited"], False)
# 空にした → 確認しない
check(st("   ", "これわ/てすとです")["edited"], False)

# 学習タブの候補
c_new = Candidate("てすと", "て'すと", "語", False)                       # 新規・チェックあり
c_off = Candidate("これわ", "これ'わ", "句", False, use=False)            # チェックを外した
c_done = Candidate("あめ", "あ'め", "語", False, status="登録済み")         # 登録済み
c_upd = Candidate("はし", "は'し", "語", False, status="上書き")           # 上書き・チェックあり
c_num = Candidate("<NUMK VAL=3>", "さん", "数字", False)                  # 数字は数えない
check(st("", cands=[c_new, c_off, c_done, c_upd, c_num])["pending"], 2)
check(st("", cands=[c_off, c_done, c_num])["pending"], 0)

print(f"OK: {n} 件")
