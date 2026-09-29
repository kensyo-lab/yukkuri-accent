"""AquesTalkPlayer.preset の読み込みの確認。python tests/test_presets.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import load_player_presets

SAMPLE = '''プリセット名,棒読み,エンジン,声種,話速,音量,高さ,アクセント,声質,音程,メモ
"デフォルト","false","AquesTalk10","F1E",100,100,100,100,100,100,"AquesTalk10 女声"
"れいむ","true","AquesTalk1","f1",100,100,100,100,100,100,"ゆっくり霊夢"
"まりさ","true","AquesTalk1","f2",100,100,100,100,100,100,"ゆっくり魔理沙"
"女性１","false","AquesTalk1","f1",100,100,100,100,100,100,""
"まりさ抑揚","false","AquesTalk1","f2",110,100,100,100,100,100,"ゆっくり魔理沙"
'''
WANT = [("デフォルト", False), ("れいむ", True), ("まりさ", True), ("女性１", False), ("まりさ抑揚", False)]

d = tempfile.mkdtemp()
n = 0
for enc in ("cp932", "utf-8", "utf-8-sig", "utf-16"):
    p = os.path.join(d, f"{enc}.preset")
    with open(p, "w", encoding=enc, newline="\r\n") as f:
        f.write(SAMPLE)
    got = load_player_presets(p)
    assert got == WANT, (enc, got)
    n += 1
assert load_player_presets(os.path.join(d, "none.preset")) == []
print(f"{n + 1} 件 OK")
