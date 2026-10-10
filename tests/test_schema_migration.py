"""辞書の形式（schema）の版と移行の確認（v1.0.0 設計メモ「必須のテスト」）。
python tests/test_schema_migration.py"""
import sys, os, json, tempfile, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import (Dictionary, SCHEMA_VERSION, SECTIONS, DictionaryMigrationError, FutureSchemaError,
                         ReadOnlyDictionaryError, migrate_dictionary, open_dictionary, list_kept)

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False


def write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


d = tempfile.mkdtemp()
p = os.path.join(d, "accent_dict.json")
bk = os.path.join(d, "backup")
NOW = datetime.datetime(2026, 10, 9, 14, 30, 0)

# 1. schema 無しの旧辞書 → 最新へ移行し、項目が全件残る ──────────────────
old = {"format": "yukkuri-accent-dict", "name": "マイ辞書",
       "entries": [{"from": "たんさき", "to": "たんさ'き", "hits": 12, "added": "2026-06-01"},
                   {"from": "ぜひ", "to": "ぜ'ひ", "head_only": True, "note": "句頭だけ"},
                   {"from": "はし", "to": "はし'", "after": "をわたる"}]}
write(p, old)
dic = open_dictionary(p, bk, "1.0.0", now=NOW)
check("移行元の形式（version 無しは 1）", dic.migrated_from, 1)
saved = read(p)
check("最新の形式で保存し直す", saved["version"], SCHEMA_VERSION)
check("新しい欄が空で足される", {k: saved[k] for k in SECTIONS}, {k: {} for k in SECTIONS})
check("項目は全件そのまま", [(e["from"], e["to"]) for e in saved["entries"]],
      sorted((e["from"], e["to"]) for e in old["entries"]))
check("項目の情報も変わらない", next(e for e in saved["entries"] if e["from"] == "たんさき"),
      {"from": "たんさき", "to": "たんさ'き", "added": "2026-06-01", "hits": 12})
check("古い辞書の作成元は推測しない", ("created_with" in saved, saved["last_saved_with"]), (False, "1.0.0"))
kept = list_kept(bk)
check("移行前の辞書を keep に残す", [(os.path.basename(q), t) for q, t in kept],
      [("accent_dict_keep_pre-migrate-schema1-to3-20261009-143000.json", "辞書の形式を 1 から 3 に移行する前")])
check("残した物は移行前の中身", read(kept[0][0]), old)

# 版 1・2 を明記した辞書も1段ずつ移行する
for v in (1, 2):
    data, changed = migrate_dictionary({"version": v, "entries": []})
    check(f"形式 {v} から移行", (data["version"], changed), (SCHEMA_VERSION, True))

# 2. 現行 schema → 一切変えない（バックアップも作らない） ──────────────
d2 = tempfile.mkdtemp()
p2, bk2 = os.path.join(d2, "accent_dict.json"), os.path.join(d2, "backup")
cur = {"format": "yukkuri-accent-dict", "version": SCHEMA_VERSION, "created_with": "1.0.0",
       "last_saved_with": "1.0.0", "name": "マイ辞書", "entries": [{"from": "ぜひ", "to": "ぜ'ひ"}],
       **{k: {} for k in SECTIONS}}
write(p2, cur)
raw = open(p2, "rb").read()
dic = open_dictionary(p2, bk2, "1.0.1", now=NOW)
check("移行しない", dic.migrated_from, None)
check("ファイルは一切変わらない", open(p2, "rb").read(), raw)
check("バックアップも作らない", os.path.exists(bk2), False)
data, changed = migrate_dictionary(cur)
check("移行処理を通しても同じ", (data, changed), (cur, False))

# 3. 未来 schema → 保存せず安全に拒否 ────────────────────────────────
future = {"format": "yukkuri-accent-dict", "version": SCHEMA_VERSION + 1, "name": "マイ辞書",
          "entries": [{"from": "ぜひ", "to": "ぜ'ひ"}], "new_section": {"x": 1}}
write(p2, future)
raw = open(p2, "rb").read()
dic = open_dictionary(p2, bk2, "1.0.0", now=NOW)
check("読み取り専用で開く", (dic.read_only, dic.migrated_from), (True, None))
check("変換には使える", dic.apply("ぜひ")[0], "ぜ'ひ")
check("保存できない", raises(lambda: dic.save(p2, "1.0.0"), ReadOnlyDictionaryError), True)
check("登録できない", raises(lambda: dic.upsert("あ", "あ'"), ReadOnlyDictionaryError), True)
check("ファイルは変わらない", open(p2, "rb").read(), raw)
check("移行処理は拒否する", raises(lambda: migrate_dictionary(future), FutureSchemaError), True)

# 4. schema_version が整数以外 → エラー ──────────────────────────────
for bad in (True, False, "2", 2.0, None, 0, -1, [2]):
    write(p2, {"format": "yukkuri-accent-dict", "version": bad, "entries": []})
    check(f"version={bad!r} は受け付けない", raises(lambda: Dictionary.load(p2), DictionaryMigrationError), True)
write(p2, {"format": "yukkuri-accent-dict", "version": SCHEMA_VERSION, "entries": {}})
check("entries が一覧でなければエラー", raises(lambda: Dictionary.load(p2), DictionaryMigrationError), True)
write(p2, {"format": "yukkuri-accent-dict", "entries": [{"from": "あ"}]})
check("to の無い項目はエラー", raises(lambda: Dictionary.load(p2), DictionaryMigrationError), True)

# 5. 未知フィールド → 移行後も保持 ─────────────────────────────────
d3 = tempfile.mkdtemp()
p3 = os.path.join(d3, "accent_dict.json")
write(p3, {"format": "yukkuri-accent-dict", "version": 1, "name": "マイ辞書", "author": "kensyo",
           "entries": [{"from": "はし", "to": "はし'", "speaker": "まりさ", "score": 0.9}]})
open_dictionary(p3, os.path.join(d3, "backup"), "1.0.0", now=NOW)
saved = read(p3)
check("ファイル全体の未知の情報", saved.get("author"), "kensyo")
check("項目の未知の情報", (saved["entries"][0].get("speaker"), saved["entries"][0].get("score")), ("まりさ", 0.9))

# 6. 旧辞書 → 移行 → 保存 → 再読み込みで一致 ─────────────────────────
a = Dictionary.load(p)        # 1. で移行・保存した物
a.sections["english_dictionary"]["えぬいーえーあーる"] = {"reading": "にあ", "accent": "に'あ", "source": "NEAR"}
a.save(p, "1.0.0")
b = Dictionary.load(p)
check("項目が一致", [(e.key, e.dst, e.head_only, e.note, e.added, e.hits) for e in b.entries],
      [(e.key, e.dst, e.head_only, e.note, e.added, e.hits) for e in a.entries])
check("新しい欄も一致", b.sections, a.sections)
check("保存し直しても同じ中身", b.to_data(), read(p))

# 新しく作った辞書には、作成したアプリの版を記録する
p4 = os.path.join(d3, "new.json")
nd = Dictionary()
nd.save(p4, "1.0.0")
nd.save(p4, "1.0.1")
check("created_with は最初の1回だけ、last_saved_with は毎回", (read(p4)["created_with"], read(p4)["last_saved_with"]),
      ("1.0.0", "1.0.1"))

print(f"{n} 件 OK")
