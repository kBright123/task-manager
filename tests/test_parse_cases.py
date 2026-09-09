# -*- coding: utf-8 -*-
"""自然语言解析用例(收编自原自带 sys.exit 的脚本, 改写为 pytest 函数式).

环境变量与 sys.path 由 tests/conftest.py 统一注入, 模块内不再自行设置/退出.
"""
from datetime import datetime

from app import _parse_time, extract_title_from_text, parse_task_from_text


def test_parse_time_keeps_24h():
    """时间解析保持 24 小时制(回归: 6:15 不得被当作下午)."""
    assert _parse_time('6:15开会') == (6, 15)
    assert _parse_time('早上6点半') == (6, 30)
    assert _parse_time('凌晨1点') == (1, 0)
    assert _parse_time('晚上8点') == (20, 0)
    assert _parse_time('9点30') == (9, 30)


def test_title_colon_strip():
    """「标题:」冒号前缀被剥离."""
    assert extract_title_from_text('提醒:明天交周报') == '明天交周报'


def test_title_bracket_short_falls_back():
    """【】内容不足5字时取【】后正文(回归: 旧脚本误断言取【】内文字)."""
    assert extract_title_from_text('【项目会】下周三2点 开会') == '下周三2点 开会'


def test_recurrence_intervals():
    """「每天→daily」与「每周三→weekly+周三文本」."""
    r = parse_task_from_text('每天下班前提交日报')
    assert r['recurrence'] == 'daily' and r['recurrence_interval_days'] == 1
    r = parse_task_from_text('每周三下午2点开项目例会')
    assert r['recurrence'] == 'weekly' and r['recurrence_text'] == '每周三'


def test_category_voting():
    """同句中考试相关词计数多于工作 → 分类=考试."""
    r = parse_task_from_text('准备考试资料，复习考试大纲，工作安排往后放一放')
    assert r['category'] == '考试'


def test_jionlp_span_future_start():
    """JioNLP 集成: 明确时段 start 为未来时刻."""
    if parse_task_from_text._last_time_parser != 'jionlp':
        return  # 降级守卫: 无 jionlp 时跳过
    r = parse_task_from_text('开发登录功能从明天上午9点开始到下周五下午6点结束 发给张三')
    assert r['start_time'].hour == 9 and r['start_time'] > datetime.now()


def test_no_timeword_end_fallback():
    """无时间词待办: 兜底给出默认 end_time."""
    r = parse_task_from_text('随便写点东西')
    assert r['end_time'] is not None


def test_notice_full_parse():
    """完整培训通知: 标题/分类/@所有人/起止时间逐一解析."""
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