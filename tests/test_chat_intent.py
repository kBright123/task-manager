# -*- coding: utf-8 -*-
"""意图分类: 携带内容性宾语的句子(材料/记录/流程等)优先走检索,
不被日程关键词(会议/安排/开会)抢占, 纯日程问法仍归 schedule。"""
from kb.chat_intent import classify_question


def test_content_questions_not_hijacked_by_schedule():
    # 问的是具体内容 → 应交由检索/问答路径, 而非"查日程"
    assert classify_question('会议材料有哪些')['intent'] != 'schedule'
    assert classify_question('会议材料安排')['intent'] != 'schedule'
    assert classify_question('会议记录怎么整理')['intent'] != 'schedule'
    assert classify_question('青年学习')['intent'] != 'schedule'


def test_pure_schedule_questions_kept():
    assert classify_question('今天有什么任务')['intent'] == 'schedule'
    assert classify_question('明天有哪些待办')['intent'] == 'schedule'
    assert classify_question('下周开会时间')['intent'] == 'schedule'
    assert classify_question('今天有会议吗')['intent'] == 'schedule'
    assert classify_question('本周工作安排')['intent'] == 'schedule'