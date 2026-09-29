"""文節分解とアクセントの付け替えの確認。python tests/test_accent_edit.py"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import split_phrases, apply_accent, Phrase

def phrases(s):
    return [p for p in split_phrases(s) if isinstance(p, Phrase)]

def units(s):
    return [[(u.text, u.can_accent) for u in p.units] for p in phrases(s)]

def click(s, pi, text):
    """pi 番目の文節で、表示が text の拍を押した結果"""
    p = phrases(s)[pi]
    k = [u.text for u in p.units].index(text)
    return apply_accent(s, p, k)

ok = 0
def check(got, want):
    global ok
    assert got == want, f"\n got: {got!r}\nwant: {want!r}"
    ok += 1

# 拗音は直前の文字と1拍、ー・っ・ん はボタンなし、_ は次の文字と1拍
check(units("きゃっきゅーしょん/ま_ス"),
      [[("きゃ", True), ("っ", False), ("きゅ", True), ("ー", False), ("しょ", True), ("ん", False)],
       [("ま", True), ("_ス", True)]])
# 区切りと改行
seps = [p.text for p in split_phrases("あ/い,/う、え\nお。") if not isinstance(p, Phrase)]
check(seps, ["/", ",/", "、", "\n", "。"])
# タグは1拍（アクセント不可）
check(units("えん<NUMK VAL=3>だ"), [[("え", True), ("ん", False), ("<NUMK VAL=3>", False), ("だ", True)]])
# 付ける・付け替える・外す
check(click("ぶんしょうです", 0, "ぶ"), "ぶ'んしょうです")
check(click("ぶ'んしょうです", 0, "しょ"), "ぶんしょ'うです")
check(click("ぶ'んしょうです", 0, "ぶ"), "ぶんしょうです")
# 拗音・長音: ' は拍の直後（ー の前）
check(click("きゅーに", 0, "きゅ"), "きゅ'ーに")
check(click("おねがいしま_ス", 0, "ま"), "おねがいしま'_ス")
# 同じ文節の ' は1つだけ（2つあったものも1つにまとまる）
check(click("あ'い'うえ", 0, "う"), "あいう'え")
# 他の文節には触らない
check(click("これわ/て_スと/ぶ'んしょう", 1, "て"), "これわ/て'_スと/ぶ'んしょう")
check(click("い'ち/に\nさ'ん", 2, "さ"), "い'ち/に\nさん")
print(f"{ok} 件 OK")

# 打ったそばから直す記号（文字数は変えない・タグの中は触らない）
from accent_core import mark_fixes
def fixed(s):
    cs = list(s)
    for i, ch in mark_fixes(s):
        cs[i] = ch
    return "".join(cs)
ok2 = 0
for src, want in [
    ("ぶ’んしょう", "ぶ'んしょう"),
    ("こんにちわ／げんき？", "こんにちわ/げんき？"),
    ("ま＿すです", "ま_スです"),          # ＿ も _ の後のひらがなも直す
    ("ま_すです", "ま_スです"),
    ("あ，い＋う；え", "あ,い+う;え"),
    ("なに?", "なに？"),
    ("<NUMK VAL=1’>’", "<NUMK VAL=1’>'"),  # タグの中はそのまま
    ("すでに/ただしい'かたち", "すでに/ただしい'かたち"),
]:
    got = fixed(src)
    assert got == want, (src, got, want)
    assert len(got) == len(src)
    ok2 += 1
print(f"記号の自動修正 {ok2} 件 OK")
