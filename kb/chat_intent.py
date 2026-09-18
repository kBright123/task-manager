# -*- coding: utf-8 -*-
"""自然语言提问的规则意图分类 + 时间解析(小知识助手与所有私聊会话复用).

纯文本处理(不触碰数据库); 时间源统一来自 core.timeutil.cn_now。
规则按优先级顺序匹配(问候 → 帮助 → 教育/上传 → 创建待办/随手记 →
完成任务 → 日程 → 检索 → 知识库 → 闲聊兜底), 命中即返回。

intent 取值:
- greeting  问候
- help      帮助
- education 教育娱乐(前端打开教育模式)
- upload    上传知识(前端打开上传)
- task_create 创建待办(前端打开快速待办)
- note_create 随手记(前端打开随手记)
- task_done 标记完成任务(后端查找待办, 不做写库)
- schedule  日程/待办查询(时间解析决定查询区间)
- search    全站检索(待办+随手记+知识库)
- knowledge 知识库问答
- chat      闲聊兜底
"""
import re
from datetime import datetime, time as dt_time, timedelta

from core.timeutil import cn_now

_DAY_OFFSET = {'大后天': 3, '后天': 2, '明天': 1, '今天': 0}
_WEEKDAY = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}


def parse_question_time(text):
    """解析提问中的时间,返回 dict 或 None。

    {'label': 命中的时间原文, 'range_label': 展示用区间名,
     'start': datetime, 'end': datetime(不含)}
    未命中任何时间词时默认「今天」区间。
    """
    text = (text or '').strip()
    if not text:
        return None
    now = cn_now()
    today = now.date()

    if '最近' in text or '近期' in text or '这几天' in text:
        start = datetime.combine(today, dt_time.min)
        return {'label': '最近', 'range_label': '最近',
                'start': start, 'end': datetime.combine(today + timedelta(days=7), dt_time.min)}

    for word, off in (('大后天', 3), ('后天', 2), ('明天', 1), ('今天', 0)):
        if word in text:
            base = today + timedelta(days=off)
            if word == '今天' and '明天' in text:
                continue
            start = datetime.combine(base, dt_time.min)
            return {'label': word, 'range_label': word,
                    'start': start, 'end': start + timedelta(days=1)}

    m = re.search(r'下下(?:周|星期)([一二三四五六日天])', text)
    if m:
        target = _WEEKDAY.get(m.group(1), 0)
        days = target - today.weekday()
        if days <= 0:
            days += 14
        else:
            days += 7
        base = today + timedelta(days=days)
        start = datetime.combine(base, dt_time.min)
        label = '下下' + m.group(0)[2:]
        return {'label': label, 'range_label': label,
                'start': start, 'end': start + timedelta(days=1)}

    m = re.search(r'下(?:周|星期)([一二三四五六日天])', text)
    if m:
        target = _WEEKDAY.get(m.group(1), 0)
        days = target - today.weekday() + 7
        base = today + timedelta(days=days)
        start = datetime.combine(base, dt_time.min)
        label = '下周' + m.group(1)
        return {'label': label, 'range_label': label,
                'start': start, 'end': start + timedelta(days=1)}

    m = re.search(r'(这|本)(?:周|星期)([一二三四五六日天])', text)
    if m:
        target = _WEEKDAY.get(m.group(2), 0)
        days = target - today.weekday()
        if days < 0:
            days += 7
        base = today + timedelta(days=days)
        start = datetime.combine(base, dt_time.min)
        label = '本周' + m.group(2)
        return {'label': label, 'range_label': label,
                'start': start, 'end': start + timedelta(days=1)}

    if re.search(r'(本周|这周|这星期|本星期)', text):
        base = today - timedelta(days=today.weekday())
        start = datetime.combine(base, dt_time.min)
        return {'label': '本周', 'range_label': '本周',
                'start': start, 'end': start + timedelta(days=7)}
    if re.search(r'(下周|下星期)', text):
        base = today + timedelta(days=7 - today.weekday())
        start = datetime.combine(base, dt_time.min)
        return {'label': '下周', 'range_label': '下周',
                'start': start, 'end': start + timedelta(days=7)}
    if re.match(r'周([一二三四五六日天])', text):
        target = _WEEKDAY.get(m.group(1), 0) if (m := re.match(r'周([一二三四五六日天])', text)) else 0
        days = target - today.weekday()
        if days < 0:
            days += 7
        base = today + timedelta(days=days)
        start = datetime.combine(base, dt_time.min)
        label = '周' + (m.group(1) if m else '')
        return {'label': label, 'range_label': label,
                'start': start, 'end': start + timedelta(days=1)}

    m = re.search(r'(\d{1,2})月(\d{1,2})[日号]?', text)
    if m:
        try:
            mo, d = int(m.group(1)), int(m.group(2))
            y = now.year
            base = datetime(y, mo, d).date()
            if base < today:
                base = datetime(y + 1, mo, d).date()
            start = datetime.combine(base, dt_time.min)
            return {'label': f'{mo}月{d}日', 'range_label': f'{mo}月{d}日',
                    'start': start, 'end': start + timedelta(days=1)}
        except (ValueError, OverflowError):
            pass
    m = re.search(r'(\d{4})[年-](\d{1,2})[月-](\d{1,2})', text)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            start = datetime.combine(datetime(y, mo, d).date(), dt_time.min)
            return {'label': f'{y}年{mo}月{d}日',
                    'range_label': f'{y}年{mo}月{d}日',
                    'start': start, 'end': start + timedelta(days=1)}
        except (ValueError, OverflowError):
            pass

    start = datetime.combine(today, dt_time.min)
    return {'label': None, 'range_label': '今天',
            'start': start, 'end': start + timedelta(days=1)}


_GREETING_RE = re.compile(
    r'^(你好|您好|嗨|哈喽|hello|hi|在吗|在不在|早上好|下午好|晚上好|早安|晚安|大家好)'
    r'[!！。.，,~～]?\s*$', re.I)

_HELP_KW = ('帮助', '怎么用', '能做什么', '有什么功能', '功能列表', '使用说明',
            '帮助文档', '帮助一下', '怎么操作')

_EDU_CMD_RE = re.compile(
    r'^(教育|学习教育|去教育|进入教育|教育广场|学习模式|开始学习)(?:吧|一下)?\s*$')

_UPLOAD_CMD_RE = re.compile(r'^(上传|导入|收录)(?:知识|文档)?(?:吧|一下)?\s*$')

_TASK_CREATE_CMD_RE = re.compile(
    r'^(记一下|记一个|记个|记条|添加|新增|创建|建一个|写一个|安排一下|做个待办|'
    r'新建|待办[:：]|任务[:：]|帮我记|请记|记录一个|记得)')

_NOTE_CREATE_CMD_RE = re.compile(
    r'^(随手记[:：]?|记个笔记|记笔记|备忘|备注|记录一下|随手记一下|先记)')

_TASK_DONE_RE = re.compile(
    r'^(完成|搞定|做完了|标记完成)[\s:：]?(?:「|《|")?(?P<what>[^，。！？!?、\n]{1,30})')

_SCHEDULE_KW = ('日程', '任务', '待办', '安排', '会议', '开会', '周报', '计划',
                '做什么', '干什么', '忙什么', '在忙', '有没有事', '有什么')

# 内容性宾语: 句子携带这些词时, 优先按「检索具体内容」处理, 而不是"查日程"。
# 例:「会议材料有哪些」→ 检索; 「今天有什么任务」→ 日程。
_SCHEDULE_CONTENT_KW = ('材料', '资料', '文档', '内容', '纪要', '记录', '流程',
                        '规则', '模板', '报销', '知识', '问题', '要求', '清单',
                        '文件', '格式', '范本', '方案', '预算', '发票')

_SEARCH_KW = ('搜索', '搜一下', '查一下', '查找', '找一下', '帮忙找', '帮我找',
              '有没有', '查查', '检索', '搜搜', '查资料')

_KB_KW = ('解释', '什么意思', '是什么', '含义', '如何', '怎么', '为什么',
          '区别', '流程', '规范', '资料', '知识', '要求', '请教', '说明一下',
          '想知道', '含', '的')


def classify_question(text):
    """规则意图分类 + 时间解析。

    返回 {'intent', 'content', 'time'}; content 为去除首尾标点的原句。
    """
    raw = (text or '').strip()
    content = re.sub(r'[\s，。！？,.;!?、：:~～]+$', '', raw)
    out = {'intent': 'chat', 'content': content, 'time': None}
    if not raw:
        return out
    out['time'] = parse_question_time(raw)

    if _GREETING_RE.match(raw):
        out['intent'] = 'greeting'
        return out
    if any(k in raw for k in _HELP_KW) and len(raw) <= 30:
        out['intent'] = 'help'
        return out
    if _EDU_CMD_RE.match(raw):
        out['intent'] = 'education'
        return out
    if _UPLOAD_CMD_RE.match(raw) or '上传知识' in raw:
        out['intent'] = 'upload'
        return out
    if _TASK_CREATE_CMD_RE.match(raw):
        out['intent'] = 'task_create'
        return out
    if _NOTE_CREATE_CMD_RE.match(raw):
        out['intent'] = 'note_create'
        return out
    if _TASK_DONE_RE.match(raw):
        out['intent'] = 'task_done'
        return out
    if any(k in raw for k in _SCHEDULE_KW) and not any(
            k in raw for k in _SCHEDULE_CONTENT_KW):
        out['intent'] = 'schedule'
        return out
    if any(k in raw for k in _SEARCH_KW):
        out['intent'] = 'search'
        return out
    if any(k in raw for k in _KB_KW):
        out['intent'] = 'knowledge'
        return out
    out['intent'] = 'chat'
    return out


# 前端需打开弹窗/页面的动作类意图
ACTION_INTENTS = frozenset({'task_create', 'note_create', 'education', 'upload'})
# 私聊中发现这些意图时, 即使对方在线也由小知自动作答
QUERY_INTENTS = frozenset({'greeting', 'help', 'schedule', 'search',
                           'knowledge', 'task_done'})