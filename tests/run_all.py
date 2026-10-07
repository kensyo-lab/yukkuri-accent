"""tests/ の確認用スクリプトを全部動かす。python tests/run_all.py

このフォルダのテストは unittest / pytest の形ではなく、assert を並べて、そのまま実行する形です
（`python -m unittest` や `pytest` では「0件」と出ます）。1つずつ動かすときは
`python tests/test_dict_safety.py` のように実行してください。どれか1つでも失敗すると、終了コード 1 を返します。"""
import glob
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
scripts = sorted(p for p in glob.glob(os.path.join(here, "*.py")) if os.path.basename(p) != "run_all.py")
env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")   # Windows でも日本語の出力で落ちないように
failed = []
for p in scripts:
    name = os.path.basename(p)
    r = subprocess.run([sys.executable, p], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    if r.returncode == 0:
        print(f"OK    {name:32} {last[:60]}")
    else:
        failed.append(name)
        print(f"FAIL  {name}")
        print((r.stdout + r.stderr).strip()[-2000:])
print(f"\n{len(scripts) - len(failed)}/{len(scripts)} 本が通りました" + (f"（失敗: {', '.join(failed)}）" if failed else ""))
sys.exit(1 if failed else 0)
