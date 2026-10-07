"""育てた辞書を無駄にしない仕組みの確認（古い形式・新しい形式の読み書き、節目のバックアップ）。
python tests/test_dict_safety.py"""
import sys, os, json, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import Dictionary, keep_backup, list_kept, backup_file, list_backups

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


d = tempfile.mkdtemp()
p = os.path.join(d, "accent_dict.json")

# ── 昔の形式（v0.2〜v0.6：条件なし・使用回数と登録日つき）がそのまま読める ──
old = {"format": "yukkuri-accent-dict", "version": 1, "name": "マイ辞書",
       "entries": [{"from": "たんさき", "to": "たんさ'き", "hits": 12, "added": "2026-06-01"},
                   {"from": "ぜひ", "to": "ぜ'ひ", "head_only": True, "note": "句頭だけ"}]}
json.dump(old, open(p, "w", encoding="utf-8"), ensure_ascii=False)
dic = Dictionary.load(p)
check("昔の形式の項目", [(e.src, e.dst, e.hits, e.added, e.head_only, e.note) for e in dic.entries],
      [("たんさき", "たんさ'き", 12, "2026-06-01", False, ""), ("ぜひ", "ぜ'ひ", 0, "", True, "句頭だけ")])
dic.save(p)
check("保存し直しても、条件が無ければ形式は1のまま（昔の版でも読める）", json.load(open(p, encoding="utf-8"))["version"], 1)

# ── 将来の版で増えた情報を、この版で開いて保存しても消さない ──
future = {"format": "yukkuri-accent-dict", "version": 3, "name": "マイ辞書", "author": "kensyo",
          "entries": [{"from": "はし", "to": "はし'", "after": "をわたる", "speaker": "まりさ", "score": 0.9},
                      {"from": "たんさき", "to": "たんさ'き"}]}
json.dump(future, open(p, "w", encoding="utf-8"), ensure_ascii=False)
dic = Dictionary.load(p)
check("新しい版の辞書だと分かる", (dic.file_version, dic.newer_format), (3, True))
dic.upsert("めいおうせい", "めいおうせ'い")   # この版で1つ足して保存
dic.save(p)
back = json.load(open(p, encoding="utf-8"))
check("形式の版を下げない", back["version"], 3)
check("ファイル全体の知らない情報も残る", back.get("author"), "kensyo")
e = next(x for x in back["entries"] if x["from"] == "はし")
check("項目の知らない情報も残る", (e.get("speaker"), e.get("score"), e.get("after")), ("まりさ", 0.9, "をわたる"))
check("足した項目も入る", sorted(x["from"] for x in back["entries"]), ["たんさき", "はし", "めいおうせい"])

# ── 取り込みでも、知らない情報は消えない ──
mine = Dictionary()
mine.merge(Dictionary.load(p))
check("取り込んだ項目の知らない情報", next(x for x in mine.entries if x.src == "はし").extra.get("speaker"), "まりさ")

# ── 節目のバックアップ（古い順に消えない） ──
bk = os.path.join(d, "backup")
check("新しい版を初めて起動する前", os.path.basename(keep_backup(p, bk, "before-v0.9.0")), "accent_dict_keep_before-v0.9.0.json")
check("同じ節目は2回目からは写さない（最初の状態を残す）", keep_backup(p, bk, "before-v0.9.0"), None)
time.sleep(0.01)
keep_backup(p, bk, "month-2026-10")
check("一覧の説明", [t for _, t in list_kept(bk)], ["2026年10月の最初", "v0.9.0 を初めて起動する前"])
for i in range(25):     # ふつうのバックアップを25回（新しい20個だけ残る）
    with open(p, "a", encoding="utf-8") as f:
        f.write(" ")
    backup_file(p, bk, keep=20)
check("ふつうのバックアップは新しい20個", len(list_backups(bk)), 20)
check("節目のバックアップは消えない", len(list_kept(bk)), 2)
check("無い辞書は写さない", keep_backup(os.path.join(d, "none.json"), bk, "x"), None)

print(f"{n} 件 OK")
