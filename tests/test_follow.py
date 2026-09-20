# -*- coding: utf-8 -*-
"""关注(Follow)区块回归: 五角星关注开关 + 关注节点列表 + 时间轴移出/回归;
旧跟踪 API(/api/tasks/tracking)与自动归类下线; 时间轴「两周」分段; 看板迁移到关注。

测试直连开发库(sqlite:///tasks.db), 用例内创建的数据在 finally 中以
用户维度整体清理(标题唯一前缀), 不留脏数据。
"""
import secrets

from datetime import datetime, timedelta

CSRF = {'X-CSRF-Token': 'test-csrf'}  # 与 conftest.make_client 会话内 token 一致


def _mk(prefix='关注回归'):
    return prefix + secrets.token_hex(5)


def _cleanup(titles):
    """按唯一标题清理本用例创建的待办(关联分配级联删除); 关注任务保留原分类,
    因此不再按 category 过滤."""
    from app import app, db
    from core.models import Task
    with app.app_context():
        for t in Task.query.filter(Task.title.in_(titles)).all():
            db.session.delete(t)
        db.session.commit()


def test_legacy_tracking_api_removed(client):
    """旧跟踪 API 已下线: /api/tasks/tracking GET/POST → 404."""
    assert client.get('/api/tasks/tracking').status_code == 404
    assert client.post('/api/tasks/tracking', json={'content': 'x'},
                       headers=CSRF).status_code == 404


def _create_quick_task(client, tag, category='工作', dt=None, followed=False):
    """经 /api/quick-task 直接创建待办(不受自动归类影响)."""
    if dt is None:
        from app import cn_now
        dt = cn_now()
    st = dt.strftime('%Y-%m-%dT%H:%M')
    r = client.post('/api/quick-task', json={
        'title': tag, 'start_time': st, 'end_time': st,
        'category': category, 'description': '', 'assignee_ids': [1],
        'group_ids': [], 'is_all': False, 'followed': followed},
        headers=CSRF).get_json()
    assert r and r['ok'], r
    return r['task_id']


def test_follow_toggle_move_out_and_back(client):
    """关注 → 进入关注列表(is_followed=True)并从时间轴消失;
    取消关注 → 从关注列表消失并回到时间轴."""
    tag = _mk()
    try:
        r = client.get('/api/tasks/follow').get_json()
        assert r['ok']
        assert not [i for i in r['items'] if i['title'] == tag + '事项']

        tid = _create_quick_task(client, tag + '事项', followed=True)

        lst = client.get('/api/tasks/follow').get_json()['items']
        mine = [i for i in lst if i['id'] == tid]
        assert len(mine) == 1, lst
        assert mine[0]['is_followed'] is True
        assert mine[0]['done'] is False
        assert mine[0]['category'] == '工作'

        tl = client.get('/api/tasks/timeline').get_json()['tasks']
        assert all(t['id'] != tid for t in tl)

        r = client.post('/api/task/%d/follow' % tid, headers=CSRF).get_json()
        assert r['ok']
        assert r['is_followed'] is False
        assert not [i for i in
                    client.get('/api/tasks/follow').get_json()['items']
                    if i['id'] == tid]
        tl = client.get('/api/tasks/timeline').get_json()['tasks']
        assert any(t['id'] == tid for t in tl)

        r = client.post('/api/task/%d/follow' % tid, headers=CSRF).get_json()
        assert r['ok'] and r['is_followed'] is True
    finally:
        _cleanup([tag + '事项'])


def test_follow_cross_user_isolated(client):
    """用户1的关注列表只含用户相关(创建/被分配)的任务."""
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    tag = _mk('隔离')
    now = cn_now()
    with app.app_context():
        t = Task(title=tag + '别家的',
                 category='工作', description='',
                 start_time=now, end_time=now + timedelta(hours=1),
                 creator_id=2, is_followed=True)
        db.session.add(t)
        db.session.flush()
        db.session.add(TaskAssignment(task_id=t.id, user_id=2))
        db.session.commit()
        tid = t.id
    try:
        titles = [i['title'] for i in
                  client.get('/api/tasks/follow').get_json()['items']]
        assert tag + '别家的' not in titles
    finally:
        with app.app_context():
            t = db.session.get(Task, tid)
            if t:
                db.session.delete(t)
                db.session.commit()


def test_follow_done_sorted_last(client):
    """完成后的关注任务不再停留在关注节点: 从关注列表消失并回到时间轴
    (按其完成时间归档到原时间点); 取消完成后重新回到关注节点."""
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    tag = _mk('完成')
    now = cn_now()
    with app.app_context():
        older = Task(title=tag + 'a', category='工作', description='',
                     start_time=now - timedelta(hours=2),
                     end_time=now + timedelta(hours=1),
                     creator_id=1, is_followed=True,
                     created_at=now - timedelta(minutes=2))
        newer = Task(title=tag + 'b', category='工作', description='',
                     start_time=now + timedelta(hours=1),
                     end_time=now + timedelta(hours=2),
                     creator_id=1, is_followed=True,
                     created_at=now)
        db.session.add_all([older, newer])
        db.session.flush()
        db.session.add_all([TaskAssignment(task_id=older.id, user_id=1),
                            TaskAssignment(task_id=newer.id, user_id=1)])
        db.session.commit()
        a_id, b_id = older.id, newer.id
    try:
        items = [i['title'] for i in
                 client.get('/api/tasks/follow').get_json()['items']
                 if i['title'].startswith(tag)]
        assert items == [tag + 'b', tag + 'a'], items
        # 完成较新的 b → 从关注节点消失(不再展示已完成)
        lst = client.get('/api/tasks/follow').get_json()['items']
        bb = next(i for i in lst if i['id'] == b_id)
        r = client.post('/user/tasks/%d/toggle' % bb['assignment_id'],
                        headers=CSRF).get_json()
        assert r['ok'], r
        lst = client.get('/api/tasks/follow').get_json()['items']
        assert not [i for i in lst if i['id'] == b_id], lst
        # 回时间轴: 已完成按完成时间归档(show_completed=1 可见)
        tl = client.get('/api/tasks/timeline?show_completed=1').get_json()['tasks']
        done = [t for t in tl if t['id'] == b_id]
        assert done and all(t['display'] == 'completed' for t in done), tl
        # 取消完成 → 回到关注节点
        r = client.post('/user/tasks/%d/toggle' % bb['assignment_id'],
                        headers=CSRF).get_json()
        assert r['ok'], r
        lst = client.get('/api/tasks/follow').get_json()['items']
        assert any(i['id'] == b_id for i in lst), lst
    finally:
        with app.app_context():
            for t in Task.query.filter(Task.title.like(tag + '%')).all():
                db.session.delete(t)
            db.session.commit()


def test_followed_task_kept_in_calendar(client):
    """关注的任务保留原分类, 日历密度统计仍包含它(不再按分类排除)."""
    import calendar as _cal
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    tag = _mk('日历')
    now = cn_now()
    # 从当月日历里挑一天(优先空日, 次选最少项且<5项的日), 保证可被观测
    before = client.get('/api/tasks/calendar?year=%d&month=%d'
                        % (now.year, now.month)).get_json()
    lst = before.get('items') or {}
    empty_day = fewest_key = None
    fewest = 99
    for dd in range(1, _cal.monthrange(now.year, now.month)[1] + 1):
        key = '%04d-%02d-%02d' % (now.year, now.month, dd)
        n = len(lst.get(key, []))
        if n == 0:
            empty_day = key
            break
        if n < fewest:
            fewest, fewest_key = n, key
    target = empty_day or fewest_key
    if fewest >= 5:  # 当月每天都被占满(极端), 无法观测, 跳过
        return
    from datetime import datetime
    t0 = datetime.strptime(target + 'T09:00', '%Y-%m-%dT%H:%M')
    tid = None
    try:
        with app.app_context():
            t = Task(title=tag + '看板项', category='个人', description='',
                     start_time=t0, end_time=t0 + timedelta(hours=1),
                     creator_id=1, is_followed=True)
            db.session.add(t)
            db.session.flush()
            db.session.add(TaskAssignment(task_id=t.id, user_id=1))
            db.session.commit()
            tid = t.id
        # 关注进入列表, 但不进时间轴
        assert any(i['id'] == tid for i in
                   client.get('/api/tasks/follow').get_json()['items'])
        assert all(x['id'] != tid for x in
                   client.get('/api/tasks/timeline').get_json()['tasks'])
        # 日历仍可见
        after = client.get('/api/tasks/calendar?year=%d&month=%d'
                           % (now.year, now.month)).get_json()
        items = (after.get('items') or {}).get(target, [])
        assert any(x['title'] == tag + '看板项' for x in items), items
        assert all(x['category'] == '个人' for x in items
                   if x['title'] == tag + '看板项')
    finally:
        if tid:
            with app.app_context():
                t = db.session.get(Task, tid)
                if t:
                    db.session.delete(t)
                    db.session.commit()


def test_quick_task_followed_flag_respected(client):
    """followed=False 时默认不进入关注列表(不再自动归类)."""
    tag = _mk('非关注')
    try:
        tid = _create_quick_task(client, tag + '普通', followed=False)
        assert not [i for i in
                    client.get('/api/tasks/follow').get_json()['items']
                    if i['id'] == tid]
    finally:
        _cleanup([tag + '普通'])


def test_no_time_task_not_auto_categorized(client):
    """自动归类已下线: 无日期待办以当前时间入库, 保持原分类, 正常出现在时间轴."""
    tag = _mk('无日期')
    try:
        st = ''
        r = client.post('/api/quick-task', json={
            'title': tag + '浮动', 'start_time': st, 'end_time': st,
            'category': '个人', 'description': '', 'assignee_ids': [1],
            'group_ids': [], 'is_all': False, 'followed': False},
            headers=CSRF).get_json()
        assert r and r['ok'], r
        det = client.get('/api/task/%d' % r['task_id']).get_json()
        assert det['task']['category'] == '个人', det
        assert det['task']['title'] == tag + '浮动'
        assert not [i for i in
                    client.get('/api/tasks/follow').get_json()['items']
                    if i['id'] == r['task_id']]
        tl = client.get('/api/tasks/timeline').get_json()['tasks']
        assert any(t['id'] == r['task_id'] for t in tl)
    finally:
        _cleanup([tag + '浮动'])


def test_timeline_two_weeks_split(client):
    """时间轴分段:  过去两周(past_week)/未来两周(future_two_weeks), 更早与更远
    并入 past/later; 不再出现 past_month/future_week/future_month 分组."""
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    now = cn_now()
    by_days = {}
    titles = []
    try:
        with app.app_context():
            for days in (-25, -5, 5, 20):
                ttl = _mk('两周') + ('%dd' % days)
                t = Task(title=ttl, category='工作',
                         start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=1),
                         creator_id=1)
                db.session.add(t)
                db.session.flush()
                db.session.add(TaskAssignment(task_id=t.id, user_id=1))
                titles.append(ttl)
                by_days[days] = ttl
            db.session.commit()
        r = client.get('/api/tasks/timeline?show_history=1').get_json()
        secs = {t['title']: (t['section'], t['section_label'])
                for t in r['tasks']}
        for ti in titles:
            assert ti in secs, ti
        # 只校验本用例任务(开发库中其他历史任务属其他分组, 不参与断言)
        my_sects = [secs[ti][0] for ti in titles]
        assert all(x in ('past_week', 'past', 'future_two_weeks', 'later')
                   for x in my_sects)
        for days, (sec, lbl) in ((-25, ('past', '更早')),
                                 (-5, ('past_week', '过去两周')),
                                 (5, ('future_two_weeks', '未来两周')),
                                 (20, ('later', '更远'))):
            assert secs[by_days[days]] == (sec, lbl), secs[by_days[days]]
        assert 'past_month' not in my_sects
        assert 'future_week' not in my_sects
        assert 'future_month' not in my_sects
    finally:
        with app.app_context():
            for t in Task.query.filter(Task.title.in_(titles)).all():
                db.session.delete(t)
            db.session.commit()


def test_history_toggle_hides_past_and_cross_day(client):
    """默认(「历史待办」未勾选)不展示过去时间节点的待办(过去两周/更早);
    勾选(show_history=1)后才展示; 跨多时间点的未完成任务只从今天起展示,
    不落入过去的日期分组."""
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    tag = _mk('历史')
    now = cn_now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    start_day = today - timedelta(days=5)
    end_day = today + timedelta(days=1)
    tid_past = tid_cross = None
    try:
        with app.app_context():
            pt = Task(title=tag + '昨天', category='工作', description='',
                      start_time=datetime(yesterday.year, yesterday.month,
                                          yesterday.day, 9, 0),
                      end_time=datetime(yesterday.year, yesterday.month,
                                        yesterday.day, 10, 0),
                      creator_id=1)
            db.session.add(pt)
            db.session.flush()
            db.session.add(TaskAssignment(task_id=pt.id, user_id=1))
            tid_past = pt.id
            ct = Task(title=tag + '跨天', category='工作', description='',
                      start_time=datetime(start_day.year, start_day.month,
                                          start_day.day, 11, 16),
                      end_time=datetime(end_day.year, end_day.month,
                                        end_day.day, 18, 0),
                      creator_id=1)
            db.session.add(ct)
            db.session.flush()
            db.session.add(TaskAssignment(task_id=ct.id, user_id=1))
            tid_cross = ct.id
            db.session.commit()
        # 默认: 过去单日(逾期)不展示; 跨天未完成仅今天起展示, 不落过去节点
        ids = {t['id'] for t in
               client.get('/api/tasks/timeline').get_json()['tasks']}
        assert tid_past not in ids, '默认不应展示过去时间节点的待办'
        cross = [t for t in
                 client.get('/api/tasks/timeline').get_json()['tasks']
                 if t['id'] == tid_cross]
        assert cross, '跨天未完成应从今天起展示'
        assert all(t['section'] in ('today', 'tomorrow',
                                    'future_two_weeks', 'later')
                   for t in cross), cross
        assert not any(t['section'] in ('past', 'past_week')
                       for t in cross), cross
        # 勾选「历史待办」: 过去单日与跨天任务的过去节点恢复展示
        h = client.get('/api/tasks/timeline?show_history=1').get_json()
        h_ids = {t['id'] for t in h['tasks']}
        assert tid_past in h_ids, '历史待办勾选后应展示过去时间节点的待办'
        cross_h = [t for t in h['tasks'] if t['id'] == tid_cross]
        assert any(t['section'] in ('past', 'past_week') for t in cross_h), cross_h
        assert any(t['section'] == 'today' for t in cross_h), cross_h
    finally:
        with app.app_context():
            for t in Task.query.filter(Task.title.like(tag + '%')).all():
                db.session.delete(t)
            db.session.commit()


def test_follow_abandoned_not_in_node(client):
    """废弃(discarded)的关注任务同样不再停留关注节点."""
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    tag = _mk('废弃')
    now = cn_now()
    tid = None
    try:
        with app.app_context():
            t = Task(title=tag + '放弃', category='工作', description='',
                     start_time=now - timedelta(hours=2),
                     end_time=now + timedelta(hours=2),
                     creator_id=1, is_followed=True)
            db.session.add(t)
            db.session.flush()
            db.session.add(TaskAssignment(task_id=t.id, user_id=1, status='abandoned'))
            db.session.commit()
            tid = t.id
        lst = client.get('/api/tasks/follow').get_json()['items']
        assert not [i for i in lst if i['id'] == tid], lst
    finally:
        if tid:
            with app.app_context():
                t = db.session.get(Task, tid)
                if t:
                    db.session.delete(t)
                    db.session.commit()


def test_follow_task_not_visible_to_other_user(client):
    """用户1关注的任务在用户2的时间轴/关注节点均不可见(隔离)."""
    from app import app, db, cn_now
    from core.models import Task, TaskAssignment
    tag = _mk('隔离2')
    tid = None
    now = cn_now()
    try:
        with app.app_context():
            t = Task(title=tag + '私有', category='工作', description='',
                     start_time=now, end_time=now + timedelta(hours=1),
                     creator_id=1, is_followed=True)
            db.session.add(t)
            db.session.flush()
            db.session.add(TaskAssignment(task_id=t.id, user_id=1))
            db.session.commit()
            tid = t.id
        lst = client.get('/api/tasks/follow').get_json()['items']
        assert any(i['id'] == tid for i in lst)
    finally:
        if tid:
            with app.app_context():
                t = db.session.get(Task, tid)
                if t:
                    db.session.delete(t)
                    db.session.commit()


def test_migrate_board_to_follow(client):
    """历史看板条目并入待办库(关注+is_followed): 完成/废弃状态映射, 幂等,
    清空 board_item."""
    from app import app, db, _migrate_board_to_tracking
    from core.models import BoardItem, Task, TaskAssignment
    tag = _mk('迁移')
    try:
        with app.app_context():
            it1 = BoardItem(user_id=1, content=tag + 'A')
            it2 = BoardItem(user_id=1, content=tag + 'B', done=True)
            it3 = BoardItem(user_id=1, content=tag + 'C', discarded=True)
            db.session.add_all([it1, it2, it3])
            db.session.commit()
        with app.app_context():
            _migrate_board_to_tracking()
            _migrate_board_to_tracking()  # 幂等: 二次调用不重复导入
        with app.app_context():
            ts = Task.query.filter(
                Task.is_followed == True,
                Task.title.in_([tag + 'A', tag + 'B', tag + 'C'])).all()
            assert {t.title for t in ts} == {tag + 'A', tag + 'B', tag + 'C'}
            assert all(t.category == '关注' for t in ts)
            st = {}
            for t in ts:
                a = TaskAssignment.query.filter_by(
                    task_id=t.id, user_id=1).first()
                assert a is not None
                st[t.title] = a.status
            assert st[tag + 'A'] == 'pending'
            assert st[tag + 'B'] == 'completed'
            assert st[tag + 'C'] == 'abandoned'
            assert not BoardItem.query.filter(
                BoardItem.content.like(tag + '%')).all()
    finally:
        with app.app_context():
            for t in Task.query.filter(Task.title.like(tag + '%')).all():
                db.session.delete(t)
            db.session.commit()