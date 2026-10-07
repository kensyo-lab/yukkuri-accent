"""「?」の印の画像を作る道具。python tools/make_help_icon.py 元の絵 [出力フォルダ]

元の絵（明るい背景に黒い「丸に?」、または黒い背景に白い形のマスク）から形を取り出し、縁がなめらかになるよう大きく作ってから縮めて、
大きさごと（12〜40 ピクセル）の透過 PNG を作る。ふだんの色と、マウスを乗せたときの色（青）の2通り。
Tk のキャンバスに線で描くと縁がギザギザになるので、画面ではこの画像を使う。Pillow が必要（ビルド時のみ）。"""
import os
import sys

from PIL import Image, ImageOps

SIZES = range(12, 41)
COLORS = {"": (0, 0, 0), "_hover": (31, 95, 191)}


def mask_from(path: str) -> Image.Image:
    """暗い所ほど不透明な、形だけのマスク（正方形・形がちょうど収まる大きさ）"""
    g = ImageOps.grayscale(Image.open(path))
    hist = g.histogram()
    bg = max(range(256), key=lambda v: hist[v])           # いちばん多い明るさ = 背景
    if bg < 128:                                          # 暗い背景に明るい形（作ったマスク）なら反転して同じ扱いに
        g = ImageOps.invert(g)
        bg = 255 - bg
    m = g.point(lambda v: 0 if v >= bg - 20 else min(255, round((bg - 20 - v) * 255 / max(1, bg - 60))))
    box = m.getbbox()
    m = m.crop(box)
    side = round(max(m.size) * 1.08)                      # 縁が切れないよう、まわりに少し余白
    sq = Image.new("L", (side, side), 0)
    sq.paste(m, ((side - m.width) // 2, (side - m.height) // 2))
    return sq


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join("assets", "help")
    os.makedirs(out, exist_ok=True)
    m = mask_from(src)
    for n in SIZES:
        a = m.resize((n, n), Image.LANCZOS)
        for suffix, rgb in COLORS.items():
            im = Image.new("RGBA", (n, n), rgb + (0,))
            im.putalpha(a)
            im.save(os.path.join(out, f"help_{n}{suffix}.png"))
    print(f"{len(SIZES) * len(COLORS)} 個の画像を {out} に作りました")


if __name__ == "__main__":
    main()
