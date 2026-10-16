# -*- coding: utf-8 -*-
"""今天改动回归: 周期待办「只建一期/被误判跨天」修复 + 周期系列「只算一个」与
时间轴/日历「只展示当前一期」。

设计要点(对应今日代码改动):
1) 周期展开: 前端补传 recurrence_interval_days/count 后, /api/quick-task 按等间隔
   展开 N 期(标题 `基础 (第N期/共M期)`); 创建侧在未给出 end_time 时兜底 start+1h。
2) 周期单期不跨天: 预览/创建对周期待办把「未给时长或解析落次日」的结束时间钳制为
   同日 +1h, 避免整期被当作跨天任务。
3) 系列只算一个: 首页「待办」统计卡片把周期系列按一个计(series_dedupe_count)。
4) 时间轴/日历只展示当前一期: 系列内一旦存在更早未完成的一期, 其后各期隐藏
    (series_hidden_ids); 完成当前一期后下一期自动浮现。
 5) 跨天任务时间轴只展示最近一条: 今天/未来分区不再按每个分组重复出现, 只锚定
    在 max(开始日, 今天)(不超过截止日)输出一条, 其余日期自然隐藏。

注意: 测试直连开发库, 每条用例结束后清理本用例产生的待办(Task.assignments 级联
删除), 不留脏数据.
"""
import re
import secrets
from datetime import datetime, timedelta

CSRF = {'X-CSRF-Token': 'test-csrf'}  # 与 conftest 会话内 token 一致


def _cleanup(title_prefix):
    """按标题前缀删除本用例创建的待办(级联清理分配)."""
    from app import app, db
    from core.models import Task
    with app.app_context():
        for t in Task.query.filter(Task.title.like(title_prefix + '%')).all():
            db.session.delete(t)
        db.session.commit()


def _at_today(hour, minute):
    from app import cn_now
    now = cn_now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _mk_series(client, prefix, n, start, interval_days=7, **kw):
    """创建 n 期等间隔周期系列(单期同日 +1h), 返回响应 JSON."""
    body = {
        'title': prefix, 'category': '回归', 'description': 'x',
        'start_time': start.strftime('%Y-%m-%dT%H:%M'),
        'end_time': (start + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
        'assignee_ids': [1], 'group_ids': [], 'is_all': False,
        'recurrence_interval_days': interval_days,
        'recurrence_count': n,
    }
    body.update(kw)
    return client.post('/api/quick-task', json=body, headers=CSRF).get_json()


def _complete_first(client, title):
    """把系列第1期置为已完成(近似用户点「完成」), 供「下一期浮现」断言."""
    from app import app, db, cn_now
    from core.models import Task
    with app.app_context():
        first = Task.query.filter(
            Task.title == f'{title} (第1期/共3期)').one()
        for a in first.assignments:
            a.status = 'completed'
            a.completed_at = a.completed_at or cn_now()
        db.session.commit()


# ---------------------------------------------------------------- 1) 周期展开

def test_create_recurring_expands_multiple_instances(client):
    """等间隔周期: recurrence_count 期全部展开, 标题带期数后缀, 各期相邻偏移,
    单期同日(+1h)不跨天."""
    title = f'周期展开回归{secrets.token_hex(5)}'
    try:
        d = _mk_series(client, title, 3,
                       datetime(2028, 1, 3, 9, 0), interval_days=7)
        assert d and d['ok'], d
        assert d['created'] == [
            f'{title} (第1期/共3期)',
            f'{title} (第2期/共3期)',
            f'{title} (第3期/共3期)',
        ], d['created']
        from app import app, db
        from core.models import Task
        with app.app_context():
            tasks = Task.query.filter(
                Task.title.like(title + '%')).order_by(Task.start_time).all()
            assert len(tasks) == 3
            for i, t in enumerate(tasks):
                expect = datetime(2028, 1, 3, 9, 0) + timedelta(days=7 * i)
                assert t.start_time == expect, (i, t.start_time)
                assert t.end_time == expect + timedelta(hours=1) \
                    , (i, t.end_time)
                assert t.start_time.date() == t.end_time.date(), '单期不应跨天'
    finally:
        _cleanup(title)


def test_create_recurring_without_end_time_defaults_same_day(client):
    """周期待办未给出截止时间时, 每期兜底 start+1h(同一天), 不被当作跨天任务."""
    title = f'周期无截止回归{secrets.token_hex(5)}'
    try:
        d = client.post('/api/quick-task', json={
            'title': title, 'category': '回归', 'description': 'x',
            'start_time': '2028-05-01T08:30', 'end_time': '',
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 3, 'recurrence_count': 2,
        }, headers=CSRF).get_json()
        assert d and d['ok'], d
        assert len(d['created']) == 2, d
        from app import app, db
        from core.models import Task
        with app.app_context():
            tasks = Task.query.filter(
                Task.title.like(title + '%')).order_by(Task.start_time).all()
            assert len(tasks) == 2
            for i, t in enumerate(tasks):
                expect = datetime(2028, 5, 1, 8, 30) + timedelta(days=3 * i)
                assert t.start_time == expect
                assert t.end_time == expect + timedelta(hours=1), '缺截止应兜底+1h'
    finally:
        _cleanup(title)


# ------------------------------------------------------ 2) 周期单期不跨天

def test_preview_recurring_single_period_same_day(client):
    """预览周期待办: 单期结束时间钳制为与开始同一天(解析落次日不再整期跨天)."""
    from app import cn_now
    for text in ('每周一早上9点做报表', '每天下午3点检查设备',
                 '每周二下午2点到3点开例会'):
        d = client.post('/api/quick-task/preview',
                        json={'text': text}, headers=CSRF).get_json()
        if d.get('not_ready'):
            return  # 解析未就绪环境跳过
        assert d['ok'], d
        assert d['recurrence_interval_days'] > 0, d
        st = datetime.fromisoformat(d['start_time'])
        en = datetime.fromisoformat(d['end_time'])
        assert st.date() == en.date(), d['start_time'] + '~' + d['end_time']
        assert timedelta(hours=0) < en - st < timedelta(days=1) \
            , (text, st, en)
        assert en < cn_now() + timedelta(days=2), '不应落到下一天之后'


# -------------------------------------------------- 3) 系列隐藏/只算一个(纯函数)

def test_series_hidden_ids_first_unfinished_hides_later():
    """系列精简规则: 从系列内最早未完成一期起, 其后各期全部隐藏."""
    from types import SimpleNamespace as NS
    from routes.tasks_common import series_hidden_ids

    def mk(num, start, status):
        return NS(id=num, creator_id=1,
                  title=f'规则系列 (第{num}期/共3期)',
                  start_time=start, end_time=start, _status=status)

    D = datetime
    # 第1期未完成 → 隐藏第2、3期(即使第3期已完成)
    mem = [mk(1, D(2028, 3, 1), 'pending'),
           mk(2, D(2028, 3, 8), 'pending'),
           mk(3, D(2028, 3, 15), 'completed')]
    hid = series_hidden_ids(mem, {m.id: m._status for m in mem})
    assert hid == {2, 3}, hid
    # 第1期已完成、第2期未完成 → 只隐藏第3期
    mem = [mk(1, D(2028, 3, 1), 'completed'),
           mk(2, D(2028, 3, 8), 'pending'),
           mk(3, D(2028, 3, 15), 'pending')]
    hid = series_hidden_ids(mem, {m.id: m._status for m in mem})
    assert hid == {3}, hid
    # 全部完成 → 不隐藏任何一期
    mem = [mk(1, D(2028, 3, 1), 'completed'),
           mk(2, D(2028, 3, 8), 'approved'),
           mk(3, D(2028, 3, 15), 'completed')]
    assert series_hidden_ids(mem, {m.id: m._status for m in mem}) == set()
    # 第1期废弃、第2期末完成 → 不隐藏(废弃不算未完成)
    mem = [mk(1, D(2028, 3, 1), 'abandoned'),
           mk(2, D(2028, 3, 8), 'pending'),
           mk(3, D(2028, 3, 15), 'pending')]
    hid = series_hidden_ids(mem, {m.id: m._status for m in mem})
    assert hid == {3}, hid
    # 非系列任务不参与任何隐藏
    lone = [NS(id=90, creator_id=1, title='普通待办',
               start_time=D(2028, 3, 1), end_time=D(2028, 3, 1))]
    assert series_hidden_ids(lone, {90: 'pending'}) == set()
    # 两个不同系列互不影响: 各自独立隐藏「其后各期」
    s2 = [
        NS(id=21, creator_id=1, title='规则系列2 (第1期/共2期)',
           start_time=D(2028, 4, 1), end_time=D(2028, 4, 1), _status='pending'),
        NS(id=22, creator_id=1, title='规则系列2 (第2期/共2期)',
           start_time=D(2028, 4, 8), end_time=D(2028, 4, 8), _status='pending'),
    ]
    mem2 = [mk(1, D(2028, 4, 1), 'pending'),
            mk(2, D(2028, 4, 8), 'pending'),
            mk(3, D(2028, 4, 15), 'pending')] + s2
    hid2 = series_hidden_ids(mem2, {m.id: getattr(m, '_status', 'pending')
                                    for m in mem2})
    assert hid2 == {2, 3, 22}, hid2
    # 同名系列但创建者不同: 互不影响
    other = NS(id=31, creator_id=2, title='规则系列 (第1期/共3期)',
               start_time=D(2028, 4, 1), end_time=D(2028, 4, 1), _status='pending')
    mem3 = [mk(1, D(2028, 4, 1), 'pending')] + [other]
    assert series_hidden_ids(mem3, {m.id: m._status for m in mem3}) == set()


def test_series_dedupe_count_counts_series_once():
    """待办统计「只算一个」: 周期系列按一个计, 普通待办逐条计."""
    from types import SimpleNamespace as NS
    from routes.tasks_common import series_dedupe_count

    def tk(tid, ttitle):
        return NS(id=tid, creator_id=1, title=ttitle, start_time=None)

    items = [
        NS(task=tk(1, '周报 (第1期/共3期)')),
        NS(task=tk(2, '周报 (第2期/共3期)')),
        NS(task=tk(3, '周报 (第3期/共3期)')),
        NS(task=tk(4, '普通待办A')),
        NS(task=tk(5, '普通待办B')),
        NS(task=tk(6, '巡检 (第1期/共2期)')),
    ]
    assert series_dedupe_count(items) == 4, series_dedupe_count(items)


# ------------------------------------------- 4) 时间轴/日历/统计卡片(端到端)

def test_timeline_shows_only_current_recurring_instance(client):
    """时间轴: 系列存在更早未完成一期时, 后续各期不显示; 完成当前一期后下一期浮现."""
    title = f'时间轴精简回归{secrets.token_hex(5)}'
    try:
        d = _mk_series(client, title, 3, _at_today(10, 0), interval_days=7)
        assert d and d['ok'], d

        dl = client.get('/api/tasks/timeline').get_json()
        titles = [t['title'] for t in dl['tasks']
                  if t['title'].startswith(title)]
        assert titles == [f'{title} (第1期/共3期)'], titles

        _complete_first(client, title)
        dl2 = client.get('/api/tasks/timeline').get_json()
        titles2 = [t['title'] for t in dl2['tasks']
                   if t['title'].startswith(title)]
        assert titles2 == [f'{title} (第2期/共3期)'], titles2

        # 与系列无关的普通待办不受影响
        plain = [t['title'] for t in dl2['tasks']
                 if t['title'].startswith(title)]
        assert plain == titles2
    finally:
        _cleanup(title)


def test_calendar_shows_current_recurring_instance_once(client):
    """日历方块: 系列只计当前一期(未完成期只落在它自己那格, 后续期不落点)."""
    from app import cn_now
    title = f'日历方块回归{secrets.token_hex(5)}'
    y, m = cn_now().year, cn_now().month
    d1 = datetime(y, m, 1, 10, 0)  # 当月 1/8/15 号为系列三期
    try:
        d = _mk_series(client, title, 3, d1, interval_days=7)
        assert d and d['ok'], d

        cal = client.get(
            f'/api/tasks/calendar?year={y}&month={m}&show_completed=1'
        ).get_json()

        def has(prefix, day):
            items = cal['items'].get(f'{y:04d}-{m:02d}-{day:02d}', [])
            return any(prefix in (it.get('title') or '')
                       for it in items)

        assert has(title, 1), '当前一期应落点在 1 日'
        assert not has(title, 8), '后续第2期不应在 8 日落点'
        assert not has(title, 15), '后续第3期不应在 15 日落点'

        _complete_first(client, title)
        cal2 = client.get(
            f'/api/tasks/calendar?year={y}&month={m}&show_completed=1'
        ).get_json()

        def has2(prefix, day):
            items = cal2['items'].get(f'{y:04d}-{m:02d}-{day:02d}', [])
            return any(prefix in (it.get('title') or '')
                       for it in items)

        assert has2(title, 8), '完成第1期后第2期应在 8 日落点'
        assert not has2(title, 15), '第3期仍不应在 15 日落点'
    finally:
        _cleanup(title)


def test_dashboard_pending_card_counts_series_once(client):
    """首页「待办」统计方块: 周期系列按一个计(普通待办逐条 +1)."""
    def stat_num():
        html = client.get('/user/dashboard').data.decode('utf-8')
        m = re.search(
            r'<div class="stat-num" style="font-size:1\.5rem;" id="dashTodoCount">(\d+)</div>',
            html)
        assert m, '未找到「待办」统计数字'
        return int(m.group(1))

    before = stat_num()
    s_title = f'统计方块回归{secrets.token_hex(5)}'
    one_title = f'统计单任务{secrets.token_hex(5)}'
    try:
        d = _mk_series(client, s_title, 3, _at_today(11, 0), interval_days=7)
        assert d and d['ok'], d
        assert stat_num() == before + 1, '周期系列(3期未完成)应只算 1 个待办'

        d2 = client.post('/api/quick-task', json={
            'title': one_title, 'category': '回归', 'description': 'x',
            'start_time': _at_today(12, 0).strftime('%Y-%m-%dT%H:%M'),
            'end_time': (_at_today(12, 0) + timedelta(hours=1))
            .strftime('%Y-%m-%dT%H:%M'),
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 0, 'recurrence_count': 0,
        }, headers=CSRF).get_json()
        assert d2 and d2['ok'], d2
        assert stat_num() == before + 2, '普通待办逐条 +1'
    finally:
        _cleanup(s_title)
        _cleanup(one_title)


# ------------------------------------------- 5) 跨天任务只展示最近一条

def test_timeline_cross_day_shows_single_nearest_entry(client):
    """跨天待在今天/未来分区只显示最近一条(今天到未来锚定在最近一天; 已结束收敛为一条)."""
    from app import cn_now

    def _mk_cross(title, start, end):
        return client.post('/api/quick-task', json={
            'title': title, 'category': '回归', 'description': 'x',
            'start_time': start.strftime('%Y-%m-%dT%H:%M'),
            'end_time': end.strftime('%Y-%m-%dT%H:%M'),
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 0, 'recurrence_count': 0,
        }, headers=CSRF).get_json()

    def _entries(title):
        dl = client.get('/api/tasks/timeline').get_json()
        return [t for t in dl['tasks'] if t['title'].startswith(title)]

    today = cn_now().date()
    at10 = datetime(today.year, today.month, today.day, 10, 0)

    # 场景1: 跨天任务覆盖今天(昨天~+6天) → 只出一条, 落在「今天」分区
    c1 = f'跨天盖今{secrets.token_hex(5)}'
    try:
        assert _mk_cross(c1, at10 - timedelta(days=1),
                         at10 + timedelta(days=6))['ok']
        es = _entries(c1)
        assert len(es) == 1, '覆盖今天的跨天任务只应显示一条'
        assert es[0]['section'] == 'today', es[0]
        assert es[0]['display'] in ('today', 'overdue'), es[0]
    finally:
        _cleanup(c1)

    # 场景2: 跨天任务完全在未来的(今天+3天~+9天) → 只出一条, 落在未来两周分区
    c2 = f'跨天未来{secrets.token_hex(5)}'
    try:
        assert _mk_cross(c2, at10 + timedelta(days=3),
                         at10 + timedelta(days=9))['ok']
        es = _entries(c2)
        assert len(es) == 1, '未来跨天任务只应显示一条'
        assert es[0]['section'] == 'future_two_weeks', es[0]
        assert es[0]['display'] == 'future', es[0]
    finally:
        _cleanup(c2)

    # 场景3: 已结束的跨天任务(昨天截止, 未完成) → 默认落在「逾期未完成」分区一条
    c3 = f'跨天已完{secrets.token_hex(5)}'
    try:
        assert _mk_cross(c3, at10 - timedelta(days=5), at10 - timedelta(days=1))['ok']
        es = _entries(c3)
        assert len(es) == 1, '已结束的跨天未完成应只显示一条'
        assert es[0]['section'] == 'overdue', es[0]
        assert es[0]['display'] == 'overdue', es[0]
        dl = client.get('/api/tasks/timeline?show_history=1').get_json()
        es_h = [t for t in dl['tasks'] if t['title'].startswith(c3)]
        assert len(es_h) == 1, '勾选历史记录后仍收敛为一条'
        assert es_h[0]['section'] == 'overdue', es_h
    finally:
        _cleanup(c3)