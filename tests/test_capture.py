"""段階4: 修正の取り込みの確認（v1.0.0 設計メモ）。
python tests/test_capture.py"""
import sys, os, json, tempfile, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import (Dictionary, convert, output_lines, capture_corrections, matches_recent, classify_correction,
                         LearningStore, history_findings, change_candidates, plain_kana)

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


d = Dictionary()
t = d.number_table()
RAW = "きょりわ<NUMK VAL=10>/けーで_ス。たんさきが/とんだ"
res = convert(RAW, d, t)
OUT = res.text
check("前提：変換結果", OUT, "きょりわ,/じゅっけ'るびんで_ス。たんさきが/とんだ")
recent = output_lines(RAW, res)
check("前提：指摘の無い行", recent[0].flagged, False)


def kinds(clip, rec=recent):
    return [[c.kind for c in cap.changes] for cap in capture_corrections(clip, rec)]


# ── 設計メモの期待する結果 ─────────────────────────────────────
check("出力と同じ文字列をコピー → 何も記録しない", capture_corrections(OUT, recent), [])
check("核の位置だけ変えてコピー → 単語辞書を提案", kinds("きょりわ,/じゅっけ'るびんで_ス。たんさ'きが/とんだ"), [["単語辞書"]])
cap = capture_corrections("きょりわ,/じゅっ/け'るびんで_ス。たんさきが/とんだ", recent)
check("数字と単位のつなぎ方だけ変えてコピー → 例外表 E を提案", [c.kind for c in cap[0].changes], ["例外表 E"])
check("E の項目の案", cap[0].changes[0].data, {"unit": "kelvin", "last": "10", "join": "/"})
check("無関係な文字列をコピー → 何も起きない", capture_corrections("こんにちわ/せかい", recent), [])
check("読みそのものを直したもの → 拾わない（1.0.0）", capture_corrections("きょりわ,/じゅっけ'るびんで_ス。たんさくが/とんだ", recent), [])

st = LearningStore()
st.add(capture_corrections("きょりわ,/じゅっけ'るびんで_ス。たんさ'きが/とんだ", recent))
check("指摘していない箇所が直された → 見逃しに1件加算", (st.stats["corrected"], st.stats["misses"]), (1, 1))

flag_raw = "えぬえーえすえーの/たんさきが/とんだ"          # 頭字語らしき読みの指摘が出る行
fres = convert(flag_raw, d, t)
frec = output_lines(flag_raw, fres)
check("前提：指摘のある行", frec[0].flagged, True)
st.add(capture_corrections(fres.text.replace("たんさきが", "たんさ'きが"), frec))
check("指摘した行で直された所は見逃しに数えない", (st.stats["corrected"], st.stats["misses"]), (2, 1))
# 設定で OFF のときは、アプリが capture_corrections を呼ばない（tests/test_capture.py ではなく画面側の動き）

# ── 修正の分類 ───────────────────────────────────────────────
check("句の切り方が変わった → 文脈辞書", kinds("きょりわ,/じゅっけ'るびんで_ス。たんさきがとんだ"), [["文脈辞書"]])
check("数字の中の核だけ → 例外表 C", kinds("きょりわ,/じゅ'っけるびんで_ス。たんさきが/とんだ"), [["例外表 C"]])
check("数字の前の区切りは数字の外（文脈辞書）", kinds("きょりわ/じゅっけ'るびんで_ス。たんさきが/とんだ"), [["文脈辞書"]])
check("2か所直せば2件", kinds("きょ'りわ,/じゅっけ'るびんで_ス。たんさ'きが/とんだ"), [["単語辞書", "単語辞書"]])
check("無声化（_）だけの違いも、記号の違いとして拾う", kinds("きょりわ,/じゅっけ'るびんです。たんさきが/とんだ"), [["単語辞書"]])
check("素のかなの比べ方", plain_kana("じゅっけ'るびんで_ス"), "じゅっけるびんです")
check("直した物は、新しい読みとして自動変換しない", matches_recent("きょりわ,/じゅっ/け'るびんで_ス。たんさきが/とんだ", recent), True)
check("新しい読みは自動変換してよい", matches_recent("こんにちわ", recent), False)

# ── 学習候補 → 学習タブの候補 ─────────────────────────────────
st2 = LearningStore()
st2.add(capture_corrections("きょりわ,/じゅっ/け'るびんで_ス。たんさ'きが/とんだ", recent))
cands = change_candidates(st2.pending[0], t, d)
check("単語辞書の候補（YMM4側 → 直した後）と、例外表 E の候補", sorted((c.kind, c.dst) for c in cands),
      [("例外E", "つなぎ方「/」"), ("句", "たんさ'きが"), ("語", "たんさ'き")])
e = next(c for c in cands if c.kind == "例外E")
check("例外表の候補は、既定では登録しない", e.use, False)
d2 = Dictionary()
d2.add_exception(e.extra["kind"], e.extra["entry"])
check("登録した E が次の変換から効く", convert(RAW, d2, d2.number_table()).text, "きょりわ,/じゅ'ー/け'るびんで_ス。たんさきが/とんだ")
check("同じキーは置き換える", (d2.add_exception("join", {"unit": "kelvin", "last": "10", "join": ","}),
                          len(d2.sections["number_exceptions"]["join"])), ("updated", 1))

# ── 修正履歴と「過去に手動修正された」 ─────────────────────────────
f = history_findings(OUT, st2)
check("前に直した行を指摘", [(x.kind, x.action) for x in f], [("corrected_before", "履歴を見る")])
check("直していない行は指摘しない", history_findings("こんにちわ", st2), [])

# ── 保存（辞書とは別のファイル） ──────────────────────────────
p = os.path.join(tempfile.mkdtemp(), "learning.json")
st.save(p)
back = LearningStore.load(p)
check("学習候補・履歴・計測を保存", (len(back.pending), len(back.history), back.stats["misses"]), (2, 2, 1))
check("ファイルの形", json.load(open(p, encoding="utf-8"))["format"], "yukkuri-accent-learning")
back.record_conversion(res)
check("確認文節数を数える", (back.stats["conversions"], back.stats["phrases"] > 0), (1, True))

print(f"{n} 件 OK")
