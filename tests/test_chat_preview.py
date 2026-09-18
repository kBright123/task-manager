# -*- coding: utf-8 -*-
"""会话列表预览净化: 去除代答横幅/列表圆点/状态括号, 折叠后截断,
避免长结构化回答把联系人列表撑乱。"""
from routes.chat import _preview_text


def test_strips_daida_banner_and_meta():
    raw = ('在 房紫嫣 的资料中找到 4 条相关内容：\n'
           '· [待办] 消保无小事：【关于开展 315 专项自查】汇总表'
           '（状态 pending；截止 2026-09-18 10:26；优先级 中） [资料 1]')
    out = _preview_text(raw)
    assert not out.startswith('在 房紫嫣 的资料中')
    assert '（状态' not in out
    assert '[资料' not in out
    assert '·' not in out
    assert '消保无小事' in out
    # 单行、无换行
    assert '\n' not in out


def test_plain_text_kept():
    assert _preview_text('对方周会材料是什么') == '对方周会材料是什么'


def test_empty_after_strip_returns_empty():
    assert _preview_text('在 xx 的资料中找到 1 条相关内容：') == ''
    assert _preview_text('') == ''


def test_truncates_with_ellipsis():
    long_text = ('非常长的一段随手记内容 ' * 10).strip()
    out = _preview_text(long_text)
    assert out.endswith('…')
    assert len(out) <= 29