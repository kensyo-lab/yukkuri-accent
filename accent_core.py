"""
ゆっくりアクセント辞書 — 変換ロジック本体（GUIに依存しない部分）

流れ:
    YMM4の初期出力
      → normalize()        記号の半角/全角そろえ・空白除去・仮名の整理
      → resolve_units()    <NUMK>/ の直後の読みを単位に解決（単位辞書）。指摘も集める
      → expand_numbers()   <NUMK ...> タグを仮名に展開（数字の表＋例外表 A〜E。表は辞書の number_rules で上書き）
      → Dictionary.apply() 辞書で置き換え（最長一致・1パス）
      → validate()         AquesTalk記号列としての検査
"""
from __future__ import annotations

import copy
import csv
import datetime as _dt
import difflib
import io
import json
import os
import re
from dataclasses import dataclass, field, asdict

# ─────────────────────────────────────────────
# 記号の定義
# ─────────────────────────────────────────────
# AquesTalk 音声記号列仕様書 Ver.2.0 より
#   /  通常のアクセント句区切り（ポーズなし）
#   ,  短いポーズ　　　、 長いポーズ　　　。 ？ 文末
#   +  後ろが副次アクセント（ポーズなし）
#   ;  次の句が高く始まる（ポーズなし）
#   区切り記号は「,/」「/;」のように続けて書ける
ACCENT = "'"          # アクセント核（半角）
SEPS = "/,+;"         # アクセント句の区切り（半角）
MARKS = SEPS + ACCENT
DEVOICE = "_"         # 無声化（直後の1文字をカタカナで）
PUNCT = "、。？"       # 句読点（全角）
BOUNDARY = SEPS + PUNCT + "\n"
PLACEHOLDER = "〓"    # 自動では埋められない所（指数など）

SMALL_KANA = set("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")
# 無声化の直後に置けない音（母音・半母音・有声摩擦音）
AFTER_DEVOICE_NG = set("あいうえおやゆよわアイウエオヤユヨワざじずぜぞザジズゼゾ")

# 打ち間違えやすい記号 → AquesTalkが受け付ける形
WIDTH_MAP = {
    "’": ACCENT, "‘": ACCENT, "＇": ACCENT, "`": ACCENT, "´": ACCENT, "′": ACCENT,
    "／": "/", "＿": "_", "，": ",", "＋": "+", "；": ";",
    "?": "？", "､": "、", "｡": "。", "．": "。",
}
SPACES = " 　\t\r"

TAG_RE = re.compile(r"<[^<>\n]*>")
NUMK_RE = re.compile(r"<NUMK\b([^<>]*)>", re.IGNORECASE)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"?([^\s">]+)"?')


def is_hira(c: str) -> bool:
    return "ぁ" <= c <= "ゖ"


def is_kata(c: str) -> bool:
    return "ァ" <= c <= "ヺ"


def to_kata(c: str) -> str:
    return chr(ord(c) + 0x60) if is_hira(c) else c


def to_hira(c: str) -> str:
    return chr(ord(c) - 0x60) if ("ァ" <= c <= "ヶ") else c


# ─────────────────────────────────────────────
# 1) 正規化
# ─────────────────────────────────────────────
def _normalize_plain(s: str) -> str:
    out = []
    after_devoice = False
    for c in s:
        if c in SPACES:
            continue
        c = WIDTH_MAP.get(c, c)
        if after_devoice:
            c = to_kata(c)            # _ の直後はカタカナ
            after_devoice = False
        elif c != DEVOICE:
            c = to_hira(c)            # それ以外のカタカナはひらがなへ
        if c == DEVOICE:
            after_devoice = True
        out.append(c)
    return "".join(out)


def mark_fixes(s: str) -> list[tuple[int, str]]:
    """入力しながらその場で直す所を返す: [(位置, 直した文字)]。
    全角・似た形の記号（’ ＿ ／ ？ など）→ AquesTalk が受け付ける形、_ の直後のひらがな → カタカナ。
    normalize と違って文字数は変えない（空白の削除やカタカナ→ひらがなはしない）。<タグ> の中には触らない。"""
    tags = [(m.start(), m.end()) for m in TAG_RE.finditer(s)]
    out, prev, t = [], "", 0
    for i, c in enumerate(s):
        while t < len(tags) and tags[t][1] <= i:
            t += 1
        if t < len(tags) and tags[t][0] <= i:
            prev = c
            continue
        new = WIDTH_MAP.get(c, c)
        if prev == DEVOICE and is_hira(new):
            new = to_kata(new)
        if new != c:
            out.append((i, new))
        prev = new
    return out


def normalize(s: str) -> str:
    """記号・仮名をそろえる。<タグ> の中身には触らない。"""
    s = s.replace("\r\n", "\n")
    parts, pos = [], 0
    for m in TAG_RE.finditer(s):
        parts.append(_normalize_plain(s[pos:m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_normalize_plain(s[pos:]))
    return "".join(parts)


# ─────────────────────────────────────────────
# 2) 数字タグの展開
# ─────────────────────────────────────────────
# ここにある読み方はすべて「既定値」です。numbers.json で上書きできます。
DEFAULT_NUMBERS = {
    "_説明": "数字タグ <NUMK VAL=.. COUNTER=..> を仮名に展開するための表です。"
             "アクセント(')や区切り(/ , +)は自由に書き換えてかまいません。",
    "version": 2,

    # ── 区切り ──
    "sep_before": "/",                 # 仮名の直後に数字が来たときに入れる区切り
    "sep_before_after": {"わ": ",/"},  # 直前の文字ごとの区切り（「〜わ」の後は少し間を取る）
    "sep_between": "/",                # 数字タグが続いたときの区切り（助数詞ごとの after_sep が優先）

    # ── 整数 ──
    "zero": "ぜろ",
    "digits": {"1": "いち", "2": "に", "3": "さん", "4": "よん", "5": "ご",
               "6": "ろく", "7": "なな", "8": "はち", "9": "きゅー"},
    # 「一の位＋助数詞」でアクセントを数字の終わりに置くときの形（ろく'ねん、ご'にち）
    "digits_end": {"1": "いち'", "2": "に'", "3": "さ'ん", "4": "よ'ん", "5": "ご'",
                   "6": "ろく'", "7": "なな'", "8": "はち'", "9": "きゅ'ー"},
    "tens": {"1": "じゅ'ー", "2": "に'じゅー", "3": "さ'んじゅー", "4": "よ'んじゅー",
             "5": "ご'じゅー", "6": "ろ'くじゅー", "7": "なな'じゅー", "8": "は'ちじゅー",
             "9": "きゅ'ーじゅー"},
    "hundreds": {"1": "ひゃ'く", "2": "にひゃ'く", "3": "さ'んびゃく", "4": "よ'んひゃく",
                 "5": "ごひゃ'く", "6": "ろっぴゃ'く", "7": "なな'ひゃく", "8": "はっぴゃ'く",
                 "9": "きゅ'ー+ひゃく"},
    "thousands": {"1": "せ'ん", "2": "にせ'ん", "3": "さんぜ'ん", "4": "よんせ'ん",
                  "5": "ごせ'ん", "6": "ろくせ'ん", "7": "ななせ'ん", "8": "はっせ'ん",
                  "9": "きゅーせ'ん"},
    "thousands_in_big": {"1": "いっせん"},        # 1000万 の「千」
    "big": ["", "まん", "おく", "ちょう", "けい"],
    # 千の位がある数では、百の位を別の句にする（ないときは十の位とつなげる: にひゃくよ'んじゅー）
    "hundreds_separate_if_thousands": True,

    # ── 小数 ──
    "point": "てん",
    "point_ones": {"0": "れ'ー", "1": "い'っ", "2": "に'ー", "3": "さ'ん", "4": "よ'ん",
                   "5": "ご'ー", "6": "ろ'く", "7": "な'な", "8": "は'っ", "9": "きゅ'ー"},
    "frac_digits": {"0": "れー", "1": "いち", "2": "にー", "3": "さん", "4": "よん",
                    "5": "ごー", "6": "ろく", "7": "なな", "8": "はち", "9": "きゅー"},
    "frac_single": {"0": "れー", "2": "に", "5": "ご"},   # 小数点以下が1桁のとき
    "frac_group": 2,                                      # 小数点以下を何桁ずつ区切るか
    "frac_accent": "pair",   # "pair" = 2桁目の頭にアクセント（さんきゅ'ー）/ "none" = 付けない

    # ── 無声化（数字の読みの中だけ） ──
    "devoice": {"from": "く", "to": "_ク",
                "before": "かきくけこさしすせそたちつてとはひふへほぱぴぷぺぽ",
                "except_before": ["てん"]},

    # ── 数字の直前の語 ──
    "prefixes": {"だい": "だ'い", "やく": "や'く"},

    # ── 単位記号の化けの後始末（数字タグの直後に続く文字） ──
    "suffix_fixes": {
        "ず/": "/まいびょー/ま'いびょー",   # m/s² → 「ず/」になる
        "ず": "/ま'いびょー",               # km/s → 「ず」になる
        "/くむ": "きろめ'ーとる",           # 30億km の km → 「くむ」になる
    },
    # ── タグにする前の文字列の置き換え ──
    "raw_fixes": [
        ["かける<NUMK VAL=10>", "かけ'る/じゅ'ーの/〓じょー"],   # ×10⁶ の指数はYMM4で消えるので〓で知らせる
    ],

    # ── 助数詞 ──
    #   reading   : 助数詞の読み（省略時は COUNTER の値そのまま）
    #   mode      : digit_end = 数字の終わりにアクセント（ろく'ねん）
    #               before    = 助数詞の直前にアクセント（さんじゅ'ーど）
    #               own       = 助数詞自身のアクセントを使う（さんか'い、ななきろめ'ーとる）
    #               none      = アクセントを付けない
    #   exact     : 数全体がこの値のときの読み（助数詞込み）
    #   ones      : 一の位がこの値のときの「一の位＋助数詞」の読み
    #   tens_zero : 十の位で終わるとき（20分など）の十の位の後ろ（じゅ + っぷん）
    #   after_sep : 次に数字タグが続くときの区切り
    "big_counters": {"まん": 1, "おく": 2, "ちょう": 3},
    "counters": {
        "ねん": {"mode": "digit_end", "after_sep": ",/",
                 "ones": {"4": "よ'ねん", "7": "しち'ねん", "9": "きゅ'ーねん"}},
        "がつ": {"mode": "digit_end",
                 "ones": {"4": "し'がつ", "7": "_シちがつ", "9": "く'がつ"}},
        "にち": {"mode": "digit_end",
                 "exact": {"1": "ついたち", "2": "ふつか", "3": "みっか", "4": "よっか", "5": "いつか",
                           "6": "むいか", "7": "なのか", "8": "ようか", "9": "ここのか", "10": "とおか",
                           "14": "じゅ'ーよっか", "20": "は'つか", "24": "に'じゅー/よっか"},
                 "ones": {"4": "よっか"}},
        "じ": {"mode": "digit_end", "ones": {"4": "よ'じ", "7": "しち'じ", "9": "く'じ"}},
        "ふん": {"mode": "digit_end", "tens_zero": "っぷん",
                 "ones": {"1": "い'っぷん", "3": "さ'んぷん", "4": "よ'んぷん", "6": "ろ'っぷん",
                          "8": "は'っぷん"}},
        "びょう": {"reading": "びょー", "mode": "digit_end"},
        "ど": {"mode": "before"},
        "しょう": {"reading": "しょー", "mode": "digit_end", "tens_zero": "っしょー",
                   "ones": {"1": "い'っしょー", "8": "は'っしょー"}},
        "ばんめ": {"reading": "ば'んめ", "mode": "own"},
        "こ": {"mode": "digit_end", "tens_zero": "っこ",
               "ones": {"1": "い'っこ", "6": "ろ'っこ", "8": "は'っこ"}},
        "かい": {"reading": "か'い", "mode": "own", "tens_zero": "っか'い",
                 "ones": {"1": "いっか'い", "6": "ろっか'い", "8": "はっか'い"}},
        "つ": {"mode": "digit_end",
               "exact": {"1": "ひとつ'", "2": "ふたつ'", "3": "みっつ'", "4": "よっつ'", "5": "いつつ'",
                         "6": "むっつ'", "7": "ななつ'", "8": "やっつ'", "9": "ここのつ'", "10": "と'お"}},
        "にん": {"reading": "に'ん", "mode": "own",
                 "exact": {"1": "ひと'り", "2": "ふた'り"}, "ones": {"4": "よに'ん"}},
        "きろめーとる": {"reading": "きろめ'ーとる", "mode": "own"},
        "めーとる": {"reading": "め'ーとる", "mode": "own"},
        "せんちめーとる": {"reading": "せんちめ'ーとる", "mode": "own"},
        "きろぐらむ": {"reading": "きろぐ'らむ", "mode": "own"},
        "ぐらむ": {"reading": "ぐ'らむ", "mode": "own"},
        "こうねん": {"reading": "こ'うねん", "mode": "own"},
        "ぱーせんと": {"reading": "ぱーせ'んと", "mode": "own"},
    },
}


def merge_numbers(user: dict | None) -> dict:
    """既定の表に、ユーザーが書き換えた欄を重ねる（辞書は1段深くまで。助数詞は1つずつ丸ごと置き換え）。
    値が null（None）の欄は「未確定」として 〓 にする（変換中に使うと指摘する）"""
    table = copy.deepcopy(DEFAULT_NUMBERS)
    for k, v in (user or {}).items():
        if k == "counters" and isinstance(v, dict):
            for ck, cv in v.items():
                table["counters"][ck] = cv
        elif isinstance(v, dict) and isinstance(table.get(k), dict):
            table[k].update(v)
        else:
            table[k] = v
    for k, v in table.items():
        if isinstance(v, dict) and not k.startswith("_") and k != "counters":
            for dk, dv in v.items():
                if dv is None:
                    v[dk] = PLACEHOLDER
    return table


def load_numbers(path: str | None) -> dict:
    """既定値に numbers.json の内容を重ねる（v0.9 までの形。v1.0.0 からは辞書の number_rules を使う）"""
    user = None
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if user.get("version", 1) < 2:
            user = None           # 古い形式の表は使わない（v0.1 のもの）
    return merge_numbers(user)


def number_diff(user: dict) -> dict:
    """numbers.json（既定の表をまるごと写した物）から、既定と違う欄だけを取り出す（辞書の number_rules に移すため）。
    既定と同じ値の欄は残さない（アプリの更新で既定の表が良くなったとき、そのまま届くように）"""
    out: dict = {}
    for k, v in user.items():
        if k.startswith("_") or k == "version":
            continue
        dv = DEFAULT_NUMBERS.get(k)
        if k == "counters" and isinstance(v, dict) and isinstance(dv, dict):
            ch = {ck: cv for ck, cv in v.items() if dv.get(ck) != cv}
            if ch:
                out[k] = ch
        elif isinstance(v, dict) and isinstance(dv, dict):
            ch = {sk: sv for sk, sv in v.items() if dv.get(sk, object()) != sv}
            if ch:
                out[k] = ch
        elif v != dv:
            out[k] = v
    return out


def _plain(s: str) -> str:
    """アクセントと句内記号を外す（つなげて1句にするとき用）。"""
    return s.replace(ACCENT, "").replace("+", "")


def _first_mora_accent(s: str) -> str:
    """最初の1拍の直後に ' を置く（きゅー → きゅ'ー）。"""
    i = 1
    while i < len(s) and s[i] in SMALL_KANA:
        i += 1
    return s[:i] + ACCENT + s[i:]


def _accent_before(base: str, counter: str) -> str:
    """助数詞の直前にアクセント。ー・ん・っ で終わるときは1つ前へ（さんじゅ'ーど）。"""
    base = _plain(base)
    if len(base) > 1 and base[-1] in "ーんっ":
        return base[:-1] + ACCENT + base[-1] + counter
    return base + ACCENT + counter


def _join_counter(base: str, t: dict, counter: str, cinfo: dict, mode: str) -> str:
    reading = cinfo.get("reading", counter)
    if mode == "own":
        return _plain(base) + reading
    if mode == "before":
        return _accent_before(base, _plain(reading))
    if mode == "none":
        return _plain(base) + _plain(reading)
    return base + _plain(reading)          # digit_end: base 側のアクセントをそのまま使う


def _plain_int(n: int, t: dict) -> str:
    """アクセントなしでつなげた整数の読み（30億 の「さんじゅー」など）。"""
    if n == 0:
        return t["zero"]
    parts = []
    idx = 0
    groups = []
    while n:
        groups.append(n % 10000)
        n //= 10000
    for idx in range(len(groups) - 1, -1, -1):
        g = groups[idx]
        if not g:
            continue
        th, hu, te, on = g // 1000, g // 100 % 10, g // 10 % 10, g % 10
        s = ""
        if th:
            s += t.get("thousands_in_big", {}).get(str(th)) if (idx > 0 and str(th) in t.get("thousands_in_big", {})) \
                else _plain(t["thousands"][str(th)])
        if hu:
            s += _plain(t["hundreds"][str(hu)])
        if te:
            s += _plain(t["tens"][str(te)])
        if on:
            s += t["digits"][str(on)]
        parts.append(s + t["big"][idx])
    return "".join(parts)


def _frac_groups(frac: str, t: dict) -> list[str]:
    if len(frac) == 1:
        return [t["frac_single"].get(frac, t["frac_digits"][frac])]
    size = max(1, int(t.get("frac_group", 2)))
    out = []
    for i in range(0, len(frac), size):
        chunk = frac[i:i + size]
        words = [t["frac_digits"][d] for d in chunk]
        if t.get("frac_accent") == "pair" and len(words) >= 2:
            words[1] = _first_mora_accent(words[1])
        out.append("".join(words))
    return out


def read_number(val: str, counter: str, t: dict) -> str | None:
    counter = counter or ""
    cinfo = t.get("counters", {}).get(counter, {})
    mode = cinfo.get("mode", "digit_end" if counter else "none")
    val = val.strip().replace(",", "")
    m = re.fullmatch(r"(\d*)(?:\.(\d+))?", val)
    if not m or not (m.group(1) or m.group(2)):
        return None                       # 読めない値はタグのまま残す
    n = int(m.group(1) or "0")
    frac = m.group(2) or ""

    # 30億・130万 のように COUNTER が桁の単位のとき
    big_idx = t.get("big_counters", {}).get(counter)
    if big_idx is not None:
        s = _plain_int(n, t)
        if frac:
            s += t["point"] + "".join(t["frac_digits"][d] for d in frac)
        return s + t["big"][big_idx]

    if not frac and str(n) in cinfo.get("exact", {}):
        return cinfo["exact"][str(n)]

    phrases: list[str] = []
    high, low = n // 10000, n % 10000
    if high:
        phrases.append(_plain_int(high * 10000, t))
    th, hu, te, on = low // 1000, low // 100 % 10, low // 10 % 10, low % 10
    if th:
        phrases.append(t["thousands"][str(th)])

    # 百の位: 上の位があれば別の句、なければ次の句の頭にくっつける
    pre = ""
    if hu:
        if (th or high) and t.get("hundreds_separate_if_thousands", True):
            phrases.append(t["hundreds"][str(hu)])
        elif te == 0 and on == 0 and not frac:
            if counter:
                pre = t["hundreds"][str(hu)]          # 200年: にひゃ'くねん
            else:
                phrases.append(t["hundreds"][str(hu)])
        else:
            pre = _plain(t["hundreds"][str(hu)])

    def tens_to_sokuon(s: str) -> str:
        return s[:-1] if s.endswith("ー") else s

    # ── 小数 ──
    if frac:
        if te == 1:
            ip = pre + (_plain(t["tens"]["1"]) + t["point_ones"][str(on)] if on
                        else tens_to_sokuon(t["tens"]["1"]) + "っ")
        elif te >= 2:
            if on:
                phrases.append(pre + t["tens"][str(te)])
                ip = t["point_ones"][str(on)]
            else:
                ip = pre + tens_to_sokuon(t["tens"][str(te)]) + "っ"
        elif on or n == 0:
            ip = (_plain(pre) + _plain(t["point_ones"][str(on)])) if pre else t["point_ones"][str(on)]
        else:
            ip = pre or (phrases.pop() if phrases else "")
        phrases.append(ip + t["point"])
        groups = _frac_groups(frac, t)
        if counter:
            last = groups[-1]
            if mode in ("own", "before", "none"):
                last = _join_counter(_plain(last), t, counter, cinfo, mode)
            else:
                last = last + _plain(cinfo.get("reading", counter))
            groups[-1] = last
        phrases.extend(groups)
        return "/".join(p for p in phrases if p)

    # ── 整数 ──
    if counter:
        ones_sp = cinfo.get("ones", {})
        if te and not on:                                    # 230度 / 20分 / 10個
            base = pre + (t["tens"][str(te)] if not pre else _plain(t["tens"][str(te)]))
            tz = cinfo.get("tens_zero")
            if tz:
                b = tens_to_sokuon(base)
                last = (_plain(b) if ACCENT in tz else b) + tz
            else:
                last = _join_counter(base, t, counter, cinfo, mode)
        elif on:
            if te >= 2:
                phrases.append(pre + t["tens"][str(te)])
                pre = ""
            teen = _plain(t["tens"]["1"]) if te == 1 else ""
            head = pre + teen
            if str(on) in ones_sp:
                sp = ones_sp[str(on)]
                last = (_plain(head) + sp) if ACCENT in sp else (head + sp)
            elif mode == "digit_end":
                last = _plain(head) + t["digits_end"][str(on)] + _plain(cinfo.get("reading", counter))
            else:
                last = _join_counter(_plain(head) + t["digits"][str(on)], t, counter, cinfo, mode)
        else:                                                # 2000年 / 200年 / 0個
            if pre:
                base = pre
            elif phrases:
                base = phrases.pop()
            else:
                base = t["zero"]
            last = _join_counter(base, t, counter, cinfo, mode)
        phrases.append(last)
    else:
        if te >= 2:
            phrases.append(pre + t["tens"][str(te)])
            if on:
                phrases.append(t["digits"][str(on)])
        elif te == 1:
            phrases.append(pre + t["tens"]["1"] + (t["digits"][str(on)] if on else ""))
        elif on:
            phrases.append(pre + t["digits"][str(on)])
        elif pre:
            phrases.append(pre)
        if n == 0:
            phrases.append(t["zero"])
    return "/".join(p for p in phrases if p)


def _devoice(seg: str, t: dict) -> str:
    rule = t.get("devoice") or {}
    src, dst = rule.get("from"), rule.get("to")
    if not src or not dst:
        return seg
    before = rule.get("before", "")
    excepts = tuple(rule.get("except_before", []))
    out = []
    i = 0
    while i < len(seg):
        if seg.startswith(src, i) and (i == 0 or seg[i - 1] != DEVOICE):
            j = i + len(src)
            while j < len(seg) and seg[j] in MARKS:
                j += 1
            if j < len(seg) and seg[j] in before and not seg.startswith(excepts, j):
                out.append(dst)
                i += len(src)
                continue
        out.append(seg[i])
        i += 1
    return "".join(out)


COMMA_SPLIT_RE = re.compile(r"<NUMK\s+VAL=(\d+)\s*>,<NUMK\s+VAL=(\d{3}(?:\.\d+)?)([^<>]*)>", re.IGNORECASE)


NUM_OPEN, NUM_CLOSE = "\ue000", "\ue001"   # 学習用: 数字から作った部分の目印


def expand_numbers(s: str, t: dict, mark: bool = False, units: dict | None = None,
                   ex: dict | None = None, log: list | None = None) -> str:
    """数字タグを仮名に展開する。units（unit_table）と ex（number_exception_table）があれば、
    単位つきの数（UNIT=）と、助数詞の無い数に例外表を当てる。log には NumberHit と Finding を足す"""
    units = unit_table() if units is None else units
    ex = number_exception_table() if ex is None else ex
    # タグにする前の置き換え
    for a, b in t.get("raw_fixes", []):
        s = s.replace(a, b)
    # 「5,906.4」がYMM4で <NUMK VAL=5>,<NUMK VAL=906.4 ...> に割れるのをつなぎ直す
    while True:
        s2 = COMMA_SPLIT_RE.sub(lambda m: f"<NUMK VAL={m.group(1)}{m.group(2)}{m.group(3)}>", s)
        if s2 == s:
            break
        s = s2

    prefixes = sorted(t.get("prefixes", {}).items(), key=lambda kv: -len(kv[0]))
    fixes = sorted(t.get("suffix_fixes", {}).items(), key=lambda kv: -len(kv[0]))
    out: list[str] = []
    pos = 0
    prev_counter = None           # 直前が数字タグならその助数詞（なければ None）
    for m in NUMK_RE.finditer(s):
        if m.start() < pos:
            continue
        pre = s[pos:m.start()]
        attrs = {k.upper(): v for k, v in ATTR_RE.findall(m.group(1))}
        counter = attrs.get("COUNTER", "")
        unit = attrs.get("UNIT", "") if attrs.get("UNIT", "") in units else ""
        reading, hit = number_reading(attrs.get("VAL", ""), counter, unit, t, units, ex)
        if log is not None and hit:
            log.append(hit)
            if reading and PLACEHOLDER in reading:
                log.append(Finding("数字", "number_unfilled", hit.value,
                                   f"数字表が未確定の欄を使っています：{hit.value}（読み表の 〓 を埋めてください）", "表を埋める"))
        if reading is None:
            out.append(pre + m.group(0))
            pos = m.end()
            prev_counter = None
            continue

        seg = ""
        pv = None
        for p, v in prefixes:
            if pre.endswith(p) and (len(pre) == len(p) or pre[-len(p) - 1] in BOUNDARY):
                pre, pv = pre[:-len(p)], v
                break
        if pre:
            out.append(pre)
            prev_counter = None
        if pv is not None:
            joined = "".join(out)
            if joined and joined[-1] not in BOUNDARY:
                seg += t.get("sep_before", "/")
            seg += pv + "/"
        else:
            joined = "".join(out)
            if prev_counter is not None and not pre:
                cinfo = t.get("counters", {}).get(prev_counter, {})
                seg += cinfo.get("after_sep", t.get("sep_between", "/"))
            elif joined and joined[-1] not in BOUNDARY:
                seg += t.get("sep_before_after", {}).get(joined[-1], t.get("sep_before", "/"))
        seg += reading
        pos = m.end()
        for k, v in fixes:
            if s.startswith(k, pos):
                seg += v
                pos += len(k)
                break
        seg = _devoice(seg, t)
        out.append(NUM_OPEN + seg + NUM_CLOSE if mark else seg)
        prev_counter = counter
    out.append(s[pos:])
    return "".join(out)


# ─────────────────────────────────────────────
# 2.5) 単位の解決と、人が確かめる所の指摘
# ─────────────────────────────────────────────
# YMM4 は、知っている単位（km など）を COUNTER= にして助数詞として渡す。知らない単位は
# <NUMK VAL=n>/えぶ のように、数字との間に / を入れて「読み」で渡してくる。
# ここではその読みを単位辞書で単位IDに解決し、タグに UNIT= を足して、助数詞と同じ形に揃える
# （/ を詰め、数字と一つの句にする）。単位の後に続く文字（だった・で_ス など）はそのまま残す。
@dataclass
class Finding:
    """人が確かめる所。変換結果は変えず、下のチェック結果に並べる"""
    stage: str           # どの段で見つけたか（正規化 / 英字 / 単位 …）
    kind: str            # unit_unknown / n_head / dot_number …
    text: str            # 該当する読み
    msg: str
    action: str = ""     # できる操作（読みを登録 / 単位を登録 / 目視確認 …）
    level: str = "warn"


@dataclass
class UnitHit:
    """単位に解決した所（どの読みを、どの単位に、どの表の項目で決めたか）"""
    reading: str
    unit_id: str
    origin: str          # "既定" / "辞書"


# 既定の単位。読みとアクセントが決まったものだけを置く（決まっていない単位は「未登録」として指摘する）
#   reading      : 単位の読み＋アクセント
#   ymm4_readings: YMM4 が出す読み（大文字・小文字で読みが分かれるものは、両方を書く）
DEFAULT_UNITS = {
    "electron_volt": {"reading": "でんしぼ'ると", "ymm4_readings": ["えぶ"], "source": "eV"},
    "kelvin": {"reading": "け'るびん", "ymm4_readings": ["けー"], "source": "K"},
    "astronomical_unit": {"reading": "えーゆ'ー", "ymm4_readings": ["えーゆー", "おー"], "source": "AU / au"},
}

# 単位の後ろに続いてよい語（単位の読みの後ろがこれだけなら単位とみなす。「おーきな」の「おー」などを誤って単位にしない）
UNIT_TAILS = sorted({"について", "から", "まで", "より", "には", "では", "とは", "へは",
                     "わ", "が", "を", "に", "の", "で", "と", "も", "へ", "や",
                     "だった", "でした", "で_ス", "です", "だ", "でわ", "くらい", "ぐらい", "ほど", "いじょう",
                     "いか", "いない", "みまん", "ずつ", "しか", "だけ", "など"}, key=len, reverse=True)
UNIT_FIND_MAX = 3        # これ以下の文字数の未登録の読みを「単位らしき」とみなす（「おーきな」などを拾わない）


def unit_table(user: dict | None = None) -> dict:
    """既定の単位に、辞書の unit_dictionary（単位ID → 項目）を重ねる。同じ単位IDは辞書の方が勝つ"""
    table = {uid: dict(e, origin="既定") for uid, e in DEFAULT_UNITS.items()}
    for uid, e in (user or {}).items():
        if isinstance(e, dict) and isinstance(e.get("reading"), str) and e["reading"]:
            table[uid] = dict(e, origin="辞書")
    return table


def _is_tail(s: str) -> bool:
    """s が空か、UNIT_TAILS をつなげたものか"""
    ok = [False] * (len(s) + 1)
    ok[len(s)] = True
    for i in range(len(s) - 1, -1, -1):
        ok[i] = any(s.startswith(t, i) and ok[i + len(t)] for t in UNIT_TAILS)
    return ok[0]


def _strip_tail(s: str) -> str:
    """後ろの UNIT_TAILS を外した残り（できるだけ短く。全部外れるなら空）"""
    for c in range(1, len(s) + 1):
        if _is_tail(s[c:]):
            return s[:c]
    return ""


def resolve_units(s: str, units: dict, numbers: dict | None = None) -> tuple[str, list[UnitHit], list[Finding]]:
    """<NUMK VAL=n>/読み の「読み」を単位に解決する。数字の直後（/ の後）だけを見るので、ふつうの文の読みは変えない。
    numbers の suffix_fixes が当たる所（「/くむ」など）は、今まで通りそちらに任せる"""
    index = sorted(((normalize(r), uid) for uid, e in units.items() for r in e.get("ymm4_readings", [])),
                   key=lambda x: -len(x[0]))
    fixes = tuple((numbers or {}).get("suffix_fixes", {}))
    out, hits, found, pos = [], [], [], 0
    for m in NUMK_RE.finditer(s):
        attrs = {k.upper(): v for k, v in ATTR_RE.findall(m.group(1))}
        end = m.end()
        if attrs.get("COUNTER") or attrs.get("UNIT") or not s.startswith("/", end) or (fixes and s.startswith(fixes, end)):
            continue
        j = k = end + 1
        while k < len(s) and s[k] not in BOUNDARY and s[k] != "<":
            k += 1
        phrase = s[j:k]
        hit = next(((r, uid) for r, uid in index if phrase.startswith(r) and _is_tail(phrase[len(r):])), None)
        if hit:
            r, uid = hit
            out.append(s[pos:m.start()] + m.group(0)[:-1] + f" UNIT={uid}>")
            pos = j + len(r)
            hits.append(UnitHit(r, uid, units[uid].get("origin", "")))
            continue
        stem = _strip_tail(phrase)
        if stem and stem[0] not in "んン" and len(ctx_plain(stem)) <= UNIT_FIND_MAX:
            found.append(Finding("単位", "unit_unknown", stem, f"単位らしき未登録の読み：{stem}（数字の直後）", "単位を登録"))
    out.append(s[pos:])
    return "".join(out), hits, found


# ─────────────────────────────────────────────
# 2.6) 数字の読み: 規則エンジン＋優先順位つき例外表
# ─────────────────────────────────────────────
# 例外は規則（read_number と数字の表）に書かず、必ずこの表に書く。
#   A unit      : 数字＋単位の全体          キー (value, unit)          → reading
#   B number    : 数字の読み                キー (value)                → reading（助数詞の無い数・単位つきの数）
#   C structural: 位の読み                  キー (place, digit[, final]) → reading（属性が多い方が勝つ）
#   D            : 規則（数字の表）
#   E join      : 数字と単位のつなぎ方      キー (unit | row, last)     → join（"" / "," / "/" …）・sokuon
# A があればそれで確定。なければ数字の読みを B → C → D、つなぎ方を E → 既定（連結し、核は単位側）で決める。
#   place: thousands / hundreds / tens / digits（一の位）
#   last : 数の最後の要素。一の位（または小数の最後の桁）なら "1"〜"9"、0 で終わるなら "10" "100" "1000" "10000"
#   row  : 単位の読みの頭の行（か行の単位では じゅー → じゅっ など）
EXCEPTION_KINDS = ("unit", "number", "structural", "join")
PLACES = ("thousands", "hundreds", "tens", "digits")
UNIT_ROWS = {"か": "かきくけこ", "さ": "さしすせそ", "た": "たちつてと", "は": "はひふへほ", "ぱ": "ぱぴぷぺぽ"}

# 既定の例外（耳で確かめた実例だけ。2026-10 の実測より）
DEFAULT_NUMBER_EXCEPTIONS = {
    "unit": [
        {"value": "67", "unit": "kelvin", "reading": "ろくじゅーなな/け'るびん", "note": "耳で判断"},
    ],
    "number": [],
    "structural": [],
    "join": [
        {"unit": "electron_volt", "last": "2", "join": ",", "note": "eV での実測"},
        {"unit": "electron_volt", "last": "5", "join": ",", "note": "eV での実測"},
        {"unit": "electron_volt", "last": "9", "join": "/", "note": "eV での実測"},
        {"unit": "astronomical_unit", "last": "5", "join": ",/", "note": "39.5AU の実発音"},
        {"row": "か", "last": "10", "sokuon": True, "note": "じゅっけ'るびん（いちけ'るびん は詰めない）"},
    ],
}


def _ex_key(kind: str, e: dict) -> tuple:
    if kind == "unit":
        return (_num_key(e.get("value", "")), e.get("unit", ""))
    if kind == "number":
        return (_num_key(e.get("value", "")),)
    if kind == "structural":
        return (e.get("place", ""), str(e.get("digit", "")), bool(e.get("final")))
    return (e.get("unit", ""), e.get("row", ""), str(e.get("last", "")))


def _num_key(v) -> str:
    return str(v).strip().replace(",", "")


def number_exception_table(user: dict | None = None) -> dict:
    """既定の例外に、辞書の number_exceptions を重ねる。同じキーは辞書の方が勝つ。
    "disabled": true の項目は、同じキーの既定の例外を消す"""
    out = {}
    for kind in EXCEPTION_KINDS:
        items = {}
        for origin, src in (("既定", DEFAULT_NUMBER_EXCEPTIONS), ("辞書", user or {})):
            for e in src.get(kind, []) if isinstance(src.get(kind, []), list) else []:
                if isinstance(e, dict):
                    items[_ex_key(kind, e)] = dict(e, origin=origin)
        out[kind] = [e for e in items.values() if not e.get("disabled")]
    return out


@dataclass
class NumberHit:
    """数字1つの読みを、どの段・どの項目で決めたか"""
    value: str
    counter: str          # 助数詞（COUNTER=）
    unit: str             # 単位ID（UNIT=）
    reading_by: str       # 例外 A / 例外 B / 例外 C / 規則
    join_by: str = ""     # 例外 E / 既定（単位つきのときだけ）
    entries: list = field(default_factory=list)   # 決め手になった例外の項目


def _last_token(n: int, frac: str) -> str:
    if frac:
        return frac[-1]
    if n == 0:
        return "0"
    k = 1
    while n % 10 == 0:
        n //= 10
        k *= 10
    return str(n % 10) if k == 1 else str(k)


def _cells(n: int, frac: str) -> list[tuple[str, str, bool]]:
    """万より下の4桁で使う欄 [(place, digit, 最後の要素か)]"""
    low = n % 10000
    digs = [("thousands", low // 1000), ("hundreds", low // 100 % 10), ("tens", low // 10 % 10), ("digits", low % 10)]
    used = [(p, str(d)) for p, d in digs if d]
    return [(p, d, i == len(used) - 1 and not frac) for i, (p, d) in enumerate(used)]


def _apply_structural(n: int, frac: str, t: dict, ex: dict) -> tuple[dict, list]:
    """C: 使う欄に、当たる構造の例外があれば、その欄だけ差し替えた表を返す"""
    rules = ex.get("structural", [])
    if not rules:
        return t, []
    t2, used = None, []
    for place, digit, final in _cells(n, frac):
        cands = [e for e in rules if e.get("place") == place and str(e.get("digit")) == digit
                 and (not e.get("final") or final) and isinstance(e.get("reading"), str)]
        if not cands:
            continue
        best = max(cands, key=lambda e: 1 + bool(e.get("final")))      # 属性が多い方が勝つ
        if t2 is None:
            t2 = dict(t)
        t2[place] = dict(t2[place])
        t2[place][digit] = normalize(best["reading"])
        used.append(best)
    return (t2 or t), used


def _unit_row(reading: str) -> str:
    head = ctx_plain(reading)[:1]
    return next((r for r, cs in UNIT_ROWS.items() if head and head in cs), "")


def number_reading(val: str, counter: str, unit: str, t: dict, units: dict, ex: dict) -> tuple[str | None, NumberHit | None]:
    """数字1つの読み。助数詞つきは今まで通り read_number（C だけ当てる）。単位つき・助数詞なしは A〜E を当てる"""
    v = _num_key(val)
    m = re.fullmatch(r"(\d*)(?:\.(\d+))?", v)
    if not m or not (m.group(1) or m.group(2)):
        return None, None
    n, frac = int(m.group(1) or "0"), m.group(2) or ""
    hit = NumberHit(v, counter, unit, "規則")

    if unit:
        a = next((e for e in ex.get("unit", []) if _ex_key("unit", e) == (v, unit) and isinstance(e.get("reading"), str)), None)
        if a:
            hit.reading_by, hit.entries = "例外 A", [a]
            return normalize(a["reading"]), hit

    b = None if counter else next((e for e in ex.get("number", [])
                                   if _ex_key("number", e) == (v,) and isinstance(e.get("reading"), str)), None)
    if b:
        phrases = normalize(b["reading"]).split("/")
        hit.reading_by, hit.entries = "例外 B", [b]
    else:
        t2, used = _apply_structural(n, frac, t, ex)
        if used:
            hit.reading_by, hit.entries = "例外 C", used
        r = read_number(v, counter if not unit else "", t2)
        if r is None:
            return None, None
        if not unit:
            return r, hit
        phrases = r.split("/")
        low = n % 10000
        if not frac and low // 10 % 10 >= 2 and low % 10 and len(phrases) >= 2:
            phrases[-2:] = [_plain(phrases[-2]) + _plain(phrases[-1])]   # はちじゅー/きゅー → はちじゅーきゅー（単位の前は一つの要素）
    if not unit:
        return "/".join(phrases), hit

    # ── 単位とのつなぎ方（E → 既定） ──
    ureading = normalize(units[unit]["reading"])
    last, row = _last_token(n, frac), _unit_row(ureading)
    cands = [e for e in ex.get("join", []) if str(e.get("last", "")) == last
             and (e.get("unit") == unit or (not e.get("unit") and row and e.get("row") == row))]
    e = max(cands, key=lambda e: 2 if e.get("unit") else 1) if cands else None    # 単位ごとの方が、行のまとめより先
    join, sokuon = (e.get("join", ""), bool(e.get("sokuon"))) if e else ("", False)
    hit.join_by = "例外 E" if e else "既定"
    if e:
        hit.entries = hit.entries + [e]
    final = phrases[-1]
    if sokuon:
        final = _plain(final)
        if final.endswith("ー"):
            final = final[:-1] + "っ"
    phrases[-1] = (_plain(final) + ureading) if not join else (final + join + ureading)
    return "/".join(p for p in phrases if p), hit


DOT_NUMBER_RE = re.compile(r"<NUMK\b([^<>]*)>\.(?:<NUMK\b([^<>]*)>|(\d+))", re.IGNORECASE)


def number_findings(s: str) -> list[Finding]:
    """数字の後に「.数字」が続く所（802.11n などの規格名・版番号の可能性。YMM4 は小数として読まない）"""
    out = []
    for m in DOT_NUMBER_RE.finditer(s):
        a = dict((k.upper(), v) for k, v in ATTR_RE.findall(m.group(1))).get("VAL", "")
        b = dict((k.upper(), v) for k, v in ATTR_RE.findall(m.group(2) or "")).get("VAL", m.group(3) or "")
        text = f"{a}.{b}"
        out.append(Finding("正規化", "dot_number", text,
                           f"数字の後に「.数字」があります：{text}（規格名・版番号の可能性。読みを確かめてください）", "目視確認"))
    return out


def english_findings(s: str) -> list[Finding]:
    """英字の読み間違いらしき所。文節の頭の「ん」は、日本語にはまず無いので、英字由来とみなす（802.11n の n など）"""
    out = []
    tags = [(m.start(), m.end()) for m in TAG_RE.finditer(s)]
    for i, c in enumerate(s):
        if c not in "んン" or any(a <= i < b for a, b in tags):
            continue
        if i == 0 or s[i - 1] in BOUNDARY or s[i - 1] == ">":
            k = i
            while k < len(s) and s[k] not in BOUNDARY and s[k] != "<":
                k += 1
            out.append(Finding("英字", "n_head", s[i:k], f"文節の頭に「ん」があります：{s[i:k]}（英字の読み間違いの可能性）",
                               "読みを登録"))
    return out


# ─────────────────────────────────────────────
# 3) 辞書
# ─────────────────────────────────────────────
@dataclass
class Entry:
    src: str                 # YMM4側（置き換え前）
    dst: str                 # 置き換え後
    head_only: bool = False  # 句の頭でだけ当てる（短い語の誤爆よけ）
    note: str = ""
    added: str = ""
    hits: int = 0
    before: str = ""         # 文脈の条件: 直前がこれで終わるときだけ当てる（空なら条件なし）
    after: str = ""          # 文脈の条件: 直後がこれで始まるときだけ当てる（空なら条件なし）
    # この版が知らない項目（新しい版で増えた情報など）。読み込んだまま保存し直して、消さないようにする
    extra: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def key(self) -> tuple[str, str, str]:
        """同じ YMM4側でも、前後の条件が違えば別の項目"""
        return self.src, self.before, self.after

    def to_json(self):
        d = {"from": self.src, "to": self.dst}
        if self.before:
            d["before"] = self.before
        if self.after:
            d["after"] = self.after
        if self.head_only:
            d["head_only"] = True
        if self.note:
            d["note"] = self.note
        if self.added:
            d["added"] = self.added
        if self.hits:
            d["hits"] = self.hits
        for k, v in self.extra.items():
            d.setdefault(k, v)
        return d

    KNOWN = {"from", "to", "before", "after", "head_only", "note", "added", "hits"}

    @staticmethod
    def from_json(d):
        return Entry(normalize(d["from"]), normalize(d["to"]), bool(d.get("head_only")),
                     d.get("note", ""), d.get("added", ""), int(d.get("hits", 0)),
                     normalize(d.get("before", "")), normalize(d.get("after", "")),
                     {k: v for k, v in d.items() if k not in Entry.KNOWN})


@dataclass
class Applied:
    start: int
    end: int
    entry: Entry


CTX_IGNORE = set(ACCENT + DEVOICE + SEPS + SPACES)


def ctx_plain(t: str) -> str:
    """文脈の条件を比べるための形: アクセント・無声化・区切りの記号と空白を除き、カタカナはひらがなに。
    句読点（、。？）と改行は残すので、条件は文や大きな切れ目をまたがない。"""
    return "".join(to_hira(c) for c in t if c not in CTX_IGNORE)


def ctx_match(e: "Entry", s: str, i: int, j: int) -> bool:
    """s の [i, j) に e を当ててよいか（前後の条件を見る）"""
    if e.before:
        b = ctx_plain(e.before)
        if not ctx_plain(s[max(0, i - 3 * len(e.before) - 8):i]).endswith(b):
            return False
    if e.after:
        a = ctx_plain(e.after)
        if not ctx_plain(s[j:j + 3 * len(e.after) + 8]).startswith(a):
            return False
    return True


def ctx_label(before: str, after: str) -> str:
    """前後の条件を画面に出す形（例: 前「これ」／後「の」）。条件がなければ空"""
    parts = ([f"前「{before}」"] if before else []) + ([f"後「{after}」"] if after else [])
    return "／".join(parts)


def entry_priority(e: "Entry"):
    """同じ位置で当たりうる項目を試す順番（小さいほど先）。辞書が育っても結果が変わらないよう、ここで固定する。
    1. YMM4側が長い項目（最長一致）
    2. 前後両方の条件 → 片側だけの条件 → 条件なし
    3. 同じ段なら、前後の条件に含まれる仮名の合計文字数が多い方（記号は数えない）
    4. それでも同じなら、辞書の保存順（YMM4側・前・後の並び。登録した順番には左右されない）"""
    sides = bool(e.before) + bool(e.after)
    return (-len(e.src), -sides, -(len(ctx_plain(e.before)) + len(ctx_plain(e.after))), e.key)


# ── 辞書の形式（schema）の版と移行 ──
# 形式の版は "version"（整数）で持ち、アプリの版とは切り離す。
#   1: 条件なし（v0.2〜）  2: 前後の条件つき（v0.7〜。項目の形は1と同じ）
#   3: 英字読み辞書・単位辞書・数字の表の欄を持つ（v1.0.0〜）
#
# 移行の決まり:
# 1. 辞書の中身を壊さない。
# 2. 古い項目の意味を推測で変えない。
# 3. 知らない情報はできるだけ残す。
# 4. 移行は1段ずつ行う。
# 5. このアプリが分かるより新しい形式の辞書は、書き込まない（読み取り専用で開く）。
SCHEMA_VERSION = 3
SECTIONS = ("english_dictionary", "unit_dictionary", "number_rules", "number_exceptions")


class DictionaryMigrationError(Exception):
    pass


class FutureSchemaError(DictionaryMigrationError):
    pass


class ReadOnlyDictionaryError(Exception):
    pass


def schema_version(data: dict) -> int:
    """辞書の形式の版。無ければ 1。整数以外（true や "2" など）は受け付けない"""
    if "version" not in data:
        return 1
    v = data["version"]
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise DictionaryMigrationError(f"辞書の形式の版 {v!r} が正しくありません（1 以上の整数のはずです）。")
    return v


def migrate_1_to_2(data: dict) -> dict:
    """1 と 2 は項目の形が同じ。版だけを上げる"""
    new = copy.deepcopy(data)
    new["version"] = 2
    return new


def migrate_2_to_3(data: dict) -> dict:
    """新しい欄を空で足す。今ある項目（entries）には触らない"""
    new = copy.deepcopy(data)
    for k in SECTIONS:
        new.setdefault(k, {})
    new["version"] = 3
    return new


MIGRATIONS = {1: migrate_1_to_2, 2: migrate_2_to_3}


def migrate_dictionary(data: dict) -> tuple[dict, bool]:
    """最新の形式へ1段ずつ移行する。戻り値: (移行後, 移行したか)。元の data は変えない"""
    version = schema_version(data)
    if version > SCHEMA_VERSION:
        raise FutureSchemaError(f"辞書の形式 {version} は、このアプリが分かる {SCHEMA_VERSION} より新しい形式です。")
    changed = False
    result = copy.deepcopy(data)
    while version < SCHEMA_VERSION:
        migrate = MIGRATIONS.get(version)
        if migrate is None:
            raise DictionaryMigrationError(f"形式 {version} からの移行処理がありません。")
        result = migrate(result)
        version = schema_version(result)
        changed = True
    return result, changed


def validate_dictionary(data) -> None:
    """読み込んだ辞書の形を確かめる（おかしければ DictionaryMigrationError）"""
    if not isinstance(data, dict):
        raise DictionaryMigrationError("辞書ファイルの形が正しくありません。")
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise DictionaryMigrationError("辞書の entries が一覧になっていません。")
    for i, e in enumerate(entries):
        if not isinstance(e, dict) or not isinstance(e.get("from"), str) or not isinstance(e.get("to"), str):
            raise DictionaryMigrationError(f"辞書の {i + 1} 件目の項目が正しくありません。")
    if schema_version(data) <= SCHEMA_VERSION:
        for k in SECTIONS:
            if k in data and not isinstance(data[k], dict):
                raise DictionaryMigrationError(f"辞書の {k} の形が正しくありません。")


class Dictionary:
    FORMAT = "yukkuri-accent-dict"
    VERSION = SCHEMA_VERSION     # この版が分かる辞書の形式の版
    KNOWN = {"format", "version", "name", "entries", "created_with", "last_saved_with", *SECTIONS}

    def __init__(self, name: str = "マイ辞書"):
        self.name = name
        self.entries: list[Entry] = []
        self._index: dict[str, list[Entry]] | None = None
        self.file_version = 0        # 読み込んだファイルの形式の版（0: ファイルから読んでいない）
        self.migrated_from: int | None = None   # 読み込み時に移行したなら、元の形式の版
        self.sections: dict = {k: {} for k in SECTIONS}
        self.created_with = ""       # 辞書を最初に作ったアプリの版
        self.last_saved_with = ""    # 最後に保存したアプリの版
        self.extra: dict = {}        # この版が知らない、ファイル全体の情報（そのまま保存し直す）

    @property
    def newer_format(self) -> bool:
        """この版より新しい版で作られた辞書か"""
        return self.file_version > self.VERSION

    @property
    def read_only(self) -> bool:
        """新しい形式の辞書は、変換には使えるが、登録・保存はしない（知らない形式を書き換えて壊さないため）"""
        return self.newer_format

    def _check_writable(self):
        if self.read_only:
            raise ReadOnlyDictionaryError(f"辞書の形式 {self.file_version} は、この版が分かる {self.VERSION} "
                                          "より新しいため、読み取り専用で開いています。")

    # 入出力 ---------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Dictionary":
        """読み込んで、古い形式ならメモリ上で最新の形式に移行する（ファイルは書き換えない。open_dictionary を参照）。
        新しい形式なら移行せず、読み取り専用にする"""
        d = cls()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise DictionaryMigrationError("辞書ファイルの形が正しくありません。")
            d.file_version = schema_version(data)
            if d.file_version <= SCHEMA_VERSION:
                data, migrated = migrate_dictionary(data)
                if migrated:
                    d.migrated_from = d.file_version
            validate_dictionary(data)
            d.name = data.get("name", d.name)
            d.entries = [Entry.from_json(e) for e in data.get("entries", [])]
            d.sections = {k: copy.deepcopy(data.get(k, {})) for k in SECTIONS}
            d.created_with = data.get("created_with", "")
            d.last_saved_with = data.get("last_saved_with", "")
            d.extra = {k: v for k, v in data.items() if k not in cls.KNOWN}
        return d

    def to_data(self, app_version: str = "") -> dict:
        data = {"format": self.FORMAT, "version": SCHEMA_VERSION}
        if not self.created_with and self.file_version == 0 and app_version:
            self.created_with = app_version      # この版で新しく作った辞書（古い辞書の作成元は推測しない）
        if self.created_with:
            data["created_with"] = self.created_with
        if app_version:
            self.last_saved_with = app_version
        if self.last_saved_with:
            data["last_saved_with"] = self.last_saved_with
        data["name"] = self.name
        data["entries"] = [e.to_json() for e in sorted(self.entries, key=lambda e: e.key)]
        for k in SECTIONS:
            data[k] = copy.deepcopy(self.sections.get(k, {}))
        for k, v in self.extra.items():
            data.setdefault(k, v)
        return data

    def save(self, path: str, app_version: str = ""):
        """同じフォルダの一時ファイルに書いてから置き換える（途中で止まっても、元の辞書が半端にならない）"""
        self._check_writable()
        data = self.to_data(app_version)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def unit_table(self) -> dict:
        """既定の単位に、この辞書の単位辞書（unit_dictionary）を重ねた表"""
        return unit_table(self.sections.get("unit_dictionary"))

    def number_table(self) -> dict:
        """既定の数字の表に、この辞書の number_rules（書き換えた欄だけ）を重ねた表"""
        return merge_numbers(self.sections.get("number_rules"))

    def exception_table(self) -> dict:
        """既定の例外に、この辞書の number_exceptions を重ねた表"""
        return number_exception_table(self.sections.get("number_exceptions"))

    # 編集 -----------------------------------------------------------
    def find(self, src: str, before: str = "", after: str = "") -> Entry | None:
        """YMM4側と前後の条件が同じ項目（条件を省くと、条件なしの項目）"""
        for e in self.entries:
            if e.key == (src, before, after):
                return e
        return None

    def upsert(self, src: str, dst: str, head_only: bool = False, note: str = "",
               before: str = "", after: str = "") -> str:
        self._check_writable()
        src, dst = normalize(src), normalize(dst)
        before, after = normalize(before).strip(), normalize(after).strip()
        e = self.find(src, before, after)
        self._index = None
        if e:
            if e.dst == dst and e.head_only == head_only:
                return "same"
            e.dst, e.head_only = dst, head_only
            if note:
                e.note = note
            return "updated"
        self.entries.append(Entry(src, dst, head_only, note, _dt.date.today().isoformat(), 0, before, after))
        return "added"

    def remove(self, src: str, before: str = "", after: str = ""):
        self._check_writable()
        self.entries = [e for e in self.entries if e.key != (src, before, after)]
        self._index = None

    def merge(self, other: "Dictionary") -> tuple[int, int]:
        """他の辞書を取り込む。自分の既存項目は優先（上書きしない）。
        使用回数は持ち込まず 0 から数え、登録日は取り込んだ日にする（元の辞書の作者の利用記録を混ぜない）。"""
        self._check_writable()
        added = skipped = 0
        today = _dt.date.today().isoformat()
        for e in other.entries:
            if self.find(*e.key):
                skipped += 1
            else:
                ne = copy.copy(e)
                ne.hits, ne.added = 0, today
                self.entries.append(ne)
                added += 1
        self._index = None
        return added, skipped

    # 適用 -----------------------------------------------------------
    def _build_index(self):
        idx: dict[str, list[Entry]] = {}
        for e in self.entries:
            if e.src:
                idx.setdefault(e.src[0], []).append(e)
        for v in idx.values():
            v.sort(key=entry_priority)
        self._index = idx

    def apply(self, s: str, skip: "Entry | None" = None) -> tuple[str, list[Applied]]:
        """辞書を当てる。skip の項目は無いものとして扱う（競合チェックで「これが無かったら」を試すため）。
        使用回数はここでは数えない（count_usage で、同じ台詞を何度変換しても1回と数える）"""
        if self._index is None:
            self._build_index()
        out, applied = [], []
        olen = 0
        i = 0
        while i < len(s):
            hit = None
            for e in self._index.get(s[i], ()):
                if e is not skip and s.startswith(e.src, i):
                    if e.head_only and i > 0 and s[i - 1] not in BOUNDARY:
                        continue
                    if (e.before or e.after) and not ctx_match(e, s, i, i + len(e.src)):
                        continue
                    hit = e
                    break
            if hit:
                out.append(hit.dst)
                applied.append(Applied(olen, olen + len(hit.dst), hit))
                olen += len(hit.dst)
                i += len(hit.src)
            else:
                out.append(s[i])
                olen += 1
                i += 1
        return "".join(out), applied


# ─────────────────────────────────────────────
# 4) 検査
# ─────────────────────────────────────────────
@dataclass
class Issue:
    level: str   # "error" / "warn"
    start: int
    end: int
    msg: str


def _allowed(c: str) -> bool:
    return is_hira(c) or is_kata(c) or c in "ー" or c in MARKS or c in PUNCT or c in (DEVOICE, "\n")


def validate(s: str) -> list[Issue]:
    issues: list[Issue] = []
    tag_spans = [(m.start(), m.end()) for m in TAG_RE.finditer(s)]
    for a, b in tag_spans:
        issues.append(Issue("warn", a, b, "展開されていないタグがあります"))

    def in_tag(i):
        return any(a <= i < b for a, b in tag_spans)

    phrase_start = 0
    accent_seen = -1
    prev = ""
    for i, c in enumerate(s):
        if in_tag(i):
            prev = c
            continue
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if c == PLACEHOLDER:
            issues.append(Issue("error", i, i + 1, "〓 の所は自動で埋められません（例: ×10⁶ なら〓を「ろく」に）"))
        elif c == "！" or c == "!":
            issues.append(Issue("error", i, i + 1, "「！」は音声記号列では使えません（。 か ？ にしてください）"))
        elif not _allowed(c):
            issues.append(Issue("error", i, i + 1, f"AquesTalkで使えない文字「{c}」"))
        if c == DEVOICE:
            if not (is_kata(nxt) or is_hira(nxt)):
                issues.append(Issue("error", i, i + 1, "_ の直後に仮名がありません"))
            else:
                after = s[i + 2] if i + 2 < len(s) else ""
                if after in AFTER_DEVOICE_NG:
                    issues.append(Issue("warn", i, i + 3, f"無声化の直後に「{after}」は置けません（仕様の制限）"))
        if c == ACCENT:
            if i == phrase_start:
                issues.append(Issue("error", i, i + 1, "' が句の先頭にあります"))
            elif prev in (ACCENT, DEVOICE):
                issues.append(Issue("error", i, i + 1, f"「{prev}」の直後に ' があります"))
            if accent_seen >= 0:
                issues.append(Issue("error", i, i + 1, "1つのアクセント句に ' が2つ以上あります（/ や , などで文節区切りを行ってください）"))
            accent_seen = i
            if nxt in SMALL_KANA:
                issues.append(Issue("warn", i, i + 2, "' が拗音（ゃゅょ など）の途中にあります"))
        if c in ("っ", "ッ") and nxt in ("っ", "ッ"):
            issues.append(Issue("error", i, i + 2, "「っ」が続いています（仕様の制限）"))
        if c in ("っ", "ッ") and nxt == "ー":
            issues.append(Issue("error", i, i + 2, "「っ」の直後に「ー」は置けません（仕様の制限）"))
        if c in BOUNDARY:
            if c in SEPS and i > 0 and s[i - 1] == c:
                issues.append(Issue("warn", i - 1, i + 1, f"区切り「{c}{c}」が重なっています"))
            phrase_start = i + 1
            accent_seen = -1
        elif i == phrase_start:
            if c == "ー":
                issues.append(Issue("error", i, i + 1, "句の先頭に「ー」は置けません（仕様の制限）"))
            elif c in SMALL_KANA:
                issues.append(Issue("warn", i, i + 1, "句の先頭が小さい仮名です"))
        prev = c
    issues.sort(key=lambda x: (x.start, x.level))
    return issues


# ─────────────────────────────────────────────
# 4.5) 文節（アクセント句）の分解と、アクセントの付け替え
# ─────────────────────────────────────────────
# アクセント核を置けない拍（特殊拍）。拗音（ゃゅょ など）は直前の文字とまとめて1拍にする
NO_ACCENT = set("ーっッんン")


@dataclass
class Mora:
    start: int           # 元の文字列での位置（_ や小さい仮名を含む）
    end: int
    text: str
    can_accent: bool
    devoiced: bool = False


@dataclass
class Phrase:
    start: int
    end: int
    units: list[Mora] = field(default_factory=list)
    accents: list[int] = field(default_factory=list)   # ' の直前の拍の番号（ふつうは0か1個）
    marks: list[int] = field(default_factory=list)     # ' の位置


@dataclass
class Sep:
    start: int
    end: int
    text: str            # 区切り記号（/ 、 など）。改行は "\n" 1文字で1つ


def load_player_presets(path: str) -> list[tuple[str, bool]]:
    """AquesTalkPlayer.preset（CSV）から (プリセット名, 棒読みか) の一覧を読む。読めなければ空。
    1行目は見出し（プリセット名,棒読み,エンジン,…）。文字コードは分からないので順に試す。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    encs = ("utf-16",) if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp932")
    for enc in encs:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []
    out = []
    for row in csv.reader(io.StringIO(text)):
        name = row[0].strip() if row else ""
        if not name or name == "プリセット名":
            continue
        out.append((name, len(row) > 1 and row[1].strip().lower() == "true"))
    return out


def _join_lines(s: str) -> str:
    """試聴用に行をつなぐ。句読点で終わっていない行の後ろには「。」を補う。"""
    out = ""
    for x in (normalize(x).strip() for x in s.splitlines()):
        if not x:
            continue
        if out and out[-1] not in "。、？！,":
            out += "。"
        out += x
    return out


def preview_text(selected: str | None, whole: str) -> tuple[str, bool]:
    """試聴で読み上げる記号列を決める。選択した所に仮名が1つもなければ（改行・空白・記号だけを
    うっかり選んでいたときなど）、選択は無視して全体を読む。全体にも仮名がなければ空を返す。
    戻り値: (読み上げる記号列, 選択した所だけを読むか)"""
    def has_kana(t):
        return any(is_hira(c) or is_kata(c) for c in TAG_RE.sub("", t))
    if selected:
        t = _join_lines(selected)
        if has_kana(t):
            return t, True
    t = _join_lines(whole)
    return (t if has_kana(t) else ""), False


# ── 試聴の音量 ──────────────────────────────────
VOLUME_MIN, VOLUME_MAX, VOLUME_STEP = 0, 150, 10   # ％。100 が AquesTalkPlayer の書き出したままの大きさ


def step_volume(v: int, d: int) -> int:
    """音量を d 段（1段 = VOLUME_STEP ％）上げ下げする。端で止まり、刻みにそろえる。"""
    v = round(v / VOLUME_STEP) * VOLUME_STEP + d * VOLUME_STEP
    return max(VOLUME_MIN, min(VOLUME_MAX, v))


def scale_wav(src: str, dst: str, percent: int) -> float:
    """WAV の音量を percent ％にして dst に書く（はみ出す所は最大値で止める）。
    16ビット・8ビットの PCM に対応。それ以外の形式はそのまま写す。戻り値: 再生時間（秒）"""
    import array
    import shutil
    import sys
    import wave
    with wave.open(src, "rb") as r:
        params = r.getparams()
        frames = r.readframes(params.nframes)
    secs = params.nframes / params.framerate if params.framerate else 0.0
    g = max(0, percent) / 100
    if params.sampwidth == 2:
        a = array.array("h")
        a.frombytes(frames)
        if sys.byteorder == "big":
            a.byteswap()
        a = array.array("h", (max(-32768, min(32767, int(x * g))) for x in a))
        if sys.byteorder == "big":
            a.byteswap()
        frames = a.tobytes()
    elif params.sampwidth == 1:   # 8ビットは 128 が無音
        frames = bytes(max(0, min(255, 128 + int((x - 128) * g))) for x in frames)
    else:
        if src != dst:
            shutil.copyfile(src, dst)
        return secs
    with wave.open(dst, "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    return secs


# ── 画面に戻ったときの自動変換 ──────────────────────
_KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆]")


def looks_like_reading(s: str) -> bool:
    """クリップボードの中身が YMM4 の「読み」らしいか。仮名を含み、漢字を含まないもの。
    （ふつうの文章や、ほかのアプリでコピーした物を勝手に変換しないため）"""
    t = (s or "").strip()
    if not t or len(t) > 20000 or _KANJI_RE.search(t):
        return False
    return any(is_hira(c) or is_kata(c) for c in t)


def auto_convert_action(clip: str, seen: str | None, last_in: str, last_copied: str | None,
                        out_now: str, out_converted: str) -> str | None:
    """画面に戻ったとき、クリップボードの中身をどうするか。
    None: 何もしない（前に見た物・このツールがコピーした物・読みではない物）
    "edited": 新しい読みだが、変換結果を手直し中なので変換しない（手直しを消さないため）
    "convert": 貼り付けて変換する"""
    if clip == seen or not looks_like_reading(clip):
        return None
    c = clip.strip()
    if c in (last_in.strip(), (last_copied or "").strip(), out_now.strip()):
        return None
    if out_now.strip() and out_now != out_converted:
        return "edited"
    return "convert"


def split_phrases(s: str) -> list[Phrase | Sep]:
    """記号列を、文節（Phrase）と区切り（Sep）の並びに分ける。<タグ> は1つの拍（アクセント不可）として扱う。"""
    tags = {m.start(): m.end() for m in TAG_RE.finditer(s)}
    out: list[Phrase | Sep] = []
    cur: Phrase | None = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if i not in tags and c in BOUNDARY:
            if cur is not None:
                cur.end = i
                out.append(cur)
                cur = None
            j = i + 1
            if c != "\n":
                while j < n and j not in tags and s[j] in BOUNDARY and s[j] != "\n":
                    j += 1
            out.append(Sep(i, j, s[i:j]))
            i = j
            continue
        if cur is None:
            cur = Phrase(i, i)
        if i in tags:
            cur.units.append(Mora(i, tags[i], s[i:tags[i]], False))
            i = tags[i]
        elif c == ACCENT:
            cur.marks.append(i)
            if cur.units:
                cur.accents.append(len(cur.units) - 1)
            i += 1
        elif c == DEVOICE or is_hira(c) or is_kata(c):
            st = i
            devoiced = c == DEVOICE
            if devoiced:
                i += 1
            base = s[i] if i < n and (is_hira(s[i]) or is_kata(s[i])) else ""
            if base:
                i += 1
                while i < n and s[i] in SMALL_KANA:
                    i += 1
            ok = bool(base) and base not in NO_ACCENT and base not in SMALL_KANA
            cur.units.append(Mora(st, i, s[st:i], ok, devoiced))
        else:
            cur.units.append(Mora(i, i + 1, c, False))
            i += 1
    if cur is not None:
        cur.end = n
        out.append(cur)
    return out


def accent_edits(ph: Phrase, k: int) -> tuple[list[int], int | None]:
    """文節 ph のアクセントを k 拍目の後ろに付け替えるための編集。
    k がすでに唯一のアクセントなら外す（平板にする）。
    戻り値: (消す ' の位置のリスト, ' を入れる位置 or None)。位置は元の文字列のもの。"""
    if ph.accents == [k] and len(ph.marks) == 1:
        return list(ph.marks), None
    return list(ph.marks), ph.units[k].end


def set_accent_edits(ph: Phrase, k: int | None) -> tuple[list[int], int | None]:
    """付け外しを切り替えずに、k 拍目の後ろにアクセントを置く（k が None なら外して平板に）。"""
    if k is None:
        return list(ph.marks), None
    if ph.accents == [k] and len(ph.marks) == 1:
        return [], None        # すでにその形
    return list(ph.marks), ph.units[k].end


def is_mora(u: Mora) -> bool:
    """高低の線を描く拍か（仮名と ー。タグや 〓 などの記号は拍に数えない）"""
    t = u.text.lstrip(DEVOICE)
    return bool(t) and (is_hira(t[0]) or is_kata(t[0]) or t[0] == "ー")


def pitch_pattern(ph: Phrase, high_start: bool = False) -> list[int | None]:
    """文節の各拍の高さ（1=高 / 0=低 / None=拍ではない）。東京式アクセントの基本形:
    - 平板（' なし）: 低高高高…
    - 頭高（1拍目に '）: 高低低低…
    - それ以外: 低高…高（' の拍まで）低低…
    high_start: 前の区切りが「;」（次の句が高く始まる）のとき、1拍目を高くする。"""
    moras = [k for k, u in enumerate(ph.units) if is_mora(u)]
    out: list[int | None] = [None] * len(ph.units)
    if not moras:
        return out
    pos = None                       # アクセント核が何拍目か
    if ph.accents:
        k = ph.accents[0]
        before = [j for j, m in enumerate(moras) if m <= k]
        pos = before[-1] if before else 0
    for j, m in enumerate(moras):
        if pos is None:
            out[m] = 1 if (j > 0 or high_start) else 0
        elif pos == 0:
            out[m] = 1 if j == 0 else 0
        else:
            out[m] = 1 if (0 < j <= pos or (j == 0 and high_start)) else 0
    return out


def accent_for_pitch(ph: Phrase, k: int, want_high: bool, high_start: bool = False) -> tuple[bool, int | None]:
    """高低の線の点（k 拍目）を、高く（want_high）／低くしたいときのアクセントの置き方。
    そうなる置き方（平板か、アクセントを置ける拍のどれか）の中から、今の線から変わる拍がいちばん少ないものを選ぶ。
    同じなら平板 → k に近い拍の順。戻り値: (変えるか, アクセントを置く拍 or None=平板)。"""
    now = pitch_pattern(ph, high_start)
    if now[k] is None or now[k] == (1 if want_high else 0):
        return False, None
    cur = ph.accents[0] if ph.accents else None
    best = None
    for cand in [None] + [j for j, u in enumerate(ph.units) if u.can_accent]:
        trial = Phrase(ph.start, ph.end, ph.units, [] if cand is None else [cand], [])
        pat = pitch_pattern(trial, high_start)
        if pat[k] != (1 if want_high else 0) or cand == cur:
            continue
        cost = sum(1 for a, b in zip(now, pat) if a is not None and a != b)
        key = (cost, cand is not None, abs((cand if cand is not None else k) - k))
        if best is None or key < best[0]:
            best = (key, cand)
    if best is None:
        return False, None
    return True, best[1]


def apply_accent(s: str, ph: Phrase, k: int) -> str:
    dels, ins = accent_edits(ph, k)
    chars = list(s)
    if ins is not None:
        chars.insert(ins, ACCENT)
    for d in sorted(dels, reverse=True):
        chars.pop(d if ins is None or d < ins else d + 1)
    return "".join(chars)


# ─────────────────────────────────────────────
# まとめ: 変換
# ─────────────────────────────────────────────
@dataclass
class Result:
    text: str
    applied: list[Applied] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    findings: list["Finding"] = field(default_factory=list)   # 人が確かめる所（変換はしない）
    units: list["UnitHit"] = field(default_factory=list)      # 単位に解決した所と、決め手になった項目
    numbers: list["NumberHit"] = field(default_factory=list)  # 数字ごとの、読みとつなぎ方の決め手


@dataclass
class Prepared:
    text: str
    findings: list["Finding"]
    units: list["UnitHit"]
    numbers: list["NumberHit"] = field(default_factory=list)


def preprocess(raw: str, numbers: dict, units: dict | None = None, ex: dict | None = None) -> Prepared:
    """辞書を当てる直前の形と、各段の指摘。units は unit_table()、ex は number_exception_table() の表
    （省略すると既定のものだけ）"""
    units = unit_table() if units is None else units
    s = normalize(raw)
    findings = number_findings(s)
    s, hits, unit_found = resolve_units(s, units, numbers)
    findings += english_findings(s) + unit_found
    log: list = []
    text = expand_numbers(s, numbers, units=units, ex=ex, log=log)
    findings += [x for x in log if isinstance(x, Finding)]
    return Prepared(text, findings, hits, [x for x in log if isinstance(x, NumberHit)])


def prepare(raw: str, numbers: dict, units: dict | None = None, ex: dict | None = None) -> str:
    """辞書を当てる直前の形（正規化＋単位の解決＋数字展開）。学習でも同じものを使う。"""
    return preprocess(raw, numbers, units, ex).text


def convert(raw: str, dic: Dictionary, numbers: dict) -> Result:
    pre = preprocess(raw, numbers, dic.unit_table(), dic.exception_table())
    s, applied = dic.apply(pre.text)
    return Result(s, applied, validate(s), pre.findings, pre.units, pre.numbers)


# ─────────────────────────────────────────────
# 5) 学習: ビフォー/アフターから辞書候補を出す
# ─────────────────────────────────────────────
PARTICLES = sorted(["について", "から", "まで", "より", "には", "では", "とは", "へは", "のわ",
                    "わ", "が", "を", "に", "の", "で", "と", "も", "へ", "や"], key=len, reverse=True)


@dataclass
class Candidate:
    src: str
    dst: str
    kind: str            # "句" / "語" / "数字"（数字は既定で登録しない）
    head_only: bool
    status: str = "新規"  # 新規 / 登録済み / 上書き
    use: bool = True
    before: str = ""     # 前後の条件（候補を編集して付けたとき）
    after: str = ""


def _tokenize(s: str, with_pos: bool = False):
    """文字（_X は1文字扱い）と、その間の記号に分ける。"""
    chars, gaps, pos = [], [""], []
    i = 0
    while i < len(s):
        c = s[i]
        if c in MARKS:
            gaps[-1] += c
            i += 1
            continue
        pos.append(i)
        if c == DEVOICE and i + 1 < len(s):
            chars.append(s[i:i + 2])
            i += 2
        else:
            chars.append(c)
            i += 1
        gaps.append("")
    return (chars, gaps, pos) if with_pos else (chars, gaps)


def _has_sep(g: str) -> bool:
    return any(c in SEPS for c in g)


def _skel_len(s: str) -> int:
    return len(_tokenize(s)[0])


def learn(before_raw: str, after_raw: str, numbers: dict, dic: Dictionary | None = None) -> list[Candidate]:
    units = dic.unit_table() if dic else unit_table()
    ex = dic.exception_table() if dic else None
    b_units = resolve_units(normalize(before_raw), units, numbers)[0]
    b_all = expand_numbers(b_units, numbers, mark=True, units=units, ex=ex).split("\n")
    a_all = normalize(after_raw).split("\n")
    cands: list[Candidate] = []
    for bm, a in zip(b_all, a_all):
        # 目印を外しつつ、数字から作った文字の位置を覚える
        b, flags, inside = [], [], False
        for ch in bm:
            if ch == NUM_OPEN:
                inside = True
            elif ch == NUM_CLOSE:
                inside = False
            else:
                b.append(ch)
                flags.append(inside)
        cands.extend(_learn_line("".join(b), a, flags))
    # 重複をまとめ、辞書と照合
    seen, uniq = set(), []
    for c in cands:
        if (c.src, c.dst) in seen or c.src == c.dst or not c.src or PLACEHOLDER in c.src:
            continue
        seen.add((c.src, c.dst))
        if dic:
            e = dic.find(c.src)
            if e and e.dst == c.dst:
                c.status, c.use = "登録済み", False
            elif e:
                c.status = "上書き"
        uniq.append(c)
    return uniq


def _learn_line(b: str, a: str, numflags: list[bool] | None = None) -> list[Candidate]:
    bc, bg, bpos = _tokenize(b, with_pos=True)
    ac, ag = _tokenize(a)
    numflags = numflags or [False] * len(b)
    bnum = [numflags[p] for p in bpos]       # 各文字が数字から作られたか
    items = []   # (b_text, a_text, dirty)
    item_num = []
    gaps = []    # (b_gap, a_gap) — items の前の隙間
    sm = difflib.SequenceMatcher(None, bc, ac, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                gaps.append((bg[i1 + k], ag[j1 + k]))
                items.append((bc[i1 + k], ac[j1 + k], False))
                item_num.append(bnum[i1 + k])
        else:
            bt = "".join(bc[k] + (bg[k + 1] if k + 1 < i2 else "") for k in range(i1, i2))
            at = "".join(ac[k] + (ag[k + 1] if k + 1 < j2 else "") for k in range(j1, j2))
            gaps.append((bg[i1], ag[j1]))
            items.append((bt, at, True))
            item_num.append(any(bnum[i1:i2]) if i2 > i1 else (i1 > 0 and bnum[i1 - 1]))
    gaps.append((bg[-1], ag[-1]))

    def is_punct(k):
        bt, at, dirty = items[k]
        return not dirty and bt == at and bt in PUNCT

    # 区切り位置を決める
    cuts = [0]
    for k in range(1, len(items)):
        g_b, g_a = gaps[k]
        if (_has_sep(g_b) and _has_sep(g_a)) or is_punct(k - 1) or is_punct(k):
            cuts.append(k)
    cuts.append(len(items))

    out = []
    for s, e in zip(cuts, cuts[1:]):
        if s >= e or (e - s == 1 and is_punct(s)):
            continue
        bt = at = ""
        for k in range(s, e):
            if k > s:
                bt += gaps[k][0]
                at += gaps[k][1]
            bt += items[k][0]
            at += items[k][1]
        if ACCENT in gaps[e][1] and e < len(items) + 1:
            at += ACCENT
        if bt == at:
            continue
        if any(item_num[s:e]):
            # 数字の読みは numbers.json で決めるので、辞書には入れない（参考として表示）
            out.append(Candidate(bt, at, "数字", False, use=False))
            continue
        head = _skel_len(bt) <= 3
        out.append(Candidate(bt, at, "句", head))

        # 「語」の候補: 完成形の句（/ , で区切られた1かたまり）ごとに見て、
        # YMM4側でも区切りが無い範囲のものだけを、助詞を外して取り出す
        phrases = []          # (開始item, 終了item)
        ps = s
        for k in range(s + 1, e):
            if _has_sep(gaps[k][1]):
                phrases.append((ps, k))
                ps = k
        phrases.append((ps, e))
        for p0, p1 in phrases:
            if any(_has_sep(gaps[k][0]) for k in range(p0 + 1, p1)):
                continue      # YMM4側が途中で区切っている → 「句」候補に任せる
            pb = "".join(items[k][0] + (gaps[k + 1][0] if k + 1 < p1 else "") for k in range(p0, p1))
            pa = "".join(items[k][1] + (gaps[k + 1][1].replace("/", "").replace(",", "") if k + 1 < p1 else "")
                         for k in range(p0, p1))
            if ACCENT in gaps[p1][1] and p1 == e:
                pa += ACCENT
            wb, wa = _strip_particle(pb, pa)
            if ACCENT in wa and wb != wa and _skel_len(wb) >= 2 and (wb, wa) != (bt, at):
                out.append(Candidate(wb, wa, "語", _skel_len(wb) <= 3))
    return out


NO_STRIP_ENDINGS = ("こんにちわ", "こんばんわ")


def _strip_particle(b: str, a: str) -> tuple[str, str]:
    if b.endswith(NO_STRIP_ENDINGS):
        return b, a
    for p in PARTICLES:
        if b.endswith(p) and a.endswith(p) and _skel_len(a) - len(p) >= 2:
            return b[:-len(p)], a[:-len(p)]
    return b, a


# ─────────────────────────────────────────────
# 辞書のバックアップ
# ─────────────────────────────────────────────
BACKUP_PREFIX = "accent_dict_"


def backup_file(path: str, folder: str, keep: int = 20, now: _dt.datetime | None = None) -> str | None:
    """path を folder に日時つきで写す。いちばん新しいバックアップと中身が同じなら写さない。
    keep より古いものは消す。写したファイルの場所（写さなかったら None）を返す。"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    os.makedirs(folder, exist_ok=True)
    old = list_backups(folder)
    if old:
        try:
            with open(old[0], "rb") as f:
                if f.read() == data:
                    return None
        except OSError:
            pass
    stamp = (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(folder, f"{BACKUP_PREFIX}{stamp}.json")
    n = 1
    while os.path.exists(dst):            # 同じ秒に2回写すとき
        n += 1
        dst = os.path.join(folder, f"{BACKUP_PREFIX}{stamp}-{n}.json")
    with open(dst, "wb") as f:
        f.write(data)
    for p in list_backups(folder)[keep:]:
        try:
            os.remove(p)
        except OSError:
            pass
    return dst


KEEP_DIR = "keep"      # バックアップのうち、古い順に消さずに残し続けるもの（版を上げる前・月の最初）


def keep_backup(path: str, folder: str, label: str) -> str | None:
    """path を folder/keep/ に「label」の名前で写す。すでにあれば写さない（最初の1回だけを残す）。
    ふつうのバックアップ（新しい20個）は古い順に消えるので、節目の状態はこちらに残す。"""
    dst = os.path.join(folder, KEEP_DIR, f"{BACKUP_PREFIX}keep_{label}.json")
    if os.path.exists(dst) or not os.path.exists(path):
        return None
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(path, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)
    return dst


def list_kept(folder: str) -> list[tuple[str, str]]:
    """残し続けているバックアップ [(場所, 説明)]（新しい順）"""
    d = os.path.join(folder, KEEP_DIR)
    try:
        names = [n for n in os.listdir(d) if n.startswith(BACKUP_PREFIX + "keep_") and n.endswith(".json")]
    except OSError:
        return []
    out = []
    for n in names:
        label = n[len(BACKUP_PREFIX + "keep_"):-5]
        if label.startswith("before-v"):
            text = f"{label[7:]} を初めて起動する前"
        elif label.startswith("month-"):
            y, m = label[6:].split("-")[:2]
            text = f"{y}年{int(m)}月の最初"
        elif label.startswith("newer-"):
            text = "新しい版の辞書を、この版で初めて開く前"
        elif m := re.match(r"pre-migrate-schema(\d+)-to(\d+)", label):
            text = f"辞書の形式を {m.group(1)} から {m.group(2)} に移行する前"
        else:
            text = label
        p = os.path.join(d, n)
        out.append((p, text))
    out.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
    return out


def list_backups(folder: str) -> list[str]:
    """バックアップの一覧（新しい順）"""
    try:
        names = [n for n in os.listdir(folder) if n.startswith(BACKUP_PREFIX) and n.endswith(".json")]
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sorted(names, reverse=True)]


def move_numbers_into(dic: Dictionary, path: str, now: _dt.datetime | None = None) -> str | None:
    """v0.9 までの numbers.json（既定の表をまるごと写した物）のうち、既定と違う欄だけを辞書の number_rules に移す。
    移したら numbers.json は「numbers_moved_to_dict_日時.json」に名前を変えて残す（消さない）。
    辞書が読み取り専用・すでに number_rules がある・読めない ときは何もしない。戻り値: 名前を変えた先（しなければ None）"""
    if dic.read_only or not os.path.exists(path) or dic.sections.get("number_rules"):
        return None
    with open(path, encoding="utf-8") as f:
        user = json.load(f)
    if not isinstance(user, dict):
        return None
    if user.get("version", 1) >= 2:            # v0.1 の古い表は、今までも使っていなかった
        dic.sections["number_rules"] = number_diff(user)
    stamp = (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(os.path.dirname(path), f"numbers_moved_to_dict_{stamp}.json")
    os.replace(path, dst)
    return dst


def open_dictionary(path: str, folder: str, app_version: str = "",
                    now: _dt.datetime | None = None) -> Dictionary:
    """アプリの辞書を開く。古い形式なら、移行前の辞書を folder/keep/ に残してから、移行した形で保存し直す。
    バックアップを残せなかったときは、保存し直さない（次にふつうに保存するときに、新しい形式で書かれる）"""
    d = Dictionary.load(path)
    if d.migrated_from is not None and not d.read_only:
        stamp = (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
        try:
            kept = keep_backup(path, folder, f"pre-migrate-schema{d.migrated_from}-to{SCHEMA_VERSION}-{stamp}")
        except OSError:
            kept = None
        if kept:
            d.save(path, app_version)
    return d


# ─────────────────────────────────────────────
# ショートカットキー（Tk のキー名と、画面に出す名前）
# ─────────────────────────────────────────────
# 例: "<Control-Shift-Key-V>"。数字は "<Control-1>" だとマウスのボタンになるので、必ず "Key-" を付ける
KEY_NAMES = {
    "Return": "Enter", "plus": "+", "minus": "-", "equal": "=", "semicolon": ";", "colon": ":",
    "comma": ",", "period": ".", "slash": "/", "backslash": "\\", "space": "Space", "Escape": "Esc",
    "Left": "←", "Right": "→", "Up": "↑", "Down": "↓", "Prior": "PageUp", "Next": "PageDown",
    "bracketleft": "[", "bracketright": "]", "at": "@", "asciicircum": "^", "underscore": "_",
}
MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                 "Super_L", "Super_R", "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "App",
                 "ISO_Level3_Shift", "Kanji", "Hiragana_Katakana", "Muhenkan", "Henkan", "Zenkaku_Hankaku"}


def shortcut_from_keys(keysym: str, ctrl: bool, shift: bool, alt: bool) -> str | None:
    """押されたキーから、割り当てに使うキー名を作る。使えない押し方なら None。
    文字の入力とぶつからないよう、Ctrl/Alt なしで使えるのは F1〜F12 だけ。"""
    if not keysym or keysym in MODIFIER_KEYS:
        return None
    fkey = re.fullmatch(r"F([1-9]|1[0-2])", keysym)
    if not (ctrl or alt or fkey):
        return None
    if len(keysym) == 1 and keysym.isalpha():
        keysym = keysym.upper() if shift else keysym.lower()
    mods = [m for m, on in (("Control", ctrl), ("Alt", alt), ("Shift", shift)) if on]
    return "<" + "-".join(mods + ["Key", keysym]) + ">"


def shortcut_label(seq: str) -> str:
    """"<Control-Shift-Key-V>" → "Ctrl+Shift+V"。空なら "（なし）"。"""
    if not seq:
        return "（なし）"
    parts = seq.strip("<>").split("-")
    key = parts[-1]
    mods = parts[:-2] if len(parts) >= 2 and parts[-2] == "Key" else parts[:-1]
    names = {"Control": "Ctrl", "Alt": "Alt", "Shift": "Shift"}
    k = KEY_NAMES.get(key, key.upper() if len(key) == 1 else key)
    return "+".join([names.get(m, m) for m in mods] + [k])


def shortcut_variants(seq: str) -> list[str]:
    """英字キーは、大文字・小文字のどちらで届いても効くように両方を返す（CapsLock などで変わるため）"""
    m = re.fullmatch(r"<(.*-)?Key-([A-Za-z])>", seq or "")
    if not m:
        return [seq] if seq else []
    pre = m.group(1) or ""
    return [f"<{pre}Key-{m.group(2).lower()}>", f"<{pre}Key-{m.group(2).upper()}>"]


# ── 終了するときの確認 ──────────────────────────────
def unregistered_changes(out_now: str, out_converted: str, out_sent: str | None,
                         cands: list[Candidate]) -> dict[str, int | bool]:
    """閉じる前に、辞書に入っていない変更が残っていないかを調べる。

    out_now       : 変換結果の欄のいまの中身
    out_converted : 最後に［変換］したときの結果（手直しする前）
    out_sent      : 最後に［学習タブへ送る］をしたときの中身（送っていなければ None）
    cands         : 学習タブの候補

    返り値:
      "edited"  … 変換結果を手直ししたのに、まだ学習タブへ送っていない
      "pending" … 学習タブで登録にチェックしたまま、まだ辞書に登録していない候補の数
    """
    now = normalize(out_now).strip()
    edited = bool(now) and now != normalize(out_converted).strip() and (
        out_sent is None or now != normalize(out_sent).strip())
    pending = sum(1 for c in cands if c.use and c.status != "登録済み" and c.kind != "数字")
    return {"edited": edited, "pending": pending}


# ─────────────────────────────────────────────
# 置き場所の確認（起動時）
# ─────────────────────────────────────────────
# 同期フォルダの見分け方（フォルダ名の小文字）
SYNC_FOLDERS = {"dropbox": "Dropbox", "google drive": "Google ドライブ", "googledrive": "Google ドライブ",
                "マイドライブ": "Google ドライブ", "my drive": "Google ドライブ",
                "icloud drive": "iCloud Drive", "iclouddrive": "iCloud Drive"}


def _norm_path(p: str) -> str:
    return (p or "").replace("\\", "/").rstrip("/").lower()


def _under(path: str, parent: str) -> bool:
    parent = _norm_path(parent)
    return bool(parent) and (path == parent or path.startswith(parent + "/"))


def check_location(base_dir: str, env: dict | None = None, temp_dir: str = "",
                   writable: bool = True) -> list[tuple[str, str]]:
    """このツールが置かれている場所の困りごとを返す: [(大事さ, 内容)]。大事さは "crit" / "warn"。
    - crit: 一時フォルダ（ZIP を展開せずに開いた）・書き込めない … 辞書や設定が消える／保存されない
    - warn: OneDrive などの同期フォルダ・Program Files … 動きが食い違うことがある"""
    env = env or {}
    path = _norm_path(base_dir)
    parts = path.split("/")
    out: list[tuple[str, str]] = []
    in_temp = (temp_dir and _under(path, temp_dir)) or any(re.fullmatch(r"temp\d+_.*\.zip", x) for x in parts)
    if in_temp:
        out.append(("crit", "zip"))
    if not writable:
        out.append(("crit", "readonly"))
    if any(_under(path, env.get(k, "")) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")) \
            or any(x in ("program files", "program files (x86)") for x in parts):
        out.append(("warn", "programfiles"))
    sync = None
    if any(_under(path, env.get(k, "")) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")) \
            or any(x == "onedrive" or x.startswith("onedrive - ") for x in parts):
        sync = "OneDrive"
    else:
        sync = next((SYNC_FOLDERS[x] for x in parts if x in SYNC_FOLDERS), None)
    if sync:
        out.append(("warn", "sync:" + sync))
    return out


# ─────────────────────────────────────────────
# 文節の突き合わせ（右クリックの「変換直後に戻す」など）
# ─────────────────────────────────────────────
def _skeleton(s: str) -> tuple[str, list[int]]:
    """記号（' / , + ; 、 。 ？ _ 改行）を除いた仮名などの並びと、その元の位置。カタカナはひらがなにそろえる。"""
    chars, pos = [], []
    for i, c in enumerate(s):
        if c in MARKS or c in PUNCT or c in "\n" or c == DEVOICE or c in SPACES:
            continue
        chars.append(to_hira(c))
        pos.append(i)
    return "".join(chars), pos


def _phrase_spans(s: str) -> list[tuple[int, int]]:
    return [(p.start, p.end) for p in split_phrases(s) if isinstance(p, Phrase) and p.end > p.start]


def _expand(spans: list[tuple[int, int]], a: int, b: int) -> tuple[int, int]:
    """[a, b) に重なる文節をすべて含むように広げる"""
    hit = [(s, e) for s, e in spans if s < b and a < e] or [(s, e) for s, e in spans if s <= a <= e]
    return (min(s for s, _ in hit), max(e for _, e in hit)) if hit else (a, b)


def phrase_region(cur: str, ref: str, start: int, end: int) -> tuple[int, int, int, int] | None:
    """cur の文節 [start, end) に当たる ref 側の範囲を探す。記号を除いた仮名の並びで突き合わせるので、
    アクセントや区切りを変えていても対応がとれる。区切りの付け外しで文節の数が違うときは、
    両方を文節の切れ目まで広げて、まとめて対応させる。戻り値: (cur の始め, 終わり, ref の始め, 終わり)"""
    sc, pc = _skeleton(cur)
    sr, pr = _skeleton(ref)
    if not sc or not sr:
        return None
    ops = difflib.SequenceMatcher(None, sc, sr, autojunk=False).get_opcodes()
    cur_sp, ref_sp = _phrase_spans(cur), _phrase_spans(ref)

    def to_sk(pos, a, b):          # 文字の範囲 → 骨組みの範囲
        idx = [k for k, p in enumerate(pos) if a <= p < b]
        return (idx[0], idx[-1] + 1) if idx else None

    def to_chars(pos, rng):        # 骨組みの範囲 → 文字の範囲
        return pos[rng[0]], pos[rng[1] - 1] + 1

    def across(rng, forward):      # 骨組みの範囲を、相手側の骨組みの範囲へ
        a, b = rng
        lo, hi = None, None
        for tag, i1, i2, j1, j2 in ops:
            s1, e1, s2, e2 = (i1, i2, j1, j2) if forward else (j1, j2, i1, i2)
            if tag == "equal":
                ov_a, ov_b = max(a, s1), min(b, e1)
                if ov_a < ov_b:
                    na, nb = s2 + (ov_a - s1), s2 + (ov_b - s1)
                    lo, hi = (na if lo is None else min(lo, na)), (nb if hi is None else max(hi, nb))
            elif (s1 < b and a < e1) or (s1 == e1 and a < s1 < b):
                if e2 > s2:
                    lo, hi = (s2 if lo is None else min(lo, s2)), (e2 if hi is None else max(hi, e2))
        return (lo, hi) if lo is not None else None

    cs, ce = _expand(cur_sp, start, end)
    for _ in range(6):
        k = to_sk(pc, cs, ce)
        r = across(k, True) if k else None
        if not r:
            return None
        rs, re_ = _expand(ref_sp, *to_chars(pr, r))
        back = across(to_sk(pr, rs, re_), False)
        ncs, nce = _expand(cur_sp, *to_chars(pc, back)) if back else (cs, ce)
        ncs, nce = min(ncs, cs), max(nce, ce)
        if (ncs, nce) == (cs, ce):
            return cs, ce, rs, re_
        cs, ce = ncs, nce
    return cs, ce, rs, re_


# ─────────────────────────────────────────────
# 誤爆しやすい辞書の項目
# ─────────────────────────────────────────────
PARTICLE_CHARS = set("わがをにのでともへや")


def mora_count(s: str) -> int:
    """拍の数（小さい ゃゅょ などは前とまとめて1拍、ー・っ・ん は1拍。記号は数えない）"""
    return sum(1 for c in s if (is_hira(c) or is_kata(c) or c == "ー") and c not in SMALL_KANA)


def entry_warnings(e: Entry) -> list[str]:
    """辞書の項目のうち、ほかの所でも当たってしまいそうなもの（誤爆しやすいもの）の理由。
    辞書は文章のどこでも当たるので、短い語や助詞がらみの語は、長い語の中でも置き換わりやすい。"""
    if e.before or e.after:
        return []                    # 前後の条件で、当たる所が限られている
    plain = "".join(c for c in e.src if c not in MARKS and c not in PUNCT and c != DEVOICE)
    n = mora_count(plain)
    out = []
    if plain in PARTICLES:
        out.append("助詞だけ")
    elif n <= 2 and not e.head_only:
        out.append(f"短い（{n}拍）")
    if n <= 3 and not e.head_only and plain not in PARTICLES:
        if "わ" in plain:
            out.append("「わ」を含む（助詞の「は」と紛れやすい）")
        elif plain and (plain[0] in PARTICLE_CHARS or plain[-1] in PARTICLE_CHARS):
            out.append("助詞と同じ文字で始まる／終わる短い語")
    return out


def dict_diff(now: "Dictionary", other: "Dictionary") -> tuple[list[Entry], list[Entry], list[tuple[Entry, Entry]]]:
    """now を other に置き換えたら、どう変わるか: (増える項目, 消える項目, 変わる項目[(今, 置き換え後)])"""
    a = {e.key: e for e in now.entries}
    b = {e.key: e for e in other.entries}
    added = [b[k] for k in sorted(b) if k not in a]
    removed = [a[k] for k in sorted(a) if k not in b]
    changed = [(a[k], b[k]) for k in sorted(a) if k in b and (a[k].dst, a[k].head_only) != (b[k].dst, b[k].head_only)]
    return added, removed, changed


# ─────────────────────────────────────────────
# 変換結果の見える化（どの辞書が当たったか・どの文節がまだ誰にも見られていないか）
# ─────────────────────────────────────────────
# 文節の状態。「正しいかどうか」ではなく「何が起きたか」を表す（辞書が当たっても誤爆はありうる）
PHRASE_STATUS = {
    "manual": "手で直した",
    "checked": "確認済みにした",
    "risky": "誤爆しやすい辞書で直した",
    "dict": "辞書で直した",
    "unchecked": "まだ誰も触っていない",
}
_STATUS_ORDER = ("manual", "checked", "risky", "dict")   # 1つの文節に複数当てはまるときは、前の方を採る


@dataclass
class PhraseInfo:
    start: int
    end: int
    status: str                                      # PHRASE_STATUS のどれか
    entries: list = field(default_factory=list)      # この文節に当たった辞書の項目


def edited_marks(cur: str, ref: str) -> tuple[list[bool], set[int]]:
    """cur のうち、ref（変換した直後の形）から書き換わった所を調べる。
    戻り値: (cur の各文字が書き換わった・足された文字か, 文字が消された位置の集合)"""
    changed = [False] * len(cur)
    deleted: set[int] = set()
    sm = difflib.SequenceMatcher(None, cur, ref, autojunk=False)
    # a=cur, b=ref で比べる。"delete" は cur にだけある文字（足された）、"insert" は ref にだけある文字（消された）
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            for i in range(i1, i2):
                changed[i] = True
        elif tag == "insert":
            deleted.add(i1)                       # ref にあった文字が、cur の i1 の所で消えた
    return changed, deleted


def phrase_statuses(cur: str, converted: str, applied: list[tuple[int, int, "Entry"]],
                    checked: list[tuple[int, int]] = ()) -> list[PhraseInfo]:
    """変換結果 cur の文節ごとに、何が起きたかを決める。
    converted: ［変換］した直後の形（手直しを見分けるため）。空なら、まだ変換していないので空を返す
    applied:   辞書が当たった所 (始め, 終わり, 項目)。位置は cur の上で数える
    checked:   人が「確認済み」にした所 (始め, 終わり)"""
    if not converted:
        return []
    changed, deleted = edited_marks(cur, converted)
    out = []
    for p in split_phrases(cur):
        if not isinstance(p, Phrase) or p.end <= p.start:
            continue
        s, e = p.start, p.end
        found = set()
        if any(changed[s:e]) or any(s < i <= e for i in deleted):
            found.add("manual")
        if any(a < e and b > s for a, b in checked):
            found.add("checked")
        entries = []
        for a, b, en in applied:
            if a < e and b > s and all(en is not x for x in entries):   # 同じ項目は1回だけ
                entries.append(en)
        if entries:
            found.add("risky" if any(entry_warnings(en) for en in entries) else "dict")
        status = next((x for x in _STATUS_ORDER if x in found), "unchecked")
        out.append(PhraseInfo(s, e, status, entries))
    return out


def next_phrase(infos: list[PhraseInfo], pos: int, want=("unchecked", "risky"),
                backward: bool = False) -> PhraseInfo | None:
    """pos より後ろ（backward なら前）で、状態が want の文節を探す。端まで行ったら反対の端から続ける"""
    hits = [p for p in infos if p.status in want]
    if not hits:
        return None
    if backward:
        before = [p for p in hits if p.end < pos]
        return before[-1] if before else hits[-1]
    after = [p for p in hits if p.start > pos]
    return after[0] if after else hits[0]


@dataclass
class UsedEntry:
    entry: "Entry"
    count: int                 # 今回の変換で当たった回数
    risky: list[str]           # 誤爆しやすい理由（entry_warnings）。無ければ空


def used_entries(applied: list[tuple[int, int, "Entry"]]) -> list[UsedEntry]:
    """今回の変換で当たった辞書の項目を、最初に当たった順に、回数つきで並べる"""
    counts: dict[int, UsedEntry] = {}
    for _, _, e in sorted(applied, key=lambda x: x[0]):
        u = counts.get(id(e))
        if u:
            u.count += 1
        else:
            counts[id(e)] = UsedEntry(e, 1, entry_warnings(e))
    return list(counts.values())


def usage_summary(used: list[UsedEntry]) -> dict:
    """「適用 7か所（5項目）／文脈付き 2／誤爆注意 1」の数"""
    return {
        "places": sum(u.count for u in used),
        "entries": len(used),
        "context": sum(1 for u in used if u.entry.before or u.entry.after),
        "head": sum(1 for u in used if u.entry.head_only),
        "risky": sum(1 for u in used if u.risky),
    }


# ─────────────────────────────────────────────
# 使用回数（同じ台詞は、何度変換しても1回と数える）
# ─────────────────────────────────────────────
def line_key(line: str) -> str:
    """台詞1行を表す短い印。設定ファイルに「もう数えた台詞」として残すので、本文ではなくハッシュにする"""
    import hashlib
    return hashlib.sha1(normalize(line).strip().encode("utf-8")).hexdigest()[:16]


def count_usage(text: str, applied: list[Applied], seen: set[str]) -> int:
    """変換結果 text の行ごとに、まだ数えていない台詞なら、その行で当たった項目の使用回数を1ずつ増やす。
    同じ行で同じ項目が2回当たっても1回。数えた行の印は seen に足す。戻り値: 増やした回数の合計"""
    lines = text.split("\n")
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    by_line: dict[int, list[Entry]] = {}
    for a in applied:
        k = max(i for i, st in enumerate(starts) if st <= a.start)
        got = by_line.setdefault(k, [])
        if all(a.entry is not e for e in got):
            got.append(a.entry)
    n = 0
    for k, entries in by_line.items():
        key = line_key(lines[k])
        if key in seen:
            continue
        seen.add(key)
        for e in entries:
            e.hits += 1
            n += 1
    return n


# ─────────────────────────────────────────────
# 辞書の競合チェック（辞書の DRC）
# ─────────────────────────────────────────────
# 考え方: 項目ごとに「その項目が当たるはずの、いちばん短い文」を作り、本物の辞書で変換してみる。
# 優先順位の規則を書き直して判定するのではなく、変換そのものを使うので、判定と本番がずれない。
PROBE_MARK = "〓"    # 試しの文の頭に置く、どの項目にも当たらない文字（句頭のみの項目が文頭で当たらないように）

CONFLICT_LEVEL = {"error": "効かない", "warn": "無駄・要確認", "info": "お知らせ"}


@dataclass
class Conflict:
    level: str                 # "error" / "warn" / "info"
    kind: str                  # 短い種類名（一覧の列）
    entry: Entry               # 問題のある項目
    msg: str                   # 説明（どうすればよいかまで）
    other: Entry | None = None # 原因になっている別の項目


def _probe(e: Entry) -> tuple[str, int]:
    """e が当たるはずの最小の文と、その中で e が始まる位置"""
    before, after = normalize(e.before), normalize(e.after)
    head = PROBE_MARK + before + ("/" if e.head_only else "")   # 句頭のみの項目は、区切りの直後に置く
    return head + e.src + after, len(head)


def _label(e: Entry) -> str:
    ctx = ctx_label(e.before, e.after)
    return f"{e.src} → {e.dst}" + (f"（{ctx}）" if ctx else "") + ("（句頭のみ）" if e.head_only else "")


def dict_conflicts(dic: "Dictionary", many: int = 4) -> list[Conflict]:
    """辞書の中の競合・無駄を調べる。重いものから並べる（error → warn → info）。
    error: 条件どおりの文でも、ほかの項目が先に当たって、この項目が使われない
    warn:  何も変えない項目／無くても結果が同じ項目／置き換え後にエラーがある項目
    info:  同じ YMM4側に、条件違いの項目が many 個以上ある"""
    out: list[Conflict] = []
    if dic._index is None:
        dic._build_index()
    for e in sorted(dic.entries, key=lambda x: x.key):
        bad = [i for i in validate(e.dst) if i.level == "error"]
        if bad:
            out.append(Conflict("warn", "置き換え後にエラー", e,
                                f"置き換え後が YMM4 で正しく読まれない形です（{bad[0].msg}）。辞書タブで直してください"))
        text, at = _probe(e)
        res, applied = dic.apply(text)
        mine = [a for a in applied if a.entry is e]
        if not mine:
            # 何が先に当たったか: e の始まりを覆う当たり
            cover = next((a for a in applied if a.entry.src and
                          _src_span(text, applied, a)[0] <= at < _src_span(text, applied, a)[1]), None)
            who = cover.entry if cover else None
            if e.before or e.after:
                why = (f"条件どおりの文「{text[len(PROBE_MARK):]}」でも、" +
                       (f"長い項目「{_label(who)}」が先に当たります" if who else "ほかの項目が先に当たります") +
                       "。長い項目を消すか、長い項目に別の場面の条件を付けて、当たる所を分けてください")
            else:
                why = ("この項目だけの文でも、" + (f"「{_label(who)}」が先に当たります" if who else "ほかの項目が先に当たります"))
            out.append(Conflict("error", "ほかの項目に隠れて効かない", e, why, who))
            continue
        res2, applied2 = dic.apply(text, skip=e)
        if res2 == res:
            # 「YMM4側と置き換え後が同じ」項目でも、短い項目の誤爆よけとして働いているなら res2 != res になり、ここへは来ない
            if normalize(e.src) == normalize(e.dst):
                out.append(Conflict("warn", "何も変えない", e,
                                    "YMM4側と置き換え後が同じで、ほかの項目の誤爆よけにもなっていません。消しても結果は変わりません"))
                continue
            s0, s1 = at, at + len(e.src)
            alt = [a.entry for a in applied2 if _src_span(text, applied2, a)[0] < s1 and _src_span(text, applied2, a)[1] > s0]
            names = "・".join(dict.fromkeys(_label(x) for x in alt))
            out.append(Conflict("warn", "無くても結果が同じ", e,
                                "この項目を消しても、同じ所が同じ形になります" +
                                (f"（{names} で足りています）" if names else "") + "。整理するなら消してかまいません",
                                alt[0] if alt else None))
    by_src: dict[str, list[Entry]] = {}
    for e in dic.entries:
        by_src.setdefault(e.src, []).append(e)
    for src, es in sorted(by_src.items()):
        if len(es) >= many:
            out.append(Conflict("info", "条件違いが多い", es[0],
                                f"「{src}」には条件違いの項目が {len(es)} 個あります。意図どおりか、ときどき見直してください"))
    order = {"error": 0, "warn": 1, "info": 2}
    out.sort(key=lambda c: order[c.level])
    return out


def _src_span(text: str, applied: list[Applied], a: Applied) -> tuple[int, int]:
    """当たり a が、元の文 text のどこからどこまでを置き換えたか（apply の結果の位置から逆算）"""
    i = o = 0
    for x in applied:
        # 当たりの前の、置き換えなかった部分は1文字ずつ進む
        gap = x.start - o
        i += gap
        o = x.start
        if x is a:
            return i, i + len(x.entry.src)
        i += len(x.entry.src)
        o = x.end
    return -1, -1


# ─────────────────────────────────────────────
# 台本単位の一括チェック（1行 = 1台詞として、行ごとにまとめる）
# ─────────────────────────────────────────────
@dataclass
class LineReport:
    no: int            # 1 から数える行番号
    start: int         # 変換結果の上での位置
    end: int
    text: str
    places: int        # 辞書で置き換えた所の数
    unchecked: int     # 未確認の文節
    risky: int         # 誤爆注意の文節
    manual: int        # 手で直した文節
    errors: int
    warns: int

    @property
    def todo(self) -> bool:
        """まだ人が見るべき所が残っているか"""
        return bool(self.unchecked or self.risky or self.errors)


def line_reports(text: str, infos: list[PhraseInfo], applied: list[tuple[int, int, "Entry"]],
                 issues: list[Issue]) -> list[LineReport]:
    """変換結果を行ごとにまとめる。空の行は飛ばす"""
    out = []
    pos = 0
    for no, ln in enumerate(text.split("\n"), 1):
        s, e = pos, pos + len(ln)
        pos = e + 1
        if not ln.strip():
            continue
        inside = [p for p in infos if s <= p.start < e or (p.start == s and p.end <= e)]
        out.append(LineReport(
            no, s, e, ln,
            places=sum(1 for a, b, _ in applied if s <= a < e),
            unchecked=sum(p.status == "unchecked" for p in inside),
            risky=sum(p.status == "risky" for p in inside),
            manual=sum(p.status == "manual" for p in inside),
            errors=sum(i.level == "error" and s <= i.start <= e for i in issues),
            warns=sum(i.level != "error" and s <= i.start <= e for i in issues),
        ))
    return out


def script_summary(rows: list[LineReport]) -> dict:
    return {
        "lines": len(rows),
        "places": sum(r.places for r in rows),
        "errors": sum(r.errors for r in rows),
        "todo_lines": sum(r.todo for r in rows),
        "unchecked": sum(r.unchecked for r in rows),
        "risky": sum(r.risky for r in rows),
        "done_lines": sum(not r.todo for r in rows),
    }


# ─────────────────────────────────────────────
# アクセントの聞き比べ（A/B 試聴）
# ─────────────────────────────────────────────
@dataclass
class AccentVariant:
    k: int | None        # ' を置く拍（None は平板）
    text: str            # その形にした文節
    whole: str           # その形にした変換結果全体
    current: bool        # いまの形か


def with_accent(s: str, ph: Phrase, k: int | None) -> str:
    """文節 ph のアクセントを k 拍目の後ろだけにした s（k が None なら平板）"""
    dels, ins = set_accent_edits(ph, k)
    if not dels and ins is None:
        return s
    chars = list(s)
    if ins is not None:
        chars.insert(ins, ACCENT)
    for d in sorted(dels, reverse=True):
        chars.pop(d if ins is None or d < ins else d + 1)
    return "".join(chars)


def accent_variants(s: str, ph: Phrase) -> list[AccentVariant]:
    """文節 ph に付けられるアクセントの形を全部並べる（平板 → 1拍目 → 2拍目 …）"""
    cur_k = ph.accents[0] if len(ph.accents) == 1 and len(ph.marks) == 1 else (None if not ph.marks else -1)
    out = []
    for k in [None] + [i for i, u in enumerate(ph.units) if u.can_accent]:
        whole = with_accent(s, ph, k)
        d = len(whole) - len(s)
        out.append(AccentVariant(k, whole[ph.start:ph.end + d], whole, k == cur_k))
    return out


def line_at(s: str, pos: int) -> tuple[int, int]:
    """pos を含む行の範囲"""
    a = s.rfind("\n", 0, pos) + 1
    b = s.find("\n", pos)
    return a, (len(s) if b < 0 else b)


# ─────────────────────────────────────────────
# 辞書の統計
# ─────────────────────────────────────────────
def dict_stats(dic: "Dictionary", today: _dt.date | None = None, top: int = 10) -> dict:
    today = today or _dt.date.today()
    month = today.strftime("%Y-%m")
    es = dic.entries
    used = sorted((e for e in es if e.hits), key=lambda e: (-e.hits, e.key))
    return {
        "total": len(es),
        "this_month": sum(1 for e in es if e.added.startswith(month)),
        "hits_total": sum(e.hits for e in es),
        "top": used[:top],
        "unused": sorted((e for e in es if not e.hits), key=lambda e: e.key),
        "context": sum(1 for e in es if e.before or e.after),
        "head": sum(1 for e in es if e.head_only),
        "risky": sum(1 for e in es if entry_warnings(e)),
    }
