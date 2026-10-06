"""
ゆっくりアクセント辞書 — 変換ロジック本体（GUIに依存しない部分）

流れ:
    YMM4の初期出力
      → normalize()        記号の半角/全角そろえ・空白除去・仮名の整理
      → expand_numbers()   <NUMK ...> タグを仮名に展開（numbers.json の表に従う）
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


def load_numbers(path: str | None) -> dict:
    """既定値に numbers.json の内容を重ねる（辞書は1段深くまでマージ）。"""
    table = copy.deepcopy(DEFAULT_NUMBERS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        if user.get("version", 1) < 2:
            return table          # 古い形式の表は使わない（v0.1 のもの）
        for k, v in user.items():
            if k == "counters" and isinstance(v, dict):
                for ck, cv in v.items():
                    table["counters"][ck] = cv
            elif isinstance(v, dict) and isinstance(table.get(k), dict):
                table[k].update(v)
            else:
                table[k] = v
    return table


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


def expand_numbers(s: str, t: dict, mark: bool = False) -> str:
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
        reading = read_number(attrs.get("VAL", ""), counter, t)
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
        return d

    @staticmethod
    def from_json(d):
        return Entry(normalize(d["from"]), normalize(d["to"]), bool(d.get("head_only")),
                     d.get("note", ""), d.get("added", ""), int(d.get("hits", 0)),
                     normalize(d.get("before", "")), normalize(d.get("after", "")))


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


class Dictionary:
    FORMAT = "yukkuri-accent-dict"

    def __init__(self, name: str = "マイ辞書"):
        self.name = name
        self.entries: list[Entry] = []
        self._index: dict[str, list[Entry]] | None = None

    # 入出力 ---------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Dictionary":
        d = cls()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            d.name = data.get("name", d.name)
            d.entries = [Entry.from_json(e) for e in data.get("entries", [])]
        return d

    def save(self, path: str):
        data = {"format": self.FORMAT, "version": 2 if any(e.before or e.after for e in self.entries) else 1,
                "name": self.name, "entries": [e.to_json() for e in sorted(self.entries, key=lambda e: e.key)]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    # 編集 -----------------------------------------------------------
    def find(self, src: str, before: str = "", after: str = "") -> Entry | None:
        """YMM4側と前後の条件が同じ項目（条件を省くと、条件なしの項目）"""
        for e in self.entries:
            if e.key == (src, before, after):
                return e
        return None

    def upsert(self, src: str, dst: str, head_only: bool = False, note: str = "",
               before: str = "", after: str = "") -> str:
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
        self.entries = [e for e in self.entries if e.key != (src, before, after)]
        self._index = None

    def merge(self, other: "Dictionary") -> tuple[int, int]:
        """他の辞書を取り込む。自分の既存項目は優先（上書きしない）。
        使用回数は持ち込まず 0 から数え、登録日は取り込んだ日にする（元の辞書の作者の利用記録を混ぜない）。"""
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

    def apply(self, s: str) -> tuple[str, list[Applied]]:
        if self._index is None:
            self._build_index()
        out, applied = [], []
        olen = 0
        i = 0
        while i < len(s):
            hit = None
            for e in self._index.get(s[i], ()):
                if s.startswith(e.src, i):
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
                hit.hits += 1
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


def prepare(raw: str, numbers: dict) -> str:
    """辞書を当てる直前の形（正規化＋数字展開）。学習でも同じものを使う。"""
    return expand_numbers(normalize(raw), numbers)


def convert(raw: str, dic: Dictionary, numbers: dict) -> Result:
    s = prepare(raw, numbers)
    s, applied = dic.apply(s)
    return Result(s, applied, validate(s))


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
    b_all = expand_numbers(normalize(before_raw), numbers, mark=True).split("\n")
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


def list_backups(folder: str) -> list[str]:
    """バックアップの一覧（新しい順）"""
    try:
        names = [n for n in os.listdir(folder) if n.startswith(BACKUP_PREFIX) and n.endswith(".json")]
    except OSError:
        return []
    return [os.path.join(folder, n) for n in sorted(names, reverse=True)]


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
