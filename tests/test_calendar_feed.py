# -*- coding: utf-8 -*-
"""日历订阅(/user/todo.ics)回归: 令牌鉴权、内容格式、轮换失效."""
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSRF = {'X-CSRF-Token': 'test-csrf'}  # 与 conftest.make_client 会话内 token 一致


def _anon_client():
    from app import app
    return app.test_client()  # 不注入会话 → 匿名


def _db_user(fn):
    """在应用上下文中对 user(id=1) 执行 fn(u) 并提交。"""
    from app import app
    from core.extensions import db
    from core.models import User
    with app.app_context():
        u = db.session.get(User, 1)
        r = fn(u)
        db.session.commit()
        return r


def _set_token(token):
    def _fn(u):
        u.api_token = token
        u.api_token_created_at = None
    _db_user(_fn)


def _get_token():
    return _db_user(lambda u: u.api_token or '')


def _mk_task(client, start=None, end=None):
    """创建一条待办并返回标题; 缺省时间为今天 09:00-10:00(截止=今天)。"""
    rnd = secrets.token_hex(10)
    from core.timeutil import cn_now
    now = cn_now()
    if start is None:
        start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if end is None:
        end = now.replace(hour=10, minute=0, second=0, microsecond=0)
    title = f'日历订阅{rnd}'
    r = client.post('/api/quick-task', json={
        'title': title,
        # 注意: /api/quick-task 仅接受 %Y-%m-%dT%H:%M(ISO-T)格式,
        # 其他格式会被静默回退为创建时刻+1天
        'start_time': start.strftime('%Y-%m-%dT%H:%M'),
        'end_time': end.strftime('%Y-%m-%dT%H:%M'),
        'category': '会议',
        'description': f'备注{rnd},含逗号', 'assignee_ids': [1], 'group_ids': [],
        'is_all': False}, headers=CSRF).get_json()
    assert r and r.get('ok'), r
    return title


def test_feed_requires_token():
    c = _anon_client()
    assert c.get('/user/todo.ics').status_code == 401
    assert c.get('/user/todo.ics?token=bad-token').status_code == 401


def test_feed_content_and_rotation(client):
    title = _mk_task(client)
    old = _get_token() or ('old-' + secrets.token_urlsafe(16))
    _set_token(old)

    # 会话登录可直接访问; 内容含 VCALENDAR/转义/UID
    r = client.get('/user/todo.ics')
    assert r.status_code == 200, r.status_code
    assert r.mimetype == 'text/calendar'
    body = r.get_data(as_text=True)
    assert 'BEGIN:VCALENDAR' in body and 'END:VCALENDAR' in body
    assert 'METHOD:PUBLISH' in body
    assert title in body
    assert '\\,' in body, '描述中的逗号应被 RFC5545 转义'
    assert 'UID:todo-' in body
    # 空值属性行必须省略(小米日历/ical4j 对个别空属性解析严格)
    for ln in body.split('\r\n'):
        head = ln.split(':', 1)[0]
        assert not (head in ('DESCRIPTION', 'CATEGORIES', 'SUMMARY')
                    and ln.endswith(':')), ln
    # 默认自带提醒: 开始在今天的待办→开始前30分钟
    assert 'BEGIN:VALARM' in body and 'TRIGGER:-PT30M' in body

    # 默认同步「未来3天」: 今天与明天截止的都在源里;
    # 开始不在今天的→截止前60分钟(RELATED=END)
    from datetime import timedelta
    from core.timeutil import cn_now as _cn_now
    tomorrow = _cn_now() + timedelta(days=1)
    tmr_title = _mk_task(
        client,
        start=tomorrow.replace(hour=9, minute=0, second=0, microsecond=0),
        end=tomorrow.replace(hour=10, minute=0, second=0, microsecond=0))
    bd = client.get('/user/todo.ics').get_data(as_text=True)
    assert title in bd and tmr_title in bd
    assert '未来3日待办' in bd
    # 非今天开始的→截止前60分钟(绝对时间格式,避免小米RELATED=END兼容问题)
    assert 'TRIGGER;VALUE=DATE-TIME:' in bd

    # 第4天(窗口外)默认不出现, ?days=N 可扩大时间窗
    far = _cn_now() + timedelta(days=3)
    far_title = _mk_task(
        client,
        start=far.replace(hour=9, minute=0, second=0, microsecond=0),
        end=far.replace(hour=10, minute=0, second=0, microsecond=0))
    bd2 = client.get('/user/todo.ics').get_data(as_text=True)
    assert far_title not in bd2
    b7 = client.get('/user/todo.ics?days=7').get_data(as_text=True)
    assert far_title in b7 and '未来7日待办' in b7

    # token 鉴权访问 / 错误令牌 401
    r2 = _anon_client().get(f'/user/todo.ics?token={old}')
    assert r2.status_code == 200 and title in r2.get_data(as_text=True)
    assert _anon_client().get(f'/user/todo.ics?token={old}x').status_code == 401

    # 轮换: 旧链接立即失效, 新链接可用
    rr = client.post('/profile/api-token/rotate', headers=CSRF)
    assert rr.status_code == 200, rr.status_code
    d = rr.get_json()
    assert d.get('ok') and d.get('feed_path', '').startswith('/user/todo.ics')
    new = _get_token()
    assert new and new != old
    assert _anon_client().get(f'/user/todo.ics?token={old}').status_code == 401
    r3 = _anon_client().get(f'/user/todo.ics?token={new}')
    assert r3.status_code == 200 and title in r3.get_data(as_text=True)


def test_ics_fold_and_allday():
    """行折叠 ≤75 字节且续行带空格; 全天事件输出 VALUE=DATE."""
    from routes.tasks_api import _ics_fold, _build_todo_ics

    long_line = 'SUMMARY:' + '很长的标题' * 60
    for ln in _ics_fold(long_line):
        assert len(ln.encode('utf-8')) <= 75, ln[:80]
    folded = '\r\n'.join(_ics_fold(long_line))
    assert '很长的标题' * 60 not in folded

    from datetime import datetime
    t = type('T', (), {'id': 9, 'title': '全天事项', 'category': '个人',
                       'description': '',
                       'start_time': datetime(2026, 8, 26, 0, 0, 0),
                       'end_time': datetime(2026, 8, 26, 23, 59, 0)})()
    body = _build_todo_ics(type('U', (), {'name': '张三', 'username': 'zs'})(), [t])
    assert 'DTSTART;VALUE=DATE:20260826' in body
    assert 'DTEND;VALUE=DATE:20260827' in body
    assert '[个人] 全天事项' in body
    assert 'DESCRIPTION:' not in body, '空描述应省略属性行'
    assert 'CATEGORIES:个人' in body

    # 提醒规则: 开始在今天→开始前30分钟(相对DTSTART);
    # 开始不在今天→截止前60分钟(RELATED=END); 全天事件永不附
    from datetime import timedelta
    from core.timeutil import cn_now as _cn_now
    now = _cn_now()
    u2 = type('U', (), {'name': '张三', 'username': 'zs'})()
    t_today = type('T', (), {'id': 10, 'title': '定时事项', 'category': '工作',
                             'description': '',
                             'start_time': now.replace(hour=9, minute=0,
                                                       second=0,
                                                       microsecond=0),
                             'end_time': now.replace(hour=10, minute=0,
                                                     second=0,
                                                     microsecond=0)})()
    bt = _build_todo_ics(u2, [t_today])
    assert 'TRIGGER:-PT30M' in bt and '待办即将开始' in bt
    tmr = now + timedelta(days=1)
    t_tmr = type('T', (), {'id': 11, 'title': '未来事项', 'category': '工作',
                           'description': '',
                           'start_time': tmr.replace(hour=9, minute=0,
                                                     second=0,
                                                     microsecond=0),
                           'end_time': tmr.replace(hour=12, minute=0,
                                                   second=0,
                                                   microsecond=0)})()
    bf = _build_todo_ics(u2, [t_tmr], feed_label='未来3日待办')
    # 小米兼容: 截止前提醒改绝对时间(RELATED=END → VALUE=DATE-TIME)
    # 预期值: DTEND(12:00) - 60分钟 = 11:00 UTC
    assert 'TRIGGER;VALUE=DATE-TIME:' in bf and '待办即将截止' in bf
    assert 'TRIGGER:-PT30M' not in bf, '非今日开始的提醒应锚定截止时间'
    assert 'VALARM' not in body, '全天事件不附提醒'


def test_feed_excludes_completed(client):
    """已完成的待办不再同步/提醒: 完成后从订阅源消失。"""
    title = _mk_task(client)
    body = client.get('/user/todo.ics').get_data(as_text=True)
    assert title in body
    from app import app as flask_app
    from core.extensions import db as _db
    from core.models import Task, TaskAssignment
    with flask_app.app_context():
        t = Task.query.filter(Task.title == title).first()
        assert t is not None
        n = TaskAssignment.query.filter_by(task_id=t.id).update(
            {'status': 'completed'})
        assert n >= 1
        _db.session.commit()
    body = client.get('/user/todo.ics').get_data(as_text=True)
    assert title not in body
