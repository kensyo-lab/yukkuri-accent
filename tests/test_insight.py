"""変換結果の見える化（文節の状態・今回使われた辞書）の確認。python tests/test_insight.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import accent_core as core
from accent_core import Dictionary, convert, phrase_statuses, next_phrase, used_entries, usage_summary

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


NUM = core.DEFAULT_NUMBERS
d = Dictionary()
d.upsert("たんさき", "たんさ'き")
d.upsert("めいおうせい", "めいおうせ'い")
d.upsert("わ", "わ'")                          # 助詞だけ → 誤爆しやすい
d.upsert("はし", "はし'", after="をわたる")     # 文脈付き


def run(raw):
    res = convert(raw, d, NUM)
    applied = [(a.start, a.end, a.entry) for a in res.applied]
    return res.text, applied


def statuses(cur, conv, applied, checked=()):
    return [(cur[p.start:p.end], p.status) for p in phrase_statuses(cur, conv, applied, checked)]


# ── 変換した直後 ──
text, ap = run("たんさきが/めいおうせいを/とおった")
check("変換結果", text, "たんさ'きが/めいおうせ'いを/とおった")
check("辞書が当たった文節と、誰も触っていない文節",
      statuses(text, text, ap),
      [("たんさ'きが", "dict"), ("めいおうせ'いを", "dict"), ("とおった", "unchecked")])
check("まだ変換していなければ何も出さない", phrase_statuses(text, "", ap), [])

# ── 誤爆しやすい項目 ──
text2, ap2 = run("これわ/たんさき")
check("助詞だけの項目が当たった文節は「誤爆しやすい」", statuses(text2, text2, ap2),
      [("これわ'", "risky"), ("たんさ'き", "dict")])

# ── 文脈付き ──
text3, ap3 = run("はしを/わたる")
check("文脈付きの項目も「辞書で直した」", statuses(text3, text3, ap3)[0], ("はし'を", "dict"))
check("文脈付きの項目には誤爆の印を付けない", [u.risky for u in used_entries(ap3)][0], [])

# ── 手直し ──
edited = text.replace("とおった", "とお'った")
check("手で ' を足した文節は「手で直した」（位置がずれても、ほかの文節はそのまま）",
      statuses(edited, text, ap)[-1], ("とお'った", "manual"))
removed = text.replace("たんさ'き", "たんさき")
check("' を消した文節も「手で直した」（辞書より手直しを優先）", statuses(removed, text, ap)[0], ("たんさきが", "manual"))
check("消したのが文節の一番後ろの ' でも気づく",
      statuses("とおった/くも", "とおった'/くも", [])[0], ("とおった", "manual"))
check("区切りを消してつないだ文節", statuses("とおったくも", "とおった/くも", []), [("とおったくも", "manual")])

# ── 確認済み ──
s = text.index("とおった")
check("確認済みにした文節", statuses(text, text, ap, [(s, s + 4)])[-1], ("とおった", "checked"))

# ── 次の未確認へ ──
infos = phrase_statuses("あ/い/う/え", "あ/い/う/え", [], [(2, 3)])   # 「い」だけ確認済み
check("次の未確認（カーソルより後ろ）", "あ/い/う/え"[next_phrase(infos, 1).start], "う")
check("最後まで行ったら最初へ戻る", "あ/い/う/え"[next_phrase(infos, 7).start], "あ")
check("前の未確認", "あ/い/う/え"[next_phrase(infos, 4, backward=True).start], "あ")
check("未確認が無ければ None", next_phrase(phrase_statuses("あ", "あ", [], [(0, 1)]), 0), None)

# ── 今回使われた辞書 ──
text4, ap4 = run("たんさきわ/たんさきと/めいおうせいを/はしを/わたる")
used = used_entries(ap4)
# 「わ」は「たんさきわ」のほかに「わたる」の頭でも当たる（＝誤爆）。こういうのを一覧で見つけるための機能
check("当たった順・回数", [(u.entry.src, u.count) for u in used],
      [("たんさき", 2), ("わ", 2), ("めいおうせい", 1), ("はし", 1)])
check("集計", usage_summary(used), {"places": 6, "entries": 4, "context": 1, "head": 0, "risky": 1})
check("何も当たらなければ 0", usage_summary(used_entries([])), {"places": 0, "entries": 0, "context": 0, "head": 0, "risky": 0})

# ── 台本単位の一括チェック ──
from accent_core import line_reports, script_summary, validate
raw = "たんさきが/とおった\n\nこれわ/めいおうせい\nあ'め'"
text5, ap5 = run(raw)
inf5 = phrase_statuses(text5, text5, ap5)
rows = line_reports(text5, inf5, ap5, validate(text5))
check("空行は飛ばし、行番号は元のまま", [r.no for r in rows], [1, 3, 4])
check("1行目：辞書1・未確認1", (rows[0].places, rows[0].unchecked, rows[0].risky, rows[0].errors), (1, 1, 0, 0))
check("3行目：誤爆注意（これわ'）", (rows[1].places, rows[1].risky), (2, 1))
check("4行目：エラー（' が2つ）", rows[2].errors >= 1, True)
check("まとめ", script_summary(rows), {"lines": 3, "places": 3, "errors": rows[2].errors, "todo_lines": 3,
                                       "unchecked": 2, "risky": 1, "done_lines": 0})
s0 = text5.index("とおった")
inf6 = phrase_statuses(text5, text5, ap5, [(s0, s0 + 4)])
check("確認済みにすると、その行は済み", line_reports(text5, inf6, ap5, validate(text5))[0].todo, False)

print(f"{n} 件 OK")
