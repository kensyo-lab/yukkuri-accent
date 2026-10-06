"""試聴の音量（WAVの音量変更）と、画面に戻ったときの自動変換の判定の確認。
python tests/test_volume_autopaste.py"""
import sys, os, tempfile, wave, array
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from accent_core import step_volume, scale_wav, looks_like_reading, auto_convert_action, VOLUME_MAX

n = 0


def check(name, got, want):
    global n
    assert got == want, f"{name}: {got!r} != {want!r}"
    n += 1


# ── 音量の段 ──
check("上げる", step_volume(100, 1), 110)
check("下げる", step_volume(100, -1), 90)
check("上の端で止まる", step_volume(VOLUME_MAX, 1), VOLUME_MAX)
check("下の端で止まる", step_volume(0, -1), 0)
check("刻みにそろえる", step_volume(57, 0), 60)
check("設定ファイルの変な値", step_volume(999, 0), VOLUME_MAX)

# ── WAV の音量 ──
d = tempfile.mkdtemp()


def make(path, samples, width=2, rate=16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        if width == 2:
            a = array.array("h", samples)
            if sys.byteorder == "big":
                a.byteswap()
            w.writeframes(a.tobytes())
        else:
            w.writeframes(bytes(samples))


def read(path):
    with wave.open(path, "rb") as r:
        p, fr = r.getparams(), r.readframes(r.getnframes())
    if p.sampwidth == 2:
        a = array.array("h")
        a.frombytes(fr)
        if sys.byteorder == "big":
            a.byteswap()
        return p, list(a)
    return p, list(fr)


src = os.path.join(d, "a.wav")
make(src, [0, 1000, -1000, 30000, -30000] * 3200)   # 16000 フレーム = 1 秒
out = os.path.join(d, "b.wav")
secs = scale_wav(src, out, 50)
check("再生時間", round(secs, 3), 1.0)
p, v = read(out)
check("半分の音量", v[:5], [0, 500, -500, 15000, -15000])
check("形式はそのまま", (p.nchannels, p.sampwidth, p.framerate, p.nframes), (1, 2, 16000, 16000))
scale_wav(src, out, 150)
check("大きくすると、はみ出す所は最大値で止める", read(out)[1][:5], [0, 1500, -1500, 32767, -32768])
scale_wav(src, out, 0)
check("0% は無音", set(read(out)[1]), {0})
scale_wav(src, out, 100)
check("100% は元のまま", read(out)[1], read(src)[1])
src8 = os.path.join(d, "c.wav")
make(src8, [128, 228, 28, 255, 0], width=1, rate=8000)
scale_wav(src8, out, 50)
check("8ビット（128 が無音）", read(out)[1], [128, 178, 78, 191, 64])
check("元のファイルは変えない", read(src)[1][:5], [0, 1000, -1000, 30000, -30000])

# ── 読みらしいか ──
check("YMM4 の読み", looks_like_reading("たんさ'き/にゅーほら'いずんずわ。"), True)
check("カタカナ・記号入り", looks_like_reading("_キかせてくださ'い"), True)
check("漢字入りの文章は変換しない", looks_like_reading("探査機ニューホライズンズは"), False)
check("々 も漢字扱い", looks_like_reading("ときどき々"), False)
check("英数字だけ", looks_like_reading("https://example.com"), False)
check("空", looks_like_reading("  \n"), False)

# ── 戻ってきたときの動き ──
R = "このどうがわ/たいようけい"
check("新しい読み → 変換", auto_convert_action(R, "前の物", "", None, "", ""), "convert")
check("前に見た物 → 何もしない", auto_convert_action(R, R, "", None, "", ""), None)
check("いま①に入っている物 → 何もしない", auto_convert_action(R, None, R + "\n", None, "", ""), None)
check("このツールがコピーした物 → 何もしない", auto_convert_action(R, None, "x", R, "y", "y"), None)
check("②と同じ物 → 何もしない", auto_convert_action(R, None, "x", None, R, R), None)
check("漢字の文章 → 何もしない", auto_convert_action("宇宙の話", None, "", None, "", ""), None)
check("②を手直し中 → 変換しない（知らせるだけ）", auto_convert_action(R, None, "あ", "い'", "い'う", "い'"), "edited")
check("②は手直ししていない → 変換", auto_convert_action(R, None, "あ", "い'", "い'", "い'"), "convert")

print(f"{n} 件 OK")
