"""
ゆっくりアクセント辞書 — tkinter GUI

使い方:
    python accent_app.py
同じフォルダに accent_dict.json（辞書）と numbers.json（数字の読み表）が作られます。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

import accent_core as core

APP_NAME = "ゆっくりアクセント辞書"
VERSION = "0.3"

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DICT_PATH = os.path.join(BASE_DIR, "accent_dict.json")
NUM_PATH = os.path.join(BASE_DIR, "numbers.json")
CONF_PATH = os.path.join(BASE_DIR, "settings.json")
# 同梱ファイル（アイコンなど）の場所: .exe では展開先、スクリプトでは同じフォルダ
RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

COL_APPLIED = "#fff2b3"
COL_ERROR = "#ffb3b3"
COL_WARN = "#ffd9a6"
COL_MK_ACCENT = "#d0342c"      # ' アクセント
COL_MK_SEP = "#8a8f98"         # / , + ; 区切り
COL_MK_DEVOICE = "#1f5fbf"     # _ 無声化

IS_WINDOWS = sys.platform.startswith("win")
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
        root.geometry("1040x720")
        root.minsize(820, 560)
        icon = os.path.join(RES_DIR, "assets", "icon.png")
        if os.path.exists(icon):
            try:
                self._icon = tk.PhotoImage(file=icon)
                root.iconphoto(True, self._icon)
            except tk.TclError:
                pass

        fam = pick_font(root)
        self.f_text = (fam, 14)
        self.f_entry = (pick_font(root, ENTRY_FONTS), 13)
        self.f_ui = (fam, 10)
        style = ttk.Style(root)
        style.configure(".", font=self.f_ui)
        style.configure("Treeview", font=(fam, 11), rowheight=26)
        style.configure("Treeview.Heading", font=(fam, 10, "bold"))
        style.configure("Big.TButton", font=(fam, 11, "bold"), padding=(12, 6))

        self._ensure_numbers_file()
        self.numbers = core.load_numbers(NUM_PATH)
        self.dic = core.Dictionary.load(DICT_PATH)
        self.conf = self._load_conf()

        self.color_marks = tk.BooleanVar(value=self.conf.get("color_marks", True))
        self.player_path = tk.StringVar(value=self.conf.get("aquestalk_player", ""))
        self._preview_gen = 0      # 試聴の世代。停止や新しい試聴で古い結果を捨てる
        self._proc = None          # 書き出し中の AquesTalkPlayer
        self._wav = None           # いま再生している一時WAV
        self._texts = []

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.nb = nb
        self._build_convert(nb)
        self._build_learn(nb)
        self._build_dict(nb)
        self._build_settings(nb)

        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, anchor="w", padding=(10, 4)).pack(fill="x")
        self._refresh_status()

        for w in (self.in_text, self.out_text):
            w.bind("<Control-Return>", lambda e: self.do_convert())
        root.bind("<Control-Return>", lambda e: self.do_convert())
        for k in ("<Control-Shift-V>", "<Control-Shift-v>"):
            root.bind_all(k, lambda e: (self.paste_and_convert(), "break")[1])
        for k in ("<Control-Shift-C>", "<Control-Shift-c>"):
            root.bind_all(k, lambda e: (self.copy_output(), "break")[1])
        root.protocol("WM_DELETE_WINDOW", self.on_close)

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
        self.conf["aquestalk_player"] = self.player_path.get().strip()
        self.conf["voice_preset"] = self.voice.get().strip()
        self.conf["voice_presets"] = list(self.voice_box["values"])
        try:
            with open(CONF_PATH, "w", encoding="utf-8") as f:
                json.dump(self.conf, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def on_close(self):
        self.stop_preview()
        self._remove_wav()
        self.save_dict()
        self._save_conf()
        self.root.destroy()

    def save_dict(self):
        try:
            self.dic.save(DICT_PATH)
        except Exception as ex:
            messagebox.showerror(APP_NAME, f"辞書を保存できませんでした。\n{ex}")

    def _refresh_status(self, extra: str = ""):
        if not hasattr(self, "status"):
            return
        s =f"辞書: {len(self.dic.entries)} 件（{os.path.basename(DICT_PATH)}）"
        if extra:
            s += "　｜　" + extra
        self.status.set(s)

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
        fam = self.f_entry[0]
        size = self.f_text[1]
        t.tag_configure("mk_acc", foreground=COL_MK_ACCENT, font=(self.f_text[0], size, "bold"))
        t.tag_configure("mk_sep", foreground=COL_MK_SEP)
        t.tag_configure("mk_dv", foreground=COL_MK_DEVOICE, font=(fam, size, "bold"))
        t.bind("<<Modified>>", lambda e, w=t: self._on_modified(w))
        self._texts.append(t)
        return frm, t

    def _repaint_all(self):
        for t in self._texts:
            self._paint_marks(t)

    def _on_modified(self, t):
        if t.edit_modified():
            t.edit_modified(False)
            t.after_idle(lambda: self._paint_marks(t))

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
        ttk.Button(top, text="貼り付けて変換（Ctrl+Shift+V）", command=self.paste_and_convert).pack(side="right", padx=6)
        frm, self.in_text = self._text(tab, 5)
        frm.pack(fill="both", expand=True, pady=(4, 8))

        mid = ttk.Frame(tab)
        mid.pack(fill="x")
        ttk.Button(mid, text="変換 ▼（Ctrl+Enter）", style="Big.TButton", command=self.do_convert).pack(side="left")
        self.auto_copy = tk.BooleanVar(value=self.conf.get("auto_copy", True))
        ttk.Checkbutton(mid, text="変換したら自動でコピー", variable=self.auto_copy).pack(side="left", padx=12)
        ttk.Checkbutton(mid, text="記号を色分け", variable=self.color_marks,
                        command=self._repaint_all).pack(side="left")

        lab = ttk.Frame(tab)
        lab.pack(fill="x", pady=(10, 0))
        ttk.Label(lab, text="② 変換結果（ここで手直しもできます）").pack(side="left")
        tk.Label(lab, text=" 辞書で置き換えた所 ", bg=COL_APPLIED, font=self.f_ui).pack(side="right")
        tk.Label(lab, text=" 注意 ", bg=COL_WARN, font=self.f_ui).pack(side="right", padx=4)
        tk.Label(lab, text=" エラー ", bg=COL_ERROR, font=self.f_ui).pack(side="right")
        frm, self.out_text = self._text(tab, 5)
        frm.pack(fill="both", expand=True, pady=(4, 6))
        self.out_text.tag_configure("applied", background=COL_APPLIED)
        self.out_text.tag_configure("warn", background=COL_WARN)
        self.out_text.tag_configure("error", background=COL_ERROR)
        self.out_text.tag_raise("sel")

        bot = ttk.Frame(tab)
        bot.pack(fill="x")
        ttk.Button(bot, text="コピー（Ctrl+Shift+C）", style="Big.TButton", command=self.copy_output).pack(side="left")
        ttk.Button(bot, text="再チェック", command=self.recheck).pack(side="left", padx=6)
        ttk.Button(bot, text="この手直しを学習タブへ送る →", command=self.send_to_learn).pack(side="right")

        pv = ttk.Frame(tab)
        pv.pack(fill="x", pady=(8, 0))
        self.btn_play = ttk.Button(pv, text="▶ 試聴", command=self.preview)
        self.btn_play.pack(side="left")
        self.btn_stop = ttk.Button(pv, text="■ 停止", command=self.stop_preview)
        self.btn_stop.pack(side="left", padx=(4, 12))
        ttk.Label(pv, text="声（プリセット）:").pack(side="left")
        presets = list(self.conf.get("voice_presets") or DEFAULT_PRESETS)
        last = self.conf.get("voice_preset", presets[0] if presets else "")
        if last and last not in presets:
            presets.insert(0, last)
        self.voice = tk.StringVar(value=last)
        self.voice_box = ttk.Combobox(pv, textvariable=self.voice, values=presets, width=16, font=self.f_ui)
        self.voice_box.pack(side="left", padx=4)
        if IS_WINDOWS:
            hint = "選択範囲があればその部分、なければ変換結果の全体を読み上げます"
        else:
            hint = "試聴は Windows 専用です（AquesTalkPlayer が Windows 用のため）"
            for w in (self.btn_play, self.btn_stop, self.voice_box):
                w.state(["disabled"])
        ttk.Label(pv, text=hint, foreground="#666").pack(side="left", padx=8)

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

    def do_convert(self):
        raw = self.in_text.get("1.0", "end-1c")
        res = core.convert(raw, self.dic, self.numbers)
        self.out_text.delete("1.0", "end")
        self.out_text.insert("1.0", res.text)
        for a in res.applied:
            self.out_text.tag_add("applied", f"1.0+{a.start}c", f"1.0+{a.end}c")
        self._show_issues(res.issues)
        if self.auto_copy.get() and res.text:
            self._copy(res.text)
        if res.applied:
            self._fill_dict()   # 使用回数の表示を更新
        n_err = sum(i.level == "error" for i in res.issues)
        n_warn = len(res.issues) - n_err
        extra = f"置き換え {len(res.applied)} か所 ／ エラー {n_err} ／ 注意 {n_warn}"
        if self.auto_copy.get() and res.text:
            extra += "　— コピーしました"
        self._refresh_status(extra)
        return "break"

    def recheck(self):
        s = self.out_text.get("1.0", "end-1c")
        norm = core.normalize(s)
        if norm != s:
            self.out_text.delete("1.0", "end")
            self.out_text.insert("1.0", norm)
        self._show_issues(core.validate(norm))
        n_err = sum(i.level == "error" for i in self._issues)
        self._refresh_status(f"再チェック: エラー {n_err} ／ 注意 {len(self._issues) - n_err}")

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

    def copy_output(self):
        s = self.out_text.get("1.0", "end-1c")
        if s:
            self._copy(core.normalize(s))
            self._refresh_status("コピーしました")
        return "break"

    def send_to_learn(self):
        self.l_before.delete("1.0", "end")
        self.l_before.insert("1.0", self.in_text.get("1.0", "end-1c"))
        self.l_after.delete("1.0", "end")
        self.l_after.insert("1.0", self.out_text.get("1.0", "end-1c"))
        self.nb.select(1)
        self.do_learn()

    # ── 試聴（AquesTalkPlayer） ─────────────────────
    def _preview_text(self) -> str:
        """選択範囲があればその部分、なければ全体。行の区切りは、句読点で終わっていなければ「。」を補う。"""
        t = self.out_text
        if t.tag_ranges("sel"):
            s = t.get("sel.first", "sel.last")
        else:
            s = t.get("1.0", "end-1c")
        out = ""
        for x in (core.normalize(x).strip() for x in s.splitlines()):
            if not x:
                continue
            if out and out[-1] not in "。、？！,":
                out += "。"
            out += x
        return out

    def _remember_voice(self, name):
        vals = [v for v in self.voice_box["values"] if v != name]
        self.voice_box["values"] = [name] + vals if name else vals

    def preview(self):
        if not IS_WINDOWS:
            return
        exe = self.player_path.get().strip()
        if not exe:
            messagebox.showinfo(APP_NAME, "試聴には AquesTalkPlayer が必要です。\n\n"
                                "「設定」タブで AquesTalkPlayer.exe の場所を指定してください。\n"
                                "（AquesTalkPlayer は株式会社アクエストの公式サイトから入手できます）")
            self.nb.select(self.settings_tab)
            return
        if not os.path.isfile(exe):
            messagebox.showerror(APP_NAME, f"AquesTalkPlayer が見つかりません。\n{exe}\n\n"
                                 "「設定」タブで AquesTalkPlayer.exe の場所を指定し直してください。")
            self.nb.select(self.settings_tab)
            return
        text = self._preview_text()
        if not text:
            messagebox.showinfo(APP_NAME, "読み上げる所がありません。\n"
                                "変換結果の欄に読みを入れてから押してください。")
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
        self._preview_said = text if len(text) <= 60 else text[:60] + "…"
        self._refresh_status("試聴: 音声を作っています…")
        threading.Thread(target=self._synth, args=(gen, args, wav, voice), daemon=True).start()

    def _synth(self, gen, args, wav, voice):
        """別スレッドで AquesTalkPlayer を動かし、終わるまで待つ。結果は画面側のスレッドへ渡す。"""
        err = None
        proc = None
        try:
            # --windowed の .exe では標準入出力が無いので、明示的に捨て先を渡す
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
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
            self._refresh_status("試聴できませんでした")
            messagebox.showerror(APP_NAME, err)
            return
        self._remember_voice(voice)   # 使えたプリセットだけ候補に残す
        self._save_conf()
        import winsound
        self._wav = wav
        try:
            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            self._refresh_status(f"試聴: 再生中 — {self._preview_said}")
        except RuntimeError as ex:
            messagebox.showerror(APP_NAME, f"音声を再生できませんでした。\n{ex}")

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
        if self._wav:
            self._remove_file(self._wav)
            self._wav = None

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
            tv.insert("", "end", iid=str(i), values=(
                "☑" if c.use else "☐", c.kind, c.src, c.dst, "○" if c.head_only else "", c.status))

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
        r = EntryDialog(self.root, self, "候補を編集", c.src, c.dst, c.head_only, "").result
        if r:
            c.src, c.dst, c.head_only, _ = r
            c.use = True
            self._fill_cands()

    def commit_candidates(self):
        cnt = {"added": 0, "updated": 0, "same": 0}
        for c in self.cands:
            if c.use:
                cnt[self.dic.upsert(c.src, c.dst, c.head_only)] += 1
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
        ttk.Button(top, text="数字の読み表を開く", command=self.open_numbers).pack(side="right")
        ttk.Button(top, text="読み表を再読み込み", command=self.reload_numbers).pack(side="right", padx=6)

        cols = ("src", "dst", "head", "hits", "added", "note")
        tv = ttk.Treeview(tab, columns=cols, show="headings", selectmode="extended")
        for c, w, txt in (("src", 300, "YMM4側"), ("dst", 300, "置き換え後"), ("head", 70, "句頭のみ"),
                          ("hits", 70, "使用回数"), ("added", 100, "登録日"), ("note", 160, "メモ")):
            tv.heading(c, text=txt, command=lambda c=c: self._sort_dict(c))
            tv.column(c, width=w, anchor="center" if c in ("head", "hits", "added") else "w",
                      stretch=c in ("src", "dst", "note"))
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
        ttk.Button(bot, text="別名で書き出す…", command=self.export_dict).pack(side="right")
        ttk.Button(bot, text="他の辞書を取り込む…", command=self.import_dict).pack(side="right", padx=6)
        self._fill_dict()

    def _sort_dict(self, col):
        self._sort_key = col
        self._fill_dict()

    def _fill_dict(self):
        tv = self.dict_tv
        tv.delete(*tv.get_children())
        q = core.normalize(self.q.get()) if hasattr(self, "q") else ""
        key = {"src": lambda e: e.src, "dst": lambda e: e.dst, "head": lambda e: not e.head_only,
               "hits": lambda e: -e.hits, "added": lambda e: e.added, "note": lambda e: e.note}[self._sort_key]
        for e in sorted(self.dic.entries, key=key):
            if q and q not in e.src and q not in e.dst and q not in e.note:
                continue
            tv.insert("", "end", iid=e.src, values=(e.src, e.dst, "○" if e.head_only else "",
                                                     e.hits or "", e.added, e.note))
        self._refresh_status()

    def add_entry(self):
        r = EntryDialog(self.root, self, "辞書に追加", "", "", False, "").result
        if r:
            src, dst, head, note = r
            if self.dic.find(core.normalize(src)) and not messagebox.askyesno(
                    APP_NAME, "同じ「YMM4側」の項目があります。上書きしますか？"):
                return
            self.dic.upsert(src, dst, head, note)
            self.save_dict()
            self._fill_dict()

    def edit_entry(self):
        sel = self.dict_tv.selection()
        if not sel:
            return
        e = self.dic.find(sel[0])
        if not e:
            return
        r = EntryDialog(self.root, self, "辞書を編集", e.src, e.dst, e.head_only, e.note).result
        if r:
            src, dst, head, note = r
            if core.normalize(src) != e.src:
                self.dic.remove(e.src)
            self.dic.upsert(src, dst, head, note)
            ne = self.dic.find(core.normalize(src))
            if ne:
                ne.note = note
            self.save_dict()
            self._fill_dict()

    def delete_entries(self):
        sel = self.dict_tv.selection()
        if not sel or not messagebox.askyesno(APP_NAME, f"{len(sel)} 件を削除しますか？"):
            return
        for s in sel:
            self.dic.remove(s)
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
        added, skipped = self.dic.merge(other)
        self.save_dict()
        self._fill_dict()
        messagebox.showinfo(APP_NAME, f"{added} 件を取り込みました。\n"
                                      f"（すでにある {skipped} 件は、自分の辞書を優先して残しました）")

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
        ttk.Label(tab, text="試聴（AquesTalkPlayer）", font=(self.f_ui[0], 11, "bold")).pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="AquesTalkPlayer.exe の場所:").pack(side="left")
        e = ttk.Entry(row, textvariable=self.player_path, font=self.f_ui)
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<FocusOut>", lambda ev: self._save_conf())
        ttk.Button(row, text="参照…", command=self.browse_player).pack(side="left")
        note = ("AquesTalkPlayer は株式会社アクエストのソフトです。このツールには同梱していないので、"
                "公式サイトから各自で入手してください（個人の非営利使用は無料、営利目的には使用ライセンスの購入が必要です）。\n"
                "声は、変換タブの「声（プリセット）」に AquesTalkPlayer のプリセット名を入れて選びます。"
                "AquesTalkPlayer で自分のキャラクター用のプリセットを作れば、その名前も使えます。")
        if not IS_WINDOWS:
            note += "\n\n※ AquesTalkPlayer は Windows 用のソフトなので、この環境では試聴できません。"
        ttk.Label(tab, text=note, foreground="#444", wraplength=960, justify="left").pack(anchor="w", pady=(4, 0))

    def browse_player(self):
        cur = self.player_path.get().strip()
        p = filedialog.askopenfilename(
            title="AquesTalkPlayer.exe を選ぶ",
            initialdir=os.path.dirname(cur) if cur and os.path.isdir(os.path.dirname(cur)) else None,
            filetypes=[("AquesTalkPlayer", "AquesTalkPlayer.exe"), ("実行ファイル", "*.exe"), ("すべて", "*.*")])
        if p:
            self.player_path.set(os.path.normpath(p))
            self._save_conf()
            self._refresh_status("AquesTalkPlayer の場所を保存しました")


class EntryDialog:
    """辞書項目の入力ダイアログ。入力は全角/半角どちらでもOK（保存時にそろえる）。"""

    def __init__(self, root, app: App, title, src, dst, head, note):
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
        ttk.Label(w, text="メモ").grid(row=3, column=0, sticky="w", **pad)
        self.v_src, self.v_dst = tk.StringVar(value=src), tk.StringVar(value=dst)
        self.v_head, self.v_note = tk.BooleanVar(value=head), tk.StringVar(value=note)
        e1 = ttk.Entry(w, textvariable=self.v_src, font=app.f_entry, width=36)
        e2 = ttk.Entry(w, textvariable=self.v_dst, font=app.f_entry, width=36)
        e1.grid(row=0, column=1, sticky="ew", **pad)
        e2.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Checkbutton(w, text="句の頭でだけ置き換える（短い語の誤爆よけ）",
                        variable=self.v_head).grid(row=2, column=1, sticky="w", **pad)
        ttk.Entry(w, textvariable=self.v_note, width=36).grid(row=3, column=1, sticky="ew", **pad)
        self.msg = tk.StringVar()
        ttk.Label(w, textvariable=self.msg, foreground="#a05a00").grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        bf = ttk.Frame(w)
        bf.grid(row=5, column=0, columnspan=2, sticky="e", **pad)
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
        self.result = (src, dst, bool(self.v_head.get()), self.v_note.get().strip())
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
