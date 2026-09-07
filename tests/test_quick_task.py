# -*- coding: utf-8 -*-
"""快速创建待办 API 回归: 多场次拆分(预览/创建/回退路径).

注意: 测试直连开发库(sqlite:///tasks.db), 每条创建用例结束后
清理本用例产生的待办(Task.assignments 级联删除), 不留脏数据.
"""
import secrets
from datetime import timedelta

CSRF = {'X-CSRF-Token': 'test-csrf'}  # 与 conftest.make_client 会话内 token 一致

NOTICE = '''【关于举办软件研发中心合肥分中心2026年软件项目全方位精细化管理培训班的通知】 @所有人
各位领导、同事：
      大家好！拟举办软件项目全方位精细化管理培训班，分三期开展专题授课，现将有关事项通知如下：
       培训时间：
       第一期：2026年8月28日14:30-16:30
       第二期：2026年9月3日14:00-18:00
       第三期：2026年9月4日14:30-15:30'''


def _cleanup(title_prefix):
    """按标题前缀删除本用例创建的待办(级联清理分配)."""
    from app import app, db
    from core.models import Task
    with app.app_context():
        for t in Task.query.filter(Task.title.like(title_prefix + '%')).all():
            db.session.delete(t)
        db.session.commit()


def test_preview_returns_sessions(client):
    """预览接口返回场次列表: 标签+ISO-T 时间, 主时间为第一场."""
    r = client.post('/api/quick-task/preview',
                    json={'text': NOTICE}, headers=CSRF)
    d = r.get_json()
    if d.get('not_ready'):
        return  # jionlp 未就绪环境跳过
    assert d['ok'], d
    assert d['category'] == '培训'
    assert d['is_all'] is True
    sess = d['sessions']
    assert len(sess) == 3, sess
    assert [s['label'] for s in sess] == ['第一期', '第二期', '第三期']
    assert sess[0]['start_time'] == '2026-08-28T14:30'
    assert sess[0]['end_time'] == '2026-08-28T16:30'
    assert sess[2]['end_time'] == '2026-09-04T15:30'
    # 单时间字段与第一场一致(供相似度查重)
    assert d['start_time'] == '2026-08-28T14:30'


def test_create_splits_sessions(client):
    """确认发布: sessions≥2 时每场拆一个待办, 标题带（第X期）后缀."""
    title = f'场次拆分回归{secrets.token_hex(5)}'
    try:
        r = client.post('/api/quick-task', json={
            'title': title, 'category': '培训', 'description': NOTICE,
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 0, 'recurrence_count': 0,
            'sessions': [
                {'label': '第一期', 'start_time': '2026-08-28T14:30',
                 'end_time': '2026-08-28T16:30'},
                {'label': '第二期', 'start_time': '2026-09-03T14:00',
                 'end_time': '2026-09-03T18:00'},
            ]}, headers=CSRF).get_json()
        assert r and r.get('ok'), r
        assert r['created'] == [f'{title}（第一期）', f'{title}（第二期）']
        from app import app, db
        from core.models import Task, TaskAssignment
        with app.app_context():
            tasks = Task.query.filter(
                Task.title.like(title + '%')).order_by(Task.id).all()
            assert len(tasks) == 2
            last = db.session.get(Task, r['task_id'])
            assert last.id == tasks[-1].id
            assert last.title == f'{title}（第二期）'
            assert last.start_time.strftime('%Y-%m-%dT%H:%M') == '2026-09-03T14:00'
            assert last.end_time.strftime('%Y-%m-%dT%H:%M') == '2026-09-03T18:00'
            first = tasks[0]
            assert first.start_time.strftime('%Y-%m-%dT%H:%M') == '2026-08-28T14:30'
            # 分配关系: 两场均已指派本人(user id=1)
            for t in tasks:
                uids = {a.user_id for a in t.assignments}
                assert 1 in uids, (t.title, uids)
            assert TaskAssignment.query.filter(
                TaskAssignment.task_id.in_([t.id for t in tasks])).count() == 2
    finally:
        _cleanup(title)


def test_create_bad_session_times_fallback(client):
    """sessions 全非法时走普通单任务路径; 部分非法则仅保留有效场次."""

    def _mk(body_title, sessions):
        return client.post('/api/quick-task', json={
            'title': body_title, 'category': '培训', 'description': 'x',
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 0, 'recurrence_count': 0,
            'sessions': sessions}, headers=CSRF).get_json()

    # 全部非法 → 忽略 sessions, 创建单个普通待办
    t1 = f'场次非法全量{secrets.token_hex(5)}'
    try:
        d1 = _mk(t1, [{'label': '第一期', 'start_time': 'bad', 'end_time': ''},
                      {'label': '第二期', 'start_time': '', 'end_time': 'x'}])
        assert d1 and d1['ok'], d1
        assert d1['created'] == [t1]  # 无后缀=普通单任务
        from app import app
        from core.models import Task
        with app.app_context():
            assert Task.query.filter(Task.title.like(t1 + '%')).count() == 1
    finally:
        _cleanup(t1)

    # 一坏两好 → 坏的被剔除, 按有效两场拆分
    t2 = f'场次非法部分{secrets.token_hex(5)}'
    try:
        d2 = _mk(t2, [{'label': '坏场', 'start_time': 'oops', 'end_time': 'oops'},
                      {'label': '第一期', 'start_time': '2026-08-28T14:30',
                       'end_time': '2026-08-28T16:30'},
                      {'label': '第二期', 'start_time': '2026-09-03T14:00',
                       'end_time': ''}])  # 缺结束 → 后端兜底 +1 小时
        assert d2 and d2['ok'], d2
        assert d2['created'] == [f'{t2}（第一期）', f'{t2}（第二期）']
        from app import app, db
        from core.models import Task
        with app.app_context():
            second = db.session.get(Task, d2['task_id'])
            # 结束缺省兜底: 开始+1小时
            assert second.end_time - second.start_time == timedelta(hours=1)
    finally:
        _cleanup(t2)


def test_create_sessions_missing_assignee_rejected(client):
    """多场次同样要求至少一位负责人(与单任务一致, assign_self 显式关闭)."""
    title = f'场次无负责人{secrets.token_hex(5)}'
    r = client.post('/api/quick-task', json={
        'title': title, 'category': '培训', 'description': 'x',
        'assignee_ids': [], 'group_ids': [], 'is_all': False,
        'assign_self': False,
        'recurrence_interval_days': 0, 'recurrence_count': 0,
        'sessions': [{'label': '第一期', 'start_time': '2026-08-28T14:30',
                      'end_time': '2026-08-28T16:30'},
                     {'label': '第二期', 'start_time': '2026-09-03T14:00',
                      'end_time': '2026-09-03T18:00'}]}, headers=CSRF).get_json()
    assert r and not r['ok'], r
    assert '负责人' in r['error'], r


def test_create_single_session_plain_title(client):
    """单个场次(前端显示为 '-')应按普通单任务创建, 标题不追加期数后缀."""
    title = f'单场次回归{secrets.token_hex(5)}'
    try:
        d = client.post('/api/quick-task', json={
            'title': title, 'category': '培训', 'description': 'x',
            'start_time': '2026-09-03T14:00', 'end_time': '2026-09-03T18:00',
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 0, 'recurrence_count': 0,
            'sessions': [{'label': '-', 'start_time': '2026-09-03T14:00',
                          'end_time': '2026-09-03T18:00'}]}, headers=CSRF).get_json()
        assert d and d['ok'], d
        assert d['created'] == [title]  # 无（第X期）后缀
        from app import app, db
        from core.models import Task
        with app.app_context():
            t = db.session.get(Task, d['task_id'])
            assert t.title == title
            assert t.start_time.strftime('%Y-%m-%dT%H:%M') == '2026-09-03T14:00'
            assert t.end_time.strftime('%Y-%m-%dT%H:%M') == '2026-09-03T18:00'
            assert Task.query.filter(Task.title.like(title + '%')).count() == 1
    finally:
        _cleanup(title)


def test_preview_single_stage_no_sessions(client):
    """单段「第X期: 时间」不是多场次, 预览 sessions 为空(前端回退为 '-')."""
    r = client.post('/api/quick-task/preview', json={
        'text': '第一期：2026年9月3日14:00-18:00'}, headers=CSRF).get_json()
    if r.get('not_ready'):
        return
    assert r['ok'], r
    assert r['sessions'] == []
    assert r['start_time'] == '2026-09-03T14:00'
    assert r['end_time'] == '2026-09-03T18:00'


def test_cascade_delete_multi_session_subsequent(client):
    """删除分阶段待办({标题}（阶段)）支持级联: 只删除开始时间晚于当前场的后续场次."""
    title = f'级联删除回归{secrets.token_hex(5)}'
    sessions = [
        {'label': '第一阶段', 'start_time': '2026-09-07T15:00',
         'end_time': '2026-09-07T16:00'},
        {'label': '第二阶段', 'start_time': '2026-09-18T15:00',
         'end_time': '2026-09-18T16:00'},
        {'label': '第三阶段', 'start_time': '2026-09-30T08:30',
         'end_time': '2026-09-30T17:30'},
    ]
    try:
        d = client.post('/api/quick-task', json={
            'title': title, 'category': '培训', 'description': 'x',
            'start_time': '2026-09-07T15:00', 'end_time': '2026-09-30T17:30',
            'assignee_ids': [1], 'group_ids': [], 'is_all': False,
            'recurrence_interval_days': 0, 'recurrence_count': 0,
            'sessions': sessions}, headers=CSRF).get_json()
        assert d and d['ok'], d
        from app import app, db
        from core.models import Task
        with app.app_context():
            tasks = Task.query.filter(
                Task.title.like(title + '%')).order_by(Task.start_time).all()
            assert len(tasks) == 3
            first, second, third = tasks
        # 删除「第二阶段」并级联 → 删除目标+后续(第三阶段), 保留更早的第一阶段
        r = client.post('/api/tasks/batch_delete', json={
            'task_ids': [second.id], 'cascade': True},
            headers=CSRF).get_json()
        assert r and r['ok'], r
        with app.app_context():
            from sqlalchemy import select
            f1 = db.session.execute(
                select(Task).where(Task.id == first.id)
                .execution_options(include_deleted=True)).scalar_one_or_none()
            f2 = db.session.execute(
                select(Task).where(Task.id == second.id)
                .execution_options(include_deleted=True)).scalar_one_or_none()
            f3 = db.session.execute(
                select(Task).where(Task.id == third.id)
                .execution_options(include_deleted=True)).scalar_one_or_none()
            assert f1.deleted_at is None, '更早的第一阶段不应被级联删除'
            assert f2.deleted_at is not None, '目标(第二阶段)应被删除'
            assert f3.deleted_at is not None, '后续的第三阶段应被级联删除'
    finally:
        _cleanup(title)


def test_astro_visit_logged_out_logs_ip(client):
    """公开星运页访问写入操作记录: 未登录用户记录 IP(空用户名)+访问页面."""
    from app import app, db
    from core.models import OperationLog
    with app.app_context():
        before = db.session.query(db.func.max(OperationLog.id)).scalar() or 0
        c = app.test_client()  # 未登录(不注入会话)
        r = c.get('/astro', follow_redirects=True)
        assert r.status_code == 200
        recs = (OperationLog.query
                .filter(OperationLog.id > before,
                        OperationLog.action == 'astro_visit')
                .order_by(OperationLog.id.desc()).all())
        assert recs, '公开访问 /astro 应写入 astro_visit 记录'
        rec = recs[0]
        assert rec.ip, '未登录访问也需记录 IP'
        assert not rec.username, '未登录用户用户名应为空'
        assert rec.target in ('/astro', '/astro/'), rec.target
