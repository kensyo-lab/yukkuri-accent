"""変換結果に、仮名・記号以外の文字を通さない決まりの確認。
python tests/test_bad_chars.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import validate, has_bad_chars, bad_char_list, looks_like_source_text, reading_bad_spans

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


# ── 台詞の文（漢字まじり）が入っているか ──
check("台詞の文", looks_like_source_text("秒で終わるな。この小惑星には"), True)
check("YMM4 の読み", looks_like_source_text("びょーで/おわ'るな。"), False)
check("々も漢字あつかい", looks_like_source_text("ときどき々"), True)
check("タグの中は見ない", looks_like_source_text("<NUMK VAL=10 COUNTER=年>"), False)
check("空", looks_like_source_text(""), False)

# ── 読みの段階のチェック（変換の前に止める） ──
def chars(s):
    return "".join(c for _a, _b, c in reading_bad_spans(s))


check("台詞の文は漢字の所を指す", reading_bad_spans("秒で終わるな"), [(0, 1, "秒"), (2, 3, "終")])
check("ふつうの読みは通す", reading_bad_spans("びょーで/おわ'るな。こんどわ、しょーわ'くせーに"), [])
check("カタカナ・無声化も通す", reading_bad_spans("_シた/アステロイド？"), [])
check("数字タグは通す", reading_bad_spans("<NUMK VAL=1898 COUNTER=年>/はちがつ"), [])
check("空白・改行・全角記号は通す（正規化で直せる）", reading_bad_spans("あ’い／う　え\r\nお？"), [])
check("！は変換後のチェックに任せる", reading_bad_spans("すごい！"), [])
check("英字は止める", chars("NASAの/たんさき"), "NASA")
check("数字そのままも止める", chars("じゅう2ねん"), "2")
check("〓は読みには来ないので止める", chars("じゅー〓"), "〓")
check("空", reading_bad_spans(""), [])

# ── 使えない文字が残っているか ──
src = "秒で終わるな。この小惑星には"
iss = validate(src)
check("漢字はコピー・試聴させない", has_bad_chars(iss), True)
check("使えない文字の一覧（重複なし）", bad_char_list(iss, src), "秒・終・小・惑・星")

ok = "びょーで/おわ'るな。こんどわ/しょーわ'くせーに"
check("仮名と記号だけなら通す", has_bad_chars(validate(ok)), False)

check("英字も通さない", has_bad_chars(validate("NASAの/たんさき")), True)
check("〓も通さない", has_bad_chars(validate("じゅー〓じょー")), True)
check("！も通さない", has_bad_chars(validate("すごい！")), True)

# アクセントの置き方の誤り（仕様の制限）は、これまでどおりコピーはできる（警告だけ）
acc = validate("'あいう")
check("アクセントの誤りはエラーだが文字の問題ではない", (any(i.level == "error" for i in acc), has_bad_chars(acc)), (True, False))

print(f"{n} 件 OK")
