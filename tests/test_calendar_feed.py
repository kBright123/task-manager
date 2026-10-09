# -*- coding: utf-8 -*-
"""日历订阅(/user/todo.ics)回归: 令牌鉴权、内容格式、轮换失效."""
import os
import secrets
import sys
from datetime import timedelta

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
    """创建一条待办并返回标题; 缺省时间为「当前时刻+2小时 起 1 小时」
    (保证提醒时点在未来, 用例不随时钟漂移; 仍落在默认 3 天窗口内)。"""
    rnd = secrets.token_hex(10)
    from core.timeutil import cn_now
    now = cn_now()
    if start is None:
        start = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
    if end is None:
        end = start + timedelta(hours=1)
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


def _cleanup_titles(titles):
    """按唯一标题清理本用例创建的待办(关联分配级联删除), 防止重复检测累积误报."""
    from app import app
    from core.extensions import db
    from core.models import Task
    with app.app_context():
        for t in Task.query.filter(Task.title.in_(titles)).all():
            db.session.delete(t)
        db.session.commit()


def _start_with_future_alarm(now):
    """挑一个「闹钟时点仍在未来」的待办时段, 返回
    (开始, 结束, 期望提醒文案, 期望闹钟时刻), 避免用例随时钟漂移。
    开始在今天 → 「待办即将开始」/开始前30分钟; 否则 → 「待办即将截止」/截止前60分钟。"""
    s = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
    if s.date() == now.date() and s - timedelta(minutes=30) > now:
        return s, s + timedelta(hours=1), '待办即将开始', s - timedelta(
            minutes=30)
    nxt = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0,
                                            microsecond=0)
    return nxt, nxt + timedelta(hours=1), '待办即将截止', nxt  # 截止前60分钟=开始


def test_feed_requires_token():
    c = _anon_client()
    assert c.get('/user/todo.ics').status_code == 401
    assert c.get('/user/todo.ics?token=bad-token').status_code == 401


def test_feed_content_and_rotation(client):
    title = _mk_task(client)
    titles = [title]
    try:
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
        # 默认自带提醒: 开始在今天的待办→开始前30分钟(绝对时间)
        assert 'BEGIN:VALARM' in body
        assert 'TRIGGER;VALUE=DATE-TIME:' in body, '提醒须用绝对时间避免重复触发'
        assert 'TRIGGER:-PT30M' not in body, '不应再用相对触发器'

        # 默认同步「未来3天」: 今天与明天截止的都在源里;
        # 开始不在今天的→截止前60分钟(绝对时间)
        from core.timeutil import cn_now as _cn_now
        tomorrow = _cn_now() + timedelta(days=1)
        tmr_title = _mk_task(
            client,
            start=tomorrow.replace(hour=9, minute=0, second=0, microsecond=0),
            end=tomorrow.replace(hour=10, minute=0, second=0, microsecond=0))
        titles.append(tmr_title)
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
        titles.append(far_title)
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
        # DB 仅存哈希, 原始令牌只通过签发响应返回
        assert _get_token() != d.get('token')
        new = d.get('token')
        assert new and new != old
        assert _anon_client().get(f'/user/todo.ics?token={old}').status_code == 401
        r3 = _anon_client().get(f'/user/todo.ics?token={new}')
        assert r3.status_code == 200 and title in r3.get_data(as_text=True)
    finally:
        _cleanup_titles(titles)


def test_ics_fold_and_allday():
    """行折叠 ≤75 字节且续行带空格; 全天事件输出 VALUE=DATE."""
    from routes.tasks_api import _ics_fold, _build_todo_ics, _ics_utc

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

    # 提醒规则: 开始在今天→开始前30分钟; 开始不在今天→截止前60分钟;
    # 两者均为绝对时间(VALUE=DATE-TIME); 全天事件永不附
    from core.timeutil import cn_now as _cn_now
    now = _cn_now()
    u2 = type('U', (), {'name': '张三', 'username': 'zs'})()
    s, e, exp_desc, exp_at = _start_with_future_alarm(now)
    t_today = type('T', (), {'id': 10, 'title': '定时事项', 'category': '工作',
                             'description': '', 'start_time': s,
                             'end_time': e})()
    bt = _build_todo_ics(u2, [t_today])
    # 小米兼容: 今天开始的提醒也用绝对时间(不用 TRIGGER:-PT30M / RELATED=END:
    # 相对触发器在订阅刷新时会被重复触发, RELATED=END 会被算成异常值)
    assert exp_desc in bt
    assert f'TRIGGER;VALUE=DATE-TIME:{_ics_utc(exp_at)}' in bt
    assert 'TRIGGER:-PT30M' not in bt, '不应使用相对触发器(小米会重复提醒)'
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
    assert f'TRIGGER;VALUE=DATE-TIME:{_ics_utc(t_tmr.end_time - timedelta(minutes=60))}' in bf
    assert 'TRIGGER:-PT30M' not in bf, '非今日开始的提醒应锚定截止时间'
    assert 'VALARM' not in body, '全天事件不附提醒'


def test_alarm_skipped_when_time_passed():
    """提醒时点已过的待办不下发闹钟(否则刷新时小米日历会反复补提醒):
    逾期未完成 → 无闹钟; 进行中(截止未到) → 退回截止前30分钟。"""
    from core.timeutil import cn_now as _cn_now
    from routes.tasks_api import _build_todo_ics, _ics_utc

    now = _cn_now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    u = type('U', (), {'name': '张三', 'username': 'zs'})()

    def _t(tid, title, s, e):
        return type('T', (), {'id': tid, 'title': title, 'category': '工作',
                              'description': '', 'start_time': s,
                              'end_time': e})()

    # 1) 已逾期: 开始/截止都在过去 → 不下发任何闹钟(每次刷新不再补一次过期提醒)
    overdue = _t(20, '已逾期事项', now - timedelta(hours=5),
                 now - timedelta(hours=4))
    bo = _build_todo_ics(u, [overdue])
    assert 'BEGIN:VEVENT' in bo and '[工作] 已逾期事项' in bo
    assert 'BEGIN:VALARM' not in bo, '已逾期待办不应再挂过期闹钟'

    # 2) 进行中: 开始已过(今天)、截止未到 → 退回「截止前30分钟」
    ongoing = _t(21, '进行中事项', day0 + timedelta(minutes=1),
                 now + timedelta(hours=2))
    bg = _build_todo_ics(u, [ongoing])
    assert 'BEGIN:VALARM' in bg
    assert '待办即将截止' in bg
    assert (f'TRIGGER;VALUE=DATE-TIME:'
            f'{_ics_utc(ongoing.end_time - timedelta(minutes=30))}' in bg)
    # 事件本身仍在源里(当天日程可见), 只是不再补已过的开始提醒
    assert 'DTSTART:' in bg

    # 3) 提醒时点未过 → 闹钟仍挂在未来时点上, 且只用绝对时间
    s, e, exp_desc, exp_at = _start_with_future_alarm(now)
    ft = _t(22, '未开始事项', s, e)
    bfu = _build_todo_ics(u, [ft])
    assert exp_desc in bfu
    assert f'TRIGGER;VALUE=DATE-TIME:{_ics_utc(exp_at)}' in bfu
    for name, txt in (('逾期', bo), ('进行中', bg), ('未开始', bfu)):
        assert 'TRIGGER:-PT30M' not in txt, f'{name}: 不应使用相对触发器'
        assert 'RELATED=END' not in txt, f'{name}: 小米不支持 RELATED=END'


def _task_row(title, include_deleted=False):
    from core.extensions import db
    from core.models import Task
    q = Task.query.filter(Task.title == title)
    if include_deleted:
        q = q.execution_options(include_deleted=True)
    return q.first()


def _task_id(title):
    from app import app
    with app.app_context():
        return _task_row(title).id


def _vevent_blocks(body, uid=None):
    """拆出 VEVENT 块; uid 为 None 时返回全部。"""
    blocks = ['BEGIN:VEVENT' + b.split('END:VEVENT')[0]
              for b in body.split('BEGIN:VEVENT')[1:]]
    return [b for b in blocks if uid is None or f'UID:{uid}' in b]


def test_feed_excludes_completed(client):
    """已完成的待办不再同步/提醒: 从正式事件中消失, 并补一条取消通知,
    让手机日历删掉旧条目/撤销提醒(只从源里去掉客户端删不掉)。"""
    title = _mk_task(client)
    try:
        body = client.get('/user/todo.ics').get_data(as_text=True)
        blocks = _vevent_blocks(body, f'UID:todo-{_task_id(title)}@taskmanager')
        assert len(blocks) == 1, blocks
        assert 'STATUS:CONFIRMED' in blocks[0] and 'BEGIN:VALARM' in blocks[0]
        from app import app as flask_app
        from core.extensions import db as _db
        from core.models import TaskAssignment
        with flask_app.app_context():
            t = _task_row(title)
            n = TaskAssignment.query.filter_by(task_id=t.id).update(
                {'status': 'completed'})
            assert n >= 1
            _db.session.commit()
        body = client.get('/user/todo.ics').get_data(as_text=True)
        blocks = _vevent_blocks(body, f'UID:todo-{_task_id(title)}@taskmanager')
        # 只剩取消通知: 同 UID + STATUS:CANCELLED + 更高 SEQUENCE, 不再带闹钟
        assert len(blocks) == 1, blocks
        blk = blocks[0]
        assert 'STATUS:CANCELLED' in blk and 'SEQUENCE:1' in blk
        assert 'BEGIN:VALARM' not in blk
        assert title in blk, '取消事件需保留标题, 便于手机端定位条目'
    finally:
        _cleanup_titles([title])


def test_feed_cancels_deleted(client):
    """进回收站的待办同样下发取消通知, 且不再作为正式事件出现。"""
    title = _mk_task(client)
    tid = _task_id(title)
    uid = f'todo-{tid}@taskmanager'
    try:
        from app import app as flask_app
        from core.extensions import db as _db
        from core.timeutil import cn_now
        with flask_app.app_context():
            t = _task_row(title)
            t.deleted_at = cn_now()
            _db.session.commit()
        body = client.get('/user/todo.ics').get_data(as_text=True)
        blocks = _vevent_blocks(body, f'UID:{uid}')
        assert len(blocks) == 1, blocks
        assert 'STATUS:CANCELLED' in blocks[0]
        assert 'STATUS:CONFIRMED' not in blocks[0]
    finally:
        from app import app as flask_app
        from core.extensions import db as _db
        with flask_app.app_context():
            t = _task_row(title, include_deleted=True)
            if t is not None:
                t.deleted_at = None
                _db.session.commit()
        _cleanup_titles([title])
