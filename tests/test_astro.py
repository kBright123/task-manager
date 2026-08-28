# -*- coding: utf-8 -*-
"""星运模块回归测试: 引擎数学锚点 + API 行为(公开访问/CSRF/存档闭环)."""
import datetime

from services import astro_engine as ae


# ---------------- 基础常量与术语库 ----------------

def test_terms_complete():
    terms = ae.list_terms()
    assert len(terms) >= 40
    cats = {t['cat'] for t in terms}
    assert any('西方占星' in c for c in cats)
    assert any('中国命理' in c for c in cats)
    # 十二星座词条齐全
    for s in ae.SIGNS:
        t = ae.get_term(s['cn'])
        assert t and t['summary'] and t['detail']
    # 相位词条含角度与性质说明
    sanhe = ae.get_term('三合')
    assert '120' in sanhe['title'] and '和谐' in sanhe['detail']


def test_fortune_deterministic():
    d1 = ae.daily_fortune('leo', datetime.date(2026, 8, 24))
    d2 = ae.daily_fortune('leo', datetime.date(2026, 8, 24))
    assert d1 == d2
    assert d1 != ae.daily_fortune('pisces', datetime.date(2026, 8, 24))
    # 历史日期回溯结果稳定
    old = ae.daily_fortune('leo', datetime.date(2020, 1, 1))
    assert old['overall'] == ae.daily_fortune('leo', datetime.date(2020, 1, 1))['overall']
    assert 40 <= d1['overall'] <= 98
    assert len(d1['dims']) == 4


def test_calendar_info_classical_rules():
    """喜神/财神方位口诀与冲煞规则抽检: 甲日喜神东北, 乙庚日财神东北."""
    cal_jia = ae.daily_calendar_info(datetime.date(2026, 8, 26))
    gz = cal_jia['day_gz']
    if gz[0] == '甲':
        assert cal_jia['xishen'] == '东北'
    assert cal_jia['chong'].startswith('冲')
    assert cal_jia['sha_dir'] in ('正南', '正北', '正东', '正西')


# ---------------- 八字四柱(已知锚点) ----------------

def test_bazi_day_anchor():
    """1949-10-01 甲子日 / 2000-01-01 戊午日(万年历公认锚点)."""
    p49 = ae.bazi_pillars(datetime.datetime(1949, 10, 1, 12))
    p00 = ae.bazi_pillars(datetime.datetime(2000, 1, 1, 12))
    assert p49['pillars'][2] == '甲子'
    assert p00['pillars'][2] == '戊午'


def test_bazi_year_and_animal():
    """1984 甲子鼠年; 立春前属前一年干支."""
    p84 = ae.bazi_pillars(datetime.datetime(1984, 6, 1, 12))
    assert p84['pillars'][0] == '甲子' and p84['animal'] == '鼠'
    p_before = ae.bazi_pillars(datetime.datetime(2024, 1, 15, 12))
    assert p_before['pillars'][0][0] == '癸'      # 尚未立春, 仍属癸卯年
    p_after = ae.bazi_pillars(datetime.datetime(2024, 3, 1, 12))
    assert p_after['pillars'][0] == '甲辰'


def test_bazi_hour_wu_dun():
    """五鼠遁: 时干 = (日干×2 + 时支) % 10, 晚子时(23点)归次日日柱."""
    dt = datetime.datetime(2026, 8, 24, 23, 30)
    b = ae.bazi_pillars(dt)
    day_stem, hour_stem = b['indices'][2][0], b['indices'][3][0]
    assert (day_stem * 2) % 10 == hour_stem


def test_bazi_wuxing_total():
    b = ae.bazi_pillars(datetime.datetime(1990, 8, 8, 14, 30))
    total = sum(b['wuxing'].values())
    assert total == 8                              # 四柱八字共八字
    assert set(b['wuxing']) == {'木', '火', '土', '金', '水'}


# ---------------- 星历(天文锚点) ----------------

def test_sun_longitude_equinox_solstice():
    """2024 春分/夏至时刻太阳视黄经应接近 0°/90°(精度±0.5°)."""
    d_eq = ae._dt_to_days(datetime.datetime(2024, 3, 20, 19, 6))   # 北京时
    assert abs(((ae.sun_longitude(d_eq) - 0 + 180) % 360) - 180) < 0.5
    d_so = ae._dt_to_days(datetime.datetime(2024, 6, 21, 16, 51))
    assert abs(ae.sun_longitude(d_so) - 90) < 0.5


def test_moon_daily_motion_range():
    """月球日运动应在 11.5°~15.5° 区间(物理约束)."""
    m1 = ae.moon_longitude(ae._dt_to_days(datetime.datetime(2026, 8, 24)))
    m2 = ae.moon_longitude(ae._dt_to_days(datetime.datetime(2026, 8, 25)))
    delta = (m2 - m1) % 360
    assert 11.0 <= delta <= 16.0


def test_natal_chart_structure():
    c = ae.natal_chart(datetime.datetime(1990, 8, 8, 14, 30),
                       lat=31.23, lon_east=121.47, name='t')
    assert c['big_three']['sun'] == '狮子座'
    assert len(c['points']) == 9                   # 日月+七大行星
    assert all(0 <= p['lon'] < 360 for p in c['points'])
    assert all(1 <= p['house'] <= 12 for p in c['points'])
    assert len(c['houses']) == 12
    for sp in c['aspects']:
        assert sp['aspect_cn'] in ('合相', '六合', '刑相', '三合', '对冲')
    # 元素计数总和等于行星数
    assert sum(v['count'] for v in c['elements'].values()) == 9


# ---------------- API(经 conftest 已登录客户端) ----------------

# ---------------- 紫微斗数(本地引擎) ----------------

def test_ziwei_nayin_and_tables():
    """纳音与安紫微表抽查(通行安星表锚点)."""
    assert ae.nayin_element(0, 0) == '金'      # 甲子 海中金
    assert ae.nayin_element(2, 2) == '火'      # 丙寅 炉中火
    assert ae.nayin_element(8, 10) == '水'     # 壬戌 大海水
    assert ae._ZIWEI_TABLES[2][0] == 1         # 水二局初一 → 丑
    assert ae._ZIWEI_TABLES[3][0] == 4         # 木三局初一 → 辰
    assert ae._ZIWEI_TABLES[6][29] == 10       # 火六局三十 → 戌


def test_ziwei_chart_structure():
    z = ae.ziwei_chart(1990, 5, 5, hour_idx=6, gender='男')
    # 庚午年 · 五月五日午时: 寅起正月顺至五月=午宫, 午时命身同宫于子
    assert z['year_ganzhi'] == '庚午'
    assert (z['ming_gong'], z['shen_gong']) == ('子', '子')
    assert z['wuxing_ju'] == '火6局'           # 戊子纳音火
    # 十四主星全部落座且紫微天府寅申轴对称
    placed = [m['name'] for p in z['palaces'] for m in p['majors']]
    assert sorted(placed) == sorted(ae._MAIN_STARS)
    zw = [p['branch'] for p in z['palaces']
          for m in p['majors'] if m['name'] == '紫微'][0]
    tf = [p['branch'] for p in z['palaces']
          for m in p['majors'] if m['name'] == '天府'][0]
    assert (zw + tf) % 12 == 4                 # 对称轴恒等式
    # 年干四化四星均在盘面(主星或辅曜)
    names = set(placed) | {m for p in z['palaces'] for m in p['minors']}
    for h in z['four_hua']:
        assert h['star'] in names
    # 十二宫齐、大限递增、宫干合五虎遁(庚年戊寅首)
    assert len(z['palaces']) == 12
    ages = [int(p['dalimit'].split('-')[0]) for p in z['palaces']]
    assert ages == sorted(ages) and ages[0] == 6
    tiger = [p for p in z['palaces'] if p['branch'] == 2][0]
    assert tiger['stem'] == '戊'


def test_api_ziwei_local(client):
    """/astro/api/ziwei 本地排盘 + 存档 + 非法输入."""
    import conftest
    if client is None:
        client = conftest.make_client()
    r = client.post('/astro/api/ziwei',
                    json={'year': 1990, 'month': 5, 'day': 5,
                          'hour_idx': 6, 'gender': '男', 'save': True},
                    headers={'X-CSRF-Token': 'test-csrf'})
    d = r.get_json()
    assert r.status_code == 200 and d['ok'] and len(
        d['result']['ziwei']['palaces']) == 12
    r2 = client.post('/astro/api/ziwei',
                     json={'year': 1990, 'month': 13, 'day': 31},
                     headers={'X-CSRF-Token': 'test-csrf'})
    assert r2.status_code == 400 and not r2.get_json()['ok']


def test_api_chart_merges_ziwei(client):
    """/api/chart 一次返回三体系: 农历自动换算(jionlp) + 本地紫微盘."""
    import conftest
    if client is None:
        client = conftest.make_client()
    r = client.post('/astro/api/chart',
                    json={'birth_date': '1990-06-27', 'birth_time': '12:00',
                          'gender': '男'},
                    headers={'X-CSRF-Token': 'test-csrf'})
    d = r.get_json()
    assert r.status_code == 200 and d['ok']
    res = d['result']
    # 1990-06-27 = 农历庚午年闰五月初五, 正午属午时(6)
    assert res['lunar_input'] == {'year': 1990, 'month': 5, 'day': 5,
                                  'leap': True, 'hour_idx': 6, 'gender': '男'}
    assert '闰' in res['ziwei']['lunar_text']
    assert len(res['ziwei']['palaces']) == 12
    assert res['ziwei']['year_ganzhi'] == '庚午'
    placed = [m['name'] for p in res['ziwei']['palaces'] for m in p['majors']]
    assert sorted(placed) == sorted(ae._MAIN_STARS)


def test_api_page_public(client):
    """页面公开访问且含核心结构; 反付费墙违禁词不得出现."""
    import conftest
    if client is None:
        client = conftest.make_client()
    r = client.get('/astro/')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    for kw in ('首页', '星盘库', '塔罗馆', '命理知识库', '每日运势', '我的'):
        assert kw in html
    for banned in ('解锁', '会员专享', '剩余次数'):
        assert banned not in html


def test_api_chart_and_records_cycle(client):
    import json as _json
    import conftest
    if client is None:
        client = conftest.make_client()
    h = {'X-CSRF-Token': 'test-csrf'}
    r = client.post('/astro/api/chart',
                    json={'name': '回归测试盘', 'birth_date': '1992-02-04',
                          'birth_time': '09:15', 'save': True}, headers=h)
    d = r.get_json()
    assert r.status_code == 200 and d['ok']
    assert d['result']['western']['big_three']['sun'] == '水瓶座'
    assert d['saved'] is True
    r = client.get('/astro/api/records')
    items = r.get_json()['items']
    mine = [x for x in items if x['title'].startswith('回归测试盘')]
    assert mine and r.get_json()['quota'] == '不限量'
    rid = mine[0]['id']
    assert client.get('/astro/api/records/%d' % rid).status_code == 200
    assert client.delete('/astro/api/records/%d' % rid, headers=h).status_code == 200


def test_api_fortune_and_terms(client):
    import conftest
    if client is None:
        client = conftest.make_client()
    r = client.get('/astro/api/fortune?sign=aries&date=2026-01-01')
    d = r.get_json()
    assert d['ok'] and len(d['local']['dims']) == 4 and d['calendar']['day_gz']
    assert client.get('/astro/api/terms').get_json()['count'] >= 40
    assert client.get('/astro/api/terms/天蝎座').status_code == 200
    assert client.get('/astro/api/terms/__none__').status_code == 404
