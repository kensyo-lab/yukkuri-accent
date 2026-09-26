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
import datetime as _dt
import difflib
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

    def to_json(self):
        d = {"from": self.src, "to": self.dst}
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
                     d.get("note", ""), d.get("added", ""), int(d.get("hits", 0)))


@dataclass
class Applied:
    start: int
    end: int
    entry: Entry


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
        data = {"format": self.FORMAT, "version": 1, "name": self.name,
                "entries": [e.to_json() for e in sorted(self.entries, key=lambda e: e.src)]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    # 編集 -----------------------------------------------------------
    def find(self, src: str) -> Entry | None:
        for e in self.entries:
            if e.src == src:
                return e
        return None

    def upsert(self, src: str, dst: str, head_only: bool = False, note: str = "") -> str:
        src, dst = normalize(src), normalize(dst)
        e = self.find(src)
        self._index = None
        if e:
            if e.dst == dst and e.head_only == head_only:
                return "same"
            e.dst, e.head_only = dst, head_only
            if note:
                e.note = note
            return "updated"
        self.entries.append(Entry(src, dst, head_only, note, _dt.date.today().isoformat()))
        return "added"

    def remove(self, src: str):
        self.entries = [e for e in self.entries if e.src != src]
        self._index = None

    def merge(self, other: "Dictionary") -> tuple[int, int]:
        """他の辞書を取り込む。自分の既存項目は優先（上書きしない）。"""
        added = skipped = 0
        for e in other.entries:
            if self.find(e.src):
                skipped += 1
            else:
                self.entries.append(copy.copy(e))
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
            v.sort(key=lambda e: -len(e.src))
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
                issues.append(Issue("error", i, i + 1, "1つのアクセント句に ' が2つ以上あります（/ で区切ってください）"))
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
