import sys; import os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import *

PAIRS = [
("みなさんこんにちわ。","みな'さん/こんにちわ。"),
("この/どうがわ/たいようけい/がいえん/てんたい/たんさき/にゅーほらいずんずに/ついて/かいせ_ツしていくぜ。","このどうがわ,たいようけい/がいえんてんたいたんさ'き,/にゅーほら'いずんずについて/かいせ_ツ_シていく'ぜ。"),
("よろ_シく/おねがいしま_ス。","よろ_シく/おねがいしま'_ス。"),
("<NUMK VAL=2015 COUNTER=ねん><NUMK VAL=7 COUNTER=がつ><NUMK VAL=14 COUNTER=にち>。じんるいわはじめて、めいおうせいの/ほんとうの/すがたを/めに/_シた。","にせ'ん/じゅ'ーごねん,_シちがつ/じゅ'ーよっか。じ'んるいわ/はじ'めて、めいおうせいの/ほんとうのす'がたを/め'に_シた。"),
("そんざいわけっこう/まえから/しられていま_シたけど、_チかくまで/いったのわあんがい/さいきんなんですよね。","そんざいわ/け'っこう/ま'えから/しられていま'_シたけど、_チか'くまで/いった'のわ/あんがいさいきん/な'んですよね。"),
("そうだな。がぞうわ<NUMK VAL=9 COUNTER=ねん>いじょうを/ついやし、およそ<NUMK VAL=50 COUNTER=おく>きろめーとるの/たびを/はた_シた/たんさき、にゅーほらいずんずが/さつえい_シた/めいおうせいの/がぞうだ。","そ'うだな。がぞうわ/きゅーねんい'じょうを/ついや'し、およそ/ごじゅーお_クきろめ'ーとるの/たび'を/はた'_シた/たんさ'き、にゅーほら'いずんずがさつえい_シた,/めいおうせいのがぞうだ。"),
("たんさき/にゅーほらいずんずわ/めいおうせいを/とおりすぎた/あと、<NUMK VAL=2026 COUNTER=ねん>/げんざいも/たいようけいがい/えんを/_ツきすすんでいる。こんかいわ/その,めいおうせいの/さき、の/はなしも/しよう。","たんさ'き/にゅーほら'いずんずわ/めいおうせいを/とおりす'ぎたあと、にせ'ん/に'じゅー/ろくねんげ'んざいも,/たいようけい/がいえんを/_ツきすす'んでいる。こ'んかいわその,めいおうせいの/さきの/はな'しもしよう。"),
("それわ/きょうみ/ありますね。ぜひ/_キかせてください。","それわ/きょ'うみ/ありま'すね。ぜ'ひ/_キかせてくださ'い。"),
]
if __name__ == "__main__":
    t = load_numbers(None)
    print("== 完成形の検査（問題が出ないこと）")
    for _, a in PAIRS:
        iss = validate(normalize(a))
        if iss: print(a, iss)
    print("== 数字展開")
    for b,_ in PAIRS:
        if "NUMK" in b: print(prepare(b,t))
    d = Dictionary()
    print("== 学習候補")
    for b,a in PAIRS:
        for c in learn(b,a,t,d):
            print(f"  [{c.kind}]{'頭' if c.head_only else '  '} {c.src}  →  {c.dst}")
            d.upsert(c.src,c.dst,c.head_only)
    print("entries:",len(d.entries))
    print("== 学習後の再現")
    ok=0
    for b,a in PAIRS:
        r = convert(b,d,t)
        if r.text==normalize(a): ok+=1
        else: print(" 出力:",r.text,"\n 正解:",normalize(a))
        if r.issues: print(" issues",r.issues)
    print(f"{ok}/{len(PAIRS)} 完全一致")
