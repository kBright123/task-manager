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

"""tasks 路由共享的纯函数, 自 routes_tasks.py 拆分。"""
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
