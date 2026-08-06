# -*- coding: utf-8 -*-
"""
動画「同じ家を47か所に置いたら、冷暖房費はいくら変わるか」の全計算。

このファイル1つで、04と05のCSVを作り直せます。
必要なのは Python 3 だけ。追加ライブラリは要りません。

    python3 calc.py

同じフォルダの 01・02・03 のCSVを読み、
    04_結果_年間冷暖房費_47都道府県.csv
    05_検証_感度分析_729通り.csv
を書き出します（同名ファイルは上書きされます）。

────────────────────────────────────────────────────────
計算の背骨（動画の主張そのもの）
────────────────────────────────────────────────────────
1. 必要な熱量は「度日」で決まる。気温と基準温度の差を、年間ぶん足し上げる
2. エアコンの効率(COP)は外気温で変わる。寒いほど落ち、霜取りでさらに落ちる
3. 電気単価は地域で違う。寒い地方ほど高い傾向があり、差が掛け算になる

前提（47都道府県すべてで固定。ここを地域で変えないのがこの企画の核）
  延べ床面積 120m2・2階建て想定
  断熱等級5（UA=0.60 W/m2K）
  外皮面積 307m2 → 貫流損失 184.2 W/K
  換気 0.5回/h × 気積288m3 × 0.35Wh/m3K → 50.4 W/K
  熱損失係数 H = 234.6 W/K
  設定温度 冬20℃ / 夏27℃
  度日の基準温度 暖房18℃ / 冷房24℃
    （内部発熱と日射で室温は外気より上がるため、設定温度から2〜3K引くのが
      度日法の標準的な扱い。D18・D24は日本で慣用される基準）

COPモデル
  暖房: 15℃→5.5 / 7℃→4.6 / 2℃→3.8 / -7℃→2.8 / -15℃→2.2 を折れ線で結ぶ（下限2.0）
  霜取り: 月平均が -5〜+3℃ の月は暖房COPを0.85倍
  冷房: COP = 5.0 - 0.10×(月平均気温 - 24)、下限3.2

電気単価
  各社 従量電灯の第2段階（120〜300kWh。家庭の標準帯）＋ 再エネ賦課金4.18円/kWh
  燃料費調整額は毎月・会社別に変わるため含めない

正直に言っておく限界
  ・月平均気温で計算するため、朝晩の冷え込みと日中の猛暑がならされ、実際より低め
  ・基本料金と燃料費調整額は含まない
  ・断熱を全国同一にしているので、現実の寒冷地の家より暖房費は高めに出る
  ・COP係数は代表値であり、機種によって違う

だからこそ 05 の感度分析を付けています。
主要な仮定6つを各3通りに振って729通り計算し、
どの結論が仮定によらず生き残るかを確かめたものです。
"""
import calendar
import csv
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))

F_ACTUAL = "01_入力_月別平均気温_実測12か月_47地点.csv"
F_NORMAL = "02_入力_月別平均気温_平年値30年_47地点.csv"
F_PRICE = "03_入力_電力単価_10社.csv"
F_RESULT = "04_結果_年間冷暖房費_47都道府県.csv"
F_SENS = "05_検証_感度分析_729通り.csv"

# ── 既定の前提 ──────────────────────────────────────────
H_LOSS = 234.6          # 熱損失係数 W/K
BASE_HEAT = 18.0        # 度日の基準温度（暖房）
BASE_COOL = 24.0        # 度日の基準温度（冷房）
COOL_A = 5.0            # 冷房COPの切片
COOL_B = 0.10           # 冷房COPの傾き
COOL_MIN = 3.2          # 冷房COPの下限
DEFROST_F = 0.85        # 霜取りによる暖房COPの低下係数
DEFROST_LO, DEFROST_HI = -5.0, 3.0   # 霜が問題になる月平均気温の範囲
COP_RATED = 4.6         # 「効率一定」と仮定したときのCOP（7℃の定格点。COP水準を振るときは連動）

# 1月〜12月の日数。平年値（30年平均）を使うときは2月を28.25日として扱う。
# 実測12か月のときは、その年の実際の日数（2026年2月は28日）に置き換える
DAYS_NORMAL = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# 都道府県 → 電力会社（標準的な供給区域。長野は中部、静岡は静岡市＝中部とする）
AREA = {}
for _prefs, _comp in [
    (["北海道"], "北海道電力"),
    (["青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "新潟県"], "東北電力"),
    (["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県", "山梨県"], "東京電力EP"),
    (["静岡県", "愛知県", "岐阜県", "三重県", "長野県"], "中部電力ミライズ"),
    (["富山県", "石川県", "福井県"], "北陸電力"),
    (["大阪府", "京都府", "兵庫県", "奈良県", "滋賀県", "和歌山県"], "関西電力"),
    (["広島県", "岡山県", "山口県", "島根県", "鳥取県"], "中国電力"),
    (["香川県", "徳島県", "愛媛県", "高知県"], "四国電力"),
    (["福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県"], "九州電力"),
    (["沖縄県"], "沖縄電力"),
]:
    for _p in _prefs:
        AREA[_p] = _comp


# ── モデル ──────────────────────────────────────────────
def cop_heat(t, shift=1.0):
    """外気温 t での暖房COP。shift は感度分析でCOP水準ごと上下させるための倍率"""
    pts = [(-15, 2.2), (-7, 2.8), (2, 3.8), (7, 4.6), (15, 5.5)]
    if t <= pts[0][0]:
        return 2.0 * shift
    if t >= pts[-1][0]:
        return pts[-1][1] * shift
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if x1 <= t <= x2:
            return (y1 + (y2 - y1) * (t - x1) / (x2 - x1)) * shift


def defrost(t, f=DEFROST_F):
    """霜取りによる暖房COPの低下。0℃前後の湿った空気で最も着霜する"""
    return f if DEFROST_LO <= t <= DEFROST_HI else 1.0


def cop_cool(t, a=COOL_A):
    return max(COOL_MIN, a - COOL_B * (t - BASE_COOL))


def annual(temps, price, days=None, bh=BASE_HEAT, bc=BASE_COOL, hloss=H_LOSS,
           cop_shift=1.0, cool_a=COOL_A, defrost_f=DEFROST_F):
    """temps: 1月〜12月の月平均気温 / price: 円/kWh（賦課金込み） / days: 各月の日数"""
    heat_kwh = cool_kwh = heat_kwh_fixcop = 0.0
    for t, d in zip(temps, days or DAYS_NORMAL):
        if t < bh:
            th = hloss * (bh - t) * 24 * d / 1000.0             # 必要な熱量 kWh
            heat_kwh += th / (cop_heat(t, cop_shift) * defrost(t, defrost_f))
            heat_kwh_fixcop += th / (COP_RATED * cop_shift)     # 効率一定と仮定した場合
        if t > bc:
            tc = hloss * (t - bc) * 24 * d / 1000.0
            cool_kwh += tc / max(COOL_MIN, cool_a - COOL_B * (t - bc))
    return {
        "暖房kWh": round(heat_kwh), "冷房kWh": round(cool_kwh),
        "暖房円": round(heat_kwh * price), "冷房円": round(cool_kwh * price),
        "合計円": round((heat_kwh + cool_kwh) * price),
        "効率一定なら円": round((heat_kwh_fixcop + cool_kwh) * price),
    }


# ── 入力を読む ──────────────────────────────────────────
def read_temps(fn):
    """{都道府県: (地点, [1月〜12月の気温])} と、各月の日数を返す。

    列見出しは「1月」形式（平年値）でも「2025-08」形式（実測）でもよい。
    どちらでも暦の月の順に並べ替える。
    """
    out = {}
    with io.open(os.path.join(HERE, fn), encoding="utf-8") as f:
        rd = csv.reader(f)
        head = next(rd)
        cols = head[2:]
        order = sorted(range(len(cols)),
                       key=lambda i: int(cols[i].replace("月", "").split("-")[-1]))
        for r in rd:
            if not r or not r[0]:
                continue
            vals = r[2:]
            out[r[0]] = (r[1], [float(vals[i]) for i in order])
    # 「2025-08」形式なら、その年の実際の日数を使う（2026年2月は28日）
    if "-" in cols[0]:
        days = [calendar.monthrange(*(int(x) for x in cols[i].split("-")))[1] for i in order]
    else:
        days = list(DAYS_NORMAL)
    return out, days


def read_price():
    """{電力会社: 賦課金込みの円/kWh}"""
    out = {}
    with io.open(os.path.join(HERE, F_PRICE), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["電力会社"]] = float(r["計算に使った単価_円kWh"])
    return out


# ── 04 年間冷暖房費 ─────────────────────────────────────
def make_result(actual, adays, normal, ndays, price):
    rows = []
    for pref, (st, temps) in actual.items():
        comp = AREA[pref]
        p = price[comp]
        a = annual(temps, p, adays)
        n = annual(normal[pref][1], p, ndays)
        rows.append({
            "都道府県": pref, "地点": st, "電力会社": comp,
            "実測12か月_合計円": a["合計円"], "実測_暖房円": a["暖房円"],
            "実測_冷房円": a["冷房円"], "平年値_合計円": n["合計円"],
            "実測-平年_円": a["合計円"] - n["合計円"],
            "実測_効率一定なら円": a["効率一定なら円"],
        })
    rows.sort(key=lambda x: -x["実測12か月_合計円"])
    cols = ["順位", "都道府県", "地点", "電力会社", "実測12か月_合計円", "実測_暖房円",
            "実測_冷房円", "平年値_合計円", "実測-平年_円", "実測_効率一定なら円"]
    with io.open(os.path.join(HERE, F_RESULT), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, r in enumerate(rows, 1):
            r["順位"] = i
            w.writerow([r[c] for c in cols])
    return rows


# ── 05 感度分析 729通り ─────────────────────────────────
# 「上位5は北海道と東北」を機械的に確かめるための顔ぶれ（東北6県。新潟は含めない）
HOKKAIDO_TOHOKU = {"北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県"}

GRID = {
    "bh":        [16.0, 18.0, 20.0],    # 度日の基準温度（暖房）
    "bc":        [23.0, 24.0, 26.0],    # 度日の基準温度（冷房）
    "hloss":     [200.0, 234.6, 270.0],  # 熱損失係数 = 断熱と家の大きさ
    "cop_shift": [0.85, 1.0, 1.15],     # 暖房COPの水準（機種差）
    "cool_a":    [4.3, 5.0, 5.7],       # 冷房COPの水準
    "defrost_f": [0.78, 0.85, 0.95],    # 霜取りによる低下の大きさ
}


def make_sensitivity(actual, adays, price):
    with io.open(os.path.join(HERE, F_SENS), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["試行", "bh", "bc", "hloss", "cop_shift", "cool_a", "defrost_f",
                    "最高の県", "最高円", "最安の県", "最安円", "倍率",
                    "札幌円", "東京円", "札幌_効率一定円", "過小評価%",
                    "東京の順位", "上位5は北海道と東北か"])
        n = 0
        for bh in GRID["bh"]:
            for bc in GRID["bc"]:
                for hl in GRID["hloss"]:
                    for cs in GRID["cop_shift"]:
                        for ca in GRID["cool_a"]:
                            for df in GRID["defrost_f"]:
                                n += 1
                                res = {}
                                for pref, (st, temps) in actual.items():
                                    res[pref] = annual(temps, price[AREA[pref]], adays,
                                                       bh, bc, hl, cs, ca, df)
                                hi = max(res, key=lambda k: res[k]["合計円"])
                                lo = min(res, key=lambda k: res[k]["合計円"])
                                sap = res["北海道"]
                                rank = sorted(res, key=lambda k: -res[k]["合計円"])
                                tokyo_rank = rank.index("東京都") + 1
                                top5 = "はい" if all(p in HOKKAIDO_TOHOKU for p in rank[:5]) else "いいえ"
                                w.writerow([
                                    n, bh, bc, hl, cs, ca, df,
                                    hi, res[hi]["合計円"], lo, res[lo]["合計円"],
                                    round(res[hi]["合計円"] / res[lo]["合計円"], 2),
                                    sap["合計円"], res["東京都"]["合計円"],
                                    sap["効率一定なら円"],
                                    round((1 - sap["効率一定なら円"] / sap["合計円"]) * 100, 1),
                                    tokyo_rank, top5,
                                ])
        return n


# ── まとめ ──────────────────────────────────────────────
def main():
    actual, adays = read_temps(F_ACTUAL)
    normal, ndays = read_temps(F_NORMAL)
    price = read_price()
    rows = make_result(actual, adays, normal, ndays, price)
    top, bot = rows[0], rows[-1]
    print("── 基準ケース（実測12か月・2025年8月〜2026年7月）──")
    print("最も高い: %s(%s) %s円" % (top["都道府県"], top["地点"], format(top["実測12か月_合計円"], ",")))
    print("最も安い: %s(%s) %s円" % (bot["都道府県"], bot["地点"], format(bot["実測12か月_合計円"], ",")))
    print("倍率: %.2f倍  差額: %s円/年"
          % (top["実測12か月_合計円"] / bot["実測12か月_合計円"],
             format(top["実測12か月_合計円"] - bot["実測12か月_合計円"], ",")))
    tokyo = next(r for r in rows if r["都道府県"] == "東京都")
    print("東京: %s円（47都道府県中 %d位）" % (format(tokyo["実測12か月_合計円"], ","), tokyo["順位"]))
    print("効率一定と仮定すると札幌は %s円 → %s円（%.0f%%小さく見える）"
          % (format(top["実測12か月_合計円"], ","), format(top["実測_効率一定なら円"], ","),
             (1 - top["実測_効率一定なら円"] / top["実測12か月_合計円"]) * 100))
    print()
    print("── 感度分析 ──")
    n = make_sensitivity(actual, adays, price)
    print("%d通りを計算して %s に書き出しました" % (n, F_SENS))


if __name__ == "__main__":
    main()
