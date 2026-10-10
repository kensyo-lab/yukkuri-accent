"""段階3: 英字読み辞書・文脈辞書の確認（v1.0.0 設計メモ）。
python tests/test_english_context.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import Dictionary, convert, prepare, learn, ReadOnlyDictionaryError

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


def run(raw, dic):
    r = convert(raw, dic, dic.number_table())
    return r.text, [(f.kind, f.text) for f in r.findings]


d = Dictionary()
d.set_english("えぬいーえーあーる", "にあ", "に'あ", "NEAR")

# ── 設計メモの期待する結果 ─────────────────────────────────────
check("登録あり: えぬいーえーあーるが → に'あが", run("えぬいーえーあーるが", d), ("に'あが", []))
r = convert("えぬいーえーあーるが", d, d.number_table())
check("決め手を残す", [(h.ymm4_reading, h.accent, h.source, h.origin) for h in r.english],
      [("えぬいーえーあーる", "に'あ", "NEAR", "辞書")])

text, found = run("えぬえーえすえーわ", d)
check("未登録: 頭字語らしき読みを指摘（置き換えない）", (text, found), ("えぬえーえすえーわ", [("acronym", "えぬえーえすえー")]))
f = convert("えぬえーえすえーわ", d, d.number_table()).findings[0]
check("操作は［読みを登録］", (f.action, f.data["ymm4_reading"]), ("読みを登録", "えぬえーえすえー"))

nasa = Dictionary()
nasa.set_english("えぬえーえすえー", "なさ", "な'さ", "NASA")
nasa.upsert("なさ", "な_サ")                       # 日本語の「〜がなさそう」用の登録
check("英字由来の「なさ」は英字エントリのアクセント", run("えぬえーえすえーわ", nasa)[0], "な'さわ")
check("通常の「なさ」は通常の辞書", run("なさそう", nasa)[0], "な_サそう")
plain = Dictionary()
plain.set_english("えぬえーえすえー", "なさ")
plain.upsert("なさ", "な'さ")
check("英字エントリにアクセントが無ければ、通常のアクセント辞書へ", run("えぬえーえすえーわ", plain)[0], "な'さわ")

lm = Dictionary()
lm.upsert("うちゅう", "う'ちゅう")
lm.upsert("うちゅうたんさき", "うちゅうたんさ'き")
check("長い方が勝つ", run("うちゅうたんさきが", lm)[0], "うちゅうたんさ'きが")
check("短い方も単独なら効く", run("うちゅうが", lm)[0], "う'ちゅうが")

cx = Dictionary()
cx.upsert("はし", "は'し")
cx.upsert("はし", "はし'", after="をわたる")
check("前後が一致した時だけ効く", run("はしを/わたる", cx)[0], "はし'を/わたる")
check("一致しなければ条件なしの項目", run("はしで/たべる", cx)[0], "は'しで/たべる")

cf = Dictionary()
cf.upsert("かき", "か'き", before="これ")
cf.upsert("かき", "かき'", after="のわ")
text, found = run("これかきのわ", cf)
check("候補が食い違えば自動で決めない（そのまま残す）", text, "これかきのわ")
check("指摘「複数のアクセント候補」", found, [("accent_conflict", "かき")])
f = convert("これかきのわ", cf, cf.number_table()).findings[0]
check("候補と位置を渡す", (sorted(e.dst for e in f.data["entries"]), f.data["start"], f.data["end"]),
      (["か'き", "かき'"], 2, 4))
check("片方だけ当たる所は、ふつうに置き換える", run("これかきで", cf)[0], "これか'きで")
cf.upsert("かき", "か'き", before="これ", after="のわ")      # 人が選んだ形（前後両方の条件）
check("選んだ形を登録すれば、次からはそれが優先", run("これかきのわ", cf), ("これか'きのわ", []))

# ── 頭字語らしき読みの見つけ方 ───────────────────────────────
for raw, want in [("しーぴーゆーの/せいのう", [("acronym", "しーぴーゆー")]),
                  ("えいち/あいあいえー", [("acronym", "あいあいえー")]),
                  ("えーえむでぃー", [("acronym", "えーえむでぃー")]),
                  ("わいわい/さわぐ", []),            # 同じ名の繰り返しは日本語
                  ("えーと/ですね", []),              # アルファベット名が1つだけ
                  ("あいすを/たべる", []),            # 後ろが助詞などでない
                  ("おーきな/けーき", [])]:
    check(f"頭字語の検出: {raw}", run(raw, Dictionary())[1], want)

# ── 後続パターン ─────────────────────────────────────────────
fp = Dictionary()
fp.sections["follow_patterns"] = {"について": {"sep": "/"}}
fp.upsert("にゅーほらいずんずについて", "にゅーほら'いずんずについて")
check("後続側に1回書けば全語に効く", run("めいおうせいについて", fp)[0], "めいおうせい/について")
check("もう区切りがあれば足さない", run("めいおうせい/について", fp)[0], "めいおうせい/について")
check("辞書の項目が当たった所の中には入れない", run("にゅーほらいずんずについて", fp)[0], "にゅーほら'いずんずについて")
r = convert("たいようけいについて/かいせ_ツ。はしを", fp, fp.number_table())
check("区切りを入れても、辞書が当たった位置はずれない", r.text, "たいようけい/について/かいせ_ツ。はしを")

# ── 学習と、辞書を当てる前の形 ────────────────────────────────
check("辞書を当てる前の形に目印は残らない", prepare("えぬいーえーあーるが", d.number_table(), english=d.english_table()), "に'あが")
check("英字で直した所は学習候補にしない", learn("えぬいーえーあーるが", "に'あが", d.number_table(), d), [])

# ── 登録と保存 ───────────────────────────────────────────────
p = os.path.join(tempfile.mkdtemp(), "accent_dict.json")
d.add_unit_reading("pascal", "ぺい", "ぱ'すかる", "Pa")
d.add_unit_reading("kelvin", "けるびん")
d.save(p)
back = Dictionary.load(p)
check("英字読み辞書を保存・読み込み", back.sections["english_dictionary"],
      {"えぬいーえーあーる": {"reading": "にあ", "accent": "に'あ", "source": "NEAR"}})
check("単位を足す", back.sections["unit_dictionary"]["pascal"],
      {"reading": "ぱ'すかる", "ymm4_readings": ["ぺい"], "source": "Pa"})
check("既定の単位に読みを足す（既定の項目を写す）", back.sections["unit_dictionary"]["kelvin"]["ymm4_readings"], ["けー", "けるびん"])
check("足した読みで解決する", run("<NUMK VAL=101325>/ぺいで", back)[0].endswith("ぱ'すかるで"), True)
back.file_version = 99
try:
    back.set_english("あ", "い")
    ok = False
except ReadOnlyDictionaryError:
    ok = True
check("読み取り専用の辞書には登録できない", ok, True)

print(f"{n} 件 OK")
