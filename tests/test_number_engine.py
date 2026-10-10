"""段階2: 数字の規則エンジン＋例外表（A〜E）と、数字の表を辞書へ移す確認（v1.0.0 設計メモ）。
python tests/test_number_engine.py"""
import sys, os, json, tempfile, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import (Dictionary, DEFAULT_NUMBERS, load_numbers, merge_numbers, number_diff, convert, prepare,
                         number_exception_table, move_numbers_into, open_dictionary)

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


UNIT_READING = {"electron_volt": "えぶ", "kelvin": "けー", "astronomical_unit": "えーゆー"}


def run(val, unit, dic=None):
    dic = dic or Dictionary()
    r = convert(f"<NUMK VAL={val}>/{UNIT_READING[unit]}", dic, dic.number_table())
    h = r.numbers[0]
    return r.text, h.reading_by, h.join_by, r.findings


# ── 設計メモの期待する結果 ─────────────────────────────────────
for val, unit, want, join_by in [
        (1, "electron_volt", "いちでんしぼ'ると", "既定"),
        (5, "electron_volt", "ご,でんしぼ'ると", "例外 E"),
        (9, "electron_volt", "きゅー/でんしぼ'ると", "例外 E"),
        (10, "electron_volt", "じゅーでんしぼ'ると", "既定"),
        (10, "kelvin", "じゅっけ'るびん", "例外 E"),          # か行で促音化
        (1, "kelvin", "いちけ'るびん", "既定"),               # 促音化しない
        (89, "kelvin", "はちじゅーきゅーけ'るびん", "既定"),
        (67, "astronomical_unit", "ろくじゅーななえーゆ'ー", "既定")]:
    text, by, jb, _ = run(val, unit)
    check(f"{val} ＋ {unit}", (text, by, jb), (want, "規則", join_by))

check("67 ＋ kelvin（例外 A あり＝既定）", run(67, "kelvin")[:2], ("ろくじゅーなな/け'るびん", "例外 A"))
no_a = Dictionary()
no_a.sections["number_exceptions"] = {"unit": [{"value": "67", "unit": "kelvin", "disabled": True}]}
check("67 ＋ kelvin（例外 A なし）", run(67, "kelvin", no_a)[:2], ("ろくじゅーななけ'るびん", "規則"))

unfilled = Dictionary()
unfilled.sections["number_rules"] = {"thousands": {"3": None}}
text, _, _, found = run(3000, "kelvin", unfilled)
check("未確定の欄を使う数は指摘", [(f.kind, f.text) for f in found], [("number_unfilled", "3000")])
check("未確定の欄は 〓 のまま（AquesTalk に渡す前に気付ける）", "〓" in text, True)
check("未確定の欄を使わない数は指摘しない", run(300, "kelvin", unfilled)[3], [])

bc = Dictionary()
bc.sections["number_exceptions"] = {
    "number": [{"value": "128", "reading": "ひゃくにじゅう/は'ち"}],
    "structural": [{"place": "hundreds", "digit": "1", "reading": "いっぴゃく"}]}
r = convert("<NUMK VAL=128>", bc, bc.number_table())
check("B と C が両方当たる数は B が勝つ", (r.text, r.numbers[0].reading_by), ("ひゃくにじゅう/は'ち", "例外 B"))
r = convert("<NUMK VAL=129>", bc, bc.number_table())
check("B が無ければ C", (r.text.startswith("いっぴゃく"), r.numbers[0].reading_by), (True, "例外 C"))

cc = Dictionary()
cc.sections["number_exceptions"] = {"structural": [
    {"place": "hundreds", "digit": "3", "reading": "さ'んびゃく"},
    {"place": "hundreds", "digit": "3", "final": True, "reading": "さんびゃく'"}]}
r = convert("<NUMK VAL=300>", cc, cc.number_table())
check("(hundred, 3) と (hundred, 3, final) が両方当たれば、属性の多い方", r.text, "さんびゃく'")
r = convert("<NUMK VAL=350>", cc, cc.number_table())
check("最後の要素でなければ final は当たらない", r.text.startswith("さ'んびゃく") or r.text.startswith("さんびゃく"), True)
check("final でない方が当たる", "さんびゃく'" in r.text, False)

# ── E は単位ごとの項目が、行のまとめより先 ─────────────────────────
ue = Dictionary()
ue.sections["number_exceptions"] = {"join": [{"unit": "kelvin", "last": "10", "join": "/"}]}
check("(kelvin, 10) が (か行, 10) に勝つ", run(10, "kelvin", ue)[:3], ("じゅ'ー/け'るびん", "規則", "例外 E"))   # 区切るときは、数字側のアクセントも残す

# ── 今までの変換結果を変えない ─────────────────────────────────
t = load_numbers(None)
for raw, want in [("<NUMK VAL=2026 COUNTER=ねん>", "にせ'ん/に'じゅー/ろく'ねん"),
                  ("<NUMK VAL=89>", "は'ちじゅー/きゅー"),
                  ("<NUMK VAL=0.52>", "れ'ーてん/ごーに'ー"),
                  ("<NUMK VAL=3 COUNTER=つ>", "みっつ'")]:
    check(f"例外の無い数は今まで通り: {raw}", prepare(raw, t), want)

# ── 数字の表を辞書へ移す（v0.9 の numbers.json） ─────────────────────
d = tempfile.mkdtemp()
num = os.path.join(d, "numbers.json")
old = json.loads(json.dumps(DEFAULT_NUMBERS, ensure_ascii=False))
old["tens"]["6"] = "ろく'じゅー"                       # ユーザーが書き換えた欄
old["counters"]["ど"] = {"mode": "own", "reading": "ど'"}
with open(num, "w", encoding="utf-8") as f:
    json.dump(old, f, ensure_ascii=False)
check("既定と違う欄だけを取り出す", number_diff(old),
      {"tens": {"6": "ろく'じゅー"}, "counters": {"ど": {"mode": "own", "reading": "ど'"}}})

p = os.path.join(d, "accent_dict.json")
dic = open_dictionary(p, os.path.join(d, "backup"), "1.0.0")
moved = move_numbers_into(dic, num, now=datetime.datetime(2026, 10, 10, 9, 0, 0))
check("numbers.json は名前を変えて残す", (os.path.basename(moved), os.path.exists(num)),
      ("numbers_moved_to_dict_20261010-090000.json", False))
dic.save(p, "1.0.0")
back = Dictionary.load(p)
check("辞書に書き換えた欄だけが入る", back.sections["number_rules"]["tens"], {"6": "ろく'じゅー"})
check("移した表で前と同じ読みになる", prepare("<NUMK VAL=60>", back.number_table()), prepare("<NUMK VAL=60>", load_numbers(moved)))
check("2回目は何もしない", move_numbers_into(back, num), None)
ro = Dictionary.load(p)
ro.file_version = 99
with open(num, "w", encoding="utf-8") as f:
    json.dump(old, f, ensure_ascii=False)
check("読み取り専用の辞書には移さない", (move_numbers_into(ro, num), os.path.exists(num)), (None, True))

check("既定の表は merge_numbers と load_numbers(None) で同じ", merge_numbers(None), load_numbers(None))
check("未知の種類の例外は無視", number_exception_table({"other": [{"x": 1}]})["unit"][0]["value"], "67")

print(f"{n} 件 OK")
