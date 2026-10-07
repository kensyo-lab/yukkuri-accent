"""
ゆっくりアクセント辞書 — tkinter GUI

使い方:
    python accent_app.py
同じフォルダに accent_dict.json（辞書）と numbers.json（数字の読み表）が作られます。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

import accent_core as core

APP_NAME = "ゆっくりアクセント辞書"
VERSION = "0.9.1"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DICT_PATH = os.path.join(BASE_DIR, "accent_dict.json")
NUM_PATH = os.path.join(BASE_DIR, "numbers.json")
CONF_PATH = os.path.join(BASE_DIR, "settings.json")
# 同梱ファイル（アイコンなど）の場所: .exe では展開先、スクリプトでは同じフォルダ
RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

# 外部プログラム（AquesTalkPlayer など）を呼ぶとき、黒いコンソール画面を出さない
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

COL_APPLIED = "#fff2b3"
COL_ERROR = "#ffb3b3"
COL_WARN = "#ffd9a6"
COL_UNCHECKED = "#dfe9f7"      # まだ誰も触っていない文節（耳で確かめたい所）
COL_MANUAL = "#dcefd9"         # 手で直した文節
COL_RISKY_LINE = "#c0392b"     # 誤爆しやすい辞書が当たった所の下線
COL_MK_ACCENT = "#d0342c"      # ' アクセント
COL_MK_SEP = "#8a8f98"         # / , + ; 区切り
COL_MK_DEVOICE = "#1f5fbf"     # _ 無声化

# メッセージ欄の色（背景・左の帯・強調する文字）
#   crit（最重要・赤）: 手を打たないと期待どおりに読まれない（棒読み・エラーが残っている・試聴の失敗）
#   warn（重要・橙）  : ツールが文字を書き換えた／確かめてほしい所がある（記号の自動修正・注意）
#   info（通常）      : 済んだことのお知らせ
MSG_STYLE = {
    "info": {"bg": "#f3f5f8", "bar": "#9aa3b2", "fg": "#222222"},
    "warn": {"bg": "#fff4e3", "bar": "#e08a00", "fg": "#b35c00"},
    "crit": {"bg": "#ffecec", "bar": "#d0342c", "fg": "#c0201a"},
}
MSG_LINES = 3                  # メッセージ欄は最初から3行分の高さを取っておく
WIN_W, WIN_H = 1040, 780       # 起動時のウィンドウの大きさ（文字の大きさ 100% のとき）
SCALE_MIN, SCALE_MAX = 0.8, 2.0  # 文字の大きさの範囲（80%〜200%）
BACKUP_DIR = os.path.join(BASE_DIR, "backup")
BACKUP_KEEP = 20
ACC_CANVAS_H = 200             # アクセント編集の欄の高さ（100% のとき）
COL_PITCH = "#5b7db1"          # 高低の線

# 文字の大きさ（100% のときのポイント数）。設定の倍率を掛けて使う。名前: (書体, 大きさ, 太さ)
FONT_BASE = {
    "text": ("text", 14, "normal"), "text_b": ("text", 14, "bold"),
    "entry": ("entry", 13, "normal"), "entry_b": ("entry", 14, "bold"),
    "ui": ("text", 10, "normal"), "ui_b": ("text", 10, "bold"), "small": ("text", 9, "normal"),
    "tree": ("text", 11, "normal"), "head": ("text", 10, "bold"),
    "big": ("text", 11, "bold"), "title": ("text", 11, "bold"),
    "acc": ("text", 14, "normal"), "acc_b": ("text", 14, "bold"), "acc_s": ("text", 10, "normal"),
}

# ショートカット（操作の名前, 画面に出す名前, 最初のキー）。設定タブで変えられ、settings.json に保存する
SHORTCUTS = [
    ("paste_convert", "貼り付けて変換", "<Control-Shift-Key-V>"),
    ("convert", "変換", "<Control-Key-Return>"),
    ("copy", "コピー", "<Control-Shift-Key-C>"),
    ("recheck", "再チェック", "<Key-F7>"),
    ("preview", "試聴", "<Key-F5>"),
    ("stop", "試聴を止める", "<Key-F6>"),
    ("mute", "消音（もう一度で元に戻す）", "<Key-F9>"),
    ("vol_down", "試聴の音量を下げる", ""),
    ("vol_up", "試聴の音量を上げる", ""),
    ("accent_panel", "アクセント編集を開く／閉じる", "<Key-F8>"),
    ("next_unchecked", "次の未確認の文節へ", "<Key-F11>"),
    ("prev_unchecked", "前の未確認の文節へ", "<Shift-Key-F11>"),
    ("acc_left", "アクセントを前の文字へ（カーソルのある文節）", "<Alt-Key-Left>"),
    ("acc_right", "アクセントを後ろの文字へ（カーソルのある文節）", "<Alt-Key-Right>"),
    ("acc_here", "カーソルの前の文字にアクセント", "<Alt-Key-Up>"),
    ("acc_clear", "アクセントを外す（平板）", "<Alt-Key-Down>"),
    ("send_learn", "手直しを辞書の候補に送る", ""),
    ("font_up", "文字を大きく", "<Control-Key-plus>"),
    ("font_down", "文字を小さく", "<Control-Key-minus>"),
    ("font_reset", "文字の大きさを100%に戻す", "<Control-Key-0>"),
]

IS_WINDOWS = sys.platform.startswith("win")
PHRASE_COLOR_HELP = (
    "このツールは、YMM4 の読みを全部自動で正解にするのではなく、「人が確かめるべき所だけを、いちばん早く見つける」ことを目指しています。"
    "そのために、変換結果の文節を、何が起きたかで色分けします（正しいかどうかではありません。辞書が当たった所でも、誤爆していることはあります）。\n\n"
    "・黄：辞書で置き換えた所\n"
    "・黄＋赤い下線：誤爆しやすい項目（助詞だけ・短い語 など）が当たった文節\n"
    "・淡い青（未確認）：辞書も手直しも入っていない、YMM4 の読みそのままの文節。耳で確かめたい所です\n"
    "・淡い緑（手直し）：手で直した文節\n\n"
    "［次の未確認へ ▶］（F11）で未確認・誤爆注意の文節を順に選び、そのまま［試聴］（F5）でその文節だけを聞けます。"
    "良ければ右クリック →「この文節を確認済みにする」で色が消えます。\n"
    "手で直した文節は、［手直しを辞書の候補に送る →］で、まとめて辞書の候補（学習タブ）に送れます。直すたびに聞いたりはしません。")
HELP_ICON = 18       # ［？］の印の大きさ（100% のときのピクセル）
COUNTED_MAX = 5000   # 使用回数を数え終えた台詞の印を、いくつまで覚えておくか
DEFAULT_PRESETS = ("まりさ", "れいむ")
PLAYER_TIMEOUT = 60   # AquesTalkPlayer の書き出しを待つ上限（秒）


TEXT_FONTS = ("BIZ UDゴシック", "BIZ UDGothic", "Meiryo UI", "メイリオ", "Meiryo",
              "Yu Gothic UI", "Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP")
# 1行の入力欄では行の下に余白を足せないので、アンダーバーが文字枠に収まるフォントを優先する
ENTRY_FONTS = ("Meiryo UI", "メイリオ", "Meiryo", "Yu Gothic UI") + TEXT_FONTS


def pick_font(root, candidates=TEXT_FONTS) -> str:
    fams = set(tkfont.families(root))
    for f in candidates:
        if f in fams:
            return f
    return "TkDefaultFont"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"{APP_NAME} v{VERSION}")
        self.conf = self._load_conf()
        self.scale = self._clamp_scale(self.conf.get("ui_scale", 1.0))
        w, h = self._start_size()
        root.geometry(f"{w}x{h}")
        root.minsize(*self._min_size())
        icon = os.path.join(RES_DIR, "assets", "icon.png")
        if os.path.exists(icon):
            try:
                self._icon = tk.PhotoImage(file=icon)
                root.iconphoto(True, self._icon)
            except tk.TclError:
                pass

        # 書体は「名前つきフォント」にしておき、文字の大きさを変えると画面全体がいっしょに変わるようにする
        fams = {"text": pick_font(root), "entry": pick_font(root, ENTRY_FONTS)}
        self.fonts = {n: tkfont.Font(root=root, family=fams[k], size=self._fsize(sz), weight=wt)
                      for n, (k, sz, wt) in FONT_BASE.items()}
        self.f_text, self.f_entry, self.f_ui = self.fonts["text"], self.fonts["entry"], self.fonts["ui"]
        self.style = ttk.Style(root)
        self._apply_style()

        self._ensure_numbers_file()
        self.numbers = core.load_numbers(NUM_PATH)
        self.dic, broken = self._load_dict()
        self.pitch_line = tk.BooleanVar(value=self.conf.get("pitch_line", True))
        self.check_place = tk.BooleanVar(value=self.conf.get("check_location", True))
        self.shortcuts = {k: v for k, v in (self.conf.get("shortcuts") or {}).items()}
        self._bound = []
        self._hint_buttons = []      # (操作, ボタン, 文字) … ボタンにショートカットを書き添える
        self._help_icons = []        # ［？］の印（文字の大きさを変えたら描き直す）
        self._help_imgs = {}         # (大きさ, マウスが乗っているか) → 画像

        self.color_marks = tk.BooleanVar(value=self.conf.get("color_marks", True))
        self.player_path = tk.StringVar(value=self.conf.get("aquestalk_player", ""))
        self.preset_info = tk.StringVar()   # 設定タブ: プリセットを読めたかどうか
        self._preview_gen = 0      # 試聴の世代。停止や新しい試聴で古い結果を捨てる
        self._proc = None          # 書き出し中の AquesTalkPlayer
        self._wav = None           # いま再生している一時WAV（音量を変えた物）
        self._wav_raw = None       # AquesTalkPlayer が書き出したままの一時WAV（音量を変え直す元）
        self._play_until = 0.0     # 再生が終わるおよその時刻（time.monotonic）
        self.volume = core.step_volume(int(self.conf.get("volume", 100) or 0), 0)
        self.muted = bool(self.conf.get("muted", False))
        self.auto_watch = tk.BooleanVar(value=self.conf.get("auto_watch", True))
        self._away = False         # ほかのアプリに切り替えている間 True
        self._last_copied = None   # このツールが最後にクリップボードへ入れた物
        self._texts = []
        self._out_converted = ""   # 最後に［変換］した結果（手直しの有無を見るため）
        self._out_prepared = ""    # 同じく、辞書を当てる前の形（「辞書適用前に戻す」用）
        self._raw_converted = ""   # 同じく、変換に使った YMM4 の読み（「学習候補に送る」用）
        self._out_sent = None      # 最後に学習タブへ送った変換結果
        self._ap_tags: dict[str, core.Entry] = {}   # 辞書が当たった所のタグ名 → 当たった項目（タグは手直ししても文字に付いて動く）
        self._infos: list[core.PhraseInfo] = []     # 変換結果の文節ごとの状態
        self._insight_job = None
        self._script_win = None    # 台本の一覧の窓（開いていれば、変換結果が変わるたびに書き直す）
        self.phrase_colors = tk.BooleanVar(value=self.conf.get("phrase_colors", True))
        # 使用回数を数え終えた台詞の印（同じ台詞を何度変換しても1回と数えるため。新しい順に最大 COUNTED_MAX 件）
        self._counted_order: list[str] = list(self.conf.get("counted_lines") or [])[-COUNTED_MAX:]
        self._counted = set(self._counted_order)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.nb = nb
        self._build_convert(nb)
        self._build_learn(nb)
        self._build_dict(nb)
        self._build_settings(nb)

        self._build_message_bar(nb)
        self._bind_shortcuts()
        place = self._location_message()
        if broken:
            self._refresh_status([("辞書ファイルが壊れていて読み込めませんでした。", "crit"),
                                  (f"\n元のファイルは {os.path.basename(broken)} に名前を変えて残してあります。"
                                   "辞書タブの［バックアップから戻す…］で、前の状態に戻せます。", None)])
        elif self.dic.newer_format:
            self._refresh_status([("この辞書は、もっと新しい版のゆっくりアクセント辞書で作られています。", "warn"),
                                  ("\nこの版が知らない情報も消さずに残します。念のため、開く前の辞書を backup フォルダの keep に残しました。"
                                   "できれば新しい版を使ってください", None)])
        elif place:
            self._refresh_status(place)
        else:
            if self.auto_watch.get():
                self._refresh_status("YMM4 でセリフの読みをコピーして、この画面に戻ってくると、自動で貼り付けて変換し、"
                                     "結果をクリップボードに入れます。そのまま YMM4 に貼り付けてください。"
                                     f"\n（［貼り付けて変換］（{self._key_label('paste_convert')}）を押しても同じです）")
            else:
                self._refresh_status(f"YMM4 でセリフの読みをコピーして［貼り付けて変換］（{self._key_label('paste_convert')}）を押すと、"
                                     "変換した結果がクリップボードに入ります。そのまま YMM4 に貼り付けてください。")

        # Ctrl＋マウスホイールで文字の大きさを変える
        root.bind_all("<Control-MouseWheel>", lambda e: (self.set_scale(self.scale + (0.1 if e.delta > 0 else -0.1)), "break")[1])
        root.bind_all("<Control-Button-4>", lambda e: (self.set_scale(self.scale + 0.1), "break")[1])
        root.bind_all("<Control-Button-5>", lambda e: (self.set_scale(self.scale - 0.1), "break")[1])
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        # ほかのアプリ（YMM4）から戻ってきたら、新しくコピーされた読みを自動で変換する
        self._clip_seen = self._clipboard()
        root.bind_all("<FocusOut>", lambda e: root.after(80, self._check_away), add="+")
        root.bind_all("<FocusIn>", self._on_focus_in, add="+")
        if self.conf.get("accent_panel"):
            self._open_panel_at_start()

    # ── 数字の読み表 ────────────────────────────────
    def _ensure_numbers_file(self):
        """numbers.json が無い／古い形式なら、最新の既定値で作り直す（古いものは退避）。"""
        need = not os.path.exists(NUM_PATH)
        if not need:
            try:
                with open(NUM_PATH, encoding="utf-8") as f:
                    need = json.load(f).get("version", 1) < core.DEFAULT_NUMBERS["version"]
            except Exception:
                need = True
            if need:
                bak = os.path.join(BASE_DIR, "numbers_old_backup.json")
                try:
                    os.replace(NUM_PATH, bak)
                except Exception:
                    pass
        if need:
            with open(NUM_PATH, "w", encoding="utf-8") as f:
                json.dump(core.DEFAULT_NUMBERS, f, ensure_ascii=False, indent=1)

    # ── 設定 ────────────────────────────────────────
    def _load_conf(self):
        try:
            with open(CONF_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"auto_copy": True}

    def _save_conf(self):
        self.conf["auto_copy"] = bool(self.auto_copy.get())
        self.conf["color_marks"] = bool(self.color_marks.get())
        self.conf["accent_panel"] = bool(self._acc_shown)
        self.conf["aquestalk_player"] = self.player_path.get().strip()
        self.conf["voice_preset"] = self.voice.get().strip()
        self.conf["voice_presets"] = self._used_voices[:20]
        self.conf["ui_scale"] = self.scale
        self.conf["pitch_line"] = bool(self.pitch_line.get())
        self.conf["check_location"] = bool(self.check_place.get())
        self.conf["shortcuts"] = self.shortcuts
        self.conf["volume"] = self.volume
        self.conf["muted"] = self.muted
        self.conf["auto_watch"] = bool(self.auto_watch.get())
        self.conf["phrase_colors"] = bool(self.phrase_colors.get())
        self.conf["counted_lines"] = self._counted_order[-COUNTED_MAX:]
        self.conf["last_version"] = VERSION
        try:
            with open(CONF_PATH, "w", encoding="utf-8") as f:
                json.dump(self.conf, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ── 辞書の読み込みとバックアップ ──────────────
    def _load_dict(self):
        """辞書を読む。壊れていたら名前を変えて残し、空の辞書で始める（起動できないのを防ぐ）。
        戻り値: (辞書, 壊れていたファイルの退避先 or None)"""
        try:
            dic = core.Dictionary.load(DICT_PATH)
        except Exception:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            dst = os.path.join(BASE_DIR, f"accent_dict_broken_{stamp}.json")
            try:
                os.replace(DICT_PATH, dst)
            except OSError:
                dst = DICT_PATH
            return core.Dictionary(), dst
        self._backup_dict()          # 起動時に1つ写しておく（前回と同じなら写さない）
        self._keep_backups(dic)
        return dic, None

    def _keep_backups(self, dic):
        """節目の辞書を、古い順に消えない所に残す（新しい版を初めて起動する前・月の最初・新しい形式の辞書を開く前）"""
        try:
            if dic.newer_format:
                core.keep_backup(DICT_PATH, BACKUP_DIR, f"newer-{dic.file_version}")
            if self.conf.get("last_version") != VERSION:
                core.keep_backup(DICT_PATH, BACKUP_DIR, f"before-v{VERSION}")
            core.keep_backup(DICT_PATH, BACKUP_DIR, f"month-{datetime.date.today():%Y-%m}")
        except OSError:
            pass

    def _backup_dict(self):
        try:
            return core.backup_file(DICT_PATH, BACKUP_DIR, keep=BACKUP_KEEP)
        except OSError:
            return None

    # ── 置き場所の確認（起動時） ───────────────────
    def _location_message(self):
        """ZIP の中・書き込めない・同期フォルダ・Program Files で動いていたら、知らせる文を返す（なければ None）"""
        try:
            with tempfile.NamedTemporaryFile(dir=BASE_DIR, prefix=".write_test_"):
                writable = True
        except OSError:
            writable = False
        found = core.check_location(BASE_DIR, dict(os.environ), tempfile.gettempdir(), writable)
        if not self.check_place.get():
            found = [f for f in found if f[0] == "crit"]       # 赤（消える・保存されない）は止めても知らせる
        if not found:
            return None
        level, kind = found[0]
        home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        good = os.path.join(home, "yukkuri-accent")
        if kind == "zip":
            head = "ZIP を展開しないまま開いているようです（一時フォルダで動いています）。"
            body = ("このままだと、閉じたときに辞書や設定が消えます。ZIP を右クリック →［すべて展開］して、"
                    "展開したフォルダの yukkuri-accent.exe を起動してください。")
        elif kind == "readonly":
            head = "このフォルダには書き込めないため、辞書や設定が保存されません。"
            body = f"書き込めるフォルダ（例：{good}）に、フォルダごと移してください。"
        elif kind == "programfiles":
            head = "「Program Files」の中で動いています。"
            body = f"辞書や設定が保存されないことがあります。{good} などに、フォルダごと移すのがおすすめです。"
        else:
            head = f"{kind.split(':', 1)[1]} の同期フォルダの中で動いています。"
            body = (f"古い設定が残ったり、別の場所のファイルと入れ替わったりすることがあります。"
                    f"{good} など同期されない場所に、フォルダごと移すのがおすすめです。")
        tail = "（この確認は設定タブで止められます）" if level == "warn" else ""
        return [(head, level), ("\n" + body + tail, None)]

    # ── 文字の大きさ ──────────────────────────────
    @staticmethod
    def _clamp_scale(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 1.0
        return round(min(max(v, SCALE_MIN), SCALE_MAX), 1)

    def _fsize(self, base):
        return max(6, round(base * self.scale))

    def _sc(self, v):
        """100% のときの長さ（ピクセル）を、今の文字の大きさに合わせる"""
        return round(v * self.scale)

    def _start_size(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        return min(self._sc(WIN_W), sw - 40), min(self._sc(WIN_H), sh - 80)

    def _min_size(self):
        return min(self._sc(820), self.root.winfo_screenwidth() - 40), min(self._sc(600), self.root.winfo_screenheight() - 80)

    def _apply_style(self):
        st = self.style
        st.configure(".", font=self.fonts["ui"])
        st.configure("Treeview", font=self.fonts["tree"], rowheight=self._sc(26))
        st.configure("Treeview.Heading", font=self.fonts["head"])
        st.configure("Big.TButton", font=self.fonts["big"], padding=(self._sc(12), self._sc(6)))

    def set_scale(self, v):
        """文字の大きさを変える（80%〜200%）。ウィンドウも同じ割合で大きく／小さくする"""
        new = self._clamp_scale(v)
        if new == self.scale:
            return
        ratio = new / self.scale
        self.scale = new
        for n, (_, sz, _) in FONT_BASE.items():
            self.fonts[n].configure(size=self._fsize(sz))
        self._apply_style()
        if hasattr(self, "acc_cv"):
            self.acc_cv.configure(height=self._sc(ACC_CANVAS_H))
        root = self.root
        root.minsize(*self._min_size())
        root.update_idletasks()
        if root.state() == "normal" and root.winfo_ismapped():
            w, h = root.winfo_width(), root.winfo_height()
            nw = min(max(round(w * ratio), self._min_size()[0]), root.winfo_screenwidth() - 40)
            nh = min(max(round(h * ratio), self._min_size()[1]), root.winfo_screenheight() - 80)
            self._acc_added = round(self._acc_added * ratio)
            root.geometry(f"{nw}x{nh}")
        if hasattr(self, "scale_var"):
            self.scale_var.set(round(new * 100))
        self._draw_accent_panel()
        for cv in self._help_icons:
            self._draw_help(cv)
        self._save_conf()
        self._refresh_status(f"文字の大きさ：{round(new * 100)}%")

    # ── ショートカット ────────────────────────────
    def _key(self, aid):
        default = next(d for a, _, d in SHORTCUTS if a == aid)
        return self.shortcuts.get(aid, default)

    def _key_label(self, aid):
        return core.shortcut_label(self._key(aid))

    def _bind_shortcuts(self):
        """割り当てたキーを結び直す。入力欄にも直接結んで、入力欄の既定の動き（改行など）より先に効かせる"""
        for seq in self._bound:
            self.root.unbind_all(seq)
            for w in self._texts:
                w.unbind(seq)
        self._bound = []
        for aid, _, _ in SHORTCUTS:
            for seq in core.shortcut_variants(self._key(aid)):
                h = (lambda e, a=aid: (self._run_action(a), "break")[1])
                self.root.bind_all(seq, h)
                for w in self._texts:
                    w.bind(seq, h)
                self._bound.append(seq)
        for aid, btn, text in self._hint_buttons:
            key = self._key(aid)
            btn.configure(text=f"{text}（{core.shortcut_label(key)}）" if key else text)
        if hasattr(self, "btn_acc"):
            self.btn_acc.configure(text=self._acc_btn_text())
        if hasattr(self, "keys_tv"):
            self._fill_keys()

    def _hint(self, aid, btn, text):
        """ボタンにショートカットを書き添える（キーを変えると書き直す）"""
        self._hint_buttons.append((aid, btn, text))
        key = self._key(aid)
        btn.configure(text=f"{text}（{core.shortcut_label(key)}）" if key else text)
        return btn

    def _run_action(self, aid):
        acts = {
            "paste_convert": self.paste_and_convert, "convert": self.do_convert, "copy": self.copy_output,
            "recheck": self.recheck, "preview": self.preview, "stop": self.stop_preview,
            "mute": self.toggle_mute,
            "vol_down": lambda: self.change_volume(-1), "vol_up": lambda: self.change_volume(1),
            "accent_panel": self.toggle_accent_panel,
            "next_unchecked": lambda: self.goto_unchecked(False),
            "prev_unchecked": lambda: self.goto_unchecked(True),
            "acc_left": lambda: self.move_accent(-1), "acc_right": lambda: self.move_accent(1),
            "acc_here": self.accent_at_cursor, "acc_clear": self.clear_accent,
            "send_learn": self.send_manual,
            "font_up": lambda: self.set_scale(self.scale + 0.1),
            "font_down": lambda: self.set_scale(self.scale - 0.1),
            "font_reset": lambda: self.set_scale(1.0),
        }
        acts[aid]()

    def on_close(self):
        if not self._confirm_discard():
            return
        self.stop_preview()
        self._remove_wav()
        self.save_dict()
        self._save_conf()
        self.root.destroy()

    def _confirm_discard(self) -> bool:
        """辞書に入っていない変更があれば、破棄してよいか聞く。閉じてよければ True。"""
        st = core.unregistered_changes(self.out_text.get("1.0", "end-1c"), self._out_converted,
                                       self._out_sent, self.cands)
        if not st["edited"] and not st["pending"]:
            return True
        lines = []
        if st["pending"]:
            lines.append(f"・学習タブに、登録にチェックしたまま辞書に入っていない候補が {st['pending']} 件あります")
        if st["edited"]:
            lines.append("・変換結果の手直しを、まだ学習タブへ送っていません")
        ok = messagebox.askyesno(
            APP_NAME,
            "現在の変更が辞書登録されていません。\n破棄しても宜しいですか？\n\n" + "\n".join(lines)
            + "\n\n［いいえ］を押すと、終了せずに元の画面へ戻ります。",
            icon="warning", default="no", parent=self.root)
        if not ok:
            # 残っている所を開いておく（学習タブの候補を優先）
            self.nb.select(1 if st["pending"] else 0)
            self._refresh_status([("終了をやめました。", None),
                                  ("学習タブで［チェックしたものを辞書に登録］を押すと、辞書に入ります" if st["pending"]
                                   else "［この手直しを学習タブへ送る →］から辞書に登録できます", "warn")])
        return ok

    def save_dict(self):
        try:
            self.dic.save(DICT_PATH)
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"辞書を保存できませんでした。\n{ex}")

    # ── メッセージ欄 ────────────────────────────────
    def _build_message_bar(self, nb):
        """ウィンドウ下のメッセージ欄。3行分の高さを最初から取っておき、長い案内でも大きさが変わらない"""
        st = MSG_STYLE["info"]
        box = tk.Frame(self.root, bg=st["bg"], highlightthickness=1, highlightbackground="#c9ced6")
        box.pack(fill="x", side="bottom", before=nb, padx=8, pady=(6, 8))   # ノートより先に場所を取る
        bar = tk.Frame(box, width=6, bg=st["bar"])
        bar.pack(side="left", fill="y")
        self.dict_info = tk.StringVar()
        lab = tk.Label(box, textvariable=self.dict_info, font=self.fonts["small"], fg="#666", bg=st["bg"], anchor="ne")
        lab.pack(side="right", anchor="n", padx=8, pady=5)      # 右端に先に置く（メッセージに押し出されないように）
        t = tk.Text(box, height=MSG_LINES, width=1, wrap="char", font=self.fonts["ui_b"], relief="flat", bd=0,
                    padx=10, pady=5, bg=st["bg"], fg=st["fg"], cursor="arrow", takefocus=0,
                    highlightthickness=0, spacing1=1, spacing3=1)
        t.pack(side="left", fill="x", expand=True)
        for lv, c in MSG_STYLE.items():
            t.tag_configure(lv, foreground=c["fg"])
        t.configure(state="disabled")
        self._msg_box, self._msg_bar, self._msg_text, self._msg_dict = box, bar, t, lab
        self.status = tk.StringVar()     # 表示中のメッセージ（文字だけ）

    def _refresh_status(self, extra="", level=None):
        """メッセージ欄を書き換える。
        extra: 文字列、または [(文字列, "warn"/"crit"/None), ...]（要点だけ色を付ける）。空なら辞書の件数だけ更新。
        level: 欄全体の色。省略すると、中で一番重いもの（なければ info）"""
        if not hasattr(self, "_msg_text"):
            return
        self.dict_info.set(f"辞書：{len(self.dic.entries)}件（{os.path.basename(DICT_PATH)}）")
        if not extra:
            return
        parts = [(extra, None)] if isinstance(extra, str) else list(extra)
        if level is None:
            levels = {lv for _, lv in parts}
            level = "crit" if "crit" in levels else "warn" if "warn" in levels else "info"
        st = MSG_STYLE[level]
        for w in (self._msg_box, self._msg_text, self._msg_dict):
            w.configure(bg=st["bg"])
        self._msg_bar.configure(bg=st["bar"])
        t = self._msg_text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for text, lv in parts:
            t.insert("end", text, (lv,) if lv else ())
        t.configure(state="disabled")
        self.status.set("".join(x for x, _ in parts))

    def _count_parts(self, n_err, n_warn):
        """「エラー n ／ 注意 m」を、数があるときだけ色付きで"""
        return [(f"エラー {n_err}", "crit" if n_err else None), (" ／ ", None),
                (f"注意 {n_warn}", "warn" if n_warn else None)]

    def _text(self, parent, height):
        frm = ttk.Frame(parent)
        t = tk.Text(frm, height=height, wrap="char", font=self.f_text, undo=True,
                    padx=8, pady=6, relief="solid", borderwidth=1, spacing1=2, spacing3=4)
        sb = ttk.Scrollbar(frm, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        # 記号の色分け。BIZ UDゴシックの「_」は線が細すぎて消えかけて見えるので、
        # 線の太いフォントの太字で描く
        t.tag_configure("mk_acc", foreground=COL_MK_ACCENT, font=self.fonts["text_b"])
        t.tag_configure("mk_sep", foreground=COL_MK_SEP)
        t.tag_configure("mk_dv", foreground=COL_MK_DEVOICE, font=self.fonts["entry_b"])
        t.bind("<<Modified>>", lambda e, w=t: self._on_modified(w))
        self._texts.append(t)
        return frm, t

    def _repaint_all(self):
        for t in self._texts:
            self._paint_marks(t)

    def _on_modified(self, t):
        if t.edit_modified():
            t.edit_modified(False)
            t.after_idle(lambda: self._fix_marks(t))
            t.after_idle(lambda: self._paint_marks(t))
            if t is getattr(self, "out_text", None):
                t.after_idle(self._draw_accent_panel)
                self._schedule_insight()

    def _fix_marks(self, t):
        """全角の ’ ＿ ／ などを、打ったそばから AquesTalk の形（半角）に直す。YMM4 は全角を受け付けないため"""
        s = t.get("1.0", "end-1c")
        fixes = core.mark_fixes(s)
        if not fixes:
            return
        shown = "、".join(dict.fromkeys(f"{s[i]}→{ch}" for i, ch in fixes))
        for i, ch in fixes:
            idx = f"1.0+{i}c"
            tags = [g for g in t.tag_names(idx) if g != "sel"]
            t.delete(idx)
            t.insert(idx, ch, tags)
        self._refresh_status([("記号を YMM4（AquesTalk）で使える形に直しました：", None), (shown, "warn")])

    def _paint_marks(self, t):
        for tag in ("mk_acc", "mk_sep", "mk_dv"):
            t.tag_remove(tag, "1.0", "end")
        if not self.color_marks.get():
            return
        s = t.get("1.0", "end-1c")
        for i, c in enumerate(s):
            tag = None
            if c in "'’＇":
                tag = "mk_acc"
            elif c in "/,+;／，＋；":
                tag = "mk_sep"
            elif c in "_＿":
                tag = "mk_dv"
            if tag:
                t.tag_add(tag, f"1.0+{i}c")

    # ── タブ1: 変換 ─────────────────────────────────
    def _build_convert(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="　変換　")

        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="① YMM4の読み（初期状態）を貼り付け").pack(side="left")
        ttk.Button(top, text="クリア", command=lambda: self.in_text.delete("1.0", "end")).pack(side="right")
        ttk.Button(top, text="ファイルを開く…", command=self.open_script_file).pack(side="right", padx=(0, 6))
        self._hint("paste_convert", ttk.Button(top, command=self.paste_and_convert), "貼り付けて変換").pack(side="right", padx=6)
        frm, self.in_text = self._text(tab, 5)
        frm.pack(fill="both", expand=True, pady=(4, 8))

        mid = ttk.Frame(tab)
        mid.pack(fill="x")
        self._hint("convert", ttk.Button(mid, style="Big.TButton", command=self.do_convert), "変換 ▼").pack(side="left")
        self.auto_copy = tk.BooleanVar(value=self.conf.get("auto_copy", True))
        ttk.Checkbutton(mid, text="変換したら自動でコピー", variable=self.auto_copy).pack(side="left", padx=12)
        ttk.Checkbutton(mid, text="記号を色分け", variable=self.color_marks,
                        command=self._repaint_all).pack(side="left")
        ttk.Checkbutton(mid, text="戻ってきたら自動で貼り付けて変換", variable=self.auto_watch,
                        command=self._save_conf).pack(side="left", padx=(12, 0))
        self._help(mid, "戻ってきたら自動で貼り付けて変換",
                   "YMM4 で読みをコピーして、このツールの画面に戻ってくると、ボタンを押さなくても貼り付けて変換します。\n\n"
                   "・変換タブを開いているときだけ動きます\n"
                   "・漢字を含む文章や、このツールが自分でコピーした結果には反応しません\n"
                   "・変換結果を手直ししている途中は、手直しを消さないよう、自動では変換しません\n\n"
                   "自分のタイミングで変換したいときは、チェックを外して［貼り付けて変換］を使ってください。").pack(side="left", padx=4)
        self.btn_acc = ttk.Button(mid, command=self.toggle_accent_panel)
        self.btn_acc.pack(side="right")
        self._build_accent_panel(tab, mid)

        lab = ttk.Frame(tab)
        lab.pack(fill="x", pady=(10, 0))
        ttk.Label(lab, text="② 変換結果（ここで手直しもできます）").pack(side="left")
        tk.Label(lab, text=" 辞書で置き換えた所 ", bg=COL_APPLIED, fg="black", font=self.f_ui).pack(side="right")
        tk.Label(lab, text=" 注意 ", bg=COL_WARN, fg="black", font=self.f_ui).pack(side="right", padx=4)
        tk.Label(lab, text=" エラー ", bg=COL_ERROR, fg="black", font=self.f_ui).pack(side="right")
        tk.Label(lab, text=" 手直し ", bg=COL_MANUAL, fg="black", font=self.f_ui).pack(side="right", padx=(0, 4))
        tk.Label(lab, text=" 未確認 ", bg=COL_UNCHECKED, fg="black", font=self.f_ui).pack(side="right", padx=4)
        frm, self.out_text = self._text(tab, 5)
        self.out_text.bind("<Button-3>", self._out_right_click)
        frm.pack(fill="both", expand=True, pady=(4, 6))
        # 文節の状態の色（いちばん下）→ 辞書で置き換えた所 → 注意 → エラー → 選択 の順に上へ重ねる
        self.out_text.tag_configure("ph_unchecked", background=COL_UNCHECKED)
        self.out_text.tag_configure("ph_manual", background=COL_MANUAL)
        try:
            self.out_text.tag_configure("ph_risky", underline=True, underlinefg=COL_RISKY_LINE)
        except tk.TclError:      # 下線の色を変えられない古い Tk
            self.out_text.tag_configure("ph_risky", underline=True)
        self.out_text.tag_configure("applied", background=COL_APPLIED)
        self.out_text.tag_configure("warn", background=COL_WARN)
        self.out_text.tag_configure("error", background=COL_ERROR)
        self.out_text.tag_raise("sel")
        self.out_text.bind("<ButtonRelease-1>", self._out_click, add="+")

        # 今回の変換で何が起きたか（使われた辞書・未確認の文節）
        ins = ttk.Frame(tab)
        ins.pack(fill="x", pady=(0, 6))
        self.insight = tk.StringVar(value="［変換］すると、使われた辞書と、まだ確かめていない文節の数をここに出します")
        self._help(ins, "文節の色と「今回の変換」", PHRASE_COLOR_HELP).pack(side="left", padx=(0, 6))
        ttk.Label(ins, textvariable=self.insight).pack(side="left")
        self._hint("next_unchecked", ttk.Button(ins, command=lambda: self.goto_unchecked(False)),
                   "次の未確認へ ▶").pack(side="right", padx=6)
        ttk.Button(ins, text="使われた辞書…", command=self.show_used_entries).pack(side="right")
        ttk.Button(ins, text="台本の一覧…", command=self.show_script).pack(side="right", padx=(0, 6))

        bot = ttk.Frame(tab)
        bot.pack(fill="x")
        self._hint("copy", ttk.Button(bot, style="Big.TButton", command=self.copy_output), "コピー").pack(side="left")
        self._hint("recheck", ttk.Button(bot, command=self.recheck), "再チェック").pack(side="left", padx=6)
        self._hint("send_learn", ttk.Button(bot, command=self.send_manual), "手直しを辞書の候補に送る →").pack(side="right")

        pv = ttk.Frame(tab)
        pv.pack(fill="x", pady=(8, 0))
        # よく使うので、コピーと同じ大きなボタンにする
        self.btn_play = self._hint("preview", ttk.Button(pv, style="Big.TButton", command=self.preview), "▶ 試聴")
        self.btn_play.pack(side="left")
        self.btn_stop = self._hint("stop", ttk.Button(pv, style="Big.TButton", command=self.stop_preview), "■ 停止")
        self.btn_stop.pack(side="left", padx=(4, 12))
        ttk.Label(pv, text="音量").pack(side="left")
        self.btn_vol_down = self._hint("vol_down", ttk.Button(pv, width=3, command=lambda: self.change_volume(-1)), "▼")
        self.btn_vol_down.pack(side="left", padx=(4, 0))
        self.vol_label = tk.Label(pv, width=5, font=self.fonts["big"], fg="black")
        self.vol_label.pack(side="left")
        self.btn_vol_up = self._hint("vol_up", ttk.Button(pv, width=3, command=lambda: self.change_volume(1)), "▲")
        self.btn_vol_up.pack(side="left")
        self.btn_mute = self._hint("mute", ttk.Button(pv, command=self.toggle_mute), "消音")
        self.btn_mute.pack(side="left", padx=(4, 12))
        self._show_volume()
        ttk.Label(pv, text="声（プリセット）:").pack(side="left")
        # 候補 = このツールで再生できた名前（新しい順）＋ AquesTalkPlayer.preset にあるプリセット
        self._used_voices = list(self.conf.get("voice_presets") or DEFAULT_PRESETS)
        self._player_presets: dict[str, bool] = {}   # プリセット名 → 棒読みか
        last = self.conf.get("voice_preset", self._used_voices[0] if self._used_voices else "")
        self.voice = tk.StringVar(value=last)
        self.voice_box = ttk.Combobox(pv, textvariable=self.voice, width=12, font=self.f_ui,
                                      postcommand=self._refresh_voice_list)
        self.voice_box.pack(side="left", padx=4)
        self.voice_box.bind("<<ComboboxSelected>>", lambda e: self._warn_bouyomi())
        self._refresh_voice_list()
        self.btn_open_player = ttk.Button(pv, text="AquesTalkPlayer を開く", command=self.open_player)
        self.btn_open_player.pack(side="right")
        if not IS_WINDOWS:
            ttk.Label(tab, text="試聴は Windows 専用です（AquesTalkPlayer が Windows 用のため）",
                      foreground="#666").pack(anchor="w")
            for w in (self.btn_play, self.btn_stop, self.voice_box, self.btn_open_player,
                      self.btn_vol_down, self.btn_vol_up, self.btn_mute):
                w.state(["disabled"])

        ttk.Label(tab, text="チェック結果（クリックすると該当箇所を選択）").pack(anchor="w", pady=(10, 2))
        self.issue_list = tk.Listbox(tab, height=4, font=self.f_ui, activestyle="none")
        self.issue_list.pack(fill="x")
        self.issue_list.bind("<<ListboxSelect>>", self._on_issue_click)
        self._issues: list[core.Issue] = []

    def paste_and_convert(self):
        try:
            s = self.root.clipboard_get()
        except tk.TclError:
            s = ""
        self.in_text.delete("1.0", "end")
        self.in_text.insert("1.0", s)
        self.do_convert()

    def do_convert(self, auto=False):
        raw = self.in_text.get("1.0", "end-1c")
        res = core.convert(raw, self.dic, self.numbers)
        self.out_text.delete("1.0", "end")
        self.out_text.insert("1.0", res.text)
        self._out_converted = res.text
        self._out_prepared = core.prepare(raw, self.numbers)
        self._raw_converted = raw
        for tag in self._ap_tags:
            self.out_text.tag_delete(tag)
        self._ap_tags = {}
        self.out_text.tag_remove("checked", "1.0", "end")
        for i, a in enumerate(res.applied):
            tag = f"ap{i}"     # 1か所ごとに名前を付けて、どの項目が当たったかを後から引けるようにする
            self._ap_tags[tag] = a.entry
            self.out_text.tag_add("applied", f"1.0+{a.start}c", f"1.0+{a.end}c")
            self.out_text.tag_add(tag, f"1.0+{a.start}c", f"1.0+{a.end}c")
        self._update_insight()
        self._show_issues(res.issues)
        if self.auto_copy.get() and res.text:
            self._copy(res.text)
        before = set(self._counted)
        if core.count_usage(res.text, res.applied, self._counted):
            self._counted_order += [k for k in self._counted if k not in before]
            self._fill_dict()   # 使用回数の表示を更新
        n_err = sum(i.level == "error" for i in res.issues)
        n_warn = len(res.issues) - n_err
        head = "コピーされていた読みを自動で貼り付けて変換しました" if auto else "変換しました"
        parts = [(f"{head}：辞書で置き換え {len(res.applied)} か所 ／ ", None)] + self._count_parts(n_err, n_warn)
        if self.auto_copy.get() and res.text:
            parts.append(("　— コピーしました", None))
        if n_err:
            parts.append(("\n赤い所は YMM4 で正しく読まれません。下のチェック結果を見て直してください", "crit"))
        elif n_warn:
            parts.append(("\n橙の所を確かめてください（下のチェック結果をクリックすると選択します）", "warn"))
        self._refresh_status(parts)
        return "break"

    def recheck(self):
        s = self.out_text.get("1.0", "end-1c")
        norm = core.normalize(s)
        if norm != s:
            self.out_text.delete("1.0", "end")
            self.out_text.insert("1.0", norm)
        self._show_issues(core.validate(norm))
        n_err = sum(i.level == "error" for i in self._issues)
        self._refresh_status([("再チェック：", None)] + self._count_parts(n_err, len(self._issues) - n_err))

    def _show_issues(self, issues):
        self._issues = issues
        for tag in ("warn", "error"):
            self.out_text.tag_remove(tag, "1.0", "end")
        self.issue_list.delete(0, "end")
        for i in issues:
            self.out_text.tag_add(i.level, f"1.0+{i.start}c", f"1.0+{i.end}c")
            mark = "✖ エラー" if i.level == "error" else "△ 注意"
            self.issue_list.insert("end", f"{mark}　{i.start + 1}文字目: {i.msg}")
            self.issue_list.itemconfig("end", fg="#b00000" if i.level == "error" else "#a05a00")
        if not issues:
            self.issue_list.insert("end", "問題は見つかりませんでした。")
            self.issue_list.itemconfig("end", fg="#2a7a2a")

    def _on_issue_click(self, _e):
        sel = self.issue_list.curselection()
        if not sel or sel[0] >= len(self._issues):
            return
        i = self._issues[sel[0]]
        self.out_text.tag_remove("sel", "1.0", "end")
        self.out_text.tag_add("sel", f"1.0+{i.start}c", f"1.0+{i.end}c")
        self.out_text.see(f"1.0+{i.start}c")
        self.out_text.focus_set()

    def _copy(self, s):
        self.root.clipboard_clear()
        self.root.clipboard_append(s)
        self._last_copied = s
        self._clip_seen = s

    def _clipboard(self):
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ""

    def _check_away(self):
        """フォーカスがこのツールのどの画面にも無ければ、ほかのアプリに切り替えたとみなす"""
        try:
            self._away = self.root.focus_get() is None
        except (KeyError, tk.TclError):
            pass

    def _on_focus_in(self, _e=None):
        if not self._away:
            return
        self._away = False
        self.root.after(120, self._auto_paste)

    def _auto_paste(self):
        """YMM4 などから戻ってきたとき、新しくコピーされた読みがあれば貼り付けて変換する"""
        if not self.auto_watch.get():
            return
        try:
            if self.nb.index(self.nb.select()) != 0:   # 変換タブを開いているときだけ
                return
        except tk.TclError:
            return
        clip = self._clipboard()
        act = core.auto_convert_action(clip, self._clip_seen, self.in_text.get("1.0", "end-1c"),
                                       self._last_copied, self.out_text.get("1.0", "end-1c"),
                                       self._out_converted)
        self._clip_seen = clip
        if act == "edited":
            self._refresh_status([("新しい読みがコピーされていますが、変換結果を手直し中なので自動では変換しませんでした。", "warn"),
                                  (f"\n変換するときは［貼り付けて変換］（{self._key_label('paste_convert')}）を押してください", None)])
        elif act == "convert":
            self.in_text.delete("1.0", "end")
            self.in_text.insert("1.0", clip)
            self.do_convert(auto=True)

    def copy_output(self):
        s = self.out_text.get("1.0", "end-1c")
        if s:
            norm = core.normalize(s)
            self._copy(norm)
            n_err = sum(i.level == "error" for i in core.validate(norm))
            if n_err:
                self._refresh_status([("コピーしました。", None),
                                      (f"ただし、エラーが {n_err} か所残っています（YMM4 で正しく読まれません）", "crit")])
            else:
                self._refresh_status("コピーしました")
        return "break"

    # ── アクセント編集（文節ごとの表示とボタン） ─────
    def _build_accent_panel(self, tab, anchor):
        self._acc_shown = False
        self._acc_added = 0          # 開いたときに広げたウィンドウの高さ
        self._acc_anchor = anchor
        ap = ttk.Frame(tab)
        hdr = ttk.Frame(ap)
        hdr.pack(fill="x")
        cb = ttk.Checkbutton(hdr, text="高低の線を表示", variable=self.pitch_line,
                             command=lambda: (self._draw_accent_panel(), self._save_conf()))
        cb.pack(side="right", anchor="n")
        lbl = ttk.Label(hdr, text="下の変換結果を文節ごとに表示しています。文字の上のボタンで、その文字にアクセント（'）を付け外しします"
                                  "（1つの文節に1か所）。線は音の高さで、上が高く下が低く、赤はアクセントで下がる所です。"
                                  "線の点はつまんで上下に動かせます（クリックで高低を入れ替え）。",
                        foreground="#666", justify="left")
        lbl.pack(side="left", fill="x", expand=True)
        hdr.bind("<Configure>", lambda e: lbl.configure(wraplength=max(e.width - cb.winfo_width() - 16, 200)))
        body = ttk.Frame(ap)
        body.pack(fill="x", pady=(2, 0))
        cv = tk.Canvas(body, height=self._sc(ACC_CANVAS_H), bg="white", highlightthickness=1, highlightbackground="#b8bec8")
        sb = ttk.Scrollbar(body, command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        cv.bind("<Configure>", lambda e: self._draw_accent_panel())
        cv.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        cv.bind("<Button-4>", lambda e: cv.yview_scroll(-1, "units"))
        cv.bind("<Button-5>", lambda e: cv.yview_scroll(1, "units"))
        self.acc_panel, self.acc_cv = ap, cv
        self.btn_acc.configure(text=self._acc_btn_text())
        # 高低の線の点は、つまんで上下に動かせる（離した所の高さになるようにアクセントを置き直す）
        self._dot_info, self._drag = {}, None
        cv.tag_bind("dot", "<ButtonPress-1>", self._dot_press)
        cv.tag_bind("dot", "<B1-Motion>", self._dot_motion)
        cv.tag_bind("dot", "<ButtonRelease-1>", self._dot_release)
        cv.tag_bind("dot", "<Enter>", lambda e: cv.configure(cursor="sb_v_double_arrow"))
        cv.tag_bind("dot", "<Leave>", lambda e: self._drag or cv.configure(cursor=""))
        cv.bind("<Button-3>", self._acc_right_click)

    def _acc_btn_text(self):
        key = self._key("accent_panel")
        text = "アクセント編集 " + ("▲" if self._acc_shown else "▼")
        return f"{text}（{core.shortcut_label(key)}）" if key else text

    def _open_panel_at_start(self):
        """起動時に開いておく。ウィンドウがまだ画面に出ていないので大きさは測れない（1ピクセルと返る）。
        既定の大きさにパネルの分を足して始める"""
        root = self.root
        self.acc_panel.pack(fill="x", after=self._acc_anchor, pady=(8, 0))
        root.update_idletasks()
        w, h = self._start_size()
        new_h = min(h + self.acc_panel.winfo_reqheight() + 8, max(h, root.winfo_screenheight() - 80))
        self._acc_added = new_h - h
        root.geometry(f"{w}x{new_h}")
        self._acc_shown = True
        self.btn_acc.configure(text=self._acc_btn_text())

    def toggle_accent_panel(self, show=None):
        show = (not self._acc_shown) if show is None else show
        if show == self._acc_shown:
            return
        root = self.root
        root.update_idletasks()
        w, h = root.winfo_width(), root.winfo_height()
        # 最大化中や、まだ画面に出ていないとき（大きさが測れない）は、ウィンドウの大きさを変えない
        resizable = root.state() == "normal" and root.winfo_ismapped() and h > 100
        if show:
            self.acc_panel.pack(fill="x", after=self._acc_anchor, pady=(8, 0))
            root.update_idletasks()
            if resizable:
                # パネルの分だけウィンドウを縦に広げる（画面に収まる範囲で）
                new_h = min(h + self.acc_panel.winfo_reqheight() + 8, max(h, root.winfo_screenheight() - 80))
                self._acc_added = new_h - h
                root.geometry(f"{w}x{new_h}")
        else:
            self.acc_panel.pack_forget()
            if resizable and self._acc_added:
                root.geometry(f"{w}x{max(h - self._acc_added, 200)}")
            self._acc_added = 0
        self._acc_shown = show
        self.btn_acc.configure(text=self._acc_btn_text())
        self._draw_accent_panel()

    def _draw_accent_panel(self):
        if not getattr(self, "_acc_shown", False):
            return
        cv = self.acc_cv
        top = cv.yview()[0]
        cv.delete("all")
        s = self.out_text.get("1.0", "end-1c")
        sc = self._sc
        W = max(cv.winfo_width(), 300) - sc(12)
        if not s.strip():
            cv.create_text(sc(12), sc(14), anchor="nw", fill="#888", font=self.fonts["ui"],
                           text="変換すると、ここに文節ごとに表示されます。")
            cv.configure(scrollregion=(0, 0, W, sc(60)))
            return
        pitch = self.pitch_line.get()
        fa, fab, fas = self.fonts["acc"], self.fonts["acc_b"], self.fonts["acc_s"]
        BTN, X0, MINW, PAD = sc(14), sc(10), sc(18), sc(4)
        y_hi, y_lo = BTN + sc(10), BTN + sc(22)         # 高低の線（ボタンの上端から）
        ty = BTN + (sc(40) if pitch else sc(20))        # 文字の中心
        ROW = ty + sc(22)                               # 1行の高さ
        R, LW = max(3, sc(4)), max(1, sc(2))            # 線の点の大きさ・太さ（点はつまめる大きさに）
        x, y = X0, sc(8)
        high_next = False                               # 「;」の次の文節は高く始まる
        self._dot_info = {}

        def disp_of(u):
            d = u.text.lstrip("_")
            if d.startswith("<") and len(d) > 14:
                d = d[:13] + "…>"
            return d

        for idx, it in enumerate(core.split_phrases(s)):
            if isinstance(it, core.Sep):
                high_next = ";" in it.text
                if it.text == "\n":
                    x, y = X0, y + ROW + sc(6)
                    continue
                sw = fa.measure(it.text) + sc(6)
                if x + sw > W:
                    x, y = X0, y + ROW
                cv.create_text(x + sw / 2, y + ty, text=it.text, fill=COL_MK_SEP, font=fa)
                x += sw
                continue
            hs = high_next
            pat = core.pitch_pattern(it, hs) if pitch else None
            high_next = False
            # 文節はなるべく途中で折り返さず、まるごと次の行へ送る
            fonts = [fas if u.text.startswith("<") else fab for u in it.units]
            total = sum(max(f.measure(disp_of(u)), MINW) + PAD for f, u in zip(fonts, it.units))
            if x > X0 and x + total > W and total <= W - X0:
                x, y = X0, y + ROW
            seg_x = x
            prev = None                                 # 直前の拍の点 (x, 行のy, 高低, 点のy)
            for k, u in enumerate(it.units):
                accented = k in it.accents
                disp = disp_of(u)
                font = fas if disp.startswith("<") else (fab if accented else fa)
                uw = max(font.measure(disp), MINW) + PAD
                if x + uw > W and x > seg_x:
                    self._acc_bg(seg_x, x, y, ROW, f"p{idx}")
                    x = seg_x = X0
                    y += ROW
                    prev = None
                cx = x + uw / 2
                color = (COL_MK_ACCENT if accented else COL_MK_DEVOICE if u.devoiced
                         else "#222" if u.can_accent else "#8a8f98")
                tag = f"u{idx}_{k}"
                cv.create_text(cx, y + ty, text=disp, fill=color, font=font, tags=(tag, f"p{idx}"))
                if u.can_accent:
                    cv.create_rectangle(cx - BTN / 2, y + sc(4), cx + BTN / 2, y + sc(4) + BTN,
                                        fill=COL_MK_ACCENT if accented else "#eef1f6",
                                        outline=COL_MK_ACCENT if accented else "#9aa3b2",
                                        tags=(tag, "btn", f"b{idx}_{k}", f"p{idx}"))
                    cv.tag_bind(tag, "<Button-1>", lambda e, i=idx, k=k: self._on_accent_click(i, k))
                    cv.tag_bind(tag, "<Enter>", lambda e, t=f"b{idx}_{k}", a=accented: self._acc_hover(t, a, True))
                    cv.tag_bind(tag, "<Leave>", lambda e, t=f"b{idx}_{k}", a=accented: self._acc_hover(t, a, False))
                if pat is not None:
                    lv = pat[k]
                    if lv is None:
                        prev = None                     # タグなどで線を切る
                    else:
                        py = y + (y_hi if lv else y_lo)
                        if prev and prev[1] == y:
                            drop = prev[2] == 1 and lv == 0     # アクセントで下がる所は赤
                            cv.create_line(prev[0], prev[3], cx, py, width=LW + (1 if drop else 0),
                                           fill=COL_MK_ACCENT if drop else COL_PITCH, tags=("pitch", f"p{idx}"))
                        dtag = f"d{idx}_{k}"
                        cv.create_oval(cx - R, py - R, cx + R, py + R, fill=COL_PITCH, outline="white",
                                       tags=("dot", dtag, f"p{idx}"))
                        self._dot_info[dtag] = (idx, k, y + y_hi, y + y_lo, hs, lv)
                        prev = (cx, y, lv, py)
                x += uw
            self._acc_bg(seg_x, x, y, ROW, f"p{idx}")
            x += sc(2)
        cv.tag_raise("dot")
        cv.configure(scrollregion=(0, 0, W, y + ROW + sc(4)))
        cv.yview_moveto(top)

    # ── 文節の右クリック（変換直後に戻す・辞書適用前に戻す・学習候補に送る） ──
    def _acc_right_click(self, e):
        cv = self.acc_cv
        x, y = cv.canvasx(e.x), cv.canvasy(e.y)
        for item in reversed(cv.find_overlapping(x - 2, y - 2, x + 2, y + 2)):
            ptag = next((t for t in cv.gettags(item) if re.fullmatch(r"p\d+", t)), None)
            if ptag:
                items = core.split_phrases(self.out_text.get("1.0", "end-1c"))
                i = int(ptag[1:])
                if i < len(items) and isinstance(items[i], core.Phrase):
                    self._phrase_menu(e, items[i])
                return

    def _out_right_click(self, e):
        t = self.out_text
        idx = t.index(f"@{e.x},{e.y}")
        pos = len(t.get("1.0", idx))
        phrases = [p for p in core.split_phrases(t.get("1.0", "end-1c")) if isinstance(p, core.Phrase)]
        hit = [p for p in phrases if p.start <= pos <= p.end] or [p for p in phrases if p.end <= pos][-1:]
        if hit:
            t.mark_set("insert", idx)
            self._phrase_menu(e, hit[0])
        return "break"

    @staticmethod
    def _short(s, n=24):
        s = s.replace("\n", "⏎")
        return s if len(s) <= n else s[:n - 1] + "…"

    def _phrase_menu(self, e, ph):
        cur = self.out_text.get("1.0", "end-1c")
        word = cur[ph.start:ph.end]
        m = tk.Menu(self.root, tearoff=0, font=self.fonts["ui"])
        m.add_command(label=f"文節「{self._short(word, 16)}」", state="disabled")
        info = next((p for p in self._infos if p.start == ph.start and p.end == ph.end), None)
        if info:
            m.add_command(label=f"状態：{core.PHRASE_STATUS[info.status]}", state="disabled")
            for e in info.entries[:3]:
                m.add_command(label=f"辞書：{self._short(self._entry_label(e), 40)}", state="disabled")
        m.add_separator()
        if info:
            for e in info.entries[:3]:
                m.add_command(label=f"辞書タブでこの項目を開く（{self._short(e.src, 12)}）",
                              command=lambda e=e: self.open_in_dict(e))
            if info.status == "checked":
                m.add_command(label="確認済みを外す", command=lambda: self.toggle_checked(ph, False))
            elif info.status in ("unchecked", "risky", "dict"):
                m.add_command(label="この文節を確認済みにする（耳で確かめた）", command=lambda: self.toggle_checked(ph, True))
            m.add_separator()

        def add_restore(label, ref, done):
            r = core.phrase_region(cur, ref, ph.start, ph.end) if ref else None
            if not r:
                m.add_command(label=f"{label}（［変換］した後に使えます）", state="disabled")
                return
            cs, ce, rs, re_ = r
            new = ref[rs:re_]
            if cur[cs:ce] == new:
                m.add_command(label=f"{label}（変わっていません）", state="disabled")
            else:
                m.add_command(label=f"{label}　→ {self._short(new)}",
                              command=lambda: self._replace_region(cs, ce, new, cur[cs:ce], done))
        add_restore("この文節を変換直後に戻す", self._out_converted, "変換直後の形に戻しました")
        add_restore("この文節を辞書適用前に戻す", self._out_prepared, "辞書を当てる前の形に戻しました")
        m.add_separator()
        m.add_command(label="アクセントを聞き比べる…", command=lambda: self.compare_accents(ph))
        m.add_command(label="この文節を辞書に登録…", command=lambda: self._register_phrase(ph))
        m.add_command(label="この文節を学習候補に送る", command=lambda: self._learn_phrase(ph))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _replace_region(self, cs, ce, new, old, done):
        t = self.out_text
        if t.get("1.0", "end-1c")[cs:ce] != old:          # メニューを出した後に書き換わっていたら何もしない
            return
        t.edit_separator()
        t.delete(f"1.0+{cs}c", f"1.0+{ce}c")
        t.insert(f"1.0+{cs}c", new)
        t.edit_separator()
        self._show_issues(core.validate(t.get("1.0", "end-1c")))
        self._refresh_status(f"「{self._short(old, 20)}」を{done}：{self._short(new, 30)}（Ctrl+Z で元に戻せます）")

    def _help(self, parent, title, text):
        """［？］ボタン。押した人にだけ、詳しい説明を小さな窓で見せる（画面の説明文を短くするため）"""
        def show():
            w = tk.Toplevel(self.root)
            w.title(title)
            w.transient(self.root)
            ttk.Label(w, text=text, justify="left", wraplength=self._sc(560), padding=(16, 14)).pack(fill="both", expand=True)
            b = ttk.Button(w, text="閉じる", command=w.destroy)
            b.pack(anchor="e", padx=12, pady=(0, 12))
            b.focus_set()
            w.bind("<Escape>", lambda e: w.destroy())
            w.bind("<Return>", lambda e: w.destroy())
        size = self._sc(HELP_ICON)
        bg = self.style.lookup("TFrame", "background") or parent.winfo_toplevel().cget("bg")
        cv = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bd=0, bg=bg, cursor="hand2")
        cv.bind("<Button-1>", lambda e: show())
        cv.bind("<Enter>", lambda e: self._draw_help(cv, True))
        cv.bind("<Leave>", lambda e: self._draw_help(cv, False))
        self._help_icons.append(cv)
        self._draw_help(cv, False)
        return cv

    def _help_image(self, size, hover):
        """「?」の印の画像（assets/help の、大きさごとに作っておいた縁のなめらかな PNG）。無ければ None"""
        n = min(max(size, 12), 40)
        key = (n, hover)
        if key not in self._help_imgs:
            path = os.path.join(RES_DIR, "assets", "help", f"help_{n}{'_hover' if hover else ''}.png")
            try:
                self._help_imgs[key] = tk.PhotoImage(file=path)
            except tk.TclError:
                self._help_imgs[key] = None
        return self._help_imgs[key]

    def _draw_help(self, cv, hover=False):
        """［？］の印：丸い輪の中に太い「？」。画像があれば画像を、無ければ線で描く（線だと縁がギザギザになる）"""
        try:
            size = self._sc(HELP_ICON)
            cv.configure(width=size, height=size)
            cv.delete("all")
            img = self._help_image(size, hover)
            if img is not None:
                cv.create_image(size // 2, size // 2, image=img)
                return
            col = "#1f5fbf" if hover else "black"
            w = max(1.5, size * 0.08)
            m = w / 2 + 1
            cv.create_oval(m, m, size - m, size - m, outline=col, width=w)
            f = tkfont.Font(family=self.fonts["ui"].actual("family"), size=-max(8, round(size * 0.62)), weight="bold")
            cv.create_text(size / 2, size / 2 + 0.5, text="?", fill=col, font=f)
            cv._font = f     # 消されないように持っておく
        except tk.TclError:
            pass

    # ── 変換結果の見える化 ────────────────────────
    def _off(self, idx) -> int:
        """Text の位置（"1.5" など）→ 先頭からの文字数"""
        n = self.out_text.count("1.0", idx, "chars")
        return n[0] if n else 0

    def _tag_spans(self, tag) -> list[tuple[int, int]]:
        r = self.out_text.tag_ranges(tag)
        return [(self._off(r[i]), self._off(r[i + 1])) for i in range(0, len(r), 2)]

    def _applied_now(self) -> list[tuple[int, int, core.Entry]]:
        """辞書が当たった所を、いまの変換結果の上の位置で返す（手直しで位置がずれても、タグが付いて動く）"""
        return [(a, b, e) for tag, e in self._ap_tags.items() for a, b in self._tag_spans(tag)]

    def _schedule_insight(self):
        """打つたびに数え直すと重いので、手が止まってから数え直す"""
        if self._insight_job:
            self.root.after_cancel(self._insight_job)
        self._insight_job = self.root.after(200, self._update_insight)

    def _update_insight(self):
        """文節ごとの状態を決め直して、色と「今回の変換」の行を書き直す"""
        self._insight_job = None
        t = self.out_text
        cur = t.get("1.0", "end-1c")
        applied = self._applied_now()
        self._infos = core.phrase_statuses(cur, self._out_converted, applied, self._tag_spans("checked"))
        for tag in ("ph_unchecked", "ph_manual", "ph_risky"):
            t.tag_remove(tag, "1.0", "end")
        if self.phrase_colors.get():
            for p in self._infos:
                tag = {"unchecked": "ph_unchecked", "manual": "ph_manual", "risky": "ph_risky"}.get(p.status)
                if tag:
                    t.tag_add(tag, f"1.0+{p.start}c", f"1.0+{p.end}c")
        if not self._out_converted:
            return
        sm = core.usage_summary(core.used_entries(applied))
        n_un = sum(p.status == "unchecked" for p in self._infos)
        n_risky = sum(p.status == "risky" for p in self._infos)
        extra = [f"文脈付き{sm['context']}"] * bool(sm["context"]) + [f"誤爆注意{sm['risky']}"] * bool(sm["risky"])
        line = f"辞書 {sm['places']}か所（{'・'.join([str(sm['entries']) + '項目'] + extra)}）"
        line += f"　未確認 {n_un}文節" + (f"・誤爆注意 {n_risky}文節" if n_risky else "")
        n_man = sum(p.status == "manual" for p in self._infos)
        if n_man:
            line += f"　手直し {n_man}文節"
        self.insight.set(line)
        if self._script_win is not None:
            self._fill_script()

    def goto_unchecked(self, backward=False):
        """次（前）の未確認・誤爆注意の文節を選ぶ。選んだまま［試聴］すると、その文節だけを聞ける"""
        if not self._out_converted:
            self._refresh_status([("先に①に YMM4 の読みを貼って［変換］してください", "warn")])
            return
        self._update_insight()
        t = self.out_text
        p = core.next_phrase(self._infos, self._off("insert"), backward=backward)
        if p is None:
            self._refresh_status("未確認の文節はありません（どの文節も、辞書・手直し・確認済みのどれかです）")
            return
        t.tag_remove("sel", "1.0", "end")
        t.tag_add("sel", f"1.0+{p.start}c", f"1.0+{p.end}c")
        t.mark_set("insert", f"1.0+{p.end}c")
        t.see(f"1.0+{p.start}c")
        t.focus_set()
        todo = [x for x in self._infos if x.status in ("unchecked", "risky")]
        k = next(i for i, x in enumerate(todo) if x is p) + 1
        what = core.PHRASE_STATUS[p.status]
        parts = [(f"{k}／{len(todo)}：「{self._short(t.get('1.0', 'end-1c')[p.start:p.end], 20)}」は{what}文節です。", None)]
        if p.status == "risky":
            e = next(x for x in p.entries if core.entry_warnings(x))
            parts.append((f"\n当たった項目：{self._entry_label(e)}（{'・'.join(core.entry_warnings(e))}）", "warn"))
        parts.append((f"\n［試聴］（{self._key_label('preview')}）でこの文節だけ聞けます。"
                      "良ければ右クリック →「確認済みにする」", None))
        self._refresh_status(parts)

    @staticmethod
    def _entry_label(e: core.Entry) -> str:
        ctx = core.ctx_label(e.before, e.after)
        return f"{e.src} → {e.dst}" + (f"（{ctx}）" if ctx else "") + ("（句頭のみ）" if e.head_only else "")

    def _entries_at(self, pos) -> list[core.Entry]:
        idx = f"1.0+{pos}c"
        return [self._ap_tags[g] for g in self.out_text.tag_names(idx) if g in self._ap_tags]

    def _out_click(self, _e=None):
        """黄色い所をクリックしたら、どの辞書の項目が当たったのかをメッセージ欄に出す"""
        t = self.out_text
        if t.tag_ranges("sel"):
            return
        found = self._entries_at(self._off("insert")) or self._entries_at(max(0, self._off("insert") - 1))
        if found:
            e = found[0]
            parts = [("この所は辞書で置き換えました：", None), (self._entry_label(e), None)]
            warns = core.entry_warnings(e)
            if warns:
                parts.append((f"\n誤爆しやすい項目です（{'・'.join(warns)}）", "warn"))
            parts.append(("\n右クリック →「辞書タブでこの項目を開く」で、直したり消したりできます", None))
            self._refresh_status(parts)

    def open_in_dict(self, e: core.Entry):
        """辞書タブで、その項目の行を選んで見せる（検索や絞り込みで隠れていたら、解いてから）"""
        self.nb.select(2)
        for attempt in range(2):
            iid = next((k for k, v in self._row_keys.items() if v == e.key), None)
            if iid:
                self.dict_tv.selection_set(iid)
                self.dict_tv.focus(iid)
                self.dict_tv.see(iid)
                self.dict_tv.focus_set()
                return
            self.q.set("")
            self.risky_only.set(False)
            self._fill_dict()
        self._refresh_status([("この項目は、もう辞書にありません（消したか、書き換えたようです）", "warn")])

    def toggle_checked(self, ph, on):
        t = self.out_text
        if on:
            t.tag_add("checked", f"1.0+{ph.start}c", f"1.0+{ph.end}c")
        else:
            t.tag_remove("checked", f"1.0+{ph.start}c", f"1.0+{ph.end}c")
        self._update_insight()
        n_un = sum(p.status == "unchecked" for p in self._infos)
        self._refresh_status(("確認済みにしました" if on else "確認済みを外しました") + f"（未確認の文節：残り {n_un}）"
                             + (f"。次は［次の未確認へ］（{self._key_label('next_unchecked')}）" if on and n_un else ""))

    def show_used_entries(self):
        """今回の変換で当たった辞書の項目を一覧にする。行を選ぶと、変換結果の当たった所を順に選ぶ"""
        used = core.used_entries(self._applied_now())
        if not used:
            self._refresh_status("今回の変換結果には、辞書で置き換えた所がありません" if self._out_converted
                                 else "先に①に YMM4 の読みを貼って［変換］してください")
            return
        w = tk.Toplevel(self.root)
        w.title("今回の変換で使われた辞書")
        w.transient(self.root)
        sm = core.usage_summary(used)
        ttk.Label(w, text=f"適用 {sm['places']}か所（{sm['entries']}項目）　文脈付き {sm['context']}　"
                          f"句頭のみ {sm['head']}　誤爆注意 {sm['risky']}", padding=(10, 8, 10, 0)).pack(anchor="w")
        ttk.Label(w, text="行を選ぶと変換結果の当たった所を選びます（もう一度選ぶと次の所へ）。ダブルクリックで辞書タブを開きます",
                  foreground="#666", padding=(10, 2)).pack(anchor="w")
        cols = ("n", "src", "dst", "ctx", "warn")
        tv = ttk.Treeview(w, columns=cols, show="headings", height=min(12, len(used)), selectmode="browse")
        for c, wd, txt in (("n", 60, "回数"), ("src", 200, "YMM4側"), ("dst", 200, "置き換え後"),
                           ("ctx", 170, "条件（前／後）"), ("warn", 220, "注意（誤爆しやすい）")):
            tv.heading(c, text=txt)
            tv.column(c, width=self._sc(wd), anchor="center" if c == "n" else "w", stretch=c != "n")
        tv.tag_configure("risky", foreground=MSG_STYLE["warn"]["fg"])
        rows = {}
        for i, u in enumerate(used):
            e = u.entry
            tv.insert("", "end", iid=f"u{i}", values=(u.count, e.src, e.dst, core.ctx_label(e.before, e.after),
                                                      "・".join(u.risky)), tags=("risky",) if u.risky else ())
            rows[f"u{i}"] = e
        tv.pack(fill="both", expand=True, padx=10, pady=6)
        turn = {"iid": None, "k": -1}

        def show_next(_ev=None):
            sel = tv.selection()
            if not sel:
                return
            e = rows[sel[0]]
            spans = sorted((a, b) for a, b, x in self._applied_now() if x is e)
            if not spans:
                return
            turn["k"] = (turn["k"] + 1) % len(spans) if turn["iid"] == sel[0] else 0
            turn["iid"] = sel[0]
            a, b = spans[turn["k"]]
            t = self.out_text
            t.tag_remove("sel", "1.0", "end")
            t.tag_add("sel", f"1.0+{a}c", f"1.0+{b}c")
            t.mark_set("insert", f"1.0+{b}c")
            t.see(f"1.0+{a}c")
            self._refresh_status(f"{self._entry_label(e)}：{turn['k'] + 1}／{len(spans)}か所目を選びました")

        tv.bind("<<TreeviewSelect>>", show_next)
        tv.bind("<ButtonRelease-1>", lambda ev: show_next() if tv.identify_row(ev.y) == turn["iid"] else None)
        tv.bind("<Double-1>", lambda ev: tv.selection() and open_and_close())

        def open_and_close():
            e = rows[tv.selection()[0]]
            w.destroy()
            self.open_in_dict(e)

        bf = ttk.Frame(w, padding=(10, 0, 10, 10))
        bf.pack(fill="x")
        ttk.Button(bf, text="辞書タブでこの項目を開く", command=lambda: tv.selection() and open_and_close()).pack(side="left")
        ttk.Button(bf, text="閉じる", command=w.destroy).pack(side="right")

    def _register_phrase(self, ph):
        """この文節の手直しを、辞書の追加画面に入れて開く（YMM4側＝辞書を当てる前の形、置き換え後＝今の文節）"""
        if not self._out_prepared:
            self._refresh_status([("辞書に登録するには、", None), ("先に①に YMM4 の読みを貼って［変換］してください", "warn")])
            return
        cur = self.out_text.get("1.0", "end-1c")
        r = core.phrase_region(cur, self._out_prepared, ph.start, ph.end)
        if not r:
            self._refresh_status([("この文節に当たる、変換前の読みが見つかりませんでした", "warn"),
                                  ("（文字そのものを大きく書き換えた所かもしれません）。辞書タブの［追加］から登録できます", None)])
            return
        cs, ce, rs, re_ = r
        src, dst = self._out_prepared[rs:re_], cur[cs:ce]
        if core.normalize(src) == core.normalize(dst):
            self._refresh_status("この文節は、辞書を当てる前の形と同じなので、登録する手直しがありません")
            return
        old = self.dic.find(core.normalize(src))
        # 前後の文節（辞書を当てる前の形）を、条件の候補としてボタンに出す
        prep = self._out_prepared
        spans = core._phrase_spans(prep)
        prev = [prep[a:b] for a, b in spans if b <= rs and "\n" not in prep[b:rs] and "。" not in prep[b:rs]]
        nxt = [prep[a:b] for a, b in spans if a >= re_ and "\n" not in prep[re_:a] and "。" not in prep[re_:a]]
        res = EntryDialog(self.root, self, "この文節を辞書に登録", src, dst,
                          old.head_only if old else False, old.note if old else "",
                          suggest_before=prev[-1] if prev else "", suggest_after=nxt[0] if nxt else "").result
        if not res:
            return
        src2, dst2, head, note, before, after = res
        old = self.dic.find(core.normalize(src2), before, after)
        if old and (old.dst, old.head_only) != (core.normalize(dst2), head):
            if not messagebox.askyesno(APP_NAME, f"同じ「YMM4側」の項目があります。\n今：{old.src} → {old.dst}\n"
                                                 f"新：{core.normalize(src2)} → {core.normalize(dst2)}\n\n上書きしますか？"):
                return
            self._backup_dict()                 # 上書きの前に写しておく
        kind = self.dic.upsert(src2, dst2, head, note, before, after)
        e = self.dic.find(core.normalize(src2), before, after)
        if e and note:
            e.note = note
        self.save_dict()
        self._fill_dict()
        done = {"added": "辞書に登録しました", "updated": "辞書を上書きしました", "same": "同じ項目がもう辞書にあります"}[kind]
        ctx = core.ctx_label(e.before, e.after) if e else ""
        parts = [(f"{done}：{self._short(e.src, 24)} → {self._short(e.dst, 30)}" + (f"（条件：{ctx}）" if ctx else ""), None)]
        warns = core.entry_warnings(e) if e else []
        if warns:
            parts.append((f"\n誤爆しやすい形です（{'・'.join(warns)}）。ほかの所で困ったら、辞書タブで「句頭のみ」を付けてください", "warn"))
        self._refresh_status(parts)

    def send_manual(self):
        """手で直した文節だけを、まとめて学習タブの候補に送る。直すたびに聞かず、押した人にだけ働く"""
        if not self._raw_converted:
            self._refresh_status([("先に①に YMM4 の読みを貼って［変換］してください", "warn")])
            return
        self._update_insight()
        manual = [p for p in self._infos if p.status == "manual"]
        if not manual:
            self._refresh_status("手で直した文節はありません（変換結果の欄で直すと、淡い緑になります）")
            return
        cur = self.out_text.get("1.0", "end-1c")
        regions = []
        for p in manual:
            r = core.phrase_region(cur, self._out_prepared, p.start, p.end)
            regions.append(core.normalize(cur[r[0]:r[1]] if r else cur[p.start:p.end]))
        picked = [c for c in core.learn(self._raw_converted, cur, self.numbers, self.dic)
                  if c.dst and any(core.normalize(c.dst) in g for g in regions)]
        have = {(c.src, c.dst) for c in self.cands}
        new = [c for c in picked if (c.src, c.dst) not in have]
        self.cands.extend(new)
        self._fill_cands()
        self._out_sent = cur      # 終了時の「学習タブへ送っていない手直し」の確認に使う
        if not new:
            self._refresh_status(f"手直しした {len(manual)} 文節から、新しい候補はありませんでした"
                                 "（もう学習タブにあるか、辞書と同じか、数字だけの変更です）")
            return
        self.nb.select(1)
        self._refresh_status([(f"手直しした {len(manual)} 文節から、学習タブに候補を {len(new)} 件送りました。", None),
                              ("\n確かめて［チェックしたものを辞書に登録］を押すと、辞書に入ります（押さなければ、辞書は変わりません）", "warn")])

    def _learn_phrase(self, ph):
        if not self._raw_converted:
            self._refresh_status([("学習候補に送るには、", None), ("先に①に YMM4 の読みを貼って［変換］してください", "warn")])
            return
        cur = self.out_text.get("1.0", "end-1c")
        r = core.phrase_region(cur, self._out_prepared, ph.start, ph.end)
        region = core.normalize(cur[r[0]:r[1]] if r else cur[ph.start:ph.end])
        # 学習タブと同じ方法で候補を出し、この文節の中のものだけ選ぶ
        picked = [c for c in core.learn(self._raw_converted, cur, self.numbers, self.dic)
                  if c.dst and core.normalize(c.dst) in region]
        if not picked:
            self._refresh_status([("この文節には、辞書に入れる候補になる変更がありません", "warn"),
                                  ("（変換直後と同じか、数字だけの変更です）", None)])
            return
        have = {(c.src, c.dst) for c in self.cands}
        new = [c for c in picked if (c.src, c.dst) not in have]
        self.cands.extend(new)
        self._fill_cands()
        if not new:
            self._refresh_status("この文節の候補は、もう学習タブに入っています")
            return
        self._refresh_status([(f"学習タブに候補を {len(new)} 件送りました：", None),
                              ("、".join(self._short(f"{c.src}→{c.dst}", 30) for c in new[:3]), None),
                              ("\n学習タブで確かめて［チェックしたものを辞書に登録］を押すと、辞書に入ります", "warn")])

    # 高低の線の点をつまんで動かす
    def _dot_press(self, e):
        cv = self.acc_cv
        cur = cv.find_withtag("current")
        tags = cv.gettags(cur[0]) if cur else ()
        dtag = next((t for t in tags if t in self._dot_info), None)
        if not dtag:
            return
        x1, y1, x2, y2 = cv.coords(cur[0])
        self._drag = {"item": cur[0], "info": self._dot_info[dtag], "y0": cv.canvasy(e.y),
                      "cy": (y1 + y2) / 2, "moved": False}

    def _dot_motion(self, e):
        d = self._drag
        if not d:
            return
        cv = self.acc_cv
        _, _, y_hi, y_lo, _, _ = d["info"]
        ny = min(max(cv.canvasy(e.y), y_hi), y_lo)
        if abs(cv.canvasy(e.y) - d["y0"]) > 3:
            d["moved"] = True
        x1, y1, x2, y2 = cv.coords(d["item"])
        r = (y2 - y1) / 2
        cv.coords(d["item"], x1, ny - r, x2, ny + r)

    def _dot_release(self, e):
        d, self._drag = self._drag, None
        self.acc_cv.configure(cursor="")
        if not d:
            return
        idx, k, y_hi, y_lo, hs, lv = d["info"]
        if d["moved"]:
            x1, y1, x2, y2 = self.acc_cv.coords(d["item"])
            want_high = (y1 + y2) / 2 < (y_hi + y_lo) / 2      # 真ん中より上で離したら「高」
        else:
            want_high = not lv                                 # クリックだけなら高低を入れ替える
        items = core.split_phrases(self.out_text.get("1.0", "end-1c"))
        ph = items[idx] if idx < len(items) and isinstance(items[idx], core.Phrase) else None
        ok, target = core.accent_for_pitch(ph, k, want_high, hs) if ph else (False, None)
        if not ok:
            self._draw_accent_panel()                          # 元の位置に戻す
            if ph and bool(lv) != want_high:
                self._refresh_status("この点は、アクセントの置き方ではその高さにできません")
            return
        self._set_accent(ph, target)

    def _acc_bg(self, x1, x2, y, row, ptag=""):
        """文節のまとまりを、薄い背景で示す"""
        if x2 > x1:
            r = self.acc_cv.create_rectangle(x1 - 1, y + 1, x2 + 1, y + row - self._sc(8), fill="#f4f6fa", outline="#dde2ea",
                                             tags=(ptag,) if ptag else ())
            self.acc_cv.tag_lower(r)

    def _acc_hover(self, tag, accented, on):
        cv = self.acc_cv
        cv.configure(cursor="hand2" if on else "")
        if not accented:
            cv.itemconfigure(tag, fill="#ffd2cf" if on else "#eef1f6")

    def _on_accent_click(self, idx, k):
        t = self.out_text
        items = core.split_phrases(t.get("1.0", "end-1c"))
        if idx >= len(items) or not isinstance(items[idx], core.Phrase) or k >= len(items[idx].units):
            return
        dels, ins = core.accent_edits(items[idx], k)
        self._apply_accent_edits(dels, ins)
        u = items[idx].units[k].text.lstrip("_")
        self._refresh_status(f"「{u}」にアクセントを付けました" if ins is not None else "アクセントを外しました（平板）")

    def _apply_accent_edits(self, dels, ins):
        """' を消す位置と入れる位置（元の文字列での位置）どおりに、変換結果の欄を書き換える"""
        t = self.out_text
        t.edit_separator()
        if ins is not None:
            t.insert(f"1.0+{ins}c", core.ACCENT)
        for d in sorted(dels, reverse=True):
            pos = d if ins is None or d < ins else d + 1
            t.delete(f"1.0+{pos}c")
        t.edit_separator()
        self._show_issues(core.validate(t.get("1.0", "end-1c")))

    # キーボードでのアクセント操作（変換結果の欄のカーソルがある文節が対象）
    def _phrase_at_cursor(self):
        t = self.out_text
        pos = len(t.get("1.0", "insert"))
        for it in core.split_phrases(t.get("1.0", "end-1c")):
            if isinstance(it, core.Phrase) and it.start <= pos <= it.end:
                return pos, it
        self._refresh_status([("アクセントを動かすには、", None), ("変換結果の欄で、文節の中にカーソルを置いてください", "warn")])
        return pos, None

    def _set_accent(self, ph, k):
        dels, ins = core.set_accent_edits(ph, k)
        if not dels and ins is None:
            self._refresh_status("この文節は、すでにその形です" if k is not None else "この文節は、すでに平板です")
            return
        self._apply_accent_edits(dels, ins)
        word = "".join(u.text.lstrip("_") for u in ph.units)
        if k is None:
            self._refresh_status(f"「{word}」のアクセントを外しました（平板）")
        else:
            self._refresh_status(f"「{word}」の「{ph.units[k].text.lstrip('_')}」にアクセントを付けました")

    def move_accent(self, d):
        """アクセントを前（d=-1）／後ろ（d=1）の文字へ。端まで行くと平板、平板からは端の文字へ"""
        _, ph = self._phrase_at_cursor()
        if not ph:
            return
        ks = [k for k, u in enumerate(ph.units) if u.can_accent]
        if not ks:
            self._refresh_status("この文節には、アクセントを置ける文字がありません")
            return
        cur = ph.accents[0] if ph.accents else None
        if cur is None:
            target = ks[-1] if d < 0 else ks[0]
        else:
            nxt = [k for k in ks if (k < cur if d < 0 else k > cur)]
            target = (nxt[-1] if d < 0 else nxt[0]) if nxt else None
        self._set_accent(ph, target)

    def accent_at_cursor(self):
        pos, ph = self._phrase_at_cursor()
        if not ph:
            return
        hit = [k for k, u in enumerate(ph.units) if u.start < pos <= u.end]
        if not hit or not ph.units[hit[0]].can_accent:
            self._refresh_status([("カーソルの前の文字には、アクセントを置けません", "warn"),
                                  ("（ー・っ・ん・記号には置けません）", None)])
            return
        self._set_accent(ph, hit[0])

    def clear_accent(self):
        _, ph = self._phrase_at_cursor()
        if ph:
            self._set_accent(ph, None)

    # ── 試聴（AquesTalkPlayer） ─────────────────────
    def _preview_text(self) -> str:
        """選択範囲があればその部分、なければ全体（選択に読める文字がなければ全体）。"""
        t = self.out_text
        sel = t.get("sel.first", "sel.last") if t.tag_ranges("sel") else None
        text, partial = core.preview_text(sel, t.get("1.0", "end-1c"))
        # 改行や記号だけをうっかり選んでいたときは、全体を読んだことを知らせる
        if sel and not partial:
            self._preview_note = "（選択した所に読める文字がなかったので、全体を読み上げています）"
        elif not sel:
            self._preview_note = "　※②で選択した所だけ読むこともできます"
        else:
            self._preview_note = ""
        return text

    def _remember_voice(self, name):
        if name:
            self._used_voices = [name] + [v for v in self._used_voices if v != name]
        self._refresh_voice_list()

    def _refresh_voice_list(self):
        """プルダウンを開くたびに AquesTalkPlayer.preset を読み直す（AquesTalkPlayer で作ったプリセットもすぐ出る）"""
        exe = self.player_path.get().strip()
        path = os.path.join(os.path.dirname(exe), "AquesTalkPlayer.preset") if exe else ""
        found = core.load_player_presets(path) if path else []
        self._player_presets = dict(found)
        if not path:
            self.preset_info.set("AquesTalkPlayerのプリセット：（AquesTalkPlayer.exeの場所が未設定）")
        elif found:
            self.preset_info.set(f"AquesTalkPlayerのプリセット：{len(found)}件を読み込みました\n{path}")
        else:
            self.preset_info.set(f"AquesTalkPlayerのプリセット：読み込めませんでした\n{path}")
        names = self._used_voices + [n for n, _ in found if n not in self._used_voices]
        self.voice_box["values"] = names

    def _warn_bouyomi(self, voice=None) -> str:
        """棒読みがオンのプリセットなら、メッセージ欄で知らせる（その文を返す）"""
        voice = self.voice.get().strip() if voice is None else voice
        if self._player_presets.get(voice):
            parts = [(f"「{voice}」は棒読みがオンなので、アクセント（'）が効きません。", "crit"),
                     ("\n［AquesTalkPlayer を開く］→「棒読み」のチェックを外す→［Add］で自分用のプリセットを作り、"
                      "その名前を「声（プリセット）」で選んでください", None)]
            self._refresh_status(parts)
            return "".join(x for x, _ in parts)
        return ""

    def _player_exe(self):
        """設定された AquesTalkPlayer.exe の場所。未設定・見つからないときは案内して None。"""
        exe = self.player_path.get().strip()
        if not exe:
            messagebox.showinfo(APP_NAME, "試聴には AquesTalkPlayer が必要です。\n\n"
                                "「設定」タブで AquesTalkPlayer.exe の場所を指定してください。\n"
                                "（AquesTalkPlayer は株式会社アクエストの公式サイトから入手できます）")
            self.nb.select(self.settings_tab)
            return None
        if not os.path.isfile(exe):
            messagebox.showerror(APP_NAME, f"AquesTalkPlayer が見つかりません。\n{exe}\n\n"
                                 "「設定」タブで AquesTalkPlayer.exe の場所を指定し直してください。")
            self.nb.select(self.settings_tab)
            return None
        return exe

    def open_player(self):
        """AquesTalkPlayer を画面つきで起動する（プリセットの「棒読み」などを直すため）。"""
        if not IS_WINDOWS:
            return
        exe = self._player_exe()
        if not exe:
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=NO_WINDOW)
            self._refresh_status([("AquesTalkPlayer を開きました。", None),
                                  ("最初からある「まりさ」「れいむ」は変更しても元に戻るので、［Add］で自分用のプリセットを作ってください", "warn")])
        except OSError as ex:
            messagebox.showerror(APP_NAME, f"AquesTalkPlayer を起動できませんでした。\n{exe}\n{ex}")

    def preview(self, text=None, note=None):
        """試聴する。text を渡すとそれを読む（聞き比べ用）。渡さなければ変換結果の選択範囲か全体"""
        if not IS_WINDOWS:
            return
        exe = self._player_exe()
        if not exe:
            return
        if text is None:
            text = self._preview_text()
        else:
            text = core._join_lines(text)
            self._preview_note = note or ""
        if not text:
            messagebox.showinfo(APP_NAME, "読み上げる所がありません。\n"
                                "変換結果の欄に、仮名の読みが入っていません。①に YMM4 の読みを貼って変換してから押してください。")
            return
        voice = self.voice.get().strip()

        self.stop_preview()
        self._preview_gen += 1
        gen = self._preview_gen
        fd, wav = tempfile.mkstemp(prefix="yukkuri-accent-", suffix=".wav")
        os.close(fd)
        args = [exe, "/T", "#>" + text, "/W", wav]
        if voice:
            args += ["/P", voice]
        self._preview_said = text if len(text) <= 120 else text[:120] + "…"
        self._refresh_status("試聴: 音声を作っています…")
        threading.Thread(target=self._synth, args=(gen, args, wav, voice), daemon=True).start()

    def _synth(self, gen, args, wav, voice):
        """別スレッドで AquesTalkPlayer を動かし、終わるまで待つ。結果は画面側のスレッドへ渡す。"""
        err = None
        proc = None
        try:
            # --windowed の .exe では標準入出力が無いので、明示的に捨て先を渡す
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
            self._proc = proc
            try:
                code = proc.wait(timeout=PLAYER_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                code = None
                err = (f"AquesTalkPlayer が {PLAYER_TIMEOUT} 秒たっても終わりませんでした。\n"
                       "AquesTalkPlayer の画面にメッセージが出ていないか確認してください。")
            if gen != self._preview_gen:
                code = None   # 途中で停止された
            elif err is None and code != 0:
                err = (f"AquesTalkPlayer がエラーで終了しました（終了コード {code}）。\n\n"
                       "次を確認してください。\n"
                       f"・声のプリセット名「{voice}」が AquesTalkPlayer にあるか\n"
                       "・読み上げる記号列にエラー（赤い所）が残っていないか")
            elif err is None and (not os.path.exists(wav) or os.path.getsize(wav) == 0):
                err = "AquesTalkPlayer は終了しましたが、音声ファイルが作られませんでした。"
        except OSError as ex:
            err = f"AquesTalkPlayer を起動できませんでした。\n{args[0]}\n{ex}"
        finally:
            if self._proc is proc:
                self._proc = None
        self.root.after(0, lambda: self._synth_done(gen, wav, err, voice))

    def _synth_done(self, gen, wav, err, voice):
        if gen != self._preview_gen:
            self._remove_file(wav)
            return
        if err:
            self._remove_file(wav)
            self._refresh_status([("試聴できませんでした。", "crit"), ("\n" + err.split("\n")[0], None)])
            messagebox.showerror(APP_NAME, err)
            return
        self._remember_voice(voice)   # 使えたプリセットだけ候補に残す
        self._save_conf()
        self._wav_raw = wav
        if not self._play_raw():
            return
        if self.muted:
            self._refresh_status([("消音中なので、音は出ていません。", "warn"),
                                  ("［消音中］" + (f"（{self._key_label('mute')}）" if self._key('mute') else "") + "を押すと、音を戻して最初から鳴らします", None)])
        elif not self._warn_bouyomi(voice):
            self._refresh_status(f"試聴：再生中（{voice or '前回のプリセット'}・音量 {self.volume}%）{self._preview_note}\n{self._preview_said}")

    def _silence(self):
        """鳴っている音だけを止める（直前の試聴の音声は、鳴らし直せるように残す）"""
        import winsound
        try:
            winsound.PlaySound(None, 0)
        except RuntimeError:
            pass
        if self._wav:
            self._remove_file(self._wav)
            self._wav = None

    def _play_raw(self) -> bool:
        """書き出したWAVを、いまの音量に直して最初から再生する。
        消音中は鳴らさないが、鳴っていたはずの時間は覚えておく（その間に消音を解くと、最初から鳴らす）"""
        import winsound
        self._silence()
        self._play_until = 0.0
        if not self._wav_raw:
            return True
        try:
            if self.muted:
                play, secs = None, self._wav_secs(self._wav_raw)
            elif self.volume == 100:
                play, secs = self._wav_raw, self._wav_secs(self._wav_raw)
            else:
                fd, play = tempfile.mkstemp(prefix="yukkuri-accent-vol-", suffix=".wav")
                os.close(fd)
                self._wav = play
                secs = core.scale_wav(self._wav_raw, play, self.volume)
            if play:
                winsound.PlaySound(play, winsound.SND_FILENAME | winsound.SND_ASYNC)
            self._play_until = time.monotonic() + secs
            return True
        except (RuntimeError, OSError, EOFError, ValueError) as ex:
            messagebox.showerror(APP_NAME, f"音声を再生できませんでした。\n{ex}")
            return False

    @staticmethod
    def _wav_secs(path) -> float:
        import wave
        try:
            with wave.open(path, "rb") as r:
                return r.getnframes() / (r.getframerate() or 1)
        except (OSError, EOFError, wave.Error):
            return 0.0

    def _playing(self) -> bool:
        return bool(self._wav_raw) and time.monotonic() < self._play_until

    # ── 試聴の音量 ──────────────────────────────────
    def _show_volume(self):
        if self.muted:
            self.vol_label.configure(text="消音", fg="#b00000")
        else:
            self.vol_label.configure(text=f"{self.volume}%", fg="black")
        key = self._key("mute")
        text = "消音中" if self.muted else "消音"
        for i, (aid, btn, _) in enumerate(self._hint_buttons):
            if aid == "mute":
                self._hint_buttons[i] = (aid, btn, text)
        self.btn_mute.configure(text=f"{text}（{core.shortcut_label(key)}）" if key else text)
        self.btn_vol_down.state(["disabled" if self.volume <= core.VOLUME_MIN or not IS_WINDOWS else "!disabled"])
        self.btn_vol_up.state(["disabled" if self.volume >= core.VOLUME_MAX or not IS_WINDOWS else "!disabled"])

    def change_volume(self, d):
        """試聴の音量を1段上げ下げする。消音中なら消音を解く。鳴っている途中なら、新しい音量で最初から鳴らし直す"""
        new = core.step_volume(self.volume, d)
        if new == self.volume and not self.muted:
            edge = "最大" if d > 0 else "最小"
            self._refresh_status(f"音量はこれ以上{'上げ' if d > 0 else '下げ'}られません（{edge} {self.volume}%）")
            return
        replay = IS_WINDOWS and self._playing()
        unmuted = self.muted
        self.volume, self.muted = new, False
        self._show_volume()
        self._save_conf()
        msg = f"試聴の音量：{self.volume}%" + ("（消音を解きました）" if unmuted else "")
        if replay:
            self._play_raw()
            self._refresh_status(msg + "　新しい音量で最初から鳴らし直しています")
        else:
            self._refresh_status(msg + "　次の試聴から、この音量で鳴ります")

    def toggle_mute(self):
        """消音を切り替える。消音にするとすぐ止まり、鳴っている途中で戻すと最初から鳴らし直す"""
        self.muted = not self.muted
        self._show_volume()
        self._save_conf()
        if not IS_WINDOWS:
            return
        if self.muted:
            self._silence()
            self._refresh_status([("消音にしました。", "warn"),
                                  (f"もう一度押すと、元の音量（{self.volume}%）に戻ります", None)])
        elif self._playing():
            self._play_raw()
            self._refresh_status(f"消音を解きました（音量 {self.volume}%）。鳴っている途中だった試聴を、最初から鳴らし直しています")
        else:
            self._refresh_status(f"消音を解きました（音量 {self.volume}%）")

    def stop_preview(self):
        self._preview_gen += 1
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        if IS_WINDOWS:
            import winsound
            try:
                winsound.PlaySound(None, 0)
            except RuntimeError:
                pass
        self._remove_wav()

    def _remove_wav(self):
        for name in ("_wav", "_wav_raw"):
            p = getattr(self, name)
            if p:
                self._remove_file(p)
                setattr(self, name, None)
        self._play_until = 0.0

    @staticmethod
    def _remove_file(p):
        try:
            os.remove(p)
        except OSError:
            pass

    # ── タブ2: 学習 ─────────────────────────────────
    def _build_learn(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="　学習　")
        ttk.Label(tab, text="YMM4の初期出力と、直した後の完成形を並べて貼ると、辞書に入れる候補を探します。"
                            "行ごとに対応させてください（複数行OK）。").pack(anchor="w")

        pw = ttk.Frame(tab)
        pw.pack(fill="both", expand=False, pady=6)
        pw.columnconfigure(0, weight=1)
        pw.columnconfigure(1, weight=1)
        ttk.Label(pw, text="YMM4の初期出力").grid(row=0, column=0, sticky="w")
        ttk.Label(pw, text="完成形（直した後）").grid(row=0, column=1, sticky="w", padx=(8, 0))
        f1, self.l_before = self._text(pw, 5)
        f2, self.l_after = self._text(pw, 5)
        f1.grid(row=1, column=0, sticky="nsew")
        f2.grid(row=1, column=1, sticky="nsew", padx=(8, 0))

        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(2, 6))
        ttk.Button(row, text="差分から候補を出す", style="Big.TButton", command=self.do_learn).pack(side="left")
        ttk.Button(row, text="すべてチェック", command=lambda: self._check_all(True)).pack(side="left", padx=(12, 4))
        ttk.Button(row, text="すべて外す", command=lambda: self._check_all(False)).pack(side="left")
        ttk.Button(row, text="チェックしたものを辞書に登録", style="Big.TButton",
                   command=self.commit_candidates).pack(side="right")

        cols = ("use", "kind", "src", "dst", "head", "status")
        tv = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for c, w, txt in (("use", 50, "登録"), ("kind", 50, "種類"), ("src", 330, "YMM4側"),
                          ("dst", 330, "置き換え後"), ("head", 80, "句頭のみ"), ("status", 80, "状態")):
            tv.heading(c, text=txt)
            tv.column(c, width=w, anchor="center" if c in ("use", "kind", "head", "status") else "w",
                      stretch=c in ("src", "dst"))
        tv.pack(fill="both", expand=True)
        tv.bind("<Button-1>", self._on_cand_click)
        tv.bind("<Double-1>", self._on_cand_dbl)
        self.cand_tv = tv
        ttk.Label(tab, text="「登録」「句頭のみ」はクリックで切り替え。行をダブルクリックすると中身を編集できます。"
                            "　［句］= 句のまとまり　［語］= 助詞を外した単語　［数字］= 参考表示（読み方は数字の読み表で決まるので、ふつうは登録しません）", foreground="#666", wraplength=990, justify="left").pack(anchor="w", pady=(4, 0))
        self.cands: list[core.Candidate] = []

    def do_learn(self):
        b = self.l_before.get("1.0", "end-1c")
        a = self.l_after.get("1.0", "end-1c")
        if not b.strip() or not a.strip():
            messagebox.showinfo(APP_NAME, "左右の両方に貼り付けてください。")
            return
        nb_, na_ = b.count("\n"), a.count("\n")
        if nb_ != na_:
            messagebox.showwarning(APP_NAME, "左右の行数が違います。対応する行どうしだけを比べます。")
        self.cands = core.learn(b, a, self.numbers, self.dic)
        self._fill_cands()
        new = sum(c.status != "登録済み" for c in self.cands)
        self._refresh_status(f"候補 {len(self.cands)} 件（新規・上書き {new} 件）")

    def _fill_cands(self):
        tv = self.cand_tv
        tv.delete(*tv.get_children())
        for i, c in enumerate(self.cands):
            ctx = core.ctx_label(c.before, c.after)
            tv.insert("", "end", iid=str(i), values=(
                "☑" if c.use else "☐", c.kind, f"{c.src}　［{ctx}］" if ctx else c.src, c.dst,
                "○" if c.head_only else "", c.status))

    def _check_all(self, v):
        for c in self.cands:
            if c.status != "登録済み" and c.kind != "数字":
                c.use = v
        self._fill_cands()

    def _on_cand_click(self, e):
        tv = self.cand_tv
        if tv.identify_region(e.x, e.y) != "cell":
            return
        iid, col = tv.identify_row(e.y), tv.identify_column(e.x)
        if not iid:
            return
        c = self.cands[int(iid)]
        if col == "#1":
            c.use = not c.use
        elif col == "#5":
            c.head_only = not c.head_only
        else:
            return
        self._fill_cands()
        tv.selection_set(iid)
        return "break"

    def _on_cand_dbl(self, e):
        iid = self.cand_tv.identify_row(e.y)
        col = self.cand_tv.identify_column(e.x)
        if not iid or col in ("#1", "#5"):
            return
        c = self.cands[int(iid)]
        r = EntryDialog(self.root, self, "候補を編集", c.src, c.dst, c.head_only, "", c.before, c.after).result
        if r:
            c.src, c.dst, c.head_only, _, c.before, c.after = r
            c.use = True
            self._fill_cands()

    def commit_candidates(self):
        cnt = {"added": 0, "updated": 0, "same": 0}
        for c in self.cands:
            if c.use:
                cnt[self.dic.upsert(c.src, c.dst, c.head_only, before=c.before, after=c.after)] += 1
        self.save_dict()
        self.cands = [c for c in self.cands if not c.use]
        self._fill_cands()
        self._fill_dict()
        self._refresh_status(f"辞書に登録: 追加 {cnt['added']} ／ 更新 {cnt['updated']}")

    # ── タブ3: 辞書 ─────────────────────────────────
    def _build_dict(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="　辞書　")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="検索:").pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self._fill_dict())
        ttk.Entry(top, textvariable=self.q, width=30, font=self.f_ui).pack(side="left", padx=6)
        self.risky_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="誤爆しやすい項目だけ", variable=self.risky_only,
                        command=self._fill_dict).pack(side="left", padx=(8, 4))
        self.risky_info = tk.StringVar()
        ttk.Label(top, textvariable=self.risky_info, foreground=MSG_STYLE["warn"]["fg"]).pack(side="left")
        ttk.Button(top, text="数字の読み表を開く", command=self.open_numbers).pack(side="right")
        ttk.Button(top, text="読み表を再読み込み", command=self.reload_numbers).pack(side="right", padx=6)

        cols = ("src", "dst", "ctx", "head", "hits", "added", "warn", "note")
        tv = ttk.Treeview(tab, columns=cols, show="headings", selectmode="extended")
        for c, w, txt in (("src", 220, "YMM4側"), ("dst", 220, "置き換え後"), ("ctx", 170, "条件（前／後）"),
                          ("head", 70, "句頭のみ"),
                          ("hits", 70, "使用回数"), ("added", 100, "登録日"), ("warn", 230, "注意（誤爆しやすい）"),
                          ("note", 140, "メモ")):
            tv.heading(c, text=txt, command=lambda c=c: self._sort_dict(c))
            tv.column(c, width=w, anchor="center" if c in ("head", "hits", "added") else "w",
                      stretch=c in ("src", "dst", "note", "warn", "ctx"))
        tv.tag_configure("risky", foreground=MSG_STYLE["warn"]["fg"])
        tv.pack(fill="both", expand=True, pady=6)
        tv.bind("<Double-1>", lambda e: self.edit_entry())
        tv.bind("<Delete>", lambda e: self.delete_entries())
        self.dict_tv = tv
        self._sort_key = "src"

        bot = ttk.Frame(tab)
        bot.pack(fill="x")
        ttk.Button(bot, text="追加", command=self.add_entry).pack(side="left")
        ttk.Button(bot, text="編集", command=self.edit_entry).pack(side="left", padx=4)
        ttk.Button(bot, text="削除", command=self.delete_entries).pack(side="left")
        ttk.Button(bot, text="競合を調べる…", command=self.check_conflicts).pack(side="left", padx=(16, 0))
        ttk.Button(bot, text="統計…", command=self.show_stats).pack(side="left", padx=6)
        ttk.Button(bot, text="別名で書き出す…", command=self.export_dict).pack(side="right")
        ttk.Button(bot, text="バックアップから戻す…", command=self.restore_dict).pack(side="right", padx=(6, 0))
        ttk.Button(bot, text="他の辞書を取り込む…", command=self.import_dict).pack(side="right", padx=6)
        self._fill_dict()

    # ── 台本単位の一括チェック ──────────────────────
    def open_script_file(self):
        """YMM4 の読みを1行1台詞で書いたテキストファイルを、①に読み込んで変換する"""
        path = filedialog.askopenfilename(parent=self.root, title="台本（読みのテキスト）を開く",
                                          filetypes=[("テキスト", "*.txt"), ("すべて", "*.*")])
        if not path:
            return
        raw = None
        for enc in ("utf-8-sig", "cp932", "utf-16"):
            try:
                with open(path, encoding=enc) as f:
                    raw = f.read()
                break
            except (UnicodeError, OSError):
                continue
        if raw is None:
            messagebox.showerror(APP_NAME, f"読み込めませんでした（文字コードが分かりません）。\n{path}", parent=self.root)
            return
        self.in_text.delete("1.0", "end")
        self.in_text.insert("1.0", raw.replace("\r\n", "\n"))
        self.do_convert()
        self.show_script()

    def _script_rows(self):
        t = self.out_text
        cur = t.get("1.0", "end-1c")
        return core.line_reports(cur, self._infos, self._applied_now(), core.validate(cur))

    def show_script(self):
        """台本（変換結果の全行）を1行1台詞として、行ごとの状態を一覧にする"""
        if not self._out_converted:
            self._refresh_status([("先に①に YMM4 の読みを貼って（または［ファイルを開く…］で読み込んで）［変換］してください", "warn")])
            return
        if self._script_win is not None:
            self._script_win.lift()
            self._fill_script()
            return
        w = tk.Toplevel(self.root)
        w.title("台本の一覧")
        w.transient(self.root)
        self._script_win = w
        w.protocol("WM_DELETE_WINDOW", self._close_script)
        self._script_head = tk.StringVar()
        ttk.Label(w, textvariable=self._script_head, font=self.fonts["head"], padding=(10, 8, 10, 0)).pack(anchor="w")
        ttk.Label(w, text="1行を1台詞として数えます。行を選ぶと変換結果のその行を選び、［試聴］でその台詞だけを聞けます。"
                          "未確認・誤爆注意・エラーが残っている行が「要確認」です",
                  foreground="#666", padding=(10, 2), wraplength=self._sc(860)).pack(anchor="w")
        fr = ttk.Frame(w)
        fr.pack(fill="both", expand=True, padx=10, pady=6)
        cols = ("no", "st", "places", "un", "risky", "err", "text")
        tv = ttk.Treeview(fr, columns=cols, show="headings", height=14, selectmode="browse")
        for c, wd, txt in (("no", 50, "行"), ("st", 80, "状態"), ("places", 60, "辞書"), ("un", 70, "未確認"),
                           ("risky", 80, "誤爆注意"), ("err", 70, "エラー"), ("text", 460, "台詞")):
            tv.heading(c, text=txt)
            tv.column(c, width=self._sc(wd), anchor="w" if c == "text" else "center", stretch=c == "text")
        tv.tag_configure("err", foreground=MSG_STYLE["crit"]["fg"])
        tv.tag_configure("todo", foreground=MSG_STYLE["warn"]["fg"])
        tv.tag_configure("done", foreground="#2a7a2a")
        sb = ttk.Scrollbar(fr, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._script_tv = tv
        tv.bind("<<TreeviewSelect>>", lambda e: self._select_line())
        bf = ttk.Frame(w, padding=(10, 0, 10, 10))
        bf.pack(fill="x")
        ttk.Button(bf, text="次の要確認の台詞へ ▶", command=self._next_todo_line).pack(side="left")
        ttk.Button(bf, text="この台詞をコピー", command=self._copy_line).pack(side="left", padx=6)
        ttk.Button(bf, text="閉じる", command=self._close_script).pack(side="right")
        self._fill_script()

    def _close_script(self):
        if self._script_win is not None:
            self._script_win.destroy()
        self._script_win = None

    def _fill_script(self):
        tv = self._script_tv
        keep = tv.selection()
        rows = self._script_rows()
        self._script_data = {f"l{r.no}": r for r in rows}
        tv.delete(*tv.get_children())
        for r in rows:
            st = "エラー" if r.errors else "要確認" if r.todo else "済"
            tv.insert("", "end", iid=f"l{r.no}", values=(r.no, st, r.places or "", r.unchecked or "", r.risky or "",
                                                        r.errors or "", self._short(r.text, 60)),
                      tags=("err" if r.errors else "todo" if r.todo else "done",))
        if keep and keep[0] in self._script_data:
            tv.selection_set(keep[0])
        sm = core.script_summary(rows)
        self._script_head.set(f"全{sm['lines']}台詞　辞書 {sm['places']}か所　エラー {sm['errors']}　"
                              f"要確認 {sm['todo_lines']}台詞（未確認 {sm['unchecked']}文節・誤爆注意 {sm['risky']}文節）　"
                              f"済 {sm['done_lines']}台詞")

    def _select_line(self):
        sel = self._script_tv.selection()
        if not sel or sel[0] not in self._script_data:
            return
        r = self._script_data[sel[0]]
        t = self.out_text
        t.tag_remove("sel", "1.0", "end")
        t.tag_add("sel", f"1.0+{r.start}c", f"1.0+{r.end}c")
        t.mark_set("insert", f"1.0+{r.start}c")
        t.see(f"1.0+{r.start}c")

    def _next_todo_line(self):
        tv = self._script_tv
        ids = list(tv.get_children())
        sel = tv.selection()
        start = ids.index(sel[0]) + 1 if sel and sel[0] in ids else 0
        for iid in ids[start:] + ids[:start]:
            if self._script_data[iid].todo:
                tv.selection_set(iid)
                tv.see(iid)
                r = self._script_data[iid]
                self._refresh_status(f"{r.no}行目：未確認 {r.unchecked}・誤爆注意 {r.risky}・エラー {r.errors}。"
                                     f"変換結果で［次の未確認へ］（{self._key_label('next_unchecked')}）を押すと、この行の文節を順に選びます")
                return
        self._refresh_status("要確認の台詞はありません。全部の台詞が済みです")

    def _copy_line(self):
        sel = self._script_tv.selection()
        if not sel:
            return
        r = self._script_data[sel[0]]
        self._copy(core.normalize(r.text))
        self._refresh_status(f"{r.no}行目をコピーしました。YMM4 のその台詞に貼り付けてください")

    # ── アクセントの聞き比べ ──────────────────────
    def compare_accents(self, ph):
        """文節のアクセントの形を全部並べ、選ぶとすぐ聞ける。上下キーで2つを行き来すれば A/B 比較になる"""
        t = self.out_text
        s = t.get("1.0", "end-1c")
        word = s[ph.start:ph.end]
        vs = core.accent_variants(s, ph)
        if len(vs) < 2:
            self._refresh_status("この文節には、アクセントを付けられる文字がありません")
            return
        w = tk.Toplevel(self.root)
        w.title(f"アクセントを聞き比べる：{self._short(word, 20)}")
        w.transient(self.root)
        ttk.Label(w, text="行を選ぶと、その形ですぐ読み上げます。↑↓キーで2つの行を行き来すると、聞き比べ（A/B）になります",
                  padding=(10, 8, 10, 2), wraplength=self._sc(560)).pack(anchor="w")
        scope = tk.StringVar(value="line")
        rf = ttk.Frame(w, padding=(10, 0))
        rf.pack(anchor="w")
        ttk.Label(rf, text="読む範囲:").pack(side="left")
        ttk.Radiobutton(rf, text="その行（前後の流れごと）", value="line", variable=scope).pack(side="left", padx=4)
        ttk.Radiobutton(rf, text="文節だけ", value="phrase", variable=scope).pack(side="left")
        tv = ttk.Treeview(w, columns=("form", "kind"), show="headings", height=min(10, len(vs)), selectmode="browse")
        tv.heading("form", text="形")
        tv.heading("kind", text="")
        tv.column("form", width=self._sc(240))
        tv.column("kind", width=self._sc(320))
        tv.tag_configure("cur", foreground="#1f5fbf")
        for i, v in enumerate(vs):
            kind = "平板" if v.k is None else f"{''.join(u.text.lstrip('_') for u in ph.units[:v.k + 1])} の後ろで下がる"
            tv.insert("", "end", iid=f"v{i}", values=(v.text, kind + ("（いまの形）" if v.current else "")),
                      tags=("cur",) if v.current else ())
        tv.pack(fill="both", expand=True, padx=10, pady=6)
        if not IS_WINDOWS:
            ttk.Label(w, text="試聴は Windows 専用です（AquesTalkPlayer が Windows 用のため）", foreground="#666",
                      padding=(10, 0)).pack(anchor="w")

        def chosen():
            sel = tv.selection()
            return vs[int(sel[0][1:])] if sel else None

        def play(_e=None):
            v = chosen()
            if not v:
                return
            if scope.get() == "phrase":
                text = v.text
            else:
                a, b = core.line_at(v.whole, ph.start)
                text = v.whole[a:b]
            self.preview(text, note=f"（聞き比べ：{v.text}）")

        def adopt():
            v = chosen()
            if not v:
                return
            if t.get("1.0", "end-1c") != s:
                messagebox.showinfo(APP_NAME, "聞き比べを開いた後に変換結果が書き換わったので、採用できません。もう一度開いてください。",
                                    parent=w)
                return
            self._set_accent(ph, v.k)
            w.destroy()
        tv.bind("<<TreeviewSelect>>", play)
        bf = ttk.Frame(w, padding=10)
        bf.pack(fill="x")
        ttk.Button(bf, text="▶ もう一度聞く", command=play).pack(side="left")
        ttk.Button(bf, text="この形を採用", style="Big.TButton", command=adopt).pack(side="left", padx=6)
        ttk.Button(bf, text="閉じる", command=lambda: (self.stop_preview(), w.destroy())).pack(side="right")
        tv.focus_set()

    # ── 辞書の統計 ─────────────────────────────────
    def show_stats(self):
        st = core.dict_stats(self.dic)
        w = tk.Toplevel(self.root)
        w.title("辞書の統計")
        w.transient(self.root)
        lines = [f"登録数：{st['total']}項目（今月追加 {st['this_month']}）",
                 f"使用回数の合計：{st['hits_total']}（1つの台詞で当たった項目を1回と数えます）",
                 f"文脈付き：{st['context']}　句頭のみ：{st['head']}　誤爆しやすい：{st['risky']}",
                 f"一度も使われていない：{len(st['unused'])}項目"]
        ttk.Label(w, text="\n".join(lines), padding=(10, 8)).pack(anchor="w")
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True, padx=10)
        tvs = {}
        for key, title in (("top", "よく使われた項目"), ("unused", "一度も使われていない項目")):
            fr = ttk.Frame(nb)
            nb.add(fr, text=title)
            tv = ttk.Treeview(fr, columns=("n", "e"), show="headings", height=10, selectmode="browse")
            tv.heading("n", text="使用回数")
            tv.heading("e", text="項目")
            tv.column("n", width=self._sc(80), anchor="center", stretch=False)
            tv.column("e", width=self._sc(460))
            sb = ttk.Scrollbar(fr, command=tv.yview)
            tv.configure(yscrollcommand=sb.set)
            tv.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            for i, e in enumerate(st[key]):
                tv.insert("", "end", iid=f"e{i}", values=(e.hits, self._entry_label(e)))
            tv.bind("<Double-1>", lambda ev, tv=tv, key=key: tv.selection() and
                    self.open_in_dict(st[key][int(tv.selection()[0][1:])]))
            tvs[key] = tv
        ttk.Label(w, text="ダブルクリックで辞書タブのその行を開きます。取り込んだ辞書の項目は、取り込んでからの回数です",
                  foreground="#666", padding=(10, 4)).pack(anchor="w")
        ttk.Button(w, text="閉じる", command=w.destroy).pack(anchor="e", padx=10, pady=(0, 10))

    def check_conflicts(self):
        """辞書の競合チェック（辞書の DRC）。項目ごとに、その項目が当たるはずの最小の文を本物の辞書で変換して確かめる"""
        found = core.dict_conflicts(self.dic)
        n = {lv: sum(c.level == lv for c in found) for lv in core.CONFLICT_LEVEL}
        if not found:
            self._refresh_status(f"競合は見つかりませんでした（{len(self.dic.entries)}項目を調べました）")
            messagebox.showinfo(APP_NAME, f"競合は見つかりませんでした。\n{len(self.dic.entries)}項目を調べました。", parent=self.root)
            return
        w = tk.Toplevel(self.root)
        w.title("辞書の競合チェック")
        w.transient(self.root)
        ttk.Label(w, text=f"{len(self.dic.entries)}項目を調べました：効かない {n['error']}　無駄・要確認 {n['warn']}　お知らせ {n['info']}",
                  padding=(10, 8, 10, 0)).pack(anchor="w")
        ttk.Label(w, text="各項目が当たるはずの、いちばん短い文を作って、いまの辞書で変換して確かめています。"
                          "行を選ぶと下に説明、ダブルクリックで辞書タブのその行を開きます",
                  foreground="#666", padding=(10, 2), wraplength=self._sc(820)).pack(anchor="w")
        cols = ("lv", "kind", "entry")
        tv = ttk.Treeview(w, columns=cols, show="headings", height=min(14, len(found)), selectmode="browse")
        for c, wd, txt in (("lv", 110, "重さ"), ("kind", 220, "種類"), ("entry", 420, "項目")):
            tv.heading(c, text=txt)
            tv.column(c, width=self._sc(wd), anchor="w", stretch=c == "entry")
        tv.tag_configure("error", foreground=MSG_STYLE["crit"]["fg"])
        tv.tag_configure("warn", foreground=MSG_STYLE["warn"]["fg"])
        rows = {}
        for i, c in enumerate(found):
            tv.insert("", "end", iid=f"c{i}", values=(core.CONFLICT_LEVEL[c.level], c.kind, self._entry_label(c.entry)),
                      tags=(c.level,))
            rows[f"c{i}"] = c
        tv.pack(fill="both", expand=True, padx=10, pady=6)
        msg = tk.StringVar(value="行を選ぶと、ここに説明を出します")
        ttk.Label(w, textvariable=msg, wraplength=self._sc(820), padding=(10, 0)).pack(anchor="w", fill="x")

        def sel():
            s_ = tv.selection()
            return rows[s_[0]] if s_ else None

        def on_select(_e=None):
            c = sel()
            if c:
                msg.set(c.msg + (f"\n原因の項目：{self._entry_label(c.other)}" if c.other else ""))
        tv.bind("<<TreeviewSelect>>", on_select)
        tv.bind("<Double-1>", lambda e: sel() and self.open_in_dict(sel().entry))
        bf = ttk.Frame(w, padding=10)
        bf.pack(fill="x")
        ttk.Button(bf, text="この項目を辞書タブで開く", command=lambda: sel() and self.open_in_dict(sel().entry)).pack(side="left")
        ttk.Button(bf, text="原因の項目を開く",
                   command=lambda: sel() and sel().other and self.open_in_dict(sel().other)).pack(side="left", padx=6)
        ttk.Button(bf, text="調べ直す", command=lambda: (w.destroy(), self.check_conflicts())).pack(side="left")
        ttk.Button(bf, text="閉じる", command=w.destroy).pack(side="right")
        parts = [(f"競合チェック：", None), (f"効かない {n['error']}", "crit" if n["error"] else None), (" ／ ", None),
                 (f"無駄・要確認 {n['warn']}", "warn" if n["warn"] else None), (f" ／ お知らせ {n['info']}", None)]
        self._refresh_status(parts)

    def _sort_dict(self, col):
        self._sort_key = col
        self._fill_dict()

    def _fill_dict(self):
        tv = self.dict_tv
        tv.delete(*tv.get_children())
        q = core.normalize(self.q.get()) if hasattr(self, "q") else ""
        warns = {e.key: core.entry_warnings(e) for e in self.dic.entries}
        key = {"src": lambda e: e.key, "dst": lambda e: e.dst, "head": lambda e: not e.head_only,
               "hits": lambda e: -e.hits, "added": lambda e: e.added, "note": lambda e: e.note,
               "warn": lambda e: (not warns[e.key], e.key),
               "ctx": lambda e: (not (e.before or e.after), e.key)}[self._sort_key]
        only = hasattr(self, "risky_only") and self.risky_only.get()
        self._row_keys = {}          # 行の id → (YMM4側, 前, 後)。同じ YMM4側でも条件違いは別の行
        for n, e in enumerate(sorted(self.dic.entries, key=key)):
            if q and not any(q in x for x in (e.src, e.dst, e.note, e.before, e.after)):
                continue
            if only and not warns[e.key]:
                continue
            iid = f"k{n}"
            self._row_keys[iid] = e.key
            tv.insert("", "end", iid=iid, values=(e.src, e.dst, core.ctx_label(e.before, e.after),
                                                   "○" if e.head_only else "", e.hits or "", e.added,
                                                   "・".join(warns[e.key]), e.note),
                      tags=("risky",) if warns[e.key] else ())
        if hasattr(self, "risky_info"):
            n_risky = sum(1 for v in warns.values() if v)
            self.risky_info.set(f"{n_risky} 件" if n_risky else "")
        self._refresh_status()

    def add_entry(self):
        r = EntryDialog(self.root, self, "辞書に追加", "", "", False, "").result
        if r:
            src, dst, head, note, before, after = r
            if self.dic.find(core.normalize(src), before, after) and not messagebox.askyesno(
                    APP_NAME, "同じ「YMM4側」で同じ条件の項目があります。上書きしますか？"):
                return
            self.dic.upsert(src, dst, head, note, before, after)
            self.save_dict()
            self._fill_dict()

    def edit_entry(self):
        sel = self.dict_tv.selection()
        if not sel or sel[0] not in self._row_keys:
            return
        e = self.dic.find(*self._row_keys[sel[0]])
        if not e:
            return
        r = EntryDialog(self.root, self, "辞書を編集", e.src, e.dst, e.head_only, e.note, e.before, e.after).result
        if r:
            src, dst, head, note, before, after = r
            if (core.normalize(src), before, after) != e.key:
                self.dic.remove(*e.key)
            self.dic.upsert(src, dst, head, note, before, after)
            ne = self.dic.find(core.normalize(src), before, after)
            if ne:
                ne.note = note
            self.save_dict()
            self._fill_dict()

    def delete_entries(self):
        sel = self.dict_tv.selection()
        if not sel or not messagebox.askyesno(APP_NAME, f"{len(sel)} 件を削除しますか？"):
            return
        self._backup_dict()
        for s in sel:
            if s in self._row_keys:
                self.dic.remove(*self._row_keys[s])
        self.save_dict()
        self._fill_dict()

    def import_dict(self):
        p = filedialog.askopenfilename(title="取り込む辞書", filetypes=[("辞書ファイル", "*.json")])
        if not p:
            return
        try:
            other = core.Dictionary.load(p)
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"読み込めませんでした。\n{ex}")
            return
        self._backup_dict()
        added, skipped = self.dic.merge(other)
        self.save_dict()
        self._fill_dict()
        messagebox.showinfo(APP_NAME, f"{added} 件を取り込みました。\n"
                                      f"（すでにある {skipped} 件は、自分の辞書を優先して残しました）")

    def restore_dict(self):
        files = core.list_backups(BACKUP_DIR)
        kept = core.list_kept(BACKUP_DIR)
        labels = []
        for p in files:
            m = re.search(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", os.path.basename(p))
            labels.append(f"{m[1]}/{m[2]}/{m[3]} {m[4]}:{m[5]}:{m[6]}" if m else os.path.basename(p))
        for p, text in kept:
            files.append(p)
            labels.append(f"［保管］{text}")
        if not files:
            messagebox.showinfo(APP_NAME, "バックアップはまだありません。\n\n"
                                "辞書のバックアップは、起動したときと、削除・取り込み・戻すの前に、"
                                f"自動で作られます（{os.path.basename(BACKUP_DIR)} フォルダ・新しい{BACKUP_KEEP}個まで）。")
            return
        w = tk.Toplevel(self.root)
        w.title("辞書をバックアップから戻す")
        w.transient(self.root)
        ttk.Label(w, text="戻したい時点を選んでください（新しい順）。今の辞書も、戻す前にバックアップに残します。\n"
                          "［保管］は、新しい版を初めて起動する前・各月の最初の状態です。古い順に消えずに残ります。",
                  padding=(10, 8)).pack(anchor="w")
        lb = tk.Listbox(w, height=10, width=64, font=self.fonts["ui"], activestyle="none", exportselection=False)
        lb.pack(fill="both", expand=True, padx=10)
        ttk.Label(w, text="この時点に戻すと、今の辞書がこう変わります：", padding=(10, 6, 10, 2)).pack(anchor="w")
        det = tk.Text(w, height=8, width=64, font=self.fonts["ui"], wrap="none", relief="solid", bd=1)
        det.pack(fill="both", expand=True, padx=10)
        for tg, col in (("add", "#2a7a2a"), ("del", MSG_STYLE["crit"]["fg"]), ("chg", MSG_STYLE["warn"]["fg"])):
            det.tag_configure(tg, foreground=col)
        diffs = []
        for p, when in zip(files, labels):
            try:
                d = core.Dictionary.load(p)
                diff = core.dict_diff(self.dic, d)
                a, r, c = (len(x) for x in diff)
                summary = "今と同じ" if not (a or r or c) else f"戻すと：＋{a}　－{r}　変更{c}"
                lb.insert("end", f"{when}　　{len(d.entries)} 件　　（{summary}）")
            except Exception:
                diff = None
                lb.insert("end", f"{when}　　読めません")
            diffs.append(diff)

        def show(_e=None):
            sel = lb.curselection()
            det.configure(state="normal")
            det.delete("1.0", "end")
            diff = diffs[sel[0]] if sel else None
            if diff is None:
                det.insert("end", "このバックアップは読めません。" if sel else "")
            else:
                add, rem, chg = diff
                lines = ([("add", f"＋ 増える：{e.src} → {e.dst}") for e in add]
                         + [("del", f"－ 消える：{e.src} → {e.dst}") for e in rem]
                         + [("chg", f"△ 変わる：{a_.src}：{a_.dst} → {b_.dst}") for a_, b_ in chg])
                if not lines:
                    det.insert("end", "今の辞書と同じです（戻しても変わりません）。")
                for tg, line in lines[:300]:
                    det.insert("end", line + "\n", tg)
                if len(lines) > 300:
                    det.insert("end", f"…ほか {len(lines) - 300} 件")
            det.configure(state="disabled")
        lb.bind("<<ListboxSelect>>", show)
        lb.selection_set(0)
        show()

        def do_restore():
            sel = lb.curselection()
            if not sel:
                return
            p = files[sel[0]]
            try:
                d = core.Dictionary.load(p)
            except Exception as ex:
                messagebox.showerror(APP_NAME, f"このバックアップは読めませんでした。\n{ex}", parent=w)
                return
            if not messagebox.askyesno(APP_NAME, f"辞書を「{labels[sel[0]]}」の状態"
                                                 f"（{len(d.entries)} 件）に戻しますか？\n今の辞書は、バックアップに残します。", parent=w):
                return
            self.save_dict()
            self._backup_dict()
            self.dic = d
            self.save_dict()
            self._fill_dict()
            w.destroy()
            self._refresh_status(f"辞書をバックアップから戻しました（{len(d.entries)} 件）")

        bf = ttk.Frame(w, padding=10)
        bf.pack(fill="x")
        ttk.Button(bf, text="この時点に戻す", style="Big.TButton", command=do_restore).pack(side="left")
        ttk.Button(bf, text="フォルダを開く", command=lambda: self._open_path(BACKUP_DIR)).pack(side="left", padx=6)
        ttk.Button(bf, text="閉じる", command=w.destroy).pack(side="right")
        lb.bind("<Double-1>", lambda e: do_restore())
        w.bind("<Escape>", lambda e: w.destroy())
        w.grab_set()

    def _open_path(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"開けませんでした。\n{path}\n{ex}")

    def export_dict(self):
        p = filedialog.asksaveasfilename(title="辞書を書き出す", defaultextension=".json",
                                         initialfile="accent_dict_export.json",
                                         filetypes=[("辞書ファイル", "*.json")])
        if p:
            self.dic.save(p)

    def open_numbers(self):
        try:
            if sys.platform.startswith("win"):
                os.startfile(NUM_PATH)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", NUM_PATH])
            else:
                subprocess.Popen(["xdg-open", NUM_PATH])
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"開けませんでした。\n{NUM_PATH}\n{ex}")

    def reload_numbers(self):
        try:
            self.numbers = core.load_numbers(NUM_PATH)
            self._refresh_status("数字の読み表を再読み込みしました")
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"numbers.json を読めませんでした。\n{ex}")


    # ── タブ4: 設定 ─────────────────────────────────
    def _build_settings(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="　設定　")
        self.settings_tab = tab
        hd = ttk.Frame(tab)
        hd.pack(anchor="w")
        ttk.Label(hd, text="試聴（AquesTalkPlayer）", font=self.fonts["title"]).pack(side="left")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="AquesTalkPlayer.exe の場所:").pack(side="left")
        e = ttk.Entry(row, textvariable=self.player_path, font=self.f_ui)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<FocusOut>", lambda ev: self._save_conf())
        ttk.Button(row, text="参照…", command=self.browse_player).pack(side="left")
        b = ttk.Button(row, text="AquesTalkPlayer を開く", command=self.open_player)
        b.pack(side="left", padx=(6, 0))
        if not IS_WINDOWS:
            b.state(["disabled"])
        ttk.Label(tab, textvariable=self.preset_info, foreground="#444", wraplength=960).pack(anchor="w")
        note = ("AquesTalkPlayerは株式会社アクエストのソフトです。このツールには同梱していないので、"
                "公式サイトから各自で入手してください。個人の非営利使用は無料です。それ以外の利用では使用ライセンスが必要になる場合があるので、"
                "必ず公式サイトでご確認ください。\n"
                "声は、変換タブの「声（プリセット）」にAquesTalkPlayerのプリセット名を入れて選びます。"
                "AquesTalkPlayerで自分のキャラクター用のプリセットを作れば、その名前も使えます。\n"
                "【大事】最初からある「まりさ」「れいむ」は棒読みがオンで、変更しても次の起動で元に戻ります。"
                "アクセントを効かせるには、［AquesTalkPlayerを開く］で開き、「棒読み」を外して［Add］で"
                "自分用のプリセット（例：まりさ抑揚）を作り、その名前を変換タブの「声（プリセット）」に入れてください。")
        if not IS_WINDOWS:
            note += "\n\n※ AquesTalkPlayerは Windows 用のソフトなので、この環境では試聴できません。"
        self._help(hd, "試聴（AquesTalkPlayer）について", note).pack(side="left", padx=8)
        ttk.Label(tab, text="変換タブの［▶ 試聴］に使います。「まりさ」「れいむ」のままだと棒読みになります（タイトル横の ? の印で直し方）",
                  foreground="#444").pack(anchor="w", pady=(4, 0))

        # 文字の大きさ
        ttk.Separator(tab).pack(fill="x", pady=10)
        hd = ttk.Frame(tab)
        hd.pack(anchor="w")
        ttk.Label(hd, text="文字の大きさ", font=self.fonts["title"]).pack(side="left")
        self._help(hd, "文字の大きさ", f"{round(SCALE_MIN * 100)}%〜{round(SCALE_MAX * 100)}% の間で、10% ずつ変えられます。\n"
                   "Ctrl＋マウスホイールや、Ctrl＋＋／Ctrl＋－（100%に戻すのは Ctrl＋0）でも変えられます。\n"
                   "ウィンドウも同じ割合で大きくなります。").pack(side="left", padx=8)
        fr = ttk.Frame(tab)
        fr.pack(fill="x", pady=4)
        self.scale_var = tk.IntVar(value=round(self.scale * 100))
        sp = ttk.Spinbox(fr, from_=round(SCALE_MIN * 100), to=round(SCALE_MAX * 100), increment=10, width=5,
                         textvariable=self.scale_var, font=self.fonts["ui"],
                         command=lambda: self.set_scale(self.scale_var.get() / 100))
        sp.pack(side="left")
        sp.bind("<Return>", lambda e: self._scale_from_box())
        sp.bind("<FocusOut>", lambda e: self._scale_from_box())
        ttk.Label(fr, text="%").pack(side="left", padx=(2, 12))
        for label, v in (("小 90%", 0.9), ("標準 100%", 1.0), ("大 130%", 1.3), ("特大 160%", 1.6)):
            ttk.Button(fr, text=label, command=lambda v=v: self.set_scale(v)).pack(side="left", padx=2)

        r1 = ttk.Frame(tab)
        r1.pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(r1, text="起動時に、置き場所を確かめて知らせる",
                        variable=self.check_place, command=self._save_conf).pack(side="left")
        self._help(r1, "置き場所の確認", "起動したときに、このツールが置かれている場所を確かめて、困ることがあれば知らせます。\n\n"
                   "・OneDrive などの同期フォルダ：辞書の保存が同期とぶつかって、食い違うことがあります\n"
                   "・Program Files：書き込めず、辞書や設定が保存されないことがあります\n\n"
                   "ZIP の中から開いたときと、書き込めない場所のときは、このチェックを外していても必ず知らせます"
                   "（辞書が消えたり、保存されなかったりするため）。").pack(side="left", padx=8)
        r2 = ttk.Frame(tab)
        r2.pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(r2, text="変換結果で、未確認の文節と、手で直した文節に色を付ける",
                        variable=self.phrase_colors,
                        command=lambda: (self._save_conf(), self._update_insight())).pack(side="left")
        self._help(r2, "文節の色分け", PHRASE_COLOR_HELP).pack(side="left", padx=8)

        # ショートカット
        ttk.Separator(tab).pack(fill="x", pady=10)
        hd = ttk.Frame(tab)
        hd.pack(anchor="w")
        ttk.Label(hd, text="ショートカットキー", font=self.fonts["title"]).pack(side="left")
        self._help(hd, "ショートカットキー", "行をダブルクリックするか［変更…］を押してから、割り当てたいキーを押してください。\n"
                   "Ctrl・Alt・Shift との組み合わせ、または F1〜F12 が使えます。\n"
                   "ほかの操作に使われているキーを押すと、付け替えてよいか聞きます。［外す］でキーを外し、［すべて最初に戻す］で最初の状態に戻ります。"
                   ).pack(side="left", padx=8)
        ttk.Label(tab, text="行をダブルクリックして、割り当てたいキーを押します", foreground="#444").pack(anchor="w")
        kf = ttk.Frame(tab)
        kf.pack(fill="both", expand=True, pady=4)
        tv = ttk.Treeview(kf, columns=("name", "key"), show="headings", height=7, selectmode="browse")
        tv.heading("name", text="操作")
        tv.heading("key", text="キー")
        tv.column("name", width=self._sc(420), stretch=True)
        tv.column("key", width=self._sc(180), anchor="center", stretch=False)
        ks = ttk.Scrollbar(kf, command=tv.yview)
        tv.configure(yscrollcommand=ks.set)
        tv.pack(side="left", fill="both", expand=True)
        ks.pack(side="left", fill="y")
        kb = ttk.Frame(kf)
        kb.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(kb, text="変更…", command=self.change_key).pack(fill="x")
        ttk.Button(kb, text="外す", command=self.clear_key).pack(fill="x", pady=4)
        ttk.Button(kb, text="すべて最初に戻す", command=self.reset_keys).pack(fill="x")
        tv.bind("<Double-1>", lambda e: self.change_key())
        self.keys_tv = tv
        self._fill_keys()

    def _scale_from_box(self):
        try:
            self.set_scale(int(self.scale_var.get()) / 100)
        except (tk.TclError, ValueError):
            self.scale_var.set(round(self.scale * 100))

    def _fill_keys(self):
        tv = self.keys_tv
        sel = tv.selection()
        tv.delete(*tv.get_children())
        for aid, name, _ in SHORTCUTS:
            tv.insert("", "end", iid=aid, values=(name, self._key_label(aid)))
        if sel and tv.exists(sel[0]):
            tv.selection_set(sel[0])

    def change_key(self):
        sel = self.keys_tv.selection()
        if not sel:
            return
        aid = sel[0]
        name = next(n for a, n, _ in SHORTCUTS if a == aid)
        w = tk.Toplevel(self.root)
        w.title("キーの割り当て")
        w.transient(self.root)
        ttk.Label(w, text=f"「{name}」に割り当てるキーを押してください。\n"
                          "（Ctrl・Alt・Shift との組み合わせ、または F1〜F12）\nEsc でやめます。",
                  justify="center", padding=(24, 16)).pack()
        info = tk.StringVar()
        ttk.Label(w, textvariable=info, foreground=MSG_STYLE["crit"]["fg"], padding=(16, 0, 16, 14)).pack()
        alt_bit = 0x20000 if IS_WINDOWS else 0x8

        def on_key(e):
            ctrl, shift, alt = bool(e.state & 0x4), bool(e.state & 0x1), bool(e.state & alt_bit)
            if e.keysym == "Escape" and not (ctrl or shift or alt):
                w.destroy()
                return "break"
            seq = core.shortcut_from_keys(e.keysym, ctrl, shift, alt)
            if not seq:
                if e.keysym not in core.MODIFIER_KEYS:
                    info.set("文字の入力とぶつかるので、Ctrl か Alt と組み合わせてください（F1〜F12 はそのままで使えます）")
                return "break"
            same = set(core.shortcut_variants(seq))
            others = [(a, n) for a, n, _ in SHORTCUTS if a != aid and same & set(core.shortcut_variants(self._key(a)))]
            if others and not messagebox.askyesno(
                    APP_NAME, f"{core.shortcut_label(seq)} は「{others[0][1]}」に使われています。\n"
                              f"「{others[0][1]}」の割り当てを外して、「{name}」に付けますか？", parent=w):
                return "break"
            for a, _ in others:
                self.shortcuts[a] = ""
            self.shortcuts[aid] = seq
            self._bind_shortcuts()
            self._save_conf()
            w.destroy()
            self._refresh_status(f"「{name}」を {core.shortcut_label(seq)} にしました")
            return "break"

        w.bind("<KeyPress>", on_key)
        w.grab_set()
        w.focus_force()

    def clear_key(self):
        sel = self.keys_tv.selection()
        if sel:
            self.shortcuts[sel[0]] = ""
            self._bind_shortcuts()
            self._save_conf()

    def reset_keys(self):
        if messagebox.askyesno(APP_NAME, "ショートカットキーを、すべて最初の割り当てに戻しますか？"):
            self.shortcuts = {}
            self._bind_shortcuts()
            self._save_conf()
            self._refresh_status("ショートカットキーを最初の割り当てに戻しました")

    def browse_player(self):
        cur = self.player_path.get().strip()
        p = filedialog.askopenfilename(
            title="AquesTalkPlayer.exe を選ぶ",
            initialdir=os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else None,
            filetypes=[("AquesTalkPlayer", "AquesTalkPlayer.exe"), ("実行ファイル", "*.exe"), ("すべて", "*.*")])
        if p:
            self.player_path.set(os.path.normpath(p))
            self._refresh_voice_list()
            self._save_conf()
            self._refresh_status("AquesTalkPlayer の場所を保存しました")


class EntryDialog:
    """辞書項目の入力ダイアログ。入力は全角/半角どちらでもOK（保存時にそろえる）。"""

    def __init__(self, root, app: App, title, src, dst, head, note, before="", after="",
                 suggest_before="", suggest_after=""):
        self.result = None
        w = tk.Toplevel(root)
        w.title(title)
        w.transient(root)
        w.resizable(True, False)
        w.columnconfigure(1, weight=1)
        self.w = w
        pad = {"padx": 8, "pady": 5}
        ttk.Label(w, text="YMM4側（置き換え前）").grid(row=0, column=0, sticky="w", **pad)
        ttk.Label(w, text="置き換え後").grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(w, text="メモ").grid(row=6, column=0, sticky="w", **pad)
        self.v_src, self.v_dst = tk.StringVar(value=src), tk.StringVar(value=dst)
        self.v_head, self.v_note = tk.BooleanVar(value=head), tk.StringVar(value=note)
        self.v_before, self.v_after = tk.StringVar(value=before), tk.StringVar(value=after)
        e1 = ttk.Entry(w, textvariable=self.v_src, font=app.f_entry, width=36)
        e2 = ttk.Entry(w, textvariable=self.v_dst, font=app.f_entry, width=36)
        e1.grid(row=0, column=1, sticky="ew", **pad)
        e2.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Checkbutton(w, text="句の頭でだけ置き換える（短い語の誤爆よけ）",
                        variable=self.v_head).grid(row=2, column=1, sticky="w", **pad)
        # 文脈の条件（前の語・後ろの語）。右クリックから開いたときは、前後の文節をボタン一つで入れられる
        for row, label, var, sug in ((3, "条件：直前が", self.v_before, suggest_before),
                                     (4, "条件：直後が", self.v_after, suggest_after)):
            ttk.Label(w, text=label).grid(row=row, column=0, sticky="w", **pad)
            fr = ttk.Frame(w)
            fr.grid(row=row, column=1, sticky="ew", **pad)
            ttk.Entry(fr, textvariable=var, font=app.f_entry, width=18).pack(side="left", fill="x", expand=True)
            if sug:
                ttk.Button(fr, text=f"「{sug}」を入れる", command=lambda v=var, t=sug: v.set(t)).pack(side="left", padx=(6, 0))
            ttk.Button(fr, text="消す", width=5, command=lambda v=var: v.set("")).pack(side="left", padx=(4, 0))
        ttk.Label(w, text="前後の条件を入れると、その語の直前・直後がこうなっているときだけ置き換えます"
                          "（アクセントや区切りの記号は無視して比べます。空なら条件なし）。は／わ や、同じ読みの別の言葉の誤爆よけに。",
                  foreground="#666", wraplength=app._sc(460), justify="left").grid(row=5, column=1, sticky="w", padx=8)
        ttk.Entry(w, textvariable=self.v_note, width=36).grid(row=6, column=1, sticky="ew", **pad)
        self.msg = tk.StringVar()
        ttk.Label(w, textvariable=self.msg, foreground="#a05a00").grid(row=7, column=0, columnspan=2, sticky="w", **pad)
        bf = ttk.Frame(w)
        bf.grid(row=8, column=0, columnspan=2, sticky="e", **pad)
        ttk.Button(bf, text="OK", command=self.ok).pack(side="left", padx=4)
        ttk.Button(bf, text="キャンセル", command=w.destroy).pack(side="left")
        self.v_dst.trace_add("write", lambda *a: self._check())
        self._check()
        w.bind("<Return>", lambda e: self.ok())
        w.bind("<Escape>", lambda e: w.destroy())
        (e2 if src else e1).focus_set()
        w.grab_set()
        root.wait_window(w)

    def _check(self):
        norm = core.normalize(self.v_dst.get())
        iss = core.validate(norm)
        if iss:
            self.msg.set("⚠ " + iss[0].msg)
        elif norm != self.v_dst.get() and norm:
            self.msg.set(f"保存時にそろえます → {norm}")
        else:
            self.msg.set("")

    def ok(self):
        src, dst = self.v_src.get().strip(), self.v_dst.get().strip()
        if not src or not dst:
            self.msg.set("両方入力してください")
            return
        self.result = (src, dst, bool(self.v_head.get()), self.v_note.get().strip(),
                       core.normalize(self.v_before.get()).strip(), core.normalize(self.v_after.get()).strip())
        self.w.destroy()


def main():
    try:
        from ctypes import windll  # Windowsの高DPIでぼやけないように（Tk作成前に）
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
