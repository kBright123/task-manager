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
"""admin 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import (app, login_required, init_db, EmailRecord, Group,
                 JOB_SCHEDULE_DEFAULTS, Notification, OperationLog, Task,
                 TaskAssignment, User, _clear_cached_notifications,
                 _count_kb, _count_notes,
                 cn_now,
                 create_notification, db, get_job_setting,
                 get_same_group_users, log_operation, logger,
                 seed_demo_data, set_job_setting, task_group, user_group)

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            if not current_user.is_authenticated and not request.path.startswith('/static/'):
                log_operation(
                    'unauth_access',
                    target=(request.path or '')[:200],
                    detail=f'未登录访问 {request.method} {request.path}')
                db.session.commit()
            flash('需要管理员权限', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def get_completion_rate(task):
    rows = dict(db.session.query(
        TaskAssignment.status, func.count(TaskAssignment.id)
    ).filter(TaskAssignment.task_id == task.id).group_by(
        TaskAssignment.status).all())
    total = sum(rows.values())
    if total == 0:
        return 0
    return round(rows.get('completed', 0) / total * 100, 1)


def get_overall_stats():
    total_tasks = Task.query.count()
    total_users = User.query.count()
    rows = dict(db.session.query(
        TaskAssignment.status, func.count(TaskAssignment.id)
    ).group_by(TaskAssignment.status).all())
    total_assignments = sum(rows.values())
    completed_assignments = rows.get('completed', 0)
    pending_assignments = rows.get('pending', 0)
    rejected_assignments = rows.get('rejected', 0)
    rate = round(completed_assignments / total_assignments * 100, 1) if total_assignments > 0 else 0
    return {
        'total_tasks': total_tasks,
        'total_users': total_users,
        'total_assignments': total_assignments,
        'completed': completed_assignments,
        'pending': pending_assignments,
        'rejected': rejected_assignments,
        'rate': rate
    }



from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
import os
from kb.knowledge import _log_op
import re
from datetime import datetime, timedelta

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    stats = get_overall_stats()
    uid = current_user.id
    now = cn_now()
    total = TaskAssignment.query.filter_by(user_id=uid).count()
    completed = TaskAssignment.query.filter_by(user_id=uid, status='completed').count()
    pending = TaskAssignment.query.filter_by(user_id=uid, status='pending').count()
    rejected = TaskAssignment.query.filter_by(user_id=uid, status='rejected').count()
    rate = round(completed / total * 100, 1) if total > 0 else 0
    upcoming = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid,
        TaskAssignment.status == 'pending',
        Task.end_time >= now,
        Task.end_time <= now + timedelta(days=7)
    ).order_by(Task.end_time).all()
    overdue = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid,
        TaskAssignment.status == 'pending',
        Task.end_time < now
    ).order_by(Task.end_time).all()
    recent = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid,
        TaskAssignment.completed_at.isnot(None)
    ).order_by(TaskAssignment.completed_at.desc()).limit(5).all()
    recent_tasks = Task.query.order_by(Task.created_at.desc()).limit(10).all()

    now_dt = now
    week_start = now_dt - timedelta(days=now_dt.weekday())
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    today_end = now_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    today_tasks = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid, TaskAssignment.status == 'pending',
        Task.end_time >= today_start, Task.end_time <= today_end
    ).order_by(Task.end_time).all()
    week_tasks = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid, TaskAssignment.status == 'pending',
        Task.end_time >= week_start, Task.end_time <= week_end
    ).order_by(Task.end_time).all()
    all_pending = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid, TaskAssignment.status == 'pending'
    ).order_by(Task.end_time).all()
    day_before_start = yesterday_start - timedelta(days=1)
    new_tasks_yesterday = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid, TaskAssignment.status == 'pending',
        Task.created_at >= yesterday_start, Task.created_at < today_start).count()
    new_tasks_prev = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid, TaskAssignment.status == 'pending',
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
                Note.created_at >= yesterday_start,
                Note.created_at < today_start).count()
            new_notes_prev = Note.query.filter(
                Note.created_at >= day_before_start,
                Note.created_at < yesterday_start).count()
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

    return render_template('dashboard.html', stats=stats,
                           total=total, completed=completed, pending=pending,
                           rejected=rejected, rate=rate, upcoming=upcoming,
                           overdue=overdue,
                           recent=recent, recent_tasks=recent_tasks,
                           today_tasks=today_tasks, week_tasks=week_tasks,
                           all_pending=all_pending,
                           now=now_dt,
is_admin=True,
                           users=get_same_group_users(current_user),
                           user_groups=Group.query.all() if current_user.role == 'admin' else current_user.groups.all(),
                              note_count=_count_notes(),
                             kb_count=_count_kb(),
                              new_tasks_yesterday=new_tasks_yesterday,
                              new_notes_yesterday=new_notes_yesterday,
                              new_docs_yesterday=new_docs_yesterday,
                              tasks_delta=tasks_delta,
                              notes_delta=notes_delta,
                              docs_delta=docs_delta)


@app.route('/admin/logs', methods=['GET'])
@login_required
@admin_required
def admin_logs():
    """操作日志管理:按用户/动作/时间筛选,分页展示。"""
    page = request.args.get('page', 1, type=int)
    username = (request.args.get('username') or '').strip()
    action = (request.args.get('action') or '').strip()
    days = request.args.get('days', type=int)

    query = OperationLog.query
    if username:
        like = f'%{username}%'
        query = query.filter(OperationLog.username.ilike(like))
    if action:
        query = query.filter(OperationLog.action == action)
    if days:
        since = cn_now() - timedelta(days=days)
        query = query.filter(OperationLog.created_at >= since)

    pagination = db.paginate(
        query.order_by(OperationLog.created_at.desc()),
        page=page, per_page=30, error_out=False)
    logs = pagination.items

    total_users = db.session.query(
        func.count(func.distinct(OperationLog.user_id))).scalar() or 0

    astro_visits = (OperationLog.query
                    .filter(OperationLog.action == 'astro_visit').count())
    astro_visits_today = (OperationLog.query
                          .filter(OperationLog.action == 'astro_visit',
                                  OperationLog.created_at >= cn_now().replace(
                                      hour=0, minute=0, second=0, microsecond=0))
                          .count())

    return render_template('admin/logs.html', logs=logs,
                           pagination=pagination, username=username,
                           action=action, days=days,
                           total_users=total_users,
                           total_logs=(db.session.query(OperationLog.id)
                                       .count()),
                           astro_visits=astro_visits,
                           astro_visits_today=astro_visits_today)


@app.route('/admin/logs/cleanup', methods=['POST'])
@login_required
@admin_required
def admin_logs_cleanup():
    """操作日志清理:按保留天数删除过期日志,或清空全部。"""
    mode = (request.form.get('mode') or '30d').strip()
    if mode == 'all':
        query = OperationLog.query
        label = '清空全部日志'
    else:
        days = {'7d': 7, '30d': 30, '90d': 90}.get(mode, 30)
        before = cn_now() - timedelta(days=days)
        query = OperationLog.query.filter(OperationLog.created_at < before)
        label = f'删除{days}天前日志'
    try:
        count = query.delete()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('logs cleanup failed: %s', e)
        flash(f'清理失败: {e}', 'danger')
        return redirect(url_for('admin_logs'))
    log_operation('logs_cleanup', target=label, detail=f'删除 {count} 条日志')
    flash(f'已清理 {count} 条日志', 'success')
    return redirect(url_for('admin_logs'))


@app.route('/admin/emails', methods=['GET'])
@login_required
@admin_required
def admin_emails():
    """邮件发送记录:按类型/状态筛选,分页展示。"""
    page = request.args.get('page', 1, type=int)
    category = (request.args.get('category') or '').strip()
    status = (request.args.get('status') or '').strip()

    query = EmailRecord.query
    if category:
        query = query.filter(EmailRecord.category == category)
    if status:
        query = query.filter(EmailRecord.status == status)

    pagination = db.paginate(
        query.order_by(EmailRecord.created_at.desc()),
        page=page, per_page=30, error_out=False)
    records = pagination.items

    category_counts = dict(db.session.query(
        EmailRecord.category, func.count(EmailRecord.id)
    ).group_by(EmailRecord.category).all())
    status_counts = dict(db.session.query(
        EmailRecord.status, func.count(EmailRecord.id)
    ).group_by(EmailRecord.status).all())

    return render_template('admin/emails.html', records=records,
                           pagination=pagination, category=category,
                           status=status,
                           category_counts=category_counts,
                           status_counts=status_counts,
total=(db.session.query(EmailRecord.id).count()))
                                                            
@app.route('/admin/emails/cleanup', methods=['POST'])
@login_required
@admin_required
def admin_emails_cleanup():
    """清理邮件记录:删除已超过30天的记录。"""
    try:
        from datetime import datetime, timedelta
        cutoff = cn_now() - timedelta(days=30)
        deleted = db.session.query(EmailRecord).filter(
            EmailRecord.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        _log_op('email_cleanup', f'{deleted} 条邮件记录', '邮件记录清理')
        return jsonify({'ok': True, 'deleted': deleted})
    except Exception as e:
        db.session.rollback()
        logger.exception('email cleanup failed: %s', request.path)
        return jsonify({'ok': False, 'error': '清理失败，请稍后重试'}), 500


@app.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def admin_users():
    pending_first = (User.status == 'pending').desc()
    users = User.query.order_by(pending_first, User.id.asc()).all()
    groups = Group.query.all()
    return render_template('admin/users.html', users=users, groups=groups, is_admin=True)


@app.route('/admin/users/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def admin_approve_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    user.status = 'approved'
    user.failed_login_count = 0
    user.locked_until = None
    user.unlock_code = ''
    user.unlock_code_expires_at = None
    create_notification(user.id, 'user_approved',
                        '你的注册申请已通过审批，现在可以登录了')
    log_operation('user_approve', user.username,
                  f'管理员 {current_user.name or current_user.username} 审批通过用户注册')
    db.session.commit()
    flash(f'用户 {user.name or user.username} 已通过审批', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>/reject', methods=['POST'])
@login_required
@admin_required
def admin_reject_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    user.status = 'rejected'
    create_notification(user.id, 'user_rejected',
                        '你的注册申请未通过审批，如有疑问请联系管理员')
    log_operation('user_reject', user.username,
                  f'管理员 {current_user.name or current_user.username} 拒绝了用户注册')
    db.session.commit()
    flash(f'用户 {user.name or user.username} 的注册申请已拒绝', 'warning')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/add', methods=['POST'])
@login_required
@admin_required
def admin_add_user():
    username = request.form.get('username', '').strip()
    name = request.form.get('name', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'user')
    if not username or not password:
        flash('用户名和密码不能为空', 'danger')
        return redirect(url_for('admin_users'))
    if User.query.filter_by(username=username).first():
        flash('用户名已存在', 'danger')
        return redirect(url_for('admin_users'))
    user = User(username=username, name=name, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'用户 {username} 添加成功', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    if user.username == 'bright':
        flash('不能删除管理员账号', 'danger')
        return redirect(url_for('admin_users'))
    TaskAssignment.query.filter_by(user_id=user.id).delete()
    Notification.query.filter_by(user_id=user.id).delete()
    admin = db.session.get(User, current_user.id)
    for t in list(user.created_tasks):
        t.creator = admin
    for g in list(user.groups):
        g.members.remove(user)
    db.session.delete(user)
    db.session.commit()
    flash(f'用户 {user.username} 已删除', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/reset-password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_reset_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    password = request.form.get('password', '').strip()
    if not password:
        flash('密码不能为空', 'danger')
        return redirect(url_for('admin_users'))
    user.set_password(password)
    db.session.commit()
    flash(f'用户 {user.username} 密码已重置', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/edit/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    username = request.form.get('username', '').strip()
    name = request.form.get('name', '').strip()
    role = request.form.get('role', 'user')
    password = request.form.get('password', '').strip()
    if not username:
        flash('用户名不能为空', 'danger')
        return redirect(url_for('admin_users'))
    existing = User.query.filter(User.username == username, User.id != user_id).first()
    if existing:
        flash(f'用户名 "{username}" 已被使用', 'danger')
        return redirect(url_for('admin_users'))
    user.username = username
    user.name = name
    if role in ['admin', 'user']:
        user.role = role
    if password:
        user.set_password(password)
    group_ids = request.form.getlist('groups')
    user.groups = []
    for gid in group_ids:
        g = db.session.get(Group, int(gid))
        if g:
            user.groups.append(g)
    db.session.commit()
    flash('用户信息已更新', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/set-role/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_set_role(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    role = request.form.get('role', 'user')
    if role not in ['admin', 'user']:
        flash('无效角色', 'danger')
        return redirect(url_for('admin_users'))
    user.role = role
    db.session.commit()
    flash(f'用户 {user.username} 角色已设置为 {role}', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/disable/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_disable_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    if user.username == 'bright':
        flash('不能禁用管理员账号', 'danger')
        return redirect(url_for('admin_users'))
    user.is_disabled = not user.is_disabled
    db.session.commit()
    status = '已禁用' if user.is_disabled else '已启用'
    flash(f'用户 {user.username} {status}', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/groups', methods=['GET'])
@login_required
@admin_required
def admin_groups():
    return redirect(url_for('admin_users'))


@app.route('/admin/groups/add', methods=['POST'])
@login_required
@admin_required
def admin_add_group():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if not name:
        flash('群组名称不能为空', 'danger')
        return redirect(url_for('admin_groups'))
    if Group.query.filter_by(name=name).first():
        flash('群组名称已存在', 'danger')
        return redirect(url_for('admin_groups'))
    g = Group(name=name, description=description)
    db.session.add(g)
    db.session.commit()
    flash(f'群组「{name}」创建成功', 'success')
    return redirect(url_for('admin_groups'))


@app.route('/admin/groups/edit/<int:group_id>', methods=['POST'])
@login_required
@admin_required
def admin_edit_group(group_id):
    g = db.session.get(Group, group_id)
    if not g:
        flash('群组不存在', 'danger')
        return redirect(url_for('admin_groups'))
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if not name:
        flash('群组名称不能为空', 'danger')
        return redirect(url_for('admin_groups'))
    existing = Group.query.filter(Group.name == name, Group.id != group_id).first()
    if existing:
        flash('群组名称已存在', 'danger')
        return redirect(url_for('admin_groups'))
    g.name = name
    g.description = description
    db.session.commit()
    flash('群组信息已更新', 'success')
    return redirect(url_for('admin_groups'))


@app.route('/admin/groups/delete/<int:group_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_group(group_id):
    g = db.session.get(Group, group_id)
    if not g:
        flash('群组不存在', 'danger')
        return redirect(url_for('admin_groups'))
    db.session.delete(g)
    db.session.commit()
    flash(f'群组「{g.name}」已删除', 'success')
    return redirect(url_for('admin_groups'))


@app.route('/admin/groups/<int:group_id>/members', methods=['POST'])
@login_required
@admin_required
def admin_update_group_members(group_id):
    g = db.session.get(Group, group_id)
    if not g:
        flash('群组不存在', 'danger')
        return redirect(url_for('admin_groups'))
    member_ids = request.form.getlist('members')
    g.members = []
    for uid in member_ids:
        u = db.session.get(User, int(uid))
        if u:
            g.members.append(u)
    db.session.commit()
    flash(f'群组「{g.name}」成员已更新', 'success')
    return redirect(url_for('admin_groups'))


@app.route('/admin/users/<int:user_id>/groups', methods=['POST'])
@login_required
@admin_required
def admin_update_user_groups(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('用户不存在', 'danger')
        return redirect(url_for('admin_users'))
    group_ids = request.form.getlist('groups')
    user.groups = []
    for gid in group_ids:
        g = db.session.get(Group, int(gid))
        if g:
            user.groups.append(g)
    db.session.commit()
    flash(f'用户「{user.name or user.username}」的群组已更新', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/tasks', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_tasks():
    return redirect(url_for('user_tasks'))


@app.route('/admin/tasks/<int:task_id>')
@login_required
@admin_required
def admin_task_detail(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(url_for('user_tasks'))
    assignments = task.assignments.order_by(TaskAssignment.status).all()
    rate = get_completion_rate(task)
    remaining = task.assignments.filter(
        TaskAssignment.status.in_(['pending', 'rejected'])
    ).all()
    pending_assignments = task.assignments.filter_by(status='pending').all()
    assignment = TaskAssignment.query.filter_by(
        user_id=current_user.id, task_id=task_id).first()
    return render_template('task_detail.html', task=task,
                           assignments=assignments, rate=rate,
                           remaining=remaining,
                           pending_assignments=pending_assignments,
                           assignment=assignment,
                           TaskAssignment=TaskAssignment,
                           is_admin=True,
                           now=cn_now(),
                           users=User.query.filter_by(status='approved').all(),
                           user_groups=Group.query.all(),
                           task_assignee_ids=[a.user_id for a in assignments])


@app.route('/admin/tasks/<int:task_id>/edit', methods=['POST'])
@login_required
@admin_required
def admin_edit_task(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(url_for('user_tasks'))
    if task.creator_id != current_user.id and current_user.role != 'admin':
        flash('只有待办创建者或管理员可以编辑', 'danger')
        return redirect(request.referrer or url_for('user_tasks'))
    title = request.form.get('title', '').strip()
    category = request.form.get('category', '').strip() or '工作'
    start_str = request.form.get('start_time', '').strip()
    end_str = request.form.get('end_time', '').strip()
    if not title:
        flash('待办标题不能为空', 'danger')
        return redirect(request.referrer or url_for('user_tasks'))
    try:
        task.title = title
        task.category = category
        if start_str:
            task.start_time = datetime.strptime(start_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        if end_str:
            task.end_time = datetime.strptime(end_str.replace('T', ' '), '%Y-%m-%d %H:%M')
        from routes.tasks_pages import _sync_task_assignees_from_form
        _sync_task_assignees_from_form(task)
        db.session.commit()
        flash(f'待办 "{title}" 已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'更新失败：{str(e)}', 'danger')
    return redirect(request.referrer or url_for('admin_task_detail', task_id=task_id))


@app.route('/admin/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_task(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        flash('待办不存在', 'danger')
        return redirect(url_for('user_tasks'))
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
    return redirect(url_for('user_tasks'))
@app.route('/admin/tasks/<int:task_id>/assignment/<int:assignment_id>/reject',
           methods=['POST'])
@login_required
@admin_required
def admin_reject_assignment(task_id, assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.task_id != task_id:
        flash('待办分配不存在', 'danger')
        return redirect(url_for('admin_task_detail', task_id=task_id))
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('请填写驳回原因', 'danger')
        return redirect(url_for('admin_task_detail', task_id=task_id))
    assignment.status = 'rejected'
    assignment.rejection_reason = reason
    assignment.completed_at = None
    assignment.attachment = None
    db.session.commit()
    flash(f'已驳回 {assignment.user.username} 的完成，原因：{reason}', 'success')
    return redirect(url_for('admin_task_detail', task_id=task_id))


@app.route('/admin/tasks/<int:task_id>/assignment/<int:assignment_id>/approve',
           methods=['POST'])
@login_required
@admin_required
def admin_approve_assignment(task_id, assignment_id):
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment or assignment.task_id != task_id:
        flash('待办分配不存在', 'danger')
        return redirect(url_for('admin_task_detail', task_id=task_id))
    if assignment.status == 'completed':
        assignment.status = 'approved'
        db.session.commit()
        flash(f'已确认 {assignment.user.username} 的完成', 'success')
    return redirect(url_for('admin_task_detail', task_id=task_id))
@app.route('/api/jobs')
@login_required
def api_jobs():
    """组织待办列表(管理页用,返回最近 job)。"""
    from routes.notes import NoteJob
    jobs = NoteJob.query.order_by(NoteJob.created_at.desc()).limit(100).all()
    if current_user.role != 'admin':
        jobs = [j for j in jobs if j.created_by == current_user.id]
    return jsonify({'ok': True, 'jobs': [_job_dict(j) for j in jobs]})


def _job_dict(j):
    return {
        'id': j.id,
        'scope': j.scope,
        'status': j.status,
        'trigger': j.trigger,
        'progress': j.progress,
        'created_at': j.created_at.strftime('%Y-%m-%d %H:%M') if
        j.created_at else '',
        'started_at': j.started_at.strftime('%Y-%m-%d %H:%M') if
        j.started_at else '',
        'finished_at': j.finished_at.strftime('%Y-%m-%d %H:%M') if
        j.finished_at else '',
        'result': j.result or '',
        'error': j.error or '',
    }


@app.route('/admin/jobs/trigger', methods=['POST'])
@admin_required
def admin_jobs_trigger():
    """后台手动触发整理待办(入队后由 job_worker 执行)。"""
    from routes.notes import NoteJob
    scope = request.form.get('scope', 'all')
    if scope not in ('all', 'notes', 'kb', 'refine', 'cleanup', 'backup'):
        scope = 'all'
    terms = request.form.get('terms', '').strip()
    job = NoteJob(scope=scope, target=terms, status='queued',
                  trigger='manual', created_by=current_user.id)
    db.session.add(job)
    db.session.commit()
    log_operation('job_trigger', scope, f'手动触发整理待办 #{job.id}')
    flash(f'已入队整理待办 #{job.id}({scope})', 'success')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/jobs/schedule', methods=['POST'])
@admin_required
def admin_jobs_schedule():
    """保存定时任务配置(执行时间/启用状态)。"""
    for prefix, _default_enabled, _default_wd, _default_hour in (
            ('job_organize', '1', '5', '22'),
            ('job_cleanup', '1', '6', '3')):
        enabled = request.form.get(f'{prefix}_enabled', '0')
        weekday = request.form.get(f'{prefix}_weekday', '')
        hour = request.form.get(f'{prefix}_hour', '')
        set_job_setting(f'{prefix}_enabled', '1' if enabled == '1' else '0')
        if weekday.isdigit() and 0 <= int(weekday) <= 6:
            set_job_setting(f'{prefix}_weekday', weekday)
        if hour.isdigit() and 0 <= int(hour) <= 23:
            set_job_setting(f'{prefix}_hour', hour)
    terms = re.split(r'[，,;；]+',
                     request.form.get('job_cleanup_terms', '').strip())
    terms = ','.join(t.strip() for t in terms if t.strip())
    set_job_setting('job_cleanup_terms', terms)
    days = request.form.get('job_cleanup_keep_days', '')
    if days.isdigit() and 0 < int(days) <= 3650:
        set_job_setting('job_cleanup_keep_days', days)
    enabled = request.form.get('job_backup_enabled', '0')
    weekday = request.form.get('job_backup_weekday', '')
    hour = request.form.get('job_backup_hour', '')
    minute = request.form.get('job_backup_minute', '')
    keep = request.form.get('job_backup_keep', '')
    set_job_setting('job_backup_enabled', '1' if enabled == '1' else '0')
    if weekday.isdigit() and 0 <= int(weekday) <= 6:
        set_job_setting('job_backup_weekday', weekday)
    if hour.isdigit() and 0 <= int(hour) <= 23:
        set_job_setting('job_backup_hour', hour)
    if minute.isdigit() and 0 <= int(minute) <= 59:
        set_job_setting('job_backup_minute', minute)
    if keep.isdigit() and 0 < int(keep) <= 365:
        set_job_setting('job_backup_keep', keep)
    log_operation('job_schedule', 'save', '保存定时任务配置')
    flash('已保存定时任务配置', 'success')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/jobs')
@admin_required
def admin_jobs():
    """后台管理:定时任务/整理记录(执行记录分页显示)。"""
    from routes.notes import NoteJob
    from backup import list_backups
    scope = request.args.get('scope', '')
    status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = 10
    query = NoteJob.query.order_by(NoteJob.created_at.desc())
    if scope in ('all', 'notes', 'kb', 'refine', 'cleanup', 'backup'):
        query = query.filter(NoteJob.scope == scope)
    else:
        scope = ''
    if status in ('queued', 'running', 'done', 'failed', 'cancelled'):
        query = query.filter(NoteJob.status == status)
    else:
        status = ''
    pagination = query.paginate(page=page, per_page=per_page,
                                error_out=False)
    return render_template('admin/jobs.html', jobs=pagination.items,
                           scope=scope, status=status,
                           page=pagination.page,
                           total_pages=pagination.pages,
                           total_jobs=pagination.total,
                           backups=list_backups(),
                           schedule={
                               k: get_job_setting(k) for k in JOB_SCHEDULE_DEFAULTS
                           })


@app.route('/admin/backups/import-restore', methods=['POST'])
@admin_required
def admin_backup_import_restore():
    """导入备份文件(backup-*.tar.gz)并恢复数据。

    上传的备份文件先存入 backups/ 目录,随后调用 restore_backup
    (恢复前自动对当前数据做一次安全备份)。
    """
    import os
    from backup import backup_dir, restore_backup
    f = request.files.get('file')
    name = (f.filename if f else '') or ''
    if not name:
        flash('请选择要导入的备份文件', 'danger')
        return redirect(url_for('admin_jobs'))
    base = os.path.basename(name)
    if not (base.startswith('backup-') and base.endswith('.tar.gz')):
        flash('备份文件名必须形如 backup-YYYYMMDD-HHMMSS.tar.gz', 'danger')
        return redirect(url_for('admin_jobs'))
    bdir = backup_dir()
    os.makedirs(bdir, exist_ok=True)
    target = os.path.join(bdir, base)
    if os.path.exists(target):
        flash('备份文件名已存在,请重命名后再导入', 'danger')
        return redirect(url_for('admin_jobs'))
    try:
        f.save(target)
    except Exception as e:
        logger.warning('import backup save failed: %s', e)
        flash('备份文件保存失败: %s' % e, 'danger')
        return redirect(url_for('admin_jobs'))
    ok, msg = restore_backup(base)
    log_operation('backup_import_restore', base, msg)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/backups/<name>/restore', methods=['POST'])
@admin_required
def admin_backup_restore(name):
    from backup import restore_backup
    ok, msg = restore_backup(name)
    log_operation('backup_restore', name, msg)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/backups/<name>/delete', methods=['POST'])
@admin_required
def admin_backup_delete(name):
    from backup import delete_backup
    if delete_backup(name):
        log_operation('backup_delete', name, '删除备份文件')
        flash(f'已删除备份 {name}', 'success')
    else:
        flash('备份文件不存在', 'danger')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/jobs/<int:job_id>/retry', methods=['POST'])
@admin_required
def admin_jobs_retry(job_id):
    from routes.notes import NoteJob
    job = db.session.get(NoteJob, job_id)
    if not job:
        flash('待办不存在', 'danger')
        return redirect(url_for('admin_jobs'))
    job.status = 'queued'
    job.cancel = 0
    job.error = ''
    job.result = ''
    job.progress = 0
    job.created_at = cn_now()
    job.started_at = None
    job.finished_at = None
    db.session.commit()
    flash(f'已重新入队待办 #{job.id}', 'success')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/jobs/<int:job_id>/stop', methods=['POST'])
@admin_required
def admin_jobs_stop(job_id):
    from routes.notes import NoteJob
    job = db.session.get(NoteJob, job_id)
    if not job:
        flash('待办不存在', 'danger')
        return redirect(url_for('admin_jobs'))
    job.cancel = 1
    if job.status not in ('done', 'failed', 'cancelled'):
        job.status = 'cancelled'
    job.error = ''
    job.result = job.result or ''
    db.session.commit()
    flash(f'已请求停止待办 #{job.id}', 'success')
    return redirect(url_for('admin_jobs'))
@app.route('/admin/clear-data', methods=['POST'])
@login_required
@admin_required
def admin_clear_data():
    Notification.query.delete()
    _clear_cached_notifications()
    TaskAssignment.query.delete()
    db.session.execute(task_group.delete())
    Task.query.delete()
    db.session.execute(user_group.delete())
    Group.query.delete()
    demo_users = User.query.filter(
        User.username.in_(['zhangsan', 'lisi', 'wangwu', 'zhaoliu', 'sunqi'])
    ).all()
    for u in demo_users:
        db.session.delete(u)
    db.session.commit()
    init_db()
    try:
        seed_demo_data(force=True)
    except IntegrityError:
        db.session.rollback()
        logger.warning('Demo reseed skipped after clear')
    flash('所有数据已清空并重新初始化', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/send-daily-summary', methods=['POST'])
@login_required
@admin_required
def admin_send_daily_summary():
    """管理员手动触发日报发送（可选指定用户id）。"""
    from reminder_worker import _send_daily_summary, _already_sent
    user_id = request.form.get('user_id', type=int)
    now = cn_now()
    try:
        if user_id:
            user = User.query.get(user_id)
            if not user:
                flash('用户不存在', 'danger')
                return redirect(url_for('admin_dashboard'))
            key = 'summary:%s:%d' % (now.strftime('%Y-%m-%d'), user_id)
            if _already_sent(key):
                flash('今日日报已发送过该用户，如需重发请先清除 EmailLog', 'warning')
                return redirect(url_for('admin_dashboard'))
            _send_daily_summary(now, target_user_id=user_id)
        else:
            _send_daily_summary(now)
        flash('日报发送任务已触发', 'success')
    except Exception as e:
        flash('发送失败: %s' % str(e), 'danger')
    return redirect(url_for('admin_dashboard'))


with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG') == '1')
