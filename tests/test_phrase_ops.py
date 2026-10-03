"""文節の右クリック操作（突き合わせ）・誤爆しやすい辞書・辞書の比較。python tests/test_phrase_ops.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import phrase_region, entry_warnings, Entry, Dictionary, dict_diff

def restore(cur, ref, word):
    """cur の中の word を含む文節を、ref の対応する所に戻した結果"""
    i = cur.index(word)
    r = phrase_region(cur, ref, i, i + len(word))
    assert r, (cur, word)
    cs, ce, rs, re_ = r
    return cur[:cs] + ref[rs:re_] + cur[ce:]

n = 0
def check(got, want):
    global n
    assert got == want, f"\n got: {got}\nwant: {want}"
    n += 1

REF = "これわ/て_スと/ぶ'んしょうです。すうじと/たんいが"
# アクセントを動かした文節だけ戻す（ほかの文節の手直しは残る）
check(restore("これわ/て_スと/ぶんしょ'うです。すうじと/た'んいが", REF, "しょ"),
      "これわ/て_スと/ぶ'んしょうです。すうじと/た'んいが")
# 区切りを消して2つの文節をつないだ → つないだ所まとめて戻る
check(restore("これわて_スと/ぶ'んしょうです。", "これわ/て_スと/ぶ'んしょうです。", "これわて"),
      "これわ/て_スと/ぶ'んしょうです。")
# 区切りを足して1つの文節を割った → 割ったどちらを選んでも、両方まとめて戻る（重ならない）
check(restore("これわ/ぶん/しょ'うです", "これわ/ぶ'んしょうです", "ぶん"), "これわ/ぶ'んしょうです")
check(restore("これわ/ぶん/しょ'うです", "これわ/ぶ'んしょうです", "しょ"), "これわ/ぶ'んしょうです")
# 2行目の文節も、行がずれずに戻る
check(restore("あい/う'\nか/き'く", "あい/う\nか'/きく", "う"), "あい/う\nか/き'く")   # 1行目の う だけ戻り、2行目の手直しは残る
check(restore("あい/う'\nか/き'く", "あい/う\nか'/きく", "き"), "あい/う'\nか/きく")    # 2行目の き の文節だけ戻る
# 前に文節を書き足していても、対応する所を見つける
check(restore("あたらしい/これわ'/ぶんしょう", "これわ/ぶ'んしょう", "これ"), "あたらしい/これわ/ぶんしょう")

# 誤爆しやすい辞書の項目
w = lambda src, head=False: entry_warnings(Entry(src, src, head))
check(w("わ"), ["助詞だけ"])
check(w("さき"), ["短い（2拍）"])
check(w("さき", True), [])                         # 句頭のみなら当たりにくい
check(w("かわ"), ["短い（2拍）", "「わ」を含む（助詞の「は」と紛れやすい）"])
check(w("きゅーに"), ["助詞と同じ文字で始まる／終わる短い語"])   # 「…きゅーにち」の中でも当たりうる
check(w("ひとが"), ["助詞と同じ文字で始まる／終わる短い語"])
check(w("きょうみ"), [])
check(w("たんさき"), [])
check(w("きょ'うみ"), [])

# 辞書の比較（今 → バックアップに戻したら）
now = Dictionary(); now.upsert("あ", "あ'"); now.upsert("い", "い'"); now.upsert("う", "う")
bk = Dictionary(); bk.upsert("あ", "あ'"); bk.upsert("う", "う'"); bk.upsert("え", "え'")
add, rem, chg = dict_diff(now, bk)
check(([e.src for e in add], [e.src for e in rem], [(a.dst, b.dst) for a, b in chg]), (["え"], ["い"], [("う", "う'")]))
print(f"{n} 件 OK")
