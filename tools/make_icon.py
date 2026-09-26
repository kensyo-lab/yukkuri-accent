"""PNG から Windows 用の .ico（複数サイズ入り）を作る。

使い方: python tools/make_icon.py assets/icon.png build_icon.ico
正方形でない画像は、透明な余白を足して正方形にしてから縮小します。
"""
import sys
from PIL import Image

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main(src: str, dst: str) -> None:
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    if w != h:
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(im, ((side - w) // 2, (side - h) // 2))
        im = canvas
    im = im.resize((256, 256), Image.LANCZOS)
    im.save(dst, format="ICO", sizes=SIZES)
    print(f"{dst} を作りました（{len(SIZES)} サイズ）")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
