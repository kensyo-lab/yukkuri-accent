"""段階1: 指摘の仕組み・正規化・単位辞書の確認（v1.0.0 設計メモ）。
python tests/test_units_findings.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import Dictionary, load_numbers, convert, prepare, learn, normalize

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


t = load_numbers(None)
d = Dictionary()


def run(raw, dic=d):
    r = convert(raw, dic, t)
    return r.text, [(f.kind, f.text) for f in r.findings], [(u.reading, u.unit_id, u.origin) for u in r.units]


# ── 設計メモの期待する結果 ─────────────────────────────────────
text, found, units = run("<NUMK VAL=300>/けーだった")
check("けー は kelvin に解決", units, [("けー", "kelvin", "既定")])
check("/ を詰めて数字と同じ句になる（後ろの「だった」は残す）", text, "さんびゃ_クけ'るびんだった")
check("解決できたので指摘なし", found, [])

for r in ("えーゆー", "おー"):
    check(f"{r} は astronomical_unit", run(f"<NUMK VAL=1>/{r}")[2], [(r, "astronomical_unit", "既定")])
    check(f"{r} も同じ読みになる", run(f"<NUMK VAL=1>/{r}")[0], "いちえーゆ'ー")

text, found, units = run("<NUMK VAL=101325>/ぺいで")
check("未登録の単位は置き換えない", (units, text.endswith("/ぺいで")), ([], True))
check("単位らしき未登録の読み：ぺい", found, [("unit_unknown", "ぺい")])

text, found, units = run("わいふぁい<NUMK VAL=4802>.<NUMK VAL=11>/ん、")
check("文節頭のん と 数字の後に .数字", sorted(found), [("dot_number", "4802.11"), ("n_head", "ん")])

for raw in ("おーきな/けーきを", "けーわ/おーきい", "<NUMK VAL=3>/おーきな"):
    text, found, units = run(raw)
    check(f"数字の直後の単位でなければ置き換えない: {raw}", units, [])
check("ふつうの文はそのまま", run("おーきな/けーきを")[0], "おーきな/けーきを")
check("長い読みは単位らしいとみなさない", run("<NUMK VAL=3>/おーきな")[1], [])

# ── 今までの仕組みとぶつからない ──────────────────────────────
check("助数詞（COUNTER=）は今まで通り", run("<NUMK VAL=100 COUNTER=きろめーとる>")[0:3:2], ("ひゃ_クきろめ'ーとる", []))
check("numbers.json の suffix_fixes（/くむ）は今まで通り（単位の指摘もしない）",
      run("およそ<NUMK VAL=30 COUNTER=おく>/くむ")[1], [])
check("数字の表の suffix_fixes が先", prepare("やく<NUMK VAL=130 COUNTER=まん>/くむで_ス。", t),
      "や'_ク/ひゃ_クさんじゅーまんきろめ'ーとるで_ス。")   # 0.9.2 と同じ

# ── 辞書の単位辞書（unit_dictionary）で足す・上書きする ───────────
mine = Dictionary()
mine.sections["unit_dictionary"]["pascal"] = {"reading": "ぱ'すかる", "ymm4_readings": ["ぺい"], "source": "Pa"}
text, found, units = run("<NUMK VAL=101325>/ぺいで", mine)
check("登録した単位で解決し、決め手を残す", units, [("ぺい", "pascal", "辞書")])
check("登録すれば指摘は消える", found, [])
check("数字と同じ句になる", text.endswith("ごぱ'すかるで"), True)
mine.sections["unit_dictionary"]["kelvin"] = {"reading": "けるびん'", "ymm4_readings": ["けー"]}
check("既定の単位も、同じ単位IDで上書きできる", run("<NUMK VAL=300>/けー", mine)[0], "さんびゃ_クけるびん'")

# ── 学習でも同じ形を使う（変換と学習で数字まわりの形がずれない） ──────────
cands = learn("<NUMK VAL=300>/けーだった", "さんびゃ_クけ'るびんだった", t, d)
check("直していなければ候補は出ない", cands, [])
cands = learn("<NUMK VAL=300>/けーだった", "さんびゃ_クけるび'んだった", t, d)
check("単位の読みを直した所は「数字」の候補（既定で登録しない）", [(c.kind, c.use) for c in cands], [("数字", False)])

print(f"{n} 件 OK")
