"""短い辞書の項目が長い語の中に当たる所の確認（v1.0.7）。
python tests/test_short_entry.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import Dictionary, convert, learn

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


def found(raw, dic):
    return [(f.kind, f.msg, f.data["entry"].src) for f in convert(raw, dic, dic.number_table()).findings
            if f.kind == "short_entry_inside_word"]


# ── 使うとき：長い語の頭・途中に当たったら ◇ 確認 ─────────────────────────
d = Dictionary()
d.upsert("えん", "ふち'", True)
check("「えんじん」の頭に当たる → 知らせる", found("ための/えんじん/ふんしゃを。", d),
      [("short_entry_inside_word", "短い辞書の項目が、長い語の中に当たりました：えん → ふち'（｢えんじん｣の頭）", "えん")])
check("後ろが助詞だけ → 知らせない", found("くれーたーの/えんに/たつ。", d), [])
check("後ろに何もない → 知らせない", found("くれーたーの/えん。", d), [])
check("後ろが助詞の連なり → 知らせない", found("えんには、", d), [])

m = Dictionary()
m.upsert("かい", "か'い")
check("語の途中に当たる → 知らせる", [x[1] for x in found("しゃかいが", m)],
      ["短い辞書の項目が、長い語の中に当たりました：かい → か'い（｢しゃかい｣の中）"])
check("同じ語に何度当たっても1件", len(found("しゃかいが/しゃかいを", m)), 1)

c = Dictionary()
c.upsert("えん", "ふち'", True, after="じん")
check("前後の条件つきの項目は見ない", found("えんじんが", c), [])
L = Dictionary()
L.upsert("えんじん", "え'んじん")
check("長い項目は見ない", found("えんじんふんしゃ", L), [])
w = Dictionary()
w.upsert("えん", "ふち'", True)
w.upsert("えんじん/ふんしゃ", "えんじんふ'んしゃ")
check("YMM4 の読みのままの長い形を登録すれば、長い方が当たる", (convert("ための/えんじん/ふんしゃを。", w, w.number_table()).text,
      found("ための/えんじん/ふんしゃを。", w)), ("ための/えんじんふ'んしゃを。", []))

# ── 登録するとき：短い［語］は既定でチェックしない ───────────────────────
cands = {(c.kind, c.src): c.use for c in learn("くれーたーの/えんに/たつ", "くれーたーの/ふち'に/たつ", d.number_table())}
check("短い［語］はチェックなし", cands.get(("語", "えん")), False)
check("［句］はチェックあり", cands.get(("句", "えんに")), True)
long_ = {(c.kind, c.src): c.use for c in learn("とおくの/たんさきが/とんだ", "とおくの/たんさ'きが/とんだ", d.number_table())}
check("長い［語］はチェックあり", long_.get(("語", "たんさき")), True)

print(f"{n} 件 OK")
