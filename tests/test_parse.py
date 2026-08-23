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
    assert extract_title_from_text('【项目会】下周三2点 开会') == '项目会'


def test_recurrence():
    r = parse_task_from_text('每天下班前提交日报')
    assert r['recurrence'] == 'daily' and r['recurrence_interval_days'] == 1
    r = parse_task_from_text('每周三下午2点开项目例会')
    assert r['recurrence'] == 'weekly' and r['recurrence_text'] == '每周三'


def test_category_voting():
    r = parse_task_from_text('准备考试资料，复习考试大纲，工作安排往后放一放')
    assert r['category'] == '考试'


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
