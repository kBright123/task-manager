# This file is part of 知行合一 · 任务与知识管理系统 (TaskManager).
# Copyright (C) 2026 TaskManager contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# -*- coding: utf-8 -*-
"""tasks 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import app, login_required

# chinese_calendar 返回英文名, 映射为中文用于日历展示
_HOLIDAY_CN = {
    "New Year's Day": '元旦',
    'Spring Festival': '春节',
    'Tomb-sweeping Day': '清明节',
    'Labour Day': '劳动节',
    'Dragon Boat Festival': '端午节',
    'Mid-autumn Festival': '中秋节',
    'National Day': '国庆节',
    'Anti-Fascist 70th Day': '抗战胜利纪念日',
}


def _similar_blocked_by_assignee(similar, assignee_ids, group_ids, is_all):
    """判断新任务与相似未完成待办的分配对象是否有重叠。

    新任务分配对象与任一相似待办的分配对象存在重叠时返回 True(拦截发布);
    无任何重叠时返回 False(允许正常发布)。
    """
    new_ids = set(assignee_ids) if assignee_ids else set()
    if is_all:
        new_ids.update(u.id for u in User.query.all())
    if group_ids:
        groups = Group.query.filter(Group.id.in_(group_ids)).all()
        for g in groups:
            for m in g.members:
                if not m.is_disabled and m.status == 'approved':
                    new_ids.add(m.id)
    if not new_ids:
        return True
    for d in similar:
        task = d.get('task') if isinstance(d, dict) else None
        if not task:
            continue
        old_ids = {a.user_id for a in task.assignments}
        if old_ids & new_ids:
            return True
    return False

@app.route('/user/tasks/batch_delete', methods=['POST'])
@login_required
def user_batch_delete_tasks():
    task_ids = [int(x) for x in request.form.getlist('task_ids') if x.isdigit()]
    if not task_ids:
        flash('未选择待办', 'danger')
        return redirect(url_for('user_tasks'))
    tasks = Task.query.filter(Task.id.in_(task_ids)).all()
    if not tasks:
        flash('待办不存在', 'danger')
        return redirect(url_for('user_tasks'))
    mine = [t for t in tasks if t.creator_id == current_user.id]
    if not mine:
        flash('只能删除自己创建的待办', 'danger')
        return redirect(url_for('user_tasks'))
    ids = [t.id for t in mine]
    Notification.query.filter(
        Notification.task_id.in_(ids)).update(
        {Notification.task_id: None})
    db.session.execute(
        task_group.delete().where(task_group.c.task_id.in_(ids)))
    TaskAssignment.query.filter(
        TaskAssignment.task_id.in_(ids)).delete(
        synchronize_session=False)
    Task.query.filter(Task.id.in_(ids)).delete(
        synchronize_session=False)
    db.session.commit()
    flash(f'已删除 {len(ids)} 个待办', 'success')
    return redirect(url_for('user_tasks'))


@app.route('/user/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def user_delete_task(task_id):
    """删除待办:仅创建者或管理员可删。"""
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    if task.creator_id != current_user.id and current_user.role != 'admin':
        flash('只能删除自己创建的待办', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    title = task.title
    Notification.query.filter_by(task_id=task_id).update(
        {Notification.task_id: None})
    db.session.execute(
        task_group.delete().where(task_group.c.task_id == task_id))
    TaskAssignment.query.filter_by(task_id=task_id).delete(
        synchronize_session=False)
    db.session.delete(task)
    db.session.commit()
    flash(f'待办 "{title}" 已删除', 'success')
    return redirect(request.referrer or url_for('user_dashboard'))
@app.route('/tasks/<int:task_id>/abandon', methods=['POST'])
@login_required
def abandon_task_all(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    if task.creator_id != current_user.id and current_user.role != 'admin':
        flash('只有待办创建者或管理员可以废弃整个待办', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    now = datetime.now()
    for a in task.assignments:
        if a.status not in ('abandoned',):
            a.status = 'abandoned'
            a.abandoned_at = now
    db.session.commit()
    flash(f'待办 "{task.title}" 已废弃（共 {task.assignments.count()} 人）', 'info')
    return redirect(request.referrer or url_for('user_dashboard'))
@app.route('/user/dashboard')
@login_required
def user_dashboard():
    now = datetime.now()

    # 状态计数:一次 GROUP BY 聚合,替代 4 条独立 COUNT
    _status_rows = db.session.query(
        TaskAssignment.status, func.count(TaskAssignment.id)
    ).filter(TaskAssignment.user_id == current_user.id).group_by(
        TaskAssignment.status).all()
    _status_counts = dict(_status_rows)
    total = sum(_status_counts.values())
    completed = _status_counts.get('completed', 0)
    pending = _status_counts.get('pending', 0)
    rejected = _status_counts.get('rejected', 0)
    rate = round(completed / total * 100, 1) if total > 0 else 0

    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 全部未完成分配一次取出,upcoming/overdue/today/week/all_pending 在
    # Python 内按截止时间划分,替代 5 条重叠的 join+过滤 查询。
    # joinedload 让 a.task 免于逐条懒加载(模板渲染同样受益)。
    from sqlalchemy.orm import joinedload
    pending_assigns = TaskAssignment.query.options(
        joinedload(TaskAssignment.task)).join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status == 'pending'
    ).order_by(Task.end_time).all()

    upcoming = [a for a in pending_assigns
                if now <= a.task.end_time <= now + timedelta(days=7)]
    overdue = [a for a in pending_assigns if a.task.end_time < now]
    today_tasks = [a for a in pending_assigns
                   if today_start <= a.task.end_time <= today_end]
    week_tasks = [a for a in pending_assigns
                  if week_start <= a.task.end_time <= week_end]
    all_pending = pending_assigns

    recent = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.completed_at.isnot(None)
    ).order_by(TaskAssignment.completed_at.desc()).limit(5).all()
    # 同比趋势:较前日新增的待办/随手记/知识库条目(前一日与再前一日计数差)
    day_before_start = yesterday_start - timedelta(days=1)
    new_tasks_yesterday = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id, TaskAssignment.status == 'pending',
        Task.created_at >= yesterday_start, Task.created_at < today_start).count()
    new_tasks_prev = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id, TaskAssignment.status == 'pending',
        Task.created_at >= day_before_start, Task.created_at < yesterday_start).count()
    tasks_delta = new_tasks_yesterday - new_tasks_prev
    new_notes_yesterday = 0
    new_notes_prev = 0
    new_docs_yesterday = 0
    new_docs_prev = 0
    try:
        from notes import Note
        if Note is not None:
            new_notes_yesterday = Note.query.filter(
                Note.user_id == current_user.id,
                Note.created_at >= yesterday_start, Note.created_at < today_start).count()
            new_notes_prev = Note.query.filter(
                Note.user_id == current_user.id,
                Note.created_at >= day_before_start, Note.created_at < yesterday_start).count()
    except Exception:
        pass
    try:
        from knowledge import KbDocument
        if KbDocument is not None:
            new_docs_yesterday = KbDocument.query.filter(
                KbDocument.created_at >= yesterday_start,
                KbDocument.created_at < today_start).count()
            new_docs_prev = KbDocument.query.filter(
                KbDocument.created_at >= day_before_start,
                KbDocument.created_at < yesterday_start).count()
    except Exception:
        pass
    notes_delta = new_notes_yesterday - new_notes_prev
    docs_delta = new_docs_yesterday - new_docs_prev
    # 知识点统计(仅统计当前用户可见的知识点)
    points_count = 0
    new_points_yesterday = 0
    new_points_prev = 0
    try:
        from knowledge import KbPoint as _KbPoint
        from knowledge import _visible_point_ids as _kb_visible_point_ids
        _vis_points = _kb_visible_point_ids()
        if _vis_points is None:
            points_count = _KbPoint.query.count()
            new_points_yesterday = _KbPoint.query.filter(
                _KbPoint.created_at >= yesterday_start,
                _KbPoint.created_at < today_start).count()
            new_points_prev = _KbPoint.query.filter(
                _KbPoint.created_at >= day_before_start,
                _KbPoint.created_at < yesterday_start).count()
        elif _vis_points:
            points_count = _KbPoint.query.filter(
                _KbPoint.id.in_(_vis_points)).count()
            new_points_yesterday = _KbPoint.query.filter(
                _KbPoint.created_at >= yesterday_start,
                _KbPoint.created_at < today_start,
                _KbPoint.id.in_(_vis_points)).count()
            new_points_prev = _KbPoint.query.filter(
                _KbPoint.created_at >= day_before_start,
                _KbPoint.created_at < yesterday_start,
                _KbPoint.id.in_(_vis_points)).count()
    except Exception:
        pass
    points_delta = new_points_yesterday - new_points_prev

    try:
        from knowledge import KbCollection as _KbCollection
        from knowledge import _visible_collection_ids as _kb_visible_cols
        _vis = _kb_visible_cols()
        if _vis is None:
            _collections = _KbCollection.query.order_by(
                _KbCollection.name).all()
        else:
            _collections = _KbCollection.query.filter(
                _KbCollection.id.in_(_vis)
            ).order_by(_KbCollection.name).all()
    except Exception:
        _collections = []

    return render_template('dashboard.html', total=total,
                           completed=completed, pending=pending,
                           rejected=rejected, rate=rate,
                           upcoming=upcoming, overdue=overdue,
                           recent=recent,
                           today_tasks=today_tasks, week_tasks=week_tasks,
                           all_pending=all_pending,
                           now=now,
                           is_admin=current_user.role == 'admin',
                           users=get_same_group_users(current_user),
                           user_groups=Group.query.all() if current_user.role == 'admin' else current_user.groups.all(),
                           note_count=_count_notes(),
                           kb_count=_count_kb(),
                           new_tasks_yesterday=new_tasks_yesterday,
                           new_notes_yesterday=new_notes_yesterday,
                           new_docs_yesterday=new_docs_yesterday,
                           tasks_delta=tasks_delta,
                           notes_delta=notes_delta,
                           docs_delta=docs_delta,
                           points_count=points_count,
                           points_delta=points_delta,
                           collections=_collections)


@app.route('/api/group-members')
@login_required
def api_group_members():
    members = get_same_group_users(current_user)
    result = [{'id': u.id, 'name': u.name or u.username, 'username': u.username}
              for u in members]
    return jsonify(result)


@app.route('/api/search-tasks')
@login_required
def api_search_tasks():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    filters = [TaskAssignment.user_id == current_user.id]
    if q:
        pattern = f'%{q}%'
        filters.append(db.or_(
            Task.title.like(pattern),
            Task.description.like(pattern),
            TaskAssignment.note.like(pattern)
        ))
    if category:
        filters.append(Task.category == category)
    assignments = TaskAssignment.query.join(Task).filter(
        *filters
    ).order_by(Task.end_time.desc()).limit(20).all()
    results = []
    for a in assignments:
        results.append({
            'task_id': a.task.id,
            'title': a.task.title,
            'description': a.task.description or '',
            'category': a.task.category,
            'status': a.status,
            'progress': a.progress,
            'start_time': a.task.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': a.task.end_time.strftime('%Y-%m-%d %H:%M'),
            'detail_url': url_for('user_task_detail', task_id=a.task.id),
        })
    return jsonify(results)
@app.route('/api/quick-tasks', methods=['GET'])
@login_required
def api_quick_tasks_feed():
    """待办列表：返回当前用户创建的任务（最新在前）。
    默认只返回未完成待办，?completed=1 时包含已完成；?category=分类 时按分类筛选。"""
    show_completed = request.args.get('completed') == '1'
    category = (request.args.get('category') or '').strip()
    query = Task.query.filter_by(creator_id=current_user.id)
    if category:
        query = query.filter(Task.category == category)
    if not show_completed:
        query = query.filter(Task.assignments.any(
            TaskAssignment.status.in_(['pending', 'rejected'])))
    tasks = query.order_by(Task.created_at.desc()).limit(100).all()
    ids = [t.id for t in tasks]
    counts = {}
    if ids:
        rows = TaskAssignment.query.filter(
            TaskAssignment.task_id.in_(ids)).all()
        for a in rows:
            c = counts.setdefault(a.task_id, [0, 0])
            c[0] += 1
            if a.status in ('completed', 'approved'):
                c[1] += 1
    out = []
    for t in tasks:
        total, done = counts.get(t.id, [0, 0])
        out.append({
            'id': t.id,
            'title': t.title,
            'description': t.description or '',
            'category': t.category,
            'start_time': t.start_time.strftime('%Y-%m-%d %H:%M') if t.start_time else '',
            'end_time': t.end_time.strftime('%Y-%m-%d %H:%M') if t.end_time else '',
            'total': total,
            'done': done,
            'completed': total > 0 and done >= total,
        })
    # 分类计数（按是否含已完成过滤，不受选中分类影响）
    cat_query = Task.query.filter_by(creator_id=current_user.id)
    if not show_completed:
        cat_query = cat_query.filter(Task.assignments.any(
            TaskAssignment.status.in_(['pending', 'rejected'])))
    categories = {}
    for t in cat_query.all():
        categories[t.category] = categories.get(t.category, 0) + 1
    return jsonify({'ok': True, 'tasks': out, 'show_completed': show_completed,
                    'category': category, 'categories': categories})


def _task_display_and_section(t, status, now, ref=None):
    """计算任务的显示状态(display)与时间轴分段(section/section_label)。
    分段按 ref 时间归类(已完成=完成时间,未完成=截止时间),与日历口径一致。"""
    today_date = now.date()
    ref_date = (ref or t.end_time or now).date()
    start_date = t.start_time.date() if t.start_time else today_date
    # 显示状态
    if status == 'abandoned':
        display = 'abandoned'
    elif status in ('completed', 'approved'):
        display = 'completed'
    elif t.end_time < now:
        display = 'overdue'
    elif start_date <= today_date:
        display = 'today'
    else:
        display = 'future'
    # 分段
    diff_days = (ref_date - today_date).days
    if display == 'abandoned':
        section, section_label = 'abandoned', '已废弃'
    elif diff_days < -7:
        section, section_label = 'past', '更早'
    elif diff_days < 0:
        section, section_label = 'past_week', '过去一周'
    elif diff_days == 0:
        section, section_label = 'today', '今天 · ' + today_date.strftime('%m月%d日')
    elif diff_days == 1:
        section, section_label = 'tomorrow', '明天'
    elif diff_days <= 6 - today_date.weekday():
        section, section_label = 'this_week', '本周'
    elif diff_days <= 13 - today_date.weekday():
        section, section_label = 'next_week', '下周'
    else:
        section, section_label = 'later', '更晚'
    return display, section, section_label


@app.route('/api/tasks/timeline', methods=['GET'])
@login_required
def api_tasks_timeline():
    """时间轴:返回当前用户相关任务的时间分布数据。
    ?start=YYYY-MM-DD&end=YYYY-MM-DD 可选,不传则返回全部待办;
    ?show_completed=1 包含已完成;?category=分类 按分类筛选。"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        start = datetime.strptime(request.args.get('start', ''), '%Y-%m-%d') \
            if request.args.get('start') else None
    except Exception:
        start = None
    try:
        end = datetime.strptime(request.args.get('end', ''), '%Y-%m-%d') \
            if request.args.get('end') else None
    except Exception:
        end = None
    if end:
        end = end.replace(hour=23, minute=59, second=59)
    category = (request.args.get('category') or '').strip()
    show_completed = request.args.get('show_completed', '') == '1'
    # 查询当前用户的任务(创建的 + 被分配的)
    task_ids = set()
    # 创建的任务
    created = Task.query.filter(
        Task.creator_id == current_user.id)
    if start:
        created = created.filter(Task.end_time >= start)
    if end:
        created = created.filter(Task.end_time <= end)
    if category:
        created = created.filter(Task.category == category)
    for t in created.all():
        task_ids.add(t.id)
    # 被分配的任务(show_completed 时纳入已完成,与日历口径一致)
    a_statuses = ['pending', 'rejected']
    if show_completed:
        a_statuses += ['completed', 'approved']
    assigned_ids = [r[0] for r in db.session.query(
        TaskAssignment.task_id).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status.in_(a_statuses)).all()]
    # 已完成按完成时间归档: 完成时间在范围内(截止不在)的任务也要纳入
    done_in_range = []
    if start and end:
        done_in_range = [r[0] for r in db.session.query(
            TaskAssignment.task_id).filter(
            TaskAssignment.user_id == current_user.id,
            TaskAssignment.status.in_(('completed', 'approved')),
            TaskAssignment.completed_at.isnot(None),
            TaskAssignment.completed_at >= start,
            TaskAssignment.completed_at <= end).all()]
    extra_ids = set(assigned_ids) | set(done_in_range)
    if extra_ids:
        # 不在此处过滤 end_time: 已完成任务由完成时间归档,越界项由下方 ref 校验剔除
        extra = Task.query.filter(
            Task.id.in_(extra_ids))
        if category:
            extra = extra.filter(Task.category == category)
        for t in extra.all():
            task_ids.add(t.id)
    if not task_ids:
        return jsonify({'ok': True, 'tasks': [], 'today': today.strftime('%Y-%m-%d')})
    tasks = Task.query.filter(Task.id.in_(task_ids)).order_by(Task.end_time).all()
    # 获取当前用户在这些任务上的分配状态
    assigns = {}
    for a in TaskAssignment.query.filter(
            TaskAssignment.task_id.in_(task_ids),
            TaskAssignment.user_id == current_user.id).all():
        assigns[a.task_id] = a
    out = []
    for t in tasks:
        a = assigns.get(t.id)
        status = a.status if a else 'pending'
        now = datetime.now()
        # 归类基准: 已完成按完成时间,未完成按截止时间(与日历口径一致)
        done = status in ('completed', 'approved')
        ref = (a.completed_at or t.end_time) if (done and a) else t.end_time
        if start and end and ref and not (start <= ref <= end):
            continue
        display, section, section_label = _task_display_and_section(
            t, status, now, ref=ref)
        # 默认不展示已完成
        if display == 'completed' and not show_completed:
            continue
        out.append({
            'id': t.id,
            'title': t.title,
            'description': (t.description or '')[:200],
            'full_description': t.description or '',
            'category': t.category,
            'start_time': t.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': t.end_time.strftime('%Y-%m-%d %H:%M'),
            'progress': a.progress if a else 0,
            'status': status,
            'display': display,
            'section': section,
            'section_label': section_label,
            'note': (a.note or '') if a else '',
            'attachment': (a.attachment or '') if a else '',
            'assignment_id': a.id if a else None,
            'creator_id': t.creator_id,
            'is_owner': t.creator_id == current_user.id or current_user.role == 'admin',
            'assignee_ids': [aa.user_id for aa in t.assignments],
            'group_ids': [g.id for g in t.groups],
        })
    # 分类计数 — 从全部任务计算(不受category和show_completed过滤影响)
    all_categories = {}
    for t in tasks:
        a2 = assigns.get(t.id)
        s2 = a2.status if a2 else 'pending'
        if s2 == 'abandoned':
            continue
        if s2 in ('completed', 'approved') and not show_completed:
            continue
        all_categories[t.category] = all_categories.get(t.category, 0) + 1
    return jsonify({'ok': True, 'tasks': out, 'today': today.strftime('%Y-%m-%d'),
                    'categories': all_categories})


@app.route('/api/tasks/calendar')
@login_required
def api_tasks_calendar():
    """返回指定月份每天的任务密度 + 班/休标签"""
    try:
        from chinese_calendar import is_workday, get_holiday_detail
    except ImportError:
        is_workday = get_holiday_detail = None
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(seconds=1)
    # 仅当前用户相关任务:创建的 + 被分配的(含已完成)
    # 统计口径:已完成按完成时间(completed_at),未完成按截止时间(end_time)
    assign_rows = TaskAssignment.query.filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status.in_(['pending', 'rejected', 'completed', 'approved'])
    ).all()
    status_by_task = {a.task_id: a.status for a in assign_rows}
    done_at_by_task = {a.task_id: a.completed_at for a in assign_rows
                       if a.completed_at}
    from sqlalchemy import or_, and_
    done_in_range = [tid for tid, at in done_at_by_task.items()
                     if start <= at <= end]
    tasks = Task.query.filter(
        or_(Task.creator_id == current_user.id,
            Task.id.in_(status_by_task.keys())),
        or_(and_(Task.end_time >= start, Task.end_time <= end),
            Task.id.in_(done_in_range))
    ).order_by(Task.end_time).all()
    density = {}
    items = {}
    for t in tasks:
        st = status_by_task.get(t.id)
        done = st in ('completed', 'approved')
        ref = done_at_by_task[t.id] if done and done_at_by_task.get(t.id) \
            else t.end_time
        if not (start <= ref <= end):
            continue
        ds = ref.strftime('%Y-%m-%d')
        density[ds] = density.get(ds, 0) + 1
        lst = items.setdefault(ds, [])
        if len(lst) < 5:
            lst.append({'title': t.title,
                        'time': ref.strftime('%H:%M'),
                        'category': t.category,
                        'done': done})
    tags = {}
    holidays = {}
    # 探测 chinese_calendar 是否覆盖该年份(旧版包对新年度抛 NotImplementedError)
    year_ok = True
    if get_holiday_detail is not None:
        try:
            get_holiday_detail(date(year, month, 1))
        except NotImplementedError:
            year_ok = False
        except Exception:
            pass
    import calendar as cal_mod
    num_days = (end - start).days + 1
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        dow = d.weekday()
        ds = d.strftime('%Y-%m-%d')
        is_weekend = dow >= 5
        if is_workday is None or not year_ok:
            # 未安装/版本不支持时降级:周末视为休,无补班与节日标记
            if is_weekend:
                tags[ds] = '休'
            continue
        try:
            is_hol, hname = get_holiday_detail(d)
        except Exception:
            continue
        if is_hol and hname:
            # 法定假日统一标休(含长假中的周六日,如国庆/中秋假期)
            tags[ds] = '休'
            holidays[ds] = _HOLIDAY_CN.get(hname, hname)
        elif is_weekend and is_workday(d):
            tags[ds] = '班'
    return jsonify({'ok': True, 'density': density, 'tags': tags,
                    'holidays': holidays, 'items': items,
                    'year': year, 'month': month})


@app.route('/api/quick-task/preview', methods=['POST'])
@login_required
def api_quick_task_preview():
    """首页快速创建待办第一步：自然语言解析，返回待确认预览(与待办发布一致)。"""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if len(text) < 2:
        return jsonify({'ok': False, 'error': '待办描述至少 2 个字'}), 400
    sensitive = check_sensitive_words(text) if text else []
    if sensitive:
        return jsonify({'ok': False, 'error': '输入内容包含敏感词，请修改后重试',
                        'sensitive_words': sensitive}), 400
    try:
        parsed = parse_task_from_text(text)
    except Exception as e:
        logger.error('Quick task preview failed: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': '解析待办失败，请检查输入格式'}), 400
    title = (parsed.get('title') or '').strip()
    if not title or title == '未命名待办' or len(title) < 2:
        return jsonify({'ok': False, 'error': '无法提取待办标题（至少 2 个字）'}), 400

    # 解析出可编辑的初始值
    start = parsed.get('start_time') or datetime.now()
    end = parsed.get('end_time') or (start + timedelta(days=1))
    if end <= start:
        end = start + timedelta(hours=1)

    assignee_ids = []
    assignee_names = []
    if current_user.role == 'admin' and parsed.get('is_all', False):
        is_all = True
    else:
        is_all = False
        for name in parsed.get('assignees') or []:
            u = User.query.filter(
                db.or_(User.name == name, User.username == name)).first()
            if u and not u.is_disabled and u.status == 'approved' and u.id != current_user.id:
                assignee_ids.append(u.id)
                assignee_names.append(u.name or u.username)
        assignee_ids.append(current_user.id)
        assignee_names.append(current_user.name or current_user.username)

    duplicate_tasks = []
    try:
        similar = find_similar_tasks(
            title, text, parsed.get('category') or '',
            start, end, unfinished_only=True)
        if similar and not _similar_blocked_by_assignee(
                similar, set(assignee_ids), [], is_all):
            similar = []
        for d in similar:
            creator = getattr(d.get('task'), 'creator', None)
            duplicate_tasks.append({
                'title': getattr(d.get('task'), 'title', ''),
                'similarity': d.get('similarity', 0),
                'creator': (creator.name or creator.username) if creator else '',
            })
    except Exception:
        pass

    user_groups = []
    try:
        if current_user.role == 'admin':
            _groups = Group.query.all()
        else:
            _groups = current_user.groups.all()
        user_groups = [{'id': g.id, 'name': g.name,
                        'member_count': len(g.members)} for g in _groups]
    except Exception:
        pass

    return jsonify({
        'ok': True,
        'title': title,
        'description': text,
        'category': parsed.get('category') or '工作',
        'start_time': start.strftime('%Y-%m-%dT%H:%M'),
        'end_time': end.strftime('%Y-%m-%dT%H:%M'),
        'is_all': is_all,
        'assignee_ids': assignee_ids,
        'assignee_names': assignee_names,
        'recurrence_text': parsed.get('recurrence_text', ''),
        'recurrence': parsed.get('recurrence') or '',
        'recurrence_interval_days': parsed.get('recurrence_interval_days') or 0,
        'recurrence_count': parsed.get('recurrence_count') or 0,
        'duplicate_tasks': duplicate_tasks,
        'user_groups': user_groups,
        'text': text,
    })


@app.route('/api/quick-task', methods=['POST'])
@login_required
def api_quick_task():
    """首页快速创建待办第二步：确认后创建(与待办发布一致)。"""
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title or len(title) < 2:
        return jsonify({'ok': False, 'error': '待办标题至少 2 个字'}), 400
    dt_fmt = '%Y-%m-%dT%H:%M'
    try:
        start = datetime.strptime(data.get('start_time', ''), dt_fmt)
    except Exception:
        start = datetime.now()
    try:
        end = datetime.strptime(data.get('end_time', ''), dt_fmt)
    except Exception:
        end = start + timedelta(days=1)
    if end <= start:
        end = start + timedelta(hours=1)
    category = (data.get('category') or '').strip() or '工作'
    description = (data.get('description') or '').strip() or title

    is_all = current_user.role == 'admin' and bool(data.get('is_all'))
    assign_self = bool(data.get('assign_self', True))
    recurrence_interval_days = int(data.get('recurrence_interval_days') or 0)
    recurrence_count = int(data.get('recurrence_count') or 0)
    total = recurrence_count if recurrence_interval_days and recurrence_count > 0 else 1

    assignee_ids = set()
    if not is_all:
        for uid in data.get('assignee_ids') or []:
            try:
                assignee_ids.add(int(uid))
            except (TypeError, ValueError):
                continue
        if assign_self:
            assignee_ids.add(current_user.id)

    group_ids = []
    for gid in data.get('group_ids') or []:
        try:
            group_ids.append(int(gid))
        except (TypeError, ValueError):
            continue
    if not is_all and not assignee_ids and not group_ids:
        return jsonify({'ok': False, 'error': '请至少选择一位负责人(可勾选自己)'}), 400

    similar = find_similar_tasks(title, description, category,
                                 start, end, unfinished_only=True)
    if similar and _similar_blocked_by_assignee(
            similar, assignee_ids, group_ids, is_all):
        return jsonify({'ok': False, 'duplicate': True,
                        'error': '与现有未完成待办相似度过高（相似度 ≥ 70%），不允许发布，请修改待办标题或描述'}), 400

    created_titles = []
    try:
        db.session.rollback()  # 结束只读事务, 使 begin() 成为最外层事务
        with db.session.begin():
            for i in range(total):
                offset = timedelta(days=recurrence_interval_days * i)
                t_start = start + offset
                t_end = end + offset
                t_title = f'{title} (第{i+1}期/共{total}期)' if total > 1 else title
                task = Task(title=t_title, description=description,
                            category=category, start_time=t_start,
                            end_time=t_end, creator_id=current_user.id,
                            is_all=is_all)
                db.session.add(task)
                db.session.flush()
                if is_all:
                    target_users = User.query.all()
                    for u in target_users:
                        db.session.add(TaskAssignment(task_id=task.id, user_id=u.id))
                        create_notification(u.id, 'task_assigned',
                                            f'你收到一个新待办：「{t_title}」', task.id)
                else:
                    uid_set = set(assignee_ids)
                    if group_ids:
                        selected_groups = Group.query.filter(Group.id.in_(group_ids)).all()
                        for g in selected_groups:
                            for m in g.members:
                                if not m.is_disabled and m.status == 'approved':
                                    uid_set.add(m.id)
                            task.groups.append(g)
                    for uid in uid_set:
                        db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                        create_notification(uid, 'task_assigned',
                                            f'你收到一个新待办：「{t_title}」', task.id)
                created_titles.append(t_title)
    except Exception as e:
        db.session.rollback()
        logger.error('Quick task creation failed: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': '创建失败'}), 500
    return jsonify({'ok': True, 'task_id': task.id,
                    'url': url_for('user_task_detail', task_id=task.id),
                    'created': created_titles})


@app.route('/api/quick-note', methods=['POST'])
@login_required
def api_quick_note():
    """首页随手记(走笔记自动整理管道)。"""
    from notes import (Note, parse_tags_json, apply_rules, simhash,
                       persist_md, find_duplicates, extract_title)
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': '内容不能为空'}), 400
    title = (data.get('title') or '').strip() or extract_title(content)
    tid = data.get('thread_id')
    from notes import Thread
    thread = None
    if tid:
        thread = Thread.query.filter_by(id=int(tid)).first()
    note = Note(user_id=current_user.id,
                thread_id=thread.id if thread else None,
                title=title, content=content, tags='[]', version=1)
    changes = apply_rules(note)
    note.simhash = str(simhash(content))
    db.session.add(note)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': '保存失败'}), 500
    persist_md(note)
    dup = find_duplicates(note)
    return jsonify({'ok': True, 'note_id': note.id, 'warnings': dup})
def _build_task_stats(task_ids, user_id):
    """Precompute per-task assignment counts and the current user's actionable
    assignment in bulk, avoiding per-task dynamic-relationship queries in
    tasks.html."""
    task_ids = list({t for t in (task_ids or []) if t is not None})
    if not task_ids:
        return {}, {}
    rows = db.session.query(
        TaskAssignment.task_id, TaskAssignment.status,
        func.count(TaskAssignment.id)
    ).filter(TaskAssignment.task_id.in_(task_ids)).group_by(
        TaskAssignment.task_id, TaskAssignment.status).all()
    stats = {}
    for tid, status, n in rows:
        entry = stats.setdefault(tid, {'total': 0, 'completed': 0,
                                       'abandoned': 0, 'pending': 0})
        entry['total'] += n
        if status in ('completed', 'approved'):
            entry['completed'] += n
        elif status == 'abandoned':
            entry['abandoned'] += n
        elif status == 'pending':
            entry['pending'] += n
    my_assignments = {}
    for a in TaskAssignment.query.filter(
            TaskAssignment.task_id.in_(task_ids),
            TaskAssignment.user_id == user_id,
            TaskAssignment.status.in_(['pending', 'completed', 'approved'])
    ).all():
        if a.task_id not in my_assignments or a.status == 'pending':
            my_assignments[a.task_id] = a
    return stats, my_assignments


def _assignment_counts_by_user():
    """{display name -> number of assigned tasks}, for the admin overview bar."""
    rows = db.session.query(
        func.coalesce(func.nullif(User.name, ''), User.username).label('uname'),
        func.count(TaskAssignment.id)
    ).select_from(TaskAssignment).join(User, TaskAssignment.user_id == User.id) \
     .group_by(User.id).order_by(func.count(TaskAssignment.id).desc()).all()
    return {uname: n for uname, n in rows}


def _frequent_assignees(user_id, limit=8):
    """常分配人员: 当前用户创建的任务中, 被分配次数最多的用户 id 集合(按次数降序)."""
    rows = db.session.query(
        TaskAssignment.user_id,
        func.count(TaskAssignment.id).label('cnt')
    ).join(Task, TaskAssignment.task_id == Task.id) \
     .filter(Task.creator_id == user_id) \
     .group_by(TaskAssignment.user_id) \
     .order_by(func.count(TaskAssignment.id).desc()) \
     .limit(limit).all()
    return {r.user_id: r.cnt for r in rows}


@app.route('/user/tasks', methods=['GET', 'POST'])
@login_required
def user_tasks():
    users = get_same_group_users(current_user)
    if not any(u.id == current_user.id for u in users):
        users.append(current_user)
    duplicate_tasks = []
    rejected_tasks = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status == 'rejected'
    ).order_by(Task.end_time).all()
    my_tasks = Task.query.filter_by(creator_id=current_user.id).order_by(Task.created_at.desc()).all()
    if current_user.role == 'admin':
        user_groups = Group.query.all()
    else:
        user_groups = current_user.groups.all()

    def _stats_context():
        ids = [t.id for t in my_tasks] + [t.id for t in (other_assigned or [])]
        stats, mine = _build_task_stats(ids, current_user.id)
        ctx = {'task_stats': stats, 'my_assignments': mine}
        if current_user.role == 'admin':
            ctx['assignment_counts'] = _assignment_counts_by_user()
        order = ['工作', '个人', '会议', '培训', '考试']
        seen = set()
        groups = {c: [] for c in order}
        all_t = list(my_tasks) + list(other_assigned or [])
        for t in all_t:
            if t.id in seen:
                continue
            seen.add(t.id)
            groups.setdefault(t.category, []).append(t)
        ctx['task_categories'] = [{'category': c, 'tasks': groups.get(c, [])}
                                  for c in order + [k for k in groups if k not in order]]
        return ctx

    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        action = request.form.get('action', '')
        sensitive = check_sensitive_words(text) if text else []
        if sensitive:
            my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter_by(user_id=current_user.id).all()}
            other_assigned = Task.query.filter(Task.id.in_(my_assigned_ids), Task.creator_id != current_user.id).order_by(Task.created_at.desc()).all() if my_assigned_ids else []
            template_data = {
                'rejected_tasks': rejected_tasks,
                'preview': None, 'users': users,
                'my_tasks': my_tasks,
                'other_assigned': other_assigned,
                'TaskAssignment': TaskAssignment,
                'now': datetime.now(),
                'is_admin': current_user.role == 'admin',
                'sensitive_words': sensitive,
                'sensitive_text': highlight_sensitive_words(text),
                'original_text': text,
                'user_groups': user_groups,
                'duplicate_tasks': [],
                'frequent_assignees': _frequent_assignees(current_user.id),
            }
            template_data.update(_stats_context())
            return render_template('tasks.html', **template_data)
        if action == 'save':
            try:
                title = request.form.get('title', '').strip()
                category = request.form.get('category', '').strip() or '工作'
                start_str = request.form.get('start_time', '').strip()
                end_str = request.form.get('end_time', '').strip()
                description = request.form.get('description', '').strip()
                is_all = request.form.get('is_all') == '1'
                if current_user.role != 'admin':
                    is_all = False
                assignee_ids = request.form.getlist('assignee_ids')
                group_ids = request.form.getlist('group_ids')
                if not title:
                    flash('待办标题不能为空', 'danger')
                    return redirect(url_for('user_tasks'))
                start_time = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                end_time = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
                recurrence = request.form.get('recurrence', '')
                recurrence_count = int(request.form.get('recurrence_count', '0') or '0')
                recurrence_interval_days = int(request.form.get('recurrence_interval_days', '0') or '0')
                duration = end_time - start_time
                total = recurrence_count if recurrence and recurrence_count > 0 else 1
                similar = find_similar_tasks(title, description, category,
                                             start_time, end_time,
                                             unfinished_only=True)
                sim_uid = {int(x) for x in assignee_ids if str(x).isdigit()} if assignee_ids else set()
                sim_gid = [int(gid) for gid in group_ids if str(gid).isdigit()]
                if similar and _similar_blocked_by_assignee(
                        similar, sim_uid, sim_gid, is_all):
                    preview_data = {
                        'title': title, 'category': category,
                        'start_time': start_time, 'end_time': end_time,
                        'description': description, 'is_all': is_all,
                        'assignees': [], 'raw_text': description,
                        'assignee_ids': assignee_ids,
                        'group_ids': group_ids,
                        'recurrence': recurrence,
                        'recurrence_count': recurrence_count,
                        'recurrence_interval_days': recurrence_interval_days,
                    }
                    my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter_by(user_id=current_user.id).all()}
                    other_assigned = Task.query.filter(Task.id.in_(my_assigned_ids), Task.creator_id != current_user.id).order_by(Task.created_at.desc()).all() if my_assigned_ids else []
                    template_data = {
                        'rejected_tasks': rejected_tasks,
                        'preview': preview_data, 'users': users,
                        'my_tasks': my_tasks,
                        'other_assigned': other_assigned,
                        'TaskAssignment': TaskAssignment,
                        'now': datetime.now(),
                        'is_admin': current_user.role == 'admin',
                        'user_groups': user_groups,
                        'duplicate_tasks': similar,
                        'duplicate_blocked': True,
                        'frequent_assignees': _frequent_assignees(current_user.id),
                    }
                    template_data.update(_stats_context())
                    return render_template('tasks.html', **template_data)
                created_titles = []
                # 先解析负责人集合并校验(纯读操作),避免事务内提前 return 留下半成品
                if not is_all:
                    uid_set = set(int(x) for x in assignee_ids) if assignee_ids else set()
                    selected_groups = []
                    if group_ids:
                        selected_groups = Group.query.filter(
                            Group.id.in_([int(gid) for gid in group_ids])).all()
                        for g in selected_groups:
                            for m in g.members:
                                if not m.is_disabled and m.status == 'approved':
                                    uid_set.add(m.id)
                    if str(current_user.id) in assignee_ids:
                        uid_set.add(current_user.id)
                    if not uid_set:
                        flash('请至少选择一位负责人(可勾选自己)', 'danger')
                        return redirect(url_for('user_tasks'))
                db.session.rollback()  # 结束路由开头的只读事务, 使 begin() 成为最外层事务
                with db.session.begin():
                    for i in range(total):
                        offset = timedelta(days=recurrence_interval_days * i)
                        t_start = start_time + offset
                        t_end = end_time + offset
                        t_title = f'{title} (第{i+1}期/共{total}期)' if total > 1 else title
                        task = Task(title=t_title, description=description,
                                    category=category, start_time=t_start,
                                    end_time=t_end, creator_id=current_user.id,
                                    is_all=is_all)
                        db.session.add(task)
                        db.session.flush()
                        if is_all:
                            target_users = User.query.all()
                            for u in target_users:
                                db.session.add(TaskAssignment(task_id=task.id, user_id=u.id))
                                create_notification(u.id, 'task_assigned',
                                                    f'你收到一个新待办：「{t_title}」', task.id)
                        else:
                            for g in selected_groups:
                                task.groups.append(g)
                            for uid in uid_set:
                                db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                                create_notification(uid, 'task_assigned',
                                                    f'你收到一个新待办：「{t_title}」', task.id)
                        created_titles.append(t_title)
                if total > 1:
                    flash(f'周期待办创建成功！共创建 {total} 个待办', 'success')
                else:
                    flash(f'待办 "{title}" 创建成功！', 'success')
            except Exception as e:
                db.session.rollback()
                logger.error('User task creation failed: %s', e, exc_info=True)
                flash('创建待办失败', 'danger')
            return redirect(url_for('user_tasks'))
        try:
            parsed = parse_task_from_text(text)
            if not parsed.get('title') or parsed['title'] == '未命名待办' or len(parsed.get('title', '')) < 2:
                flash('无法从描述中提取待办标题，请确保包含明确的待办名称（至少2个字）', 'danger')
                return redirect(url_for('user_tasks'))
            parsed['raw_text'] = text
            is_admin_user = current_user.role == 'admin'
            if not is_admin_user:
                parsed['is_all'] = False
                parsed['assignees'] = [a for a in parsed['assignees'] if a not in ('@所有人', '所有人')]
            parsed_duplicates = find_similar_tasks(
                parsed.get('title') or '',
                parsed.get('description') or '',
                parsed.get('category') or '',
                parsed.get('start_time'),
                parsed.get('end_time'),
                unfinished_only=True)
            parsed_uid = set()
            if not parsed.get('is_all'):
                for name in parsed.get('assignees') or []:
                    u = User.query.filter(db.or_(User.name == name,
                                                 User.username == name)).first()
                    if u:
                        parsed_uid.add(u.id)
                parsed_uid.add(current_user.id)
            if parsed_duplicates and not _similar_blocked_by_assignee(
                    parsed_duplicates, parsed_uid, [],
                    parsed.get('is_all', False)):
                parsed_duplicates = []
            template_data = {
                'rejected_tasks': rejected_tasks,
                'preview': parsed, 'users': users,
                'my_tasks': my_tasks,
                'TaskAssignment': TaskAssignment,
                'now': datetime.now(),
                'is_admin': is_admin_user,
                'user_groups': user_groups,
                'duplicate_tasks': parsed_duplicates,
                'duplicate_blocked': bool(parsed_duplicates),
                'frequent_assignees': _frequent_assignees(current_user.id),
            }
            # tasks assigned to me by others
            my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter_by(user_id=current_user.id).all()}
            other_assigned = Task.query.filter(Task.id.in_(my_assigned_ids), Task.creator_id != current_user.id).order_by(Task.created_at.desc()).all() if my_assigned_ids else []
            template_data.update({
                'my_tasks': my_tasks,
                'other_assigned': other_assigned,
                'TaskAssignment': TaskAssignment,
                'now': datetime.now(),
                'is_admin': is_admin_user,
            })
            template_data.update(_stats_context())
            return render_template('tasks.html', **template_data)
        except Exception as e:
            db.session.rollback()
            logger.error('User task parsing failed: %s', e, exc_info=True)
            flash('解析待办失败：请检查输入格式', 'danger')
            return redirect(url_for('user_tasks'))

    parsed = None
    is_admin_user = current_user.role == 'admin'
    show_completed = request.args.get('completed', '0') == '1'
    # 默认仅展示当前用户视角下尚未完成的待办(completed 以外);?completed=1 显示全部
    completed_ids = set() if show_completed else {
        a.task_id for a in TaskAssignment.query.filter(
            TaskAssignment.user_id == current_user.id,
            TaskAssignment.status == 'completed').all()
    }
    if show_completed:
        my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter_by(user_id=current_user.id).all()}
    else:
        my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter(
            TaskAssignment.user_id == current_user.id,
            TaskAssignment.status != 'completed').all()}
    other_assigned = Task.query.filter(Task.id.in_(my_assigned_ids), Task.creator_id != current_user.id).order_by(Task.created_at.desc()).all() if my_assigned_ids else []
    # 过滤"由当前人创建"的已完成任务(其完成状态取当前人的分配)
    mt = Task.query.filter_by(creator_id=current_user.id)
    if completed_ids:
        mt = mt.filter(~Task.id.in_(completed_ids))
    my_tasks = mt.order_by(Task.created_at.desc()).all()
    template_data = {
        'rejected_tasks': rejected_tasks,
        'preview': parsed, 'users': users,
        'my_tasks': my_tasks,
        'other_assigned': other_assigned,
        'TaskAssignment': TaskAssignment,
        'now': datetime.now(),
        'is_admin': is_admin_user,
        'user_groups': user_groups,
        'show_completed': show_completed,
        'frequent_assignees': _frequent_assignees(current_user.id),
    }
    # 默认展示截止时间最早的一条未完成待办(从今天起算)
    _today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    _default = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status.in_(['pending', 'rejected']),
        Task.end_time >= _today
    ).order_by(Task.end_time).first()
    if _default:
        template_data['default_task_id'] = _default.task_id
    template_data.update(_stats_context())
    if is_admin_user:
        _now = datetime.now()
        user_ids = [u.id for u in users]
        user_stats = []
        status_rows = db.session.query(
            TaskAssignment.user_id, TaskAssignment.status,
            func.count(TaskAssignment.id)
        ).filter(TaskAssignment.user_id.in_(user_ids)).group_by(
            TaskAssignment.user_id, TaskAssignment.status).all()
        per_status = {}
        for uid, status, n in status_rows:
            per_status.setdefault(uid, {})[status] = n
        if user_ids:
            urgent_rows = db.session.query(
                TaskAssignment.user_id, func.count(TaskAssignment.id)
            ).join(Task).filter(
                TaskAssignment.user_id.in_(user_ids),
                TaskAssignment.status == 'pending',
                Task.end_time <= _now
            ).group_by(TaskAssignment.user_id).all()
            overdue_rows = db.session.query(
                TaskAssignment.user_id, func.count(TaskAssignment.id)
            ).join(Task).filter(
                TaskAssignment.user_id.in_(user_ids),
                TaskAssignment.status == 'pending',
                Task.end_time < _now
            ).group_by(TaskAssignment.user_id).all()
        else:
            urgent_rows, overdue_rows = [], []
        urgent = dict(urgent_rows)
        overdue = dict(overdue_rows)
        for u in users:
            s = per_status.get(u.id, {})
            total = sum(s.values())
            completed_count = s.get('completed', 0) + s.get('approved', 0)
            rate = round(completed_count / total * 100, 1) if total > 0 else 0
            user_stats.append({
                'user': u, 'total': total, 'completed': completed_count,
                'rate': rate, 'urgent': urgent.get(u.id, 0),
                'overdue': overdue.get(u.id, 0)
            })
        template_data['user_stats'] = user_stats

    return render_template('tasks.html', **template_data)


@app.route('/user/todo')
@login_required
def user_todo():
    return redirect(url_for('user_dashboard'))


@app.route('/user/tasks/<int:assignment_id>/complete', methods=['POST'])
@login_required
def user_complete_task(assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.user_id != current_user.id:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    assignment.status = 'completed'
    assignment.completed_at = datetime.now()
    assignment.rejection_reason = None
    assignment.progress = 100
    db.session.commit()
    flash('待办已标记完成！', 'success')
    return redirect(request.referrer or url_for('user_dashboard'))


@app.route('/user/tasks/<int:assignment_id>/toggle', methods=['POST'])
@login_required
def user_toggle_task(assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.user_id != current_user.id:
        return jsonify(ok=False, error='待办不存在'), 404
    if assignment.status == 'completed':
        assignment.status = 'pending'
        assignment.progress = 0
        assignment.completed_at = None
    else:
        assignment.status = 'completed'
        assignment.progress = 100
        assignment.completed_at = datetime.now()
        assignment.rejection_reason = None
    db.session.commit()
    return jsonify(ok=True, status=assignment.status, progress=assignment.progress)


@app.route('/user/tasks/<int:assignment_id>/abandon', methods=['POST'])
@login_required
def user_abandon_task(assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.user_id != current_user.id:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    assignment.status = 'abandoned'
    assignment.abandoned_at = datetime.now()
    assignment.rejection_reason = None
    db.session.commit()
    flash('待办已标记为废弃', 'info')
    return redirect(request.referrer or url_for('user_dashboard'))


@app.route('/user/tasks/<int:assignment_id>/upload', methods=['POST'])
@login_required
def user_upload_attachment(assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.user_id != current_user.id:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    if 'file' not in request.files:
        flash('请选择文件', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    file = request.files['file']
    if file.filename == '':
        flash('请选择文件', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    if file and allowed_file(file.filename):
        head = file.stream.read(8192)
        file.stream.seek(0)
        if not file_content_matches(file.filename, head):
            flash('文件内容与扩展名不匹配，已拒绝上传', 'danger')
            return redirect(request.referrer or url_for('user_dashboard'))
        filename = secure_filename(
            f"{current_user.id}_{assignment.id}_{file.filename}"
        )
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        assignment.attachment = filename
        db.session.commit()
        flash('附件上传成功！', 'success')
    else:
        flash('不支持的文件类型', 'danger')
    return redirect(request.referrer or url_for('user_dashboard'))


@app.route('/user/tasks/<int:task_id>')
@login_required
def user_task_detail(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(url_for('user_dashboard'))
    assignment = TaskAssignment.query.filter_by(
        user_id=current_user.id, task_id=task_id).first()
    pending_assignments = TaskAssignment.query.filter(
        TaskAssignment.task_id == task_id,
        TaskAssignment.status == 'pending'
    ).all()
    return render_template('task_detail.html', task=task,
                           assignment=assignment,
                           pending_assignments=pending_assignments,
                           is_admin=False,
                           now=datetime.now(),
                           users=get_same_group_users(current_user),
                           user_groups=current_user.groups.all())


@app.route('/api/task/<int:task_id>')
@login_required
def api_task_detail(task_id):
    """待办内联详情(JSON):供待办页右侧面板展示。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if current_user.role != 'admin' and \
            not TaskAssignment.query.filter_by(
                task_id=task.id, user_id=current_user.id).first():
        return jsonify({'ok': False, 'error': '无权查看'}), 403
    assignment = TaskAssignment.query.filter_by(
        user_id=current_user.id, task_id=task.id).first()
    assigns = TaskAssignment.query.filter(
        TaskAssignment.task_id == task.id).all()
    stats = _build_task_stats([task.id], current_user.id)[0].get(task.id, {})
    return jsonify({
        'ok': True,
        'task': {
            'id': task.id,
            'title': task.title,
            'description': task.description or '',
            'category': task.category,
            'status': assignment.status if assignment else '',
            'progress': assignment.progress if assignment else 0,
            'note': assignment.note if assignment else '',
            'start_time': (task.start_time.strftime('%Y-%m-%d %H:%M')
                           if task.start_time else ''),
            'end_time': (task.end_time.strftime('%Y-%m-%d %H:%M')
                         if task.end_time else ''),
            'start_dt': (task.start_time.strftime('%Y-%m-%dT%H:%M')
                         if task.start_time else ''),
            'end_dt': (task.end_time.strftime('%Y-%m-%dT%H:%M')
                       if task.end_time else ''),
            'is_all': task.is_all,
            'creator': task.creator.name or task.creator.username,
            'creator_id': task.creator_id,
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M')
                          if task.created_at else '',
            'group_ids': [g.id for g in task.groups],
            'can_edit': (current_user.role == 'admin'
                         or task.creator_id == current_user.id
                         or assignment is not None),
            'can_delete': (current_user.role == 'admin'
                           or task.creator_id == current_user.id),
            'assignment_id': assignment.id if assignment else None,
            'assignments': [{
                'assignment_id': a.id,
                'user_id': a.user_id,
                'user': a.user.name or a.user.username,
                'status': a.status,
                'progress': a.progress,
                'note': a.note or '',
                'attachment': a.attachment or '',
                'completed_at': a.completed_at.strftime('%Y-%m-%d %H:%M')
                               if a.completed_at else '',
                'rejection_reason': a.rejection_reason or '',
                'self': a.user_id == current_user.id,
            } for a in assigns],
            'stats': stats,
        }
    })


@app.route('/api/task/<int:task_id>/edit', methods=['POST'])
@login_required
def api_task_edit(task_id):
    """右侧面板内联修改待办(JSON)。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    is_assignee = TaskAssignment.query.filter_by(
        task_id=task.id, user_id=current_user.id).first() is not None
    if task.creator_id != current_user.id and current_user.role != 'admin' \
            and not is_assignee:
        return jsonify({'ok': False, 'error': '无权编辑该待办'}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title or len(title) < 2:
        return jsonify({'ok': False, 'error': '待办标题至少 2 个字'}), 400
    try:
        start = datetime.strptime(data.get('start_time', ''), '%Y-%m-%dT%H:%M') \
            if data.get('start_time') else task.start_time
        end = datetime.strptime(data.get('end_time', ''), '%Y-%m-%dT%H:%M') \
            if data.get('end_time') else task.end_time
        if start is not None and end is not None and end <= start:
            end = start + timedelta(hours=1)
    except Exception:
        return jsonify({'ok': False, 'error': '时间格式错误'}), 400
    task.title = title
    task.category = (data.get('category') or '').strip() or '工作'
    task.start_time = start
    task.end_time = end
    if 'description' in data:
        task.description = (data.get('description') or '').strip()
    # 修改任务状态(通过编辑面板)
    new_status = (data.get('status') or '').strip()
    if new_status in ('pending', 'completed', 'abandoned'):
        assignment = TaskAssignment.query.filter_by(
            task_id=task.id, user_id=current_user.id).first()
        if assignment and assignment.status != new_status:
            assignment.status = new_status
            if new_status == 'completed':
                assignment.progress = 100
                assignment.completed_at = datetime.now()
            elif new_status == 'pending':
                assignment.progress = 0
                assignment.completed_at = None
            elif new_status == 'abandoned':
                assignment.abandoned_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True, 'task_id': task.id})


@app.route('/api/task/<int:task_id>/delete', methods=['POST'])
@login_required
def api_task_delete(task_id):
    """删除待办(仅创建者或管理员)。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '只能删除自己创建的待办'}), 403
    Notification.query.filter(Notification.task_id == task.id).update(
        {Notification.task_id: None})
    db.session.execute(
        task_group.delete().where(task_group.c.task_id == task.id))
    TaskAssignment.query.filter_by(task_id=task.id).delete(
        synchronize_session=False)
    db.session.delete(task)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/task/<int:task_id>/reopen', methods=['POST'])
@login_required
def api_task_reopen(task_id):
    """重新打开待办:将已完成的分配恢复为进行中(创建者或管理员)。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '无权操作'}), 403
    assignments = TaskAssignment.query.filter(
        TaskAssignment.task_id == task.id,
        TaskAssignment.status.in_(['completed', 'approved'])).all()
    for a in assignments:
        a.status = 'pending'
        a.completed_at = None
        a.rejection_reason = None
        a.progress = 0
    db.session.commit()
    return jsonify({'ok': True, 'reset': len(assignments)})


@app.route('/api/task/<int:task_id>/assign', methods=['POST'])
@login_required
def api_task_assign(task_id):
    """修改分配人(创建者或管理员)。

    默认仅新增分配;带 sync=true 时为全量同步:不在列表中的已分配
    用户将被标记为废弃(abandoned),废弃后再次勾选则恢复为进行中。
    """
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '无权操作'}), 403
    data = request.get_json(silent=True) or {}
    user_ids = data.get('user_ids') or []
    group_ids = data.get('group_ids') or []
    rows = TaskAssignment.query.filter_by(task_id=task.id).all()
    existing_map = {a.user_id: a for a in rows}
    added = []

    # 同步任务关联的群组
    if 'group_ids' in data:
        new_groups = [db.session.get(Group, int(gid)) for gid in group_ids
                      if str(gid).lstrip('-').isdigit()]
        new_groups = [g for g in new_groups if g is not None]
        task.groups = new_groups

    # 由群组展开得到的成员 id 集合
    group_member_ids = set()
    if group_ids:
        for gid in group_ids:
            try:
                gid = int(gid)
            except (TypeError, ValueError):
                continue
            g = db.session.get(Group, gid)
            if g:
                for m in g.members:
                    if not m.is_disabled and m.status == 'approved':
                        group_member_ids.add(m.id)

    if data.get('sync'):
        keep = set()
        for raw in user_ids:
            try:
                uid = int(raw)
            except (TypeError, ValueError):
                continue
            if uid in keep:
                continue
            keep.add(uid)
            a = existing_map.get(uid)
            if a is None:
                u = db.session.get(User, uid)
                if not u or u.is_disabled or u.status != 'approved':
                    continue
                db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                create_notification(uid, 'task_assigned',
                                    f'你收到一个新待办：「{task.title}」', task.id)
                added.append(u.name or u.username)
            elif a.status == 'abandoned':
                a.status = 'pending'
                a.abandoned_at = None
                a.progress = 0
                added.append(a.user.name or a.user.username)
        # 群组成员确保在分配名单中
        for uid in group_member_ids:
            if uid in keep:
                continue
            keep.add(uid)
            a = existing_map.get(uid)
            if a is None:
                u = db.session.get(User, uid)
                if u and not u.is_disabled and u.status == 'approved':
                    db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                    added.append(u.name or u.username)
            elif a.status == 'abandoned':
                a.status = 'pending'
                a.abandoned_at = None
                a.progress = 0
        removed = []
        now = datetime.now()
        for a in rows:
            if a.user_id not in keep and a.status != 'abandoned':
                a.status = 'abandoned'
                a.abandoned_at = now
                removed.append(a.user.name or a.user.username)
        db.session.commit()
        return jsonify({'ok': True, 'added': added, 'removed': removed})

    existing = set(existing_map.keys())
    for uid in user_ids:
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            continue
        u = db.session.get(User, uid)
        if not u or u.is_disabled or u.status != 'approved' or uid in existing:
            continue
        existing.add(uid)
        db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
        create_notification(uid, 'task_assigned',
                            f'你收到一个新待办：「{task.title}」', task.id)
        added.append(u.name or u.username)
    if added:
        db.session.commit()
    return jsonify({'ok': True, 'added': added})


def _sync_task_assignees_from_form(task):
    """Sync task assignees from form POST data (assignee_ids + group_ids + is_all)."""
    user_ids = request.form.getlist('assignee_ids')
    group_ids = request.form.getlist('group_ids')
    is_all = request.form.get('is_all') == '1'
    
    if group_ids:
        new_groups = [db.session.get(Group, int(gid)) for gid in group_ids
                      if str(gid).lstrip('-').isdigit()]
        new_groups = [g for g in new_groups if g is not None]
        task.groups = new_groups
    else:
        task.groups = []
    
    keep = set()
    existing = TaskAssignment.query.filter_by(task_id=task.id).all()
    existing_map = {a.user_id: a for a in existing}
    
    if is_all:
        all_users = User.query.filter_by(status='approved').all()
        for u in all_users:
            if not u.is_disabled:
                keep.add(u.id)
    else:
        if group_ids:
            for gid in group_ids:
                try:
                    gid = int(gid)
                except (TypeError, ValueError):
                    continue
                group = db.session.get(Group, gid)
                if group:
                    for member in group.members:
                        keep.add(member.id)
        for uid in user_ids:
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                continue
            keep.add(uid)
    
    if task.is_all:
        keep.add(task.creator_id)
    
    kept_ids = set(keep)
    for uid in kept_ids:
        a = existing_map.get(uid)
        if a is None:
            u = db.session.get(User, uid)
            if u and not u.is_disabled and u.status == 'approved':
                db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                create_notification(uid, 'task_assigned',
                                  f'你收到一个新待办：「{task.title}」', task.id)
        elif a.status == 'abandoned':
            a.status = 'pending'
            a.abandoned_at = None
            a.progress = 0
    
    now = datetime.now()
    for a in existing:
        if a.user_id not in kept_ids and a.status != 'abandoned':
            a.status = 'abandoned'
            a.abandoned_at = now


@app.route('/user/tasks/edit', methods=['POST'])
@login_required
def user_edit_task():
    """修改待办信息:创建者、管理员或待办负责人可编辑。"""
    task_id = request.form.get('task_id', type=int)
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    is_assignee = TaskAssignment.query.filter_by(
        task_id=task.id, user_id=current_user.id).first() is not None
    if task.creator_id != current_user.id and current_user.role != 'admin' \
            and not is_assignee:
        flash('只有待办创建者、管理员或待办负责人可以编辑', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    title = request.form.get('title', '').strip()
    category = request.form.get('category', '').strip() or '工作'
    start_str = request.form.get('start_time', '').strip()
    end_str = request.form.get('end_time', '').strip()
    description = request.form.get('description', '').strip()
    new_status = request.form.get('status', '').strip()
    if not title:
        flash('待办标题不能为空', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    try:
        db.session.rollback()  # 结束只读事务, 使 begin() 成为最外层事务
        with db.session.begin():
            task.title = title
            task.category = category
            if description:
                task.description = description
            if start_str:
                task.start_time = datetime.strptime(
                    start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            if end_str:
                task.end_time = datetime.strptime(
                    end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
            _sync_task_assignees_from_form(task)
            # 修改任务状态
            if new_status in ('pending', 'completed', 'abandoned'):
                assignment = TaskAssignment.query.filter_by(
                    task_id=task.id, user_id=current_user.id).first()
                if assignment and assignment.status != new_status:
                    assignment.status = new_status
                    if new_status == 'completed':
                        assignment.progress = 100
                        assignment.completed_at = datetime.now()
                    elif new_status == 'pending':
                        assignment.progress = 0
                        assignment.completed_at = None
                    elif new_status == 'abandoned':
                        assignment.abandoned_at = datetime.now()
        flash(f'待办 "{title}" 已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'更新失败：{str(e)}', 'danger')
    return redirect(request.referrer or url_for('user_dashboard'))


@app.route('/user/assignments/<int:assignment_id>/update_progress', methods=['POST'])
@login_required
def user_update_assign_progress(assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.user_id != current_user.id:
        flash('待办不存在', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    progress = request.form.get('progress', type=int)
    note = request.form.get('note', '').strip()
    if progress is not None and 0 <= progress <= 100:
        assignment.progress = progress
    if note:
        assignment.note = note
    file_saved = False
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename and f.filename.strip():
            if allowed_file(f.filename):
                original = secure_filename(f.filename)
                if not original or '.' not in original:
                    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else 'png'
                    original = f"upload_{int(datetime.now().timestamp())}.{ext}"
                filename = f"{current_user.id}_{assignment.id}_{original}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                f.save(filepath)
                assignment.attachment = filename
                file_saved = True
            else:
                flash('不支持的文件类型', 'danger')
    if progress == 100 and assignment.status == 'pending':
        assignment.status = 'completed'
        assignment.completed_at = datetime.now()
        assignment.rejection_reason = None
        flash('恭喜，待办已完成！', 'success')
    elif progress is not None and progress < 100 and assignment.status == 'completed':
        assignment.status = 'pending'
        assignment.completed_at = None
        assignment.rejection_reason = None
    db.session.commit()
    flash('进度已更新', 'success')
    return redirect(request.referrer or url_for('user_tasks'))


