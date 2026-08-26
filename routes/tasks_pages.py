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
from app import (app, login_required, Group, Notification, Task,
                 TaskAssignment, User, _count_kb, _count_notes,
                 allowed_file, check_sensitive_words, cn_now,
                 create_notification, db, file_content_matches,
                 find_similar_tasks, get_same_group_users,
                 highlight_sensitive_words, logger, parse_task_from_text,
                 task_group)



from flask import flash, jsonify, redirect, render_template, request, url_for
from services.task_service import purge_task, restore_task, soft_delete_task
from flask_login import current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
import os
from datetime import date, datetime, timedelta

"""tasks 页面路由(/user/*), 自 routes_tasks.py 拆分, endpoint 名称不变。"""
# 跨页面/API 共用的纯函数(拆分自 routes_tasks.py)
from routes.tasks_common import _build_task_stats, _similar_blocked_by_assignee

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
    now = cn_now()
    for t in mine:
        t.deleted_at = now
    db.session.commit()
    flash(f'已将 {len(ids)} 个待办移入回收站', 'success')
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
    soft_delete_task(task)
    flash(f'待办 "{task.title}" 已移入回收站', 'success')
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
    now = cn_now()
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
    now = cn_now()

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
        from routes.notes import Note
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
        from kb.knowledge import KbDocument
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
        from kb.knowledge import KbPoint as _KbPoint
        from kb.knowledge import _visible_point_ids as _kb_visible_point_ids
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
        from kb.knowledge import KbCollection as _KbCollection
        from kb.knowledge import _visible_collection_ids as _kb_visible_cols
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
def _assignment_counts_by_user(creator_id):
    """{display name -> number of assigned tasks}, 只统计当前用户创建(分配)的任务."""
    rows = db.session.query(
        func.coalesce(func.nullif(User.name, ''), User.username).label('uname'),
        func.count(TaskAssignment.id)
    ).select_from(TaskAssignment) \
     .join(User, TaskAssignment.user_id == User.id) \
     .join(Task, TaskAssignment.task_id == Task.id) \
     .filter(Task.creator_id == creator_id) \
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
            ctx['assignment_counts'] = _assignment_counts_by_user(current_user.id)
        order = ['工作', '个人', '会议', '培训', '考试']
        seen = set()
        groups = {c: [] for c in order}
        all_t = list(my_tasks) + list(other_assigned or [])
        for t in all_t:
            if t.id in seen:
                continue
            seen.add(t.id)
            key = (t.category or '').strip() or '未分类'
            groups.setdefault(key, []).append(t)
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
                'now': cn_now(),
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
                        'now': cn_now(),
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
                'now': cn_now(),
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
                'now': cn_now(),
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
        'now': cn_now(),
        'is_admin': is_admin_user,
        'user_groups': user_groups,
        'show_completed': show_completed,
        'frequent_assignees': _frequent_assignees(current_user.id),
    }
    # 默认展示截止时间最早的一条未完成待办(从今天起算)
    _today = cn_now().replace(hour=0, minute=0, second=0, microsecond=0)
    _default = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status.in_(['pending', 'rejected']),
        Task.end_time >= _today
    ).order_by(Task.end_time).first()
    if _default:
        template_data['default_task_id'] = _default.task_id
    template_data.update(_stats_context())

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
    assignment.completed_at = cn_now()
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
        assignment.completed_at = cn_now()
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
    assignment.abandoned_at = cn_now()
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
                           now=cn_now(),
                           users=get_same_group_users(current_user),
                           user_groups=current_user.groups.all())
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
    
    now = cn_now()
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
                        assignment.completed_at = cn_now()
                    elif new_status == 'pending':
                        assignment.progress = 0
                        assignment.completed_at = None
                    elif new_status == 'abandoned':
                        assignment.abandoned_at = cn_now()
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
                    original = f"upload_{int(cn_now().timestamp())}.{ext}"
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
        assignment.completed_at = cn_now()
        assignment.rejection_reason = None
        flash('恭喜，待办已完成！', 'success')
    elif progress is not None and progress < 100 and assignment.status == 'completed':
        assignment.status = 'pending'
        assignment.completed_at = None
        assignment.rejection_reason = None
    db.session.commit()
    flash('进度已更新', 'success')
    return redirect(request.referrer or url_for('user_tasks'))
