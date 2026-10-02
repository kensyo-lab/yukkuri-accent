"""配布 zip に入れる README の「最新版」バッジの行を、その zip の版に書き換える。
GitHub で見る README はバッジで最新版を、zip の README はその zip の版を、どちらも自動で正しく出すため。

使い方: python tools/stamp_readme.py <README.md> <版（例: v0.5.3）>
"""
import re
import sys

path, tag = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8", newline="") as f:
    s = f.read()
line = (f"**この zip の版：{tag}**（最新版は "
        "https://github.com/kensyo-lab/yukkuri-accent/releases/latest で確かめられます）")
s, n = re.subn(r"^\[!\[最新版\]\(.*$", lambda m: line, s, count=1, flags=re.M)
if n != 1:
    sys.exit("README に「最新版」のバッジの行が見つかりませんでした")
with open(path, "w", encoding="utf-8", newline="") as f:
    f.write(s)
print(f"README に版を書き込みました: {tag}")
