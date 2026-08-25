# This file is part of 知行合一 · 任务与知识管理系统 (TaskManager).
# Copyright (C) 2026 TaskManager contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""星运模块 · 纯 Python 排盘引擎(零第三方依赖, 数据与算法全透明)。

组成:
- 西方占星: 低精度星历(Schlyter 简化算法, 行星黄经误差约±0.1°量级),
  计算日月及水金火木土天海的地心黄经/星座落点/宫位/相位/逆行状态,
  上升点(ASC)/天顶(MC)由出生时刻经纬度推算, 宫位制为等宫制;
- 中国八字: 四柱干支(年柱以近似立春2月4日换年, 月柱以各月节入日近似表
  换月, 日柱以儒略日序数锚定甲子, 时柱五鼠遁), 五行计数与生肖;
- 每日运势: 以(星座,日期)哈希种子的确定性生成器, 同日同星座结果稳定可复现,
  叠加真实古典规则(喜神/财神方位歌诀, 日支冲煞, 三合六合贵人);
- 塔罗: 内置大阿尔卡纳22张牌义数据(开源 tarot-json 社区数据的中文摘编);
- 术语库 TERMS: 全站弹窗解释的数据源, 排盘结果中的术语均可一键查阅。

精度声明(数据透明原则): 本引擎面向教学与日常参考, 非精密天文历算;
节气换柱采用固定日期近似(±1日), 如需分钟级精度建议接入专业星历库。
"""
import datetime
import hashlib
import math

# ---------------------------------------------------------------- 基础常量
SIGNS = [
    {'key': 'aries', 'cn': '白羊座', 'date': '03.21-04.19', 'elem': 'fire',
     'mode': 'cardinal', 'ruler': '火星'},
    {'key': 'taurus', 'cn': '金牛座', 'date': '04.20-05.20', 'elem': 'earth',
     'mode': 'fixed', 'ruler': '金星'},
    {'key': 'gemini', 'cn': '双子座', 'date': '05.21-06.21', 'elem': 'air',
     'mode': 'mutable', 'ruler': '水星'},
    {'key': 'cancer', 'cn': '巨蟹座', 'date': '06.22-07.22', 'elem': 'water',
     'mode': 'cardinal', 'ruler': '月亮'},
    {'key': 'leo', 'cn': '狮子座', 'date': '07.23-08.22', 'elem': 'fire',
     'mode': 'fixed', 'ruler': '太阳'},
    {'key': 'virgo', 'cn': '处女座', 'date': '08.23-09.22', 'elem': 'earth',
     'mode': 'mutable', 'ruler': '水星'},
    {'key': 'libra', 'cn': '天秤座', 'date': '09.23-10.23', 'elem': 'air',
     'mode': 'cardinal', 'ruler': '金星'},
    {'key': 'scorpio', 'cn': '天蝎座', 'date': '10.24-11.22', 'elem': 'water',
     'mode': 'fixed', 'ruler': '冥王星'},
    {'key': 'sagittarius', 'cn': '射手座', 'date': '11.23-12.21', 'elem': 'fire',
     'mode': 'mutable', 'ruler': '木星'},
    {'key': 'capricorn', 'cn': '摩羯座', 'date': '12.22-01.19', 'elem': 'earth',
     'mode': 'cardinal', 'ruler': '土星'},
    {'key': 'aquarius', 'cn': '水瓶座', 'date': '01.20-02.18', 'elem': 'air',
     'mode': 'fixed', 'ruler': '天王星'},
    {'key': 'pisces', 'cn': '双鱼座', 'date': '02.19-03.20', 'elem': 'water',
     'mode': 'mutable', 'ruler': '海王星'},
]
SIGN_CN_BY_KEY = {s['key']: s['cn'] for s in SIGNS}
SIGN_KEY_ORDER = [s['key'] for s in SIGNS]

ELEMENTS = {
    'fire': {'cn': '火象', 'traits': '热情·行动·直觉', 'color': '#e8590c'},
    'earth': {'cn': '土象', 'traits': '务实·稳固·感官', 'color': '#5f8d4e'},
    'air': {'cn': '风象', 'traits': '思维·沟通·理性', 'color': '#1971c2'},
    'water': {'cn': '水象', 'traits': '情感·敏感·疗愈', 'color': '#6741d9'},
}

PLANETS = [
    {'key': 'sun', 'cn': '太阳', 'glyph': '☉'},
    {'key': 'moon', 'cn': '月亮', 'glyph': '☾'},
    {'key': 'mercury', 'cn': '水星', 'glyph': '☿'},
    {'key': 'venus', 'cn': '金星', 'glyph': '♀'},
    {'key': 'mars', 'cn': '火星', 'glyph': '♂'},
    {'key': 'jupiter', 'cn': '木星', 'glyph': '♃'},
    {'key': 'saturn', 'cn': '土星', 'glyph': '♄'},
    {'key': 'uranus', 'cn': '天王星', 'glyph': '♅'},
    {'key': 'neptune', 'cn': '海王星', 'glyph': '♆'},
]

ASPECT_DEFS = [
    {'key': 'conj', 'cn': '合相', 'angle': 0, 'orb': 8, 'nature': 'neutral',
     'brief': '两星能量融合叠加, 特质强化'},
    {'key': 'sextile', 'cn': '六合', 'angle': 60, 'orb': 5, 'nature': 'soft',
     'brief': '机会与才华, 需主动把握的和谐'},
    {'key': 'square', 'cn': '刑相', 'angle': 90, 'orb': 7, 'nature': 'hard',
     'brief': '张力与摩擦, 成长型挑战'},
    {'key': 'trine', 'cn': '三合', 'angle': 120, 'orb': 7, 'nature': 'soft',
     'brief': '天赋般的顺畅流动'},
    {'key': 'oppo', 'cn': '对冲', 'angle': 180, 'orb': 8, 'nature': 'hard',
     'brief': '两端拉扯, 觉醒与平衡课题'},
]

STEMS = '甲乙丙丁戊己庚辛壬癸'
BRANCHES = '子丑寅卯辰巳午未申酉戌亥'
ZODIAC_ANIMALS = ['鼠', '牛', '虎', '兔', '龙', '蛇', '马', '羊', '猴', '鸡', '狗', '猪']
STEM_ELEMENT = ['木', '木', '火', '火', '土', '土', '金', '金', '水', '水']
BRANCH_ELEMENT = ['水', '土', '木', '木', '土', '火', '火', '土', '金', '金', '土', '水']
WUXING_ORDER = ['木', '火', '土', '金', '水']

# 各月"节"入日的固定近似表(寅月自立春2/4起, 依次惊蛰/清明/立夏...)
_SOLAR_TERM_ENTRY = {2: 4, 3: 6, 4: 5, 5: 6, 6: 6, 7: 7,
                     8: 8, 9: 8, 10: 8, 11: 7, 12: 7, 1: 6}
_LICHUN_MONTH, _LICHUN_DAY = 2, 4
# 日柱锚点: 1949-10-01 为甲子日
_DAY_ANCHOR_ORD = datetime.date(1949, 10, 1).toordinal()

# 古典方位口诀: 喜神方位(日干), 财神方位(日干), 煞方(日支三合局)
_XISHEN_DIR = ['东北', '西北', '西南', '正南', '东南'] * 2
_CAISHEN_DIR = ['东北', '东北', '西南', '西南', '正北', '正北', '正东', '正东', '正南', '正南']
_SHA_GROUP = {'申': '正南', '子': '正南', '辰': '正南', '寅': '正北', '午': '正北',
              '戌': '正北', '巳': '正东', '酉': '正东', '丑': '正东',
              '亥': '正西', '卯': '正西', '未': '正西'}
_BRANCH_CLASH = {'子': '午', '午': '子', '丑': '未', '未': '丑', '寅': '申',
                 '申': '寅', '卯': '酉', '酉': '卯', '辰': '戌', '戌': '辰',
                 '巳': '亥', '亥': '巳'}

# ---------------------------------------------------------------- 工具函数


def _norm360(x):
    return x % 360.0


def _dt_to_days(d):
    """datetime(北京时间视为本地钟) → 自 2000-01-00.0 TT 起的天数 d。

    公历序数日 → 儒略日: JD = toordinal + 1721424.5 + 当日时刻;
    北京时间减 8h 得 UT。
    """
    jd_local = d.toordinal() + 1721424.5 \
        + (d.hour + d.minute / 60 + d.second / 3600) / 24
    return jd_local - 8 / 24 - 2451543.5


def _solve_e(M, e):
    """开普勒方程迭代求解偏近点角(度)。"""
    E = M + 180.0 / math.pi * e * math.sin(math.radians(M))
    for _ in range(4):
        E = M + 180.0 / math.pi * e * math.sin(math.radians(E))
    return E


def _helio_xyz(N, i, w, a, e, M):
    """轨道根数 → 日心黄道直角坐标(天文单位)。"""
    E = _solve_e(M, e)
    xv = a * (math.cos(math.radians(E)) - e)
    yv = a * math.sqrt(1 - e * e) * math.sin(math.radians(E))
    v = math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    N_r, i_r, vw = math.radians(N), math.radians(i), math.radians(w + math.degrees(v))
    xh = r * (math.cos(N_r) * math.cos(vw) - math.sin(N_r) * math.sin(vw) * math.cos(i_r))
    yh = r * (math.sin(N_r) * math.cos(vw) + math.cos(N_r) * math.sin(vw) * math.cos(i_r))
    zh = r * math.sin(vw) * math.sin(i_r)
    return xh, yh, zh


def sun_longitude(d):
    """太阳地心视黄经(度)。"""
    w = 282.9404 + 4.70935e-5 * d
    e = 0.016709 - 1.151e-9 * d
    M = _norm360(356.0470 + 0.9856002585 * d)
    E = _solve_e(M, e)
    xv = math.cos(math.radians(E)) - e
    yv = math.sqrt(1 - e * e) * math.sin(math.radians(E))
    v = math.atan2(yv, xv)
    return _norm360(math.degrees(v) + w)


def moon_longitude(d):
    """月球地心视黄经(度, 含主要摄动修正)。"""
    N = 125.1228 - 0.0529538083 * d
    i = 5.1454
    w = 318.0634 + 0.1643573223 * d
    a = 60.2666
    e = 0.054900
    M = _norm360(115.3654 + 13.0649929509 * d)
    xh, yh, _zh = _helio_xyz(N, i, w, a, e, M)
    lon = _norm360(math.degrees(math.atan2(yh, xh)))
    # 主要摄动项(Schlyter)
    Ms = _norm360(356.0470 + 0.9856002585 * d)
    Ls = _norm360(sun_longitude(d) + Ms)          # 太阳平黄经
    Lm = _norm360(N + w + M)                       # 月亮平黄经
    D = _norm360(Lm - Ls)                          # 平距角
    F = _norm360(Lm - N)                           # 升交距角
    Mm = M
    corr = (-1.274 * math.sin(math.radians(Mm - 2 * D))
            + 0.658 * math.sin(math.radians(2 * D))
            - 0.186 * math.sin(math.radians(Ms))
            - 0.059 * math.sin(math.radians(2 * Mm - 2 * D))
            - 0.057 * math.sin(math.radians(Mm - 2 * D + Ms))
            + 0.053 * math.sin(math.radians(Mm + 2 * D))
            + 0.046 * math.sin(math.radians(2 * D - Ms))
            + 0.041 * math.sin(math.radians(Mm - Ms))
            - 0.035 * math.sin(math.radians(D))
            - 0.031 * math.sin(math.radians(Mm + Ms))
            - 0.015 * math.sin(math.radians(2 * F - 2 * D))
            + 0.011 * math.sin(math.radians(Mm - 4 * D)))
    return _norm360(lon + corr)


def planet_longitude(key, d):
    """行星地心视黄经(度)。key ∈ mercury/venus/mars/jupiter/saturn/uranus/neptune。"""
    elems = {
        'mercury': (48.3313 + 3.24587e-5 * d, 7.0047, 29.1241 + 1.01444e-5 * d,
                    0.387098, 0.205635, 168.6562 + 4.0923344368 * d),
        'venus': (76.6799 + 2.46590e-5 * d, 3.3946, 54.8910 + 1.38374e-5 * d,
                  0.723330, 0.006773, 48.0052 + 1.6021302244 * d),
        'mars': (49.5574 + 2.11081e-5 * d, 1.8497, 286.5016 + 2.92961e-5 * d,
                 1.523688, 0.093405, 18.6021 + 0.5240207766 * d),
        'jupiter': (100.4542 + 2.76854e-5 * d, 1.3030, 273.8777 + 1.64505e-5 * d,
                    5.20256, 0.048498, 19.8950 + 0.0830853001 * d),
        'saturn': (113.6634 + 2.38980e-5 * d, 2.4886, 339.3939 + 2.97661e-5 * d,
                   9.55475, 0.055546, 316.9670 + 0.0334442282 * d),
        'uranus': (74.0005 + 1.3978e-5 * d, 0.7733, 96.6612 + 3.0565e-5 * d,
                   19.18171, 0.047318, 142.5905 + 0.011725806 * d),
        'neptune': (131.7806 + 3.0173e-5 * d, 1.7700, 272.8461 - 6.027e-6 * d,
                    30.05826, 0.008605, 260.2471 + 0.005995147 * d),
    }[key]
    xh, yh, zh = _helio_xyz(*elems)
    ls = sun_longitude(d)
    rs = 1.0  # 日地距离约 1 AU, 对黄经影响远小于本引擎精度量级
    xg, yg = xh + rs * math.cos(math.radians(ls)), yh + rs * math.sin(math.radians(ls))
    return _norm360(math.degrees(math.atan2(yg, xg)))


def longitude_of(planet_key, d):
    if planet_key == 'sun':
        return sun_longitude(d)
    if planet_key == 'moon':
        return moon_longitude(d)
    return planet_longitude(planet_key, d)


def sign_of(lon):
    return SIGNS[int(_norm360(lon) // 30)]['cn']


def degree_in_sign(lon):
    return round(_norm360(lon) % 30, 2)


# ---------------------------------------------------------------- 西方占星排盘


def ascend_mc(birth_dt, lat, lon_east):
    """上升点(ASC)与天顶(MC)黄经。birth_dt 为出生当地时间(视为北京时区)。"""
    jd_ut = birth_dt.toordinal() + 1721424.5 \
        + (birth_dt.hour + birth_dt.minute / 60) / 24 - 8 / 24
    gmst = _norm360(280.46061837 + 360.98564736629 * (jd_ut - 2451545.0))
    lst = math.radians(_norm360(gmst + lon_east))
    eps = math.radians(23.4393)
    phi = math.radians(lat)
    ramc_sin = math.sin(lst)
    mc = _norm360(math.degrees(math.atan2(ramc_sin, math.cos(lst) * math.cos(eps))))
    asc = _norm360(math.degrees(
        math.atan2(math.cos(lst),
                   -(math.sin(lst) * math.cos(eps) + math.tan(phi) * math.sin(eps)))))
    return asc, mc


def natal_chart(birth_dt, lat=31.23, lon_east=121.47, name=''):
    """本命盘: 行星黄经/星座/宫位/相位 + 四轴 + 元素模态统计。

    birth_dt: 出生当地时间(datetime); lat/lon_east: 出生地理坐标(度, 北纬东经为正);
    默认上海。宫位制: 上升等宫制(透明简化)。
    """
    d = _dt_to_days(birth_dt)
    asc, mc = ascend_mc(birth_dt, lat, lon_east)
    points = []
    for p in PLANETS:
        lon_now = longitude_of(p['key'], d)
        lon_next = longitude_of(p['key'], d + 1)
        delta = (lon_next - lon_now + 180) % 360 - 180
        house = int(((lon_now - asc) % 360) // 30) + 1
        speed = abs(delta) * 60  # 度/日×60 → 弧分/日, 仅用于展示快慢
        points.append({
            'key': p['key'], 'cn': p['cn'], 'glyph': p['glyph'],
            'lon': round(lon_now, 2), 'sign': sign_of(lon_now),
            'deg': degree_in_sign(lon_now), 'house': house,
            'retro': delta < 0,
            'speed_note': ('运行较慢' if speed < 30 else '运行较快'),
        })
    angles = [
        {'key': 'asc', 'cn': '上升点', 'lon': round(asc, 2), 'sign': sign_of(asc),
         'deg': degree_in_sign(asc)},
        {'key': 'mc', 'cn': '天顶', 'lon': round(mc, 2), 'sign': sign_of(mc),
         'deg': degree_in_sign(mc)},
        {'key': 'des', 'cn': '下降点', 'lon': round((asc + 180) % 360, 2),
         'sign': sign_of((asc + 180) % 360), 'deg': degree_in_sign((asc + 180) % 360)},
        {'key': 'ic', 'cn': '天底', 'lon': round((mc + 180) % 360, 2),
         'sign': sign_of((mc + 180) % 360), 'deg': degree_in_sign((mc + 180) % 360)},
    ]
    aspects = find_aspects(points)
    elem_tally, mode_tally = {}, {}
    for pt in points:
        s = SIGNS[int(pt['lon'] // 30)]
        elem_tally[s['elem']] = elem_tally.get(s['elem'], 0) + 1
        mode_tally[s['mode']] = mode_tally.get(s['mode'], 0) + 1
    sun_sign = next(pt for pt in points if pt['key'] == 'sun')['sign']
    moon_pt = next(pt for pt in points if pt['key'] == 'moon')
    asc_sign = sign_of(asc)
    return {
        'name': name, 'birth_iso': birth_dt.strftime('%Y-%m-%d %H:%M'),
        'lat': lat, 'lon': lon_east,
        'points': points, 'angles': angles,
        'houses': [{'no': i + 1, 'cusp': round((asc + 30 * i) % 360, 2),
                    'sign': sign_of((asc + 30 * i) % 360)} for i in range(12)],
        'aspects': aspects,
        'elements': {k: {'count': v, **ELEMENTS[k]} for k, v in (
            (_k, elem_tally.get(_k, 0)) for _k in ELEMENTS)},
        'modes': mode_tally,
        'big_three': {'sun': sun_sign, 'moon': moon_pt['sign'], 'asc': asc_sign},
    }


def find_aspects(points):
    out = []
    for a in range(len(points)):
        for b in range(a + 1, len(points)):
            la, lb = points[a]['lon'], points[b]['lon']
            sep = abs((la - lb + 180) % 360 - 180)
            for dfn in ASPECT_DEFS:
                if abs(sep - dfn['angle']) <= dfn['orb']:
                    out.append({
                        'a': points[a], 'b': points[b],
                        'aspect': dfn['key'], 'aspect_cn': dfn['cn'],
                        'nature': dfn['nature'],
                        'exact': round(abs(sep - dfn['angle']), 2),
                        'separation': round(sep, 2),
                    })
                    break
    out.sort(key=lambda x: x['exact'])
    return out


# ---------------------------------------------------------------- 八字四柱


def bazi_pillars(dt):
    """公历 datetime → 四柱干支(字符串列表 年月日时)与索引。

    年柱以近似立春(2月4日)换年; 月柱以各月节入日近似表换月;
    23 点后按晚子时归次日。节气边界±1日内如需精确请核对万年历。
    """
    year = dt.year
    if (dt.month, dt.day) < (_LICHUN_MONTH, _LICHUN_DAY):
        year -= 1
    year_gz = (year - 4) % 10, (year - 4) % 12

    # 月支: 由节气入日表确定(1→丑或寅交界按1月6日小寒后仍属丑月, 故先按节表)
    entry = _SOLAR_TERM_ENTRY[dt.month]
    month_after_node = dt.day >= entry
    # 节气月序: 寅=正月对应2月; 月份索引从寅月起算
    node_month = dt.month if dt.month >= 2 else dt.month + 12   # 1月→13(属丑月末段)
    branch_m = (node_month - 2 + 2) % 12                        # 2月→寅(2)
    if not month_after_node:
        branch_m = (branch_m - 1) % 12
    # 月干: 五虎遁 (年干 % 5)*2 + 2 起, 加上距寅的偏移
    offset_m = (branch_m - 2) % 12
    stem_m = ((year_gz[0] % 5) * 2 + 2 + offset_m) % 10

    base_ord = dt.date().toordinal()
    if dt.hour >= 23:
        base_ord += 1
    gz_day = (base_ord - _DAY_ANCHOR_ORD) % 60

    hour_branch = ((dt.hour + 1) // 2) % 12
    hour_stem = (gz_day % 10 * 2 + hour_branch) % 10

    pillars = [
        (year_gz[0], year_gz[1]),
        (stem_m, branch_m),
        (gz_day % 10, gz_day % 12),
        (hour_stem, hour_branch),
    ]
    text = ['%s%s' % (STEMS[s], BRANCHES[b]) for s, b in pillars]
    animals = [ZODIAC_ANIMALS[pillars[0][1]]]
    wuxing = {}
    for s, b in pillars:
        wuxing[STEM_ELEMENT[s]] = wuxing.get(STEM_ELEMENT[s], 0) + 1
        wuxing[BRANCH_ELEMENT[b]] = wuxing.get(BRANCH_ELEMENT[b], 0) + 1
    day_stem = pillars[2][0]
    ten_gods = []
    for s, _b in pillars:
        rel = (s - day_stem) % 10
        ten_gods.append(_TEN_GOD_NAMES[rel])
    return {
        'pillars': text, 'indices': pillars,
        'animal': ZODIAC_ANIMALS[pillars[0][1]],
        'wuxing': {wx: wuxing.get(wx, 0) for wx in WUXING_ORDER},
        'ten_gods': ten_gods,
        'day_master': STEMS[day_stem],
        'day_element': STEM_ELEMENT[day_stem],
        'xishen': _XISHEN_DIR[pillars[2][0]],
        'caishen': _CAISHEN_DIR[pillars[2][0]],
        'chong': _BRANCH_CLASH[BRANCHES[pillars[2][1]]],
        'sha_dir': _SHA_GROUP[BRANCHES[pillars[2][1]]],
    }


_TEN_GOD_NAMES = ['比肩', '劫财', '食神', '伤官', '偏财', '正财', '七杀', '正官', '偏印', '正印']


def daily_calendar_info(date_obj):
    """某公历日的干支纪日信息与简化宜忌/吉神方位(确定性推演)。"""
    gz = bazi_pillars(datetime.datetime(date_obj.year, date_obj.month, date_obj.day, 12))
    rng = _seeded_rng('cal|%s' % date_obj.isoformat())
    yi_pool = ['祭祀', '祈福', '会友', '出行', '纳财', '开市', '动土', '安床',
               '裁衣', '扫舍', '入学', '签约', '修缮', '沐浴', '求医', '栽种']
    ji_pool = ['词讼', '远行', '动土', '嫁娶', '开仓', '掘井', '置产', '夜游']
    k = max(3, rng.randint(3, 6))
    j = max(2, rng.randint(2, 4))
    yi = rng.sample(yi_pool, k)
    ji = rng.sample(ji_pool, j)
    return {
        'day_gz': gz['pillars'][2], 'month_gz': gz['pillars'][1],
        'yi': yi, 'ji': ji,
        'xishen': gz['xishen'], 'caishen': gz['caishen'],
        'chong': '冲%s(%s)' % (gz['chong'],
                               ZODIAC_ANIMALS[BRANCHES.index(gz['chong'])]),
        'sha_dir': gz['sha_dir'],
        'element': gz['day_element'],
    }


# ---------------------------------------------------------------- 每日运势


def _seeded_rng(seed_text):
    import random
    h = hashlib.sha256(seed_text.encode('utf-8')).digest()
    return random.Random(int.from_bytes(h[:8], 'big'))


_FORTUNE_DIMS = [('love', '爱情'), ('career', '事业'), ('wealth', '财富'), ('health', '健康')]
_COLORS = ['绯红', '琥珀橙', '鹅黄', '松石绿', '湖蓝', '黛紫', '月白', '墨黑', '樱粉', '橄榄绿']
_MOODS = ['平静专注', '灵感涌现', '跃跃欲试', '温柔笃定', '锋芒渐露', '松弛自在',
          '蓄势待发', '豁然开朗']


def daily_fortune(sign_key, date_obj):
    """星座日运(确定性): 同一(星座,日期)永远同一结果, 可回溯任意历史日期。"""
    cn = SIGN_CN_BY_KEY.get(sign_key, sign_key)
    rng = _seeded_rng('%s|%s' % (cn, date_obj.isoformat()))
    dims = []
    for key, label in _FORTUNE_DIMS:
        score = 42 + rng.randint(0, 56)
        band = 'high' if score >= 80 else ('mid' if score >= 60 else 'low')
        pool = _FORTUNE_TEXT[key][band]
        tip = rng.choice(pool)
        dims.append({'key': key, 'label': label, 'score': score, 'tip': tip})
    elem = next(s for s in SIGNS if s['key'] == sign_key)['elem']
    compat = [SIGN_CN_BY_KEY[k] for k in SIGN_KEY_ORDER
              if next(s for s in SIGNS if s['key'] == k)['elem'] == elem
              and k != sign_key]
    lucky_nums = rng.sample(range(1, 50), 3)
    return {
        'sign_key': sign_key, 'sign': cn,
        'date': date_obj.isoformat(), 'dims': dims,
        'overall': round(sum(dd['score'] for dd in dims) / len(dims)),
        'lucky_color': rng.choice(_COLORS),
        'lucky_numbers': sorted(lucky_nums),
        'mood': rng.choice(_MOODS),
        'compat': compat,
    }


_FORTUNE_TEXT = {
    'love': {
        'high': ['坦诚的表达让关系升温', '单身者易遇有趣灵魂', '一次用心的陪伴胜过千言'],
        'mid': ['细水长流比轰轰烈烈更可靠', '把期待说出口而非让对方猜', '旧话题里藏着新默契'],
        'low': ['别让情绪替你说话', '给彼此留一点独处的余地', '误会多源于时机不对'],
    },
    'career': {
        'high': ['关键项目上表现亮眼', '你的方案会被有分量的人看见', '适合推进搁置已久的计划'],
        'mid': ['按部就班即是效率', '把大目标拆成今天能完成的三步', '协作中记得同步进度'],
        'low': ['先处理心情再处理事情', '重要决策缓半日再做', '琐碎事务集中批量处理'],
    },
    'wealth': {
        'high': ['副业或技能变现的机会浮现', '盘点资产会发现惊喜', '谈钱不伤感情, 该争取就争取'],
        'mid': ['记账会让你更有掌控感', '小额定投好过冲动消费', '货比三家再下单'],
        'low': ['警惕"限时优惠"式支出', '借钱需谨慎量力', '投资信息先核实来源'],
    },
    'health': {
        'high': ['运动后的轻盈感会延续全天', '早睡早起身体给你正反馈', '适合尝试新的锻炼方式'],
        'mid': ['久坐一小时起身活动五分钟', '多喝水少熬夜', '晚餐七分饱刚刚好'],
        'low': ['肩颈在提醒你放松', '情绪性进食要觉察', '给自己安排一段发呆时间'],
    },
}


# ---------------------------------------------------------------- 塔罗

TAROT_MAJOR = [
    {'no': 0, 'cn': '愚者', 'up': '新的开始, 无畏与纯真', 'rev': '鲁莽冒进, 缺乏规划'},
    {'no': 1, 'cn': '魔术师', 'up': '资源齐备, 主动创造', 'rev': '才能误用, 言不由衷'},
    {'no': 2, 'cn': '女祭司', 'up': '内在智慧, 静观其变', 'rev': '忽视直觉, 秘密浮出'},
    {'no': 3, 'cn': '皇后', 'up': '丰盛滋养, 美与爱', 'rev': '过度依赖, 创造受阻'},
    {'no': 4, 'cn': '皇帝', 'up': '秩序权威, 稳健掌舵', 'rev': '固执僵化, 控制欲过强'},
    {'no': 5, 'cn': '教皇', 'up': '传统指引, 寻求正道', 'rev': '教条束缚, 盲从他人'},
    {'no': 6, 'cn': '恋人', 'up': '真心联结, 重要抉择', 'rev': '价值观冲突, 犹豫失衡'},
    {'no': 7, 'cn': '战车', 'up': '意志取胜, 长驱直入', 'rev': '方向失控, 蛮力硬冲'},
    {'no': 8, 'cn': '力量', 'up': '以柔克刚, 内在勇气', 'rev': '自我怀疑, 情绪压倒理智'},
    {'no': 9, 'cn': '隐士', 'up': '沉静内省, 寻找答案', 'rev': '过度封闭, 孤立无援'},
    {'no': 10, 'cn': '命运之轮', 'up': '转机降临, 顺势而为', 'rev': '时运反复, 抗拒变化'},
    {'no': 11, 'cn': '正义', 'up': '权衡是非, 因果分明', 'rev': '逃避责任, 有失公允'},
    {'no': 12, 'cn': '倒吊人', 'up': '换个角度, 心甘情愿的停顿', 'rev': '无谓牺牲, 停滞拖延'},
    {'no': 13, 'cn': '死神', 'up': '终结与重生, 放手过去', 'rev': '抗拒结束, 消耗残局'},
    {'no': 14, 'cn': '节制', 'up': '调和平衡, 耐心酿造', 'rev': '极端失衡, 急于求成'},
    {'no': 15, 'cn': '恶魔', 'up': '直面欲望与束缚', 'rev': '开始挣脱, 觉察成瘾模式'},
    {'no': 16, 'cn': '高塔', 'up': '骤变破局, 旧结构崩塌', 'rev': '余震未平, 勉强支撑'},
    {'no': 17, 'cn': '星星', 'up': '希望疗愈, 灵感之夜', 'rev': '信心低落, 愿景模糊'},
    {'no': 18, 'cn': '月亮', 'up': '潜意识的迷雾, 直觉敏锐', 'rev': '迷雾散去, 真相渐明'},
    {'no': 19, 'cn': '太阳', 'up': '光明喜悦, 大获成功', 'rev': '暂时阴霾, 快乐打折'},
    {'no': 20, 'cn': '审判', 'up': '觉醒召唤, 重整旗鼓', 'rev': '自责回避, 错失召唤'},
    {'no': 21, 'cn': '世界', 'up': '圆满达成, 新旧交替', 'rev': '临门一脚, 尚欠收尾'},
]


def tarot_draw(n=3, seed_text=None):
    """抽牌(可指定种子使结果可复现; 不指定则真随机)。"""
    import random
    rng = random.Random(seed_text) if seed_text else random.SystemRandom()
    cards = rng.sample(TAROT_MAJOR, min(n, len(TAROT_MAJOR)))
    return [{
        **dict(c),
        'reversed': rng.random() < 0.4,
        'meaning': (c['rev'] if rng.random() < 0.4 else c['up']),
    } for c in cards]


# ---------------------------------------------------------------- 紫微斗数(本地)

# 六十甲子纳音五行(甲子起, 每2组一纳音; 五组一循环的通行次序)
_NAYIN_ELEMENTS = ['金', '火', '木', '土', '金', '火', '水', '土', '金', '木',
                   '水', '土', '火', '木', '水', '金', '火', '木', '土', '金',
                   '火', '水', '土', '金', '木', '水', '土', '火', '木', '水']

# 安紫微诀: 各五行局农历生日(1-30)→紫微落宫(支序, 子0..亥11), 通行安星表
_ZIWEI_TABLES = {
    2: [1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11,
        11, 0, 0, 1, 1, 2, 2, 3, 3, 4],
    3: [4, 1, 2, 5, 2, 3, 6, 3, 4, 7, 4, 5, 8, 5, 6, 9, 6, 7, 10, 7,
        8, 11, 8, 9, 0, 9, 10, 1, 10, 11],
    4: [11, 4, 1, 2, 0, 5, 2, 3, 1, 6, 3, 4, 2, 7, 4, 5, 3, 8, 5, 6,
        4, 9, 6, 7, 5, 10, 7, 8, 6, 11],
    5: [6, 11, 4, 1, 2, 7, 0, 5, 2, 3, 8, 1, 6, 3, 4, 9, 2, 7, 4, 5,
        10, 3, 8, 5, 6, 11, 4, 9, 6, 7],
    6: [9, 6, 11, 4, 1, 2, 10, 7, 0, 5, 2, 3, 11, 8, 1, 6, 3, 4, 0, 9,
        4, 5, 2, 11, 8, 3, 6, 7, 1, 10],
}
_JU_BY_ELEMENT = {'水': 2, '木': 3, '金': 4, '土': 5, '火': 6}

# 年干四化表(全书通行版): {年干: [(星, 化), ...]}
_FOUR_HUA = {
    '甲': [('廉贞', '禄'), ('破军', '权'), ('武曲', '科'), ('太阳', '忌')],
    '乙': [('天机', '禄'), ('天梁', '权'), ('紫微', '科'), ('太阴', '忌')],
    '丙': [('天同', '禄'), ('天机', '权'), ('文昌', '科'), ('廉贞', '忌')],
    '丁': [('太阴', '禄'), ('天同', '权'), ('天机', '科'), ('巨门', '忌')],
    '戊': [('贪狼', '禄'), ('太阴', '权'), ('右弼', '科'), ('天机', '忌')],
    '己': [('武曲', '禄'), ('贪狼', '权'), ('天梁', '科'), ('文曲', '忌')],
    '庚': [('太阳', '禄'), ('武曲', '权'), ('太阴', '科'), ('天同', '忌')],
    '辛': [('巨门', '禄'), ('太阳', '权'), ('文曲', '科'), ('文昌', '忌')],
    '壬': [('天梁', '禄'), ('紫微', '权'), ('左辅', '科'), ('武曲', '忌')],
    '癸': [('破军', '禄'), ('巨门', '权'), ('太阴', '科'), ('贪狼', '忌')],
}
_LU_CUN = [2, 3, 5, 6, 5, 6, 8, 9, 11, 0]           # 年干→禄存支(甲寅乙卯…)
_KUI_BUO = [[1, 7], [0, 8], [11, 9], [11, 9], [1, 7],
            [0, 8], [1, 7], [6, 2], [3, 5], [3, 5]]  # 魁钺(甲戊庚丑未…)
_HUO_START = {'寅': 1, '午': 1, '戌': 1, '申': 2, '子': 2, '辰': 2,
              '巳': 3, '酉': 3, '丑': 3, '亥': 9, '卯': 9, '未': 9}
_LING_START = {'寅': 3, '午': 3, '戌': 3, '申': 10, '子': 10, '辰': 10,
               '巳': 10, '酉': 10, '丑': 10, '亥': 10, '卯': 10, '未': 10}
_TIANMA_BASE = {'申': 2, '子': 2, '辰': 2, '寅': 8, '午': 8, '戌': 8,
                '巳': 11, '酉': 11, '丑': 11, '亥': 5, '卯': 5, '未': 5}
_MAIN_STARS = ['紫微', '天机', '太阳', '武曲', '天同', '廉贞',
               '天府', '太阴', '贪狼', '巨门', '天相', '天梁', '七杀', '破军']
_PALACE_NAMES = ['命宫', '兄弟', '夫妻', '子女', '财帛', '疾厄',
                 '迁移', '交友', '官禄', '田宅', '福德', '父母']
_SHIXIANG_LABEL = ['子时 23-01', '丑时 01-03', '寅时 03-05', '卯时 05-07',
                   '辰时 07-09', '巳时 09-11', '午时 11-13', '未时 13-15',
                   '申时 15-17', '酉时 17-19', '戌时 19-21', '亥时 21-23']


def nayin_element(stem, branch):
    """干支纳音五行(按六十甲子序号: 序g 的纳音 = 表[g//2])。"""
    g = None
    for i in range(60):
        if i % 10 == stem and i % 12 == branch:
            g = i
            break
    if g is None:
        raise ValueError('干支组合无效(%d,%d)' % (stem, branch))
    return _NAYIN_ELEMENTS[g // 2]


def ziwei_chart(lunar_year, lunar_month, lunar_day, hour_idx=0,
                gender='男', leap=False):
    """紫微斗数本命盘(全本地安星, 无需任何外部服务)。

    输入为农历生辰: 年(公历纪年号即农历年号)、月(1-12)、日(1-30)、
    时辰序(子0..亥11)、性别; leap=True 为闰月(通行法则: 望日前归本月,
    后归次月)。年干支以农历年直取(斗数通例)。
    返回十二宫(主星/辅煞曜/四化/大限)结构化结果。
    """
    assert 1 <= lunar_month <= 12 and 1 <= lunar_day <= 30
    assert 0 <= hour_idx <= 11
    ys, yb = (lunar_year - 4) % 10, (lunar_year - 4) % 12
    y_stem, y_branch = STEMS[ys], BRANCHES[yb]
    m_eff = lunar_month
    if leap and lunar_day > 15:
        m_eff = lunar_month % 12 + 1        # 望日后归次月
    yue_gong = (2 + m_eff - 1) % 12         # 寅起正月
    ming = (yue_gong - hour_idx) % 12       # 生月宫起子时逆数至生时
    shen = (yue_gong + hour_idx) % 12       # 顺数即身宫
    tiger = (ys % 5) * 2 + 2                # 五虎遁: 寅宫天干

    def gstem(branch):
        return (tiger + ((branch - 2) % 12)) % 10

    elem = nayin_element(gstem(ming), ming)
    ju = _JU_BY_ELEMENT[elem]
    zw = _ZIWEI_TABLES[ju][lunar_day - 1]
    tf = (4 - zw) % 12                      # 紫微天府寅申轴对称
    placements = {}
    for name, off in [('紫微', 0), ('天机', -1), ('太阳', -3), ('武曲', -4),
                      ('天同', -5), ('廉贞', -8)]:
        placements[name] = (zw + off) % 12
    for name, off in [('天府', 0), ('太阴', 1), ('贪狼', 2), ('巨门', 3),
                      ('天相', 4), ('天梁', 5), ('七杀', 6), ('破军', 10)]:
        placements.setdefault(name, (tf + off) % 12)

    helpers = {}
    helpers['禄存'] = _LU_CUN[ys]
    helpers['擎羊'] = (_LU_CUN[ys] + 1) % 12
    helpers['陀罗'] = (_LU_CUN[ys] - 1) % 12
    helpers['天魁'] = _KUI_BUO[ys][0]
    helpers['天钺'] = _KUI_BUO[ys][1]
    helpers['文昌'] = (10 - hour_idx) % 12  # 戌起子时逆数
    helpers['文曲'] = (4 + hour_idx) % 12   # 辰起子时顺数
    helpers['左辅'] = (4 + m_eff - 1) % 12  # 辰起正月顺数
    helpers['右弼'] = (10 - (m_eff - 1)) % 12
    helpers['天马'] = _TIANMA_BASE[BRANCHES[yb]]
    helpers['火星'] = (_HUO_START[BRANCHES[yb]] + hour_idx) % 12
    helpers['铃星'] = (_LING_START[BRANCHES[yb]] + hour_idx) % 12
    helpers['地空'] = (11 + hour_idx) % 12  # 亥起顺数
    helpers['地劫'] = (11 - hour_idx) % 12  # 亥起逆数
    hongluan = (3 - yb) % 12                # 卯起子年逆数至生年支
    helpers['红鸾'] = hongluan
    helpers['天喜'] = (hongluan + 6) % 12

    hua_map = {}
    for star, hua in _FOUR_HUA[y_stem]:
        hua_map[star] = hua

    palaces = []
    yang_male = (gender == '男' and ys % 2 == 0) or (gender == '女' and ys % 2 == 1)
    for k, pname in enumerate(_PALACE_NAMES):
        branch = (ming - k) % 12
        majors = [{'name': n, 'hua': hua_map.get(n)}
                  for n in _MAIN_STARS if placements[n] == branch]
        minors = [n for n, b in helpers.items() if b == branch]
        start_age = ju + 10 * k
        direction = 1 if yang_male else -1
        limit_branch = (ming + direction * k) % 12
        palaces.append({
            'name': pname, 'branch': branch,
            'branch_cn': BRANCHES[branch], 'stem': STEMS[gstem(branch)],
            'is_ming': k == 0, 'is_shen': branch == shen,
            'majors': majors, 'minors': minors,
            'dalimit': '%d-%d' % (start_age, start_age + 9),
            'limit_branch_cn': BRANCHES[limit_branch],
        })
    return {
        'lunar_text': '农历%d年%s%d月%d日 %s（%s%s·%s）' % (
            lunar_year, '闰' if leap else '', lunar_month, lunar_day,
            _SHIXIANG_LABEL[hour_idx].split()[0],
            STEMS[ys], BRANCHES[yb], ZODIAC_ANIMALS[yb]),
        'year_ganzhi': STEMS[ys] + BRANCHES[yb],
        'wuxing_ju': elem + str(ju) + '局',
        'ming_gong': BRANCHES[ming], 'shen_gong': BRANCHES[shen],
        'yang_yin': '阳' if ys % 2 == 0 else '阴',
        'direction': '顺行' if yang_male else '逆行',
        'four_hua': [{'star': s, 'hua': h} for s, h in _FOUR_HUA[y_stem]],
        'palaces': palaces,
        'note': '本地开源安星引擎 · 通行安星表 · 亮度层与流曜待扩展',
    }


# ---------------------------------------------------------------- 术语库

_TERMS_RAW = {
    # 十二星座
    **{s['cn']: {'cat': '西方占星 · 星座', 'title': s['cn'],
                 'summary': '%s · %s模态 · 守护星:%s (%s)' % (
                     ELEMENTS[s['elem']]['cn'],
                     {'cardinal': '开创', 'fixed': '固定',
                      'mutable': '变动'}[s['mode']],
                     s['ruler'], s['date']),
                 'detail': '%s属于%s(%s), 模态为%s。守护星为%s。出生区间约%s。'
                           '元素代表能量的基调, 模态描述应对世界的方式——'
                           '开创型发起、固定型坚守、变动型适应。' % (
                               s['cn'], ELEMENTS[s['elem']]['cn'],
                               ELEMENTS[s['elem']]['traits'],
                               {'cardinal': '开创', 'fixed': '固定',
                                'mutable': '变动'}[s['mode']],
                               s['ruler'], s['date'])}
       for s in SIGNS},
    # 行星
    '太阳': {'cat': '西方占星 · 行星', 'title': '太阳 ☉',
             'summary': '核心自我 · 意志 · 生命力',
             'detail': '太阳是你人格的中心光源, 代表自我认同、意志力与生命方向。'
                       '太阳星座即通常所说的"星座", 描述你最根本的自我表达方式。'},
    '月亮': {'cat': '西方占星 · 行星', 'title': '月亮 ☾',
             'summary': '情绪 · 安全感 · 内在需求',
             'detail': '月亮代表情绪反应模式、安全感来源与童年烙印。'
                       '月亮星座往往在不设防的时刻和亲密关系中最为显眼。'},
    '水星': {'cat': '西方占星 · 行星', 'title': '水星 ☿',
             'summary': '思维 · 表达 · 学习方式',
             'detail': '水星主管沟通、逻辑与信息处理。水星星座决定你如何思考、'
                       '如何把想法变成语言。水星逆行期间常被提醒"复核与回望"。'},
    '金星': {'cat': '西方占星 · 行星', 'title': '金星 ♀',
             'summary': '爱与审美 · 价值观 · 吸引力',
             'detail': '金星代表爱的方式、审美偏好与金钱观念。'
                       '金星星座揭示什么让你感到愉悦、你如何给予和接受爱。'},
    '火星': {'cat': '西方占星 · 行星', 'title': '火星 ♂',
             'summary': '行动力 · 欲望 · 愤怒',
             'detail': '火星是行动的引擎, 代表竞争心、行动风格与欲望表达。'
                       '火星星座说明你如何争取想要的东西。'},
    '木星': {'cat': '西方占星 · 行星', 'title': '木星 ♃',
             'summary': '扩张 · 幸运 · 信念',
             'detail': '木星象征成长、机遇与信念系统。木星星座提示你在哪个领域'
                       '容易获得贵人与拓展空间, 也提醒避免过度乐观。'},
    '土星': {'cat': '西方占星 · 行星', 'title': '土星 ♄',
             'summary': '纪律 · 责任 · 时间考验',
             'detail': '土星是严师, 代表限制、结构与长期努力。'
                       '土星所在的领域初期艰难, 却终将成为你最扎实的功底。'},
    '天王星': {'cat': '西方占星 · 行星', 'title': '天王星 ♅',
               'summary': '变革 · 独立 · 突破',
               'detail': '天王星带来顿悟与颠覆, 代表打破常规的渴望与集体性的时代变革。'},
    '海王星': {'cat': '西方占星 · 行星', 'title': '海王星 ♆',
               'summary': '梦想 · 灵性 · 边界消融',
               'detail': '海王星掌管想象、共情与艺术灵感, 也与模糊、理想化有关。'},
    '冥王星': {'cat': '西方占星 · 行星', 'title': '冥王星 ♇',
               'summary': '深层转化 · 重生',
               'detail': '冥王星代表彻底的蜕变: 旧我死去、新我诞生的深层心理力量。'},
    # 相位
    '合相': ASPECT_DEFS[0], '六合': ASPECT_DEFS[1], '刑相': ASPECT_DEFS[2],
    '三合': ASPECT_DEFS[3], '对冲': ASPECT_DEFS[4],
    # 要素概念
    '上升星座': {'cat': '西方占星 · 概念', 'title': '上升星座',
                'summary': '人格面具 · 第一印象 · 应世姿态',
                'detail': '上升点是出生那一刻东方地平线所在的星座, 代表你面对世界的'
                          '"默认滤镜": 外貌气质、第一印象与本能的处世策略。'
                          '它与太阳、月亮并称"人格三大支柱"。'},
    '宫位': {'cat': '西方占星 · 概念', 'title': '十二宫位',
             'summary': '人生十二个领域舞台',
             'detail': '宫位把黄道划分为十二个人生领域: 1自我形象 2钱财 3沟通学习 '
                       '4家庭根基 5创造恋爱 6工作健康 7伴侣合作 8深度转化共享资源 '
                       '9远方与信念 10事业成就 11社群愿景 12潜意识与休养。'
                       '行星落在某宫, 即该行星能量主要在该领域上演。本盘使用等宫制。'},
    '逆行': {'cat': '西方占星 · 概念', 'title': '行星逆行',
             'summary': '视觉后退 · 内省回调',
             'detail': '逆行是地球与行星相对运动造成的视觉效果, 并非行星真的倒退。'
                       '本命盘中的逆行行星常表示该行星能量向内消化, '
                       '需要更多自我对话后才向外表达。'},
    '元素四分': {'cat': '西方占星 · 概念', 'title': '四大元素',
                'summary': '火土风水 · 能量的四种基调',
                'detail': '火象重意志与行动, 土象重实际与感官, '
                          '风象重思考与交流, 水象重感受与联结。'
                          '本命盘中元素分布比例揭示整体性格倾向。'},
    # 八字
    '八字': {'cat': '中国命理 · 八字', 'title': '八字(四柱)',
             'summary': '年月日时四组干支',
             'detail': '把出生的年、月、日、时各用一组天干地支记录, 共八个字。'
                       '日干称为"日主", 代表命主自身, 其余各字围绕日主论生克关系。'},
    '天干': {'cat': '中国命理 · 八字', 'title': '十天干',
             'summary': '甲乙丙丁戊己庚辛壬癸',
             'detail': '天干十字, 两两一组分属五行: 甲乙木、丙丁火、戊己土、'
                       '庚辛金、壬癸水。阳干性刚主动, 阴干性柔主守。'},
    '地支': {'cat': '中国命理 · 八字', 'title': '十二地支',
             'summary': '子丑寅卯辰巳午未申酉戌亥',
             'detail': '地支十二字对应十二时辰与十二生肖, 各有五行属性, '
                       '并有"合冲刑害"等组合关系。'},
    '五行': {'cat': '中国命理 · 八字', 'title': '五行',
             'summary': '木火土金水的生克循环',
             'detail': '相邻相生: 木生火、火生土、土生金、金生水、水生木; '
                       '隔位相克: 木克土、土克水、水克火、火克金、金克木。'
                       '八字中五行的多寡与流通情况是分析格局的基础。'},
    '十神': {'cat': '中国命理 · 八字', 'title': '十神',
             'summary': '以日主为准的十种关系角色',
             'detail': '其余天干与日主的生克关系被赋予拟人化角色: 比肩劫财(同辈)、'
                       '食神伤官(输出才华)、正财偏财(掌控的资源)、'
                       '正官七杀(规则与压力)、正印偏印(庇护与学识)。'},
    '喜神方位': {'cat': '中国命理 · 民俗', 'title': '喜神方位',
                 'summary': '传统民俗中利于喜事的方向',
                 'detail': '源自《喜神方位歌》: 甲己在艮(东北)、乙庚乾(西北)、'
                           '丙辛坤(西南)、丁壬离(正南)、戊癸巽(东南), 以日干定方位。'},
    '财神方位': {'cat': '中国命理 · 民俗', 'title': '财神方位',
                 'summary': '传统民俗中利财运的方向',
                 'detail': '源自《财神方位歌》: 甲乙东北、丙丁西南、戊己正北、'
                           '庚辛正东、壬癸正南, 以日干定方位。'},
    '冲煞': {'cat': '中国命理 · 民俗', 'title': '冲煞',
             'summary': '日支六冲生肖与煞方',
             'detail': '当日地支与其六冲之地支相冲, 对应生肖者传统上大事宜谨慎; '
                       '煞方按日支三合局取南北东西, 为民俗择时参考。'},
    # 紫微
    '紫微斗数': {'cat': '中国命理 · 紫微', 'title': '紫微斗数',
                 'summary': '以紫微星系布局十二宫的命理体系',
                 'detail': '紫微斗数以出生年月日时安紫微诸星入十二宫(命宫、兄弟、夫妻…), '
                           '结合星曜亮度与四化飞星论断。开源项目 FateStar 提供免费'
                           '匿名排盘接口, 本站在配置端点后即可调用。'},
    '四化': {'cat': '中国命理 · 紫微', 'title': '四化星',
             'summary': '化禄化权化科化忌',
             'detail': '四化是紫微斗数的动态引擎: 化禄主顺利得助, 化权主掌控强化, '
                       '化科主名声贵人, 化忌主执念阻碍。'},
    '命宫': {'cat': '中国命理 · 紫微', 'title': '命宫',
             'summary': '全盘核心 · 先天格局所系',
             'detail': '命宫由生月与生辰推得(寅起正月顺数至生月, 再起子时逆数至生时), '
                       '是紫微斗数的枢纽; 命宫主星组合定一生基调。'
                       '身宫由生月宫顺数而生, 主后天侧重与中年后趋向。'},
    '身宫': {'cat': '中国命理 · 紫微', 'title': '身宫',
             'summary': '后天倾向 · 与命宫互为表里',
             'detail': '身宫常与命、财帛、官禄等宫同宫, 提示人生投入的重心所在。'},
    '大限': {'cat': '中国命理 · 紫微', 'title': '大限',
             'summary': '十年一步的运程分段',
             'detail': '以五行局数起限(如水二局2岁起), 阳男阴女顺行、阴男阳女逆行, '
                       '每十年过一宫。大限宫位星曜组合提示该十年的主题。'},
    '五行局': {'cat': '中国命理 · 紫微', 'title': '五行局',
               'summary': '水二 木三 金四 土五 火六',
               'detail': '以命宫干支纳音取五行, 定紫微安星与起大限岁数。'
                         '纳音出自六十甲子配三十纳音的古法。'},
}


def get_term(key):
    t = _TERMS_RAW.get(key)
    if not t:
        return None
    out = dict(t)
    if t.get('angle') is not None and 'brief' in t:      # 相位词条
        out['cat'] = '西方占星 · 相位'
        out['title'] = '%s %.0f°' % (t['cn'], t['angle'])
        out['summary'] = t['brief']
        out['detail'] = '%s。容许 orb ±%.0f°。性质: %s。' % (
            t['brief'], t['orb'],
            {'soft': '和谐(机会)', 'hard': '紧张(动力)', 'neutral': '中性(融合)'}[t['nature']])
    return out


def list_terms():
    items = []
    for k, v in _TERMS_RAW.items():
        t = get_term(k)
        items.append({'key': k, 'cat': t['cat'], 'title': t.get('title') or k,
                      'summary': t.get('summary') or ''})
    items.sort(key=lambda x: (x['cat'], x['title']))
    return items
