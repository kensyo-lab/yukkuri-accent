"""辞書の競合チェック（DRC）と、使用回数の数え方の確認。python tests/test_drc_usage.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import accent_core as core
from accent_core import Dictionary, dict_conflicts, count_usage, convert

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


def found(d):
    return [(c.level, c.kind, c.entry.src, c.entry.before, c.entry.after) for c in dict_conflicts(d)]


# ── 隠れて効かない ──
d = Dictionary()
d.upsert("はしを", "は'しを")
d.upsert("はし", "はし'", after="をわたる")
r = dict_conflicts(d)
check("FAQ の例：長い条件なしの項目に隠れた文脈付き項目", found(d), [("error", "ほかの項目に隠れて効かない", "はし", "", "をわたる")])
check("原因の項目も分かる", r[0].other.src, "はしを")
d.remove("はしを")
d.upsert("はしを", "は'しを", after="わたる")
check("長い方に同じ条件を付けても、まだ長い方が先に当たる", [x[:2] for x in found(d)], [("error", "ほかの項目に隠れて効かない")])
d.remove("はしを", after="わたる")
d.upsert("はしを", "は'しを", after="つかう")      # 長い方を、もう一方の場面（箸を使う）に限ると…
check("長い方を別の場面に限れば、両方生きる", found(d), [])

# ── 無くても結果が同じ ──
d = Dictionary()
d.upsert("かき", "か'き")
d.upsert("かき", "か'き", before="あ")
check("条件なしと同じ置き換えをする条件付き項目", found(d), [("warn", "無くても結果が同じ", "かき", "あ", "")])
d = Dictionary()
d.upsert("たんさき", "たんさ'き")
d.upsert("たんさきわ", "たんさ'きわ")
check("短い項目で足りている長い項目", found(d), [("warn", "無くても結果が同じ", "たんさきわ", "", "")])
d.upsert("わ", "わ'")
check("…ただし短い項目の誤爆よけになっていれば言わない", found(d), [])

# ── 何も変えない ──
d = Dictionary()
d.upsert("あいう", "あいう")
check("何も変えず、誤爆よけでもない項目", found(d), [("warn", "何も変えない", "あいう", "", "")])
d.upsert("い", "い'")
check("「あいう → あいう」が「い」の誤爆よけなら言わない", found(d), [])

# ── 句頭のみ ──
d = Dictionary()
d.upsert("ぜひ", "ぜ'ひ", True)
check("句頭のみの項目は、試しの文でも句頭とみなさず誤検出しない", found(d), [])

# ── 置き換え後にエラー ──
d = Dictionary()
d.upsert("あめ", "あ'め'")
check("置き換え後に ' が2つ", [x[:2] for x in found(d)], [("warn", "置き換え後にエラー")])

# ── 条件違いが多い ──
d = Dictionary()
for i, b in enumerate(["あ", "い", "う", "え"]):
    d.upsert("はし", "はし'" if i % 2 else "は'し", before=b)
check("同じ YMM4側に条件違いが4つ", [x[:3] for x in found(d)], [("info", "条件違いが多い", "はし")])
check("重いものから並ぶ", [c.level for c in dict_conflicts(Dictionary())], [])

# ── 使用回数：同じ台詞は何度変換しても1回 ──
d = Dictionary()
d.upsert("たんさき", "たんさ'き")
d.upsert("わ", "わ'")
seen = set()
raw = "たんさきわ/たんさきと\nわたしわ"
for _ in range(3):
    res = convert(raw, d, core.DEFAULT_NUMBERS)
    count_usage(res.text, res.applied, seen)
hits = {e.src: e.hits for e in d.entries}
check("3回変換しても、行ごとに1回（たんさきは1行目だけ・わは2行とも）", hits, {"たんさき": 1, "わ": 2})
res = convert("たんさきが", d, core.DEFAULT_NUMBERS)
check("新しい台詞なら増える", (count_usage(res.text, res.applied, seen), d.entries[0].hits if d.entries[0].src == "たんさき" else None), (1, 2))
check("台詞の印は本文ではなくハッシュ", all(len(k) == 16 for k in seen), True)
check("変換しただけでは数えない（apply は回数を変えない）", (convert("たんさきが/ふゆ", d, core.DEFAULT_NUMBERS), d.find("たんさき").hits)[1], 2)

print(f"{n} 件 OK")
