"""文脈付き辞書（前後の条件）の確認。python tests/test_context_dict.py"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import Dictionary, Entry, entry_warnings, dict_diff

n = 0
def check(got, want):
    global n
    assert got == want, f"\n got: {got}\nwant: {want}"
    n += 1

def conv(d, s):
    return d.apply(s)[0]

# 後ろの条件: 「かわ」は、直後が「の」のときだけ
d = Dictionary()
d.upsert("かわ", "か'わ", after="の")
check(conv(d, "かわの/みず"), "か'わの/みず")
check(conv(d, "かわいい"), "かわいい")                 # 直後が「の」でない → 当てない
check(conv(d, "おがわ/の/ほとり"), "おがわ/の/ほとり")   # 「がわ」は「かわ」ではないので当たらない

# 前の条件: 区切りやアクセントの記号は無視して比べる
d = Dictionary()
d.upsert("わ", "わ'", before="これ")
check(conv(d, "これ/わ"), "これ/わ'")                  # 区切りをまたいでも「これ」の直後
check(conv(d, "こ'れわ"), "こ'れわ'")                   # アクセント記号も無視
check(conv(d, "それわ"), "それわ")                      # 「それ」の後は当てない
check(conv(d, "これ。わ"), "これ。わ")                  # 句点はまたがない

# 同じ YMM4側を、条件違いで複数持てる。条件付きを先に、なければ条件なし
d = Dictionary()
d.upsert("はし", "は'し")                               # 条件なし（箸）
d.upsert("はし", "はし'", after="を/わたる")             # 橋を渡る
check(len(d.entries), 2)
check(conv(d, "はしを/わたる"), "はし'を/わたる")
check(conv(d, "はしで/たべる"), "は'しで/たべる")
check(d.find("はし").dst, "は'し")                       # 条件を省くと、条件なしの項目
check(d.find("はし", after="を/わたる").dst, "はし'")

# 保存と読み込み（before / after を書く。条件のない辞書は今までと同じ形）
p = os.path.join(tempfile.mkdtemp(), "d.json")
d.save(p)
data = json.load(open(p, encoding="utf-8"))
check(data["version"], 2)
check(sorted((e["from"], e.get("after", "")) for e in data["entries"]), [("はし", ""), ("はし", "を/わたる")])
d2 = Dictionary.load(p)
check(sorted(e.key for e in d2.entries), sorted(e.key for e in d.entries))
plain = Dictionary(); plain.upsert("あ", "あ'"); plain.save(p)
check(json.load(open(p, encoding="utf-8"))["version"], 1)

# 削除・取り込みも、条件まで含めて項目を見分ける
d.remove("はし", after="を/わたる"); check([e.key for e in d.entries], [("はし", "", "")])
other = Dictionary(); other.upsert("はし", "はし'", after="を/わたる"); other.upsert("はし", "ちがう")
check(d.merge(other), (1, 1))                             # 条件付きは新しく入り、条件なしは自分を優先

# 条件付きの項目は誤爆の印を付けない／比較は条件ごと
check(entry_warnings(Entry("わ", "わ'", before="これ")), [])
check(entry_warnings(Entry("わ", "わ'")), ["助詞だけ"])
a = Dictionary(); a.upsert("はし", "は'し")
b = Dictionary(); b.upsert("はし", "は'し"); b.upsert("はし", "はし'", after="を")
add, rem, chg = dict_diff(a, b)
check(([e.key for e in add], rem, chg), ([("はし", "", "を")], [], []))
print(f"{n} 件 OK")
