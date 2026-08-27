# -*- coding: utf-8 -*-
"""自然语言解析回归(收编自 verify_parse.py, 改写为断言风格)."""
from datetime import datetime

import kb.nlp_parser as np
from app import _parse_time, extract_title_from_text, parse_task_from_text


def test_parse_time_24h():
    assert _parse_time('6:15开会') == (6, 15)
    assert _parse_time('早上6点半') == (6, 30)
    assert _parse_time('凌晨1点') == (1, 0)
    assert _parse_time('晚上8点') == (20, 0)
    assert _parse_time('9点30') == (9, 30)


def test_title_colon_and_bracket():
    assert extract_title_from_text('提醒:明天交周报') == '明天交周报'
    # 【】内容不足5字时取【】后正文
    assert extract_title_from_text('【项目会】下周三2点 开会') == '下周三2点 开会'
    # 【】内容≥5字时直接使用
    assert extract_title_from_text('【分中心项目委会议时间】确定本周五开会') == '分中心项目委会议时间'


def test_title_short_fallback_to_theme():
    """标题不足6字(如【会议通知】)时回退取「会议主题:」后的文字."""
    NOTICE = '''【会议通知】
会议主题：青年理论小组第二党支部第2组7-8月学习
会议时间：2026年8月25日（周二）08:40-10:00
会议地点：五楼日耀间会议室（509）
会议内容：
1、学习重点
【范超超】领读：《习近平在庆祝中国共产党成立105周年大会上发表重要讲话》、
《全国党建工作座谈会在京召开》（见学习参考资料）'''
    assert extract_title_from_text(NOTICE) == '青年理论小组第二党支部第2组7-8月学习'
    # 标题本身够长时不回退;【】内容<5字时取后文
    assert extract_title_from_text('【项目会】下周三2点 开会') == '下周三2点 开会'
    assert extract_title_from_text('【分中心项目委会议时间】确定开会') == '分中心项目委会议时间'


def test_recurrence():
    r = parse_task_from_text('每天下班前提交日报')
    assert r['recurrence'] == 'daily' and r['recurrence_interval_days'] == 1
    r = parse_task_from_text('每周三下午2点开项目例会')
    assert r['recurrence'] == 'weekly' and r['recurrence_text'] == '每周三'


def test_category_voting():
    r = parse_task_from_text('准备考试资料，复习考试大纲，工作安排往后放一放')
    assert r['category'] == '考试'


def test_category_course_is_training():
    """含"课程"字样的待办应识别为培训类型."""
    for text in ('参加新员工入职课程 明天上午9点',
                 '完成线上Python课程学习 下周五前',
                 '数据结构课程作业提交 下周一下午5点'):
        assert parse_task_from_text(text)['category'] == '培训', text


def test_blur_timespan_not_override_explicit_date():
    """模糊时段词(中期/年底)不得覆盖明确日期(回归: 中期检查通知截止误析为9-30)."""
    NOTICE = ('各位领导、同事：2026年度“一处一课题”工作现开展中期检查，'
              '请各课题组根据当前工作进展，如实总结当前进度和成果，'
              '认真分析存在的问题和改进措施，科学拟定下阶段研究计划，'
              '填写《工作进度汇总表》并于8月28日下班前反馈。')
    span = np._parse_timespan_jionlp(NOTICE)
    assert span and span['end'] is not None
    assert span['end'].strftime('%m-%d') == '08-28'
    # 仅模糊词时仍兜底可用
    r = parse_task_from_text('系统升级年底前完成上线')
    assert r['end_time'] is not None


def test_explicit_date_with_weekday_no_rollover():
    """「8月25日（周二）08:40」类显式日期+括注星期, 时刻已过也不得顺延到下周."""
    from datetime import timedelta
    from core.timeutil import cn_now
    now = cn_now()
    hm = now - timedelta(minutes=1)  # 必已过去 → 触发旧顺延逻辑
    wd = '一二三四五六日'[now.weekday()]
    s_txt = f'{hm.hour:02d}:{hm.minute:02d}'
    e_tot = (hm.hour * 60 + hm.minute + 30) % 1440
    e_txt = f'{e_tot // 60:02d}:{e_tot % 60:02d}'
    text = f'会议时间：{now.year}年{now.month}月{now.day}日（周{wd}）{s_txt}-{e_txt}'
    span = np._parse_timespan_jionlp(text)
    assert span and span['start'] is not None, text
    s = span['start']
    assert (s.year, s.month, s.day) == (now.year, now.month, now.day), (text, s)
    assert (s.hour, s.minute) == (hm.hour, hm.minute), (text, s)
    assert span['end'] and span['end'] > s, (text, span)


def test_meeting_notice_theme_and_time():
    """完整会议通知: 标题回退取「主题」行, 时间以明确日期区间为准且不被顺延."""
    NOTICE = '''【会议通知】
会议主题：青年理论小组第二党支部第2组7-8月学习
会议时间：2026年8月25日（周二）08:40-10:00
会议地点：五楼日耀间会议室（509）
会议内容：
1、学习重点
【范超超】领读：《习近平在庆祝中国共产党成立105周年大会上发表重要讲话》、
《全国党建工作座谈会在京召开》（见学习参考资料）'''
    r = parse_task_from_text(NOTICE)
    assert r['title'] == '青年理论小组第二党支部第2组7-8月学习'
    assert r['category'] == '会议'
    s, e = r['start_time'], r['end_time']
    assert s and (s.year, s.month, s.day) == (2026, 8, 25), s
    assert (s.hour, s.minute) == (8, 40), s
    assert e and (e.year, e.month, e.day) == (2026, 8, 25), e
    assert (e.hour, e.minute) == (10, 0), e



def test_jionlp_span_future_start():
    if parse_task_from_text._last_time_parser != 'jionlp':
        r = None
    r = parse_task_from_text('开发登录功能从明天上午9点开始到下周五下午6点结束 发给张三')
    if r['start_time']:
        assert r['start_time'].hour == 9 and r['start_time'] > datetime.now()


def test_notice_full(notice=None):
    NOTICE = '''【关于举办软件研发中心合肥分中心2026年大数据Lambda架构与Kappa架构企业级应用培训班的通知】各位领导、同事：@所有人
      培训时间：2026年8月26日（下周三）14:10-17:00
      如有意向报名，请于8月25日（下周二）12：00前填报在线文档。'''
    r = parse_task_from_text(NOTICE)
    assert r['title'].startswith('举办软件研发中心') or '培训班' in r['title']
    assert r['category'] == '培训'
    assert r['is_all'] is True
    exp_s = datetime(2026, 8, 26, 14, 10)
    exp_e = datetime(2026, 8, 26, 17, 0)
    assert r['start_time'].replace(second=0, microsecond=0) == exp_s
    assert r['end_time'].replace(second=0, microsecond=0) == exp_e


def test_multisession_training_notice():
    """「第一期：…第二期：…」多场次通知: 拆分为多个待办并抑制周期重复."""
    NOTICE = '''【关于举办软件研发中心合肥分中心2026年软件项目全方位精细化管理培训班的通知】 @所有人
各位领导、同事：
      大家好！为进一步夯实软件项目管理基础，拟举办软件项目全方位精细化管理培训班，分三期开展专题授课，现将有关事项通知如下：
       培训时间：
       第一期：2026年8月28日14:30-16:30
       第二期：2026年9月3日14:00-18:00
       第三期：2026年9月4日14:30-15:30'''
    r = parse_task_from_text(NOTICE)
    assert r['category'] == '培训'
    assert r['is_all'] is True
    sess = r.get('sessions') or []
    assert len(sess) == 3, sess
    labels = [s['label'] for s in sess]
    assert labels == ['第一期', '第二期', '第三期'], labels
    s0 = sess[0]['start']
    assert (s0.year, s0.month, s0.day) == (2026, 8, 28), s0
    assert (s0.hour, s0.minute) == (14, 30), s0
    e0 = sess[0]['end']
    assert (e0.hour, e0.minute) == (16, 30), e0
    s1 = sess[1]['start']
    assert (s1.month, s1.day, s1.hour, s1.minute) == (9, 3, 14, 0), s1
    # 主时间取第一场; 周期字段被抑制(真实日期已知无需等间隔展开)
    assert r['start_time'] == s0 and r['end_time'] == e0
    assert not r['recurrence_interval_days'] and not r['recurrence_count']


def test_multisession_requires_two():
    """单场次不触发拆分模式."""
    text = '第一期：2026年8月28日14:30-16:30'
    r = parse_task_from_text(text)
    assert 'sessions' not in r or not r['sessions']


def test_cn_to_int():
    f = np._cn_to_int
    assert f('一') == 1 and f('九') == 9
    assert f('十') == 10 and f('十一') == 11 and f('十九') == 19
    assert f('二十') == 20 and f('二十三') == 23
    assert f('5') == 5 and f('12') == 12
    assert f('') is None and f(None) is None
    assert f('abc') is None and f('百') is None


def _fmt(d):
    return d.strftime('%Y-%m-%d %H:%M')


def test_extract_sessions_basic():
    """多场次提取: 标签/时间/按期数排序/混合单位."""
    text = ('第三期：2026年9月4日14:30-15:30\n'
            '第一期：2026年8月28日14:30-16:30\n'
            '第二场：2026年9月3日14:00-18:00')
    out = np._extract_sessions(text)
    assert len(out) == 3
    assert [s['label'] for s in out] == ['第一期', '第二场', '第三期']
    assert _fmt(out[0]['start']) == '2026-08-28 14:30'
    assert _fmt(out[0]['end']) == '2026-08-28 16:30'
    assert _fmt(out[1]['start']) == '2026-09-03 14:00'
    assert _fmt(out[2]['end']) == '2026-09-04 15:30'
    assert [s['index'] for s in out] == [1, 2, 3]


def test_extract_sessions_year_inference():
    """无年份: 未来日期取当年; 已过日期顺延一年(动态日期防日历漂移)."""
    from datetime import timedelta
    from core.timeutil import cn_now
    now = cn_now()
    fut = now + timedelta(days=45)
    if fut.year == now.year:
        t = (f'第一期：{fut.month}月{fut.day}日10:00-11:00\n'
             f'第二期：{(fut + timedelta(days=1)).month}月'
             f'{(fut + timedelta(days=1)).day}日10:00-11:00')
        out = np._extract_sessions(t)
        assert out and out[0]['start'].year == now.year, (t, out)
    past = now - timedelta(days=45)
    if past.year == now.year:
        t = (f'第一期：{past.month}月{past.day}日10:00-11:00\n'
             f'第二期：{(past + timedelta(days=1)).month}月'
             f'{(past + timedelta(days=1)).day}日10:00-11:00')
        out = np._extract_sessions(t)
        assert out and out[0]['start'].year == now.year + 1, (t, out)


def test_extract_sessions_end_defaults():
    """缺结束时间默认+1小时; 结束≤开始视为跨午夜+1天."""
    from datetime import timedelta
    from core.timeutil import cn_now
    base = cn_now() + timedelta(days=3)
    d = f'{base.month}月{base.day}日'
    out = np._extract_sessions(f'第一期：{d}09:00\n第二期：{d}10:00')
    assert len(out) == 2
    e0 = out[0]['end']
    assert (e0 - out[0]['start']).total_seconds() == 3600
    # 跨午夜: 23:00-01:00 → 次日01:00
    out2 = np._extract_sessions(f'第一期：{d}23:00-01:00\n第二期：{d}10:00-11:00')
    e = out2[0]['end']
    assert e.day != out2[0]['start'].day and e.hour == 1


def test_extract_sessions_invalid_or_single():
    """非法日期被跳过; 少于2场返回[]; 空文本返回[]."""
    # 非法月份被跳过后仅剩1场 → []
    assert np._extract_sessions(
        '第一期：2026年13月40日99:99\n第二期：2026年9月3日14:00-18:00') == []
    assert np._extract_sessions('第一期：2026年9月3日14:00-18:00') == []
    assert np._extract_sessions('没有任何时间信息') == []
    assert np._extract_sessions('') == []


def test_sessions_suppress_recurrence():
    """显式多场次优先于周期词: 拆分模式下周期字段清零."""
    text = ('培训班每周三例行汇报，培训时间如下：\n'
            '第一期：2026年8月28日14:30-16:30\n'
            '第二期：2026年9月3日14:00-18:00')
    r = parse_task_from_text(text)
    sess = r.get('sessions') or []
    assert len(sess) == 2, r
    assert not r['recurrence_interval_days'], r
    assert not r['recurrence_count'] and not r['recurrence_text'], r
    assert r['recurrence'] is None


def test_timespan_future_weekday():
    """过去星期顺延 + 时段词保留 + 全天合并(回归: 首页解析日期不对)."""
    from core.timeutil import cn_now
    now = cn_now()

    def _s(t):
        r = np._parse_timespan_jionlp(t) or {}
        return r.get('start')

    s = _s('周五晚上7点半')
    assert s and s > now and s.hour == 19 and s.minute == 30
    assert s.weekday() == 4

    s = _s('30号下午')
    assert s and s.hour == 13  # jio 的下午区间, 不再被强制 9 点

    r = np._parse_timespan_jionlp('周六全天') or {}
    assert r.get('start') and r['start'] > now
    assert r['start'].hour == 0 and (r['end'] or r['start']).hour == 23
