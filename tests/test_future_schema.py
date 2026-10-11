"""新しい版の辞書の扱い（v1.0.1）。「知らない情報が増えただけ」と「対応していない形式」を分けて確かめる。
python tests/test_future_schema.py"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import (Dictionary, SCHEMA_VERSION, DictionaryMigrationError, ReadOnlyDictionaryError,
                         IncompatibleDictionaryError, open_dictionary, convert, reader_problem)

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


FUTURE = SCHEMA_VERSION + 1
d = tempfile.mkdtemp()
bk = os.path.join(d, "backup")


def put(data, name="accent_dict.json"):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return p, open(p, "rb").read()


def base(**kw):
    data = {"format": "yukkuri-accent-dict", "version": FUTURE, "name": "マイ辞書",
            "entries": [{"from": "たんさき", "to": "たんさ'き"}]}
    data.update(kw)
    return data


# ── 1. 知らない情報が増えただけ → 読み取り専用で、変換には使う ───────────────
p, raw = put(base(new_section={"x": 1}, english_dictionary={},
                  entries=[{"from": "たんさき", "to": "たんさ'き", "speaker": "まりさ", "weight": 0.5}]))
dic = open_dictionary(p, bk, "1.0.1")
check("知らない項目だけ: 対応していないとはみなさない", dic.incompatible, "")
check("知らない項目だけ: 読み取り専用", dic.read_only, True)
check("知らない項目だけ: 今までの機能で変換できる", convert("たんさきが", dic, dic.number_table()).text, "たんさ'きが")
check("知らない項目だけ: 保存はしない", raises(lambda: dic.save(p), ReadOnlyDictionaryError), True)
check("知らない項目だけ: ファイルは変わらない", open(p, "rb").read(), raw)

p, _ = put(base(min_reader_schema=SCHEMA_VERSION))
check("min_reader_schema がこの版以下なら使える", open_dictionary(p, bk).incompatible, "")

# ── 2. 対応していない形式 → 変換に使わず、ファイルにも触らない ──────────────
cases = {
    "min_reader_schema がこの版より新しい": base(min_reader_schema=FUTURE),
    "min_reader_schema が整数でない": base(min_reader_schema="4"),
    "項目の名前が変わった（from → src）": base(entries=[{"src": "たんさき", "dst": "たんさ'き"}]),
    "項目が一覧でなくなった": base(entries={"たんさき": "たんさ'き"}),
    "条件の形が変わった（文字列 → 一覧）": base(entries=[{"from": "はし", "to": "はし'", "after": ["を", "わたる"]}]),
    "欄の形が変わった": base(number_rules=[["tens", "1", "じゅー"]]),
}
for name, data in cases.items():
    p, raw = put(data)
    dic = open_dictionary(p, bk, "1.0.1")      # 例外を出さない（壊れた辞書として名前を変えない）
    check(f"{name}: 対応していないと分かる", bool(dic.incompatible), True)
    check(f"{name}: 中身は読まない", dic.entries, [])
    check(f"{name}: 変換に使わない", raises(lambda: convert("たんさき", dic, dic.number_table()), IncompatibleDictionaryError), True)
    check(f"{name}: 登録・保存しない", (raises(lambda: dic.upsert("あ", "あ'"), ReadOnlyDictionaryError),
                                     raises(lambda: dic.save(p), ReadOnlyDictionaryError)), (True, True))
    check(f"{name}: ファイルは一切変わらない", (os.path.exists(p), open(p, "rb").read()), (True, raw))

check("理由を読める形で返す", reader_problem(base(min_reader_schema=FUTURE)).startswith(f"この辞書は形式 {FUTURE} 以降"), True)

# ── 3. 今の形式・古い形式で形が壊れているものは、今まで通り「壊れた辞書」 ─────────
for v in (1, SCHEMA_VERSION):
    p, _ = put({"format": "yukkuri-accent-dict", "version": v, "entries": [{"src": "あ"}]})
    check(f"形式 {v} で項目が壊れている → 壊れた辞書", raises(lambda: Dictionary.load(p), DictionaryMigrationError), True)

# ── 4. min_reader_schema は保存し直しても消さない ─────────────────────────
p, _ = put({"format": "yukkuri-accent-dict", "version": SCHEMA_VERSION, "min_reader_schema": 1, "entries": []})
dic = Dictionary.load(p)
dic.save(p, "1.0.1")
check("min_reader_schema を残す", json.load(open(p, encoding="utf-8")).get("min_reader_schema"), 1)

print(f"{n} 件 OK")
