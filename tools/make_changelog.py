"""release-notes/ のリリースノートをまとめて、変更履歴（CHANGELOG.md）を作る。

    python tools/make_changelog.py [出力先]   （既定: CHANGELOG.md）

新しい版が上に来るように並べ、各版の「ダウンロードの案内」「入れ替え方」「二次創作の表記」は
冒頭・末尾に1回だけ書きます。日付は、その版のリリースノートを初めて入れた日（git の記録）です。
ビルドのたびに作り直すので、手で書き足す必要はありません。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NOTES = os.path.join(ROOT, "release-notes")

HEAD = """# ゆっくりアクセント辞書 変更履歴

初版（v0.2）から最新版までの変更をまとめたものです。新しい版が上にあります。
古い版から一気に上げるときに、何が変わったかを確かめるのにお使いください。

## 入れ替え方（どの版からでも同じです）
ユーザーデータの `accent_dict.json`（辞書）・`learning.json`（学習候補）・`settings.json`（設定）・`backup` フォルダ（辞書のバックアップ）はそのまま残し、それ以外の配布ファイル（`yukkuri-accent.exe`・README・FAQ・CHANGELOG・`dictionaries` など）は、新しい版のもので置き換えてください。
v0.9 以前から入れ替えるときは、`numbers.json`（数字の読み表）も残してください。v1.0.0 を初めて起動したときに、辞書の中へ移します。
心配なときは、置き換える前にフォルダごと別の場所へコピーしておくと安心です。
"""

FOOT = """
---
東方Projectの二次創作（ファン活動）です。東方Projectは上海アリス幻樂団の作品です。
"""


def version_key(name: str):
    return tuple(int(x) for x in re.findall(r"\d+", name))


def added_date(path: str) -> str:
    """そのファイルを初めて入れた日（git が無い・記録が無いときは空）"""
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--follow", "--format=%ad",
                              "--date=short", "--", path], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout.split()
        return out[-1] if out else ""
    except (OSError, subprocess.CalledProcessError):
        return ""


def body(text: str) -> str:
    """版ごとの決まり文句を外し、見出しを1段下げる。"""
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith(">"):                       # ダウンロードの案内
            continue
        if "上海アリス幻樂団" in line:                  # 二次創作の表記（末尾に1回だけ書く）
            continue
        if line.startswith("## "):
            skip = line.strip() == "## 入れ替え方"      # 入れ替え方（冒頭に1回だけ書く）
            if skip:
                continue
            line = "#" + line
        elif line.startswith("###") and not skip:       # 小見出しも1段下げる（### → ####）
            line = "#" + line
        elif skip:
            continue
        out.append(line)
    return "\n".join(out).strip()


def build() -> str:
    files = sorted((f for f in os.listdir(NOTES) if re.fullmatch(r"v[\d.]+\.md", f)),
                   key=version_key, reverse=True)
    parts = [HEAD]
    for f in files:
        path = os.path.join(NOTES, f)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        date = added_date(os.path.join("release-notes", f))
        title = f"## {f[:-3]}" + (f"（{date}）" if date else "")
        if f == files[-1]:
            title += "　初版"
        parts.append(f"\n{title}\n\n{body(text)}\n")
    parts.append(FOOT)
    return "".join(parts)


def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "CHANGELOG.md")
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build())
    print(f"変更履歴を作りました: {dst}")


if __name__ == "__main__":
    main()
