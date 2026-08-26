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
