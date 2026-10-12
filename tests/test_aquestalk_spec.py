"""AquesTalk 音声記号列仕様書（Ver.1.7）に照らした検査の確認。AquesTalk がエラー（強制終了も）になる並びを、渡す前に止める。
python tests/test_aquestalk_spec.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import (validate, blocks_aquestalk, blocking_summary, has_bad_chars, Dictionary, convert, prepare,
                         load_numbers)

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


def ok(s):
    return not blocks_aquestalk(validate(s))


# ── 報告のあった例（AquesTalkPlayer が終了コード 2008 で止まった） ──
check("きゅ'ーじゅー は通す", ok("はっぴゃ'_ク/きゅ'ーじゅー/はち'ねん。"), True)
check("き'ゅーじゅー は止める", ok("はっぴゃ'_ク/き'ゅーじゅー/はち'ねん。"), False)
check("文字の問題ではない（試聴・コピーを止める理由は仕様の誤り）", has_bad_chars(validate("き'ゅーじゅー。")), False)
check("止めた理由", blocking_summary(validate("き'ゅーじゅー。"), "き'ゅーじゅー。"), "' が拗音の途中にあります")

# ── 仕様書の例（○ は通し、× は止める） ──
for s in ["これわ、おんせーき'ごーです。", "か'れし。", "く'らぶ。", "じゅ'んび、できたよ。",
          "こ'んどわ、もーすこ'し/ふくざつな/おんせーき'ごーです。", "あ'くせんと;な'どの/かなめとな'る、",
          "あ'くせんと+な'どの/かなめとな'る、", "ふぁいるお/ほぞん、", "ろくおん+しま'すか？",
          "え'るめ_スの/あ'_クせさりー。", "よみあげまス。", "めだかの/カ゜っこーわ、かわの+な'か。",
          "あたま'が、ガ'んガんする。", "でんわば'んごーわ、<NUM VAL=01-2345-6789>です。",
          "きの'ーわ、<NUMK VAL=321162567>+でした。", "のこり+じ'かんわ、あ'と/<NUMK VAL=10 COUNTER=ふん>です。",
          "げつよ'ーの/<NUMK VAL=21 COUNTER=じ>から、<NUMK VAL=8 COUNTER=ちゃ'んねる>で/よやく+しま'した。",
          "ぐい'っと;のみた'いな。", "さんだるを、つっかけとゆう。ちょ'っと+ま'ってを、だ'んまとゆう。",
          "それから'わ、やまぐち'けんで;やとわれば'んとーお/するよ'ーに+な'り、か'ぞくの/もと'にわ、ほと'んど;もどれ'なく+なりま'した。"]:
    check(f"○ {s}", ok(s), True)

for s, why in [("じ'ゅんび、できたよ。", "' が拗音の途中"),
               ("ひと'つのあくせんと'くです。", "1つのアクセント句に ' が2つ"),
               ("ぐぃ'っと。", "読み記号表に無い読み"),
               ("あっ。", "句の最後が っ"), ("えっ、うそー。", "句の最後が っ"),
               ("えっっと。", "っ の連続"), ("えっッと。", "っ の連続（カタカナ）"),
               ("ーか。", "句の先頭の ー"), ("わたし;ーわ、", "句の先頭の ー"),
               ("えっー。", "っ の後の ー"),
               ("ナイ_スー。", "無声化の後の ー"), ("あ_キや。", "無声化の後の や"), ("え_スガ。", "無声化の後の ガ"),
               ("_カた。", "無声化にできない読み"), ("_。", "_ の後に仮名が無い"),
               ("ぢめん。", "ぢ は読み記号表に無い"), ("つづき。", "づ は読み記号表に無い"), ("ゔぁいおりん。", "ゔ は無い"),
               ("ぁいう。", "小さい仮名だけ"), ("'あいう。", "' が句の先頭"), ("あ_'い。", "_ の直後の '"),
               ("<NUMK VAL=abc>。", "読めない形のタグ"), ("<NUMK VAL=1,000>。", "読めない形のタグ")]:
    check(f"× {s}（{why}）", ok(s), False)

check("区切りの重なりは注意だけ（止めない）", ok("あいう//えお。"), True)
check("展開していない正しいタグは注意だけ", ok("<NUMK VAL=10 COUNTER=ふん>です。"), True)

# ── このツールが作る読みは止めない（数字の表・単位・同梱辞書） ──
d = Dictionary.load(os.path.join(os.path.dirname(__file__), "..", "dictionaries", "kensyo.json"))
t = d.number_table()
for c in [""] + list(t["counters"]):
    for v in (0, 1, 3, 6, 8, 10, 11, 20, 89, 100, 101, 300, 1000, 1300, 2026, 3000, 8000, 10000, 123456, 1.5, 0.52, 39.5):
        x = prepare(f"あ<NUMK VAL={v}" + (f" COUNTER={c}" if c else "") + ">。", t)
        check(f"数字の読み {v}{c}", ok(x), True)
for u, e in d.unit_table().items():
    for v in (1, 5, 9, 10, 67, 89, 300):
        check(f"単位 {v}{u}", ok(convert(f"あ<NUMK VAL={v}>/{e['ymm4_readings'][0]}。", d, t).text), True)
for e in d.entries:
    check(f"同梱辞書 {e.src}", ok(e.dst), True)

print(f"{n} 件 OK")
