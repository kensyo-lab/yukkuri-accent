# assets

- `icon.png` … アプリのアイコン（正方形・透過PNG推奨、1024×1024 程度）。
  ここに置くと、ビルド時に自動で `.ico` に変換されて `.exe` に埋め込まれ、ウィンドウのアイコンにも使われます。
- `help_source.png` … 「?」の印の元の形（黒い背景に白いマスク）。
- `help/` … 「?」の印の画像（12〜40 ピクセル、ふだんの色とマウスを乗せたときの青）。
  `python tools/make_help_icon.py assets/help_source.png assets/help` で作り直せます（Pillow が必要）。
  Tk のキャンバスに線で描くと縁がギザギザになるので、縁をなめらかにした画像を大きさごとに用意しています。
