# -*- coding: utf-8 -*-
"""待办领域服务: 回收站(软删除)状态流转, 供各路由复用."""
from core.timeutil import cn_now
from core.extensions import db
from core.models import Notification, TaskAssignment, task_group


def soft_delete_task(task):
    """移入回收站: 仅打标, 保留分配/通知以便恢复. 幂等."""
    if not task.deleted_at:
        task.deleted_at = cn_now()
        db.session.commit()


def restore_task(task):
    """从回收站恢复."""
    task.deleted_at = None
    db.session.commit()


def purge_task(task):
    """彻底删除(不可逆): 解绑通知并级联清理关系数据."""
    Notification.query.filter(Notification.task_id == task.id).update(
        {Notification.task_id: None})
    db.session.execute(
        task_group.delete().where(task_group.c.task_id == task.id))
    TaskAssignment.query.filter_by(task_id=task.id).delete(
        synchronize_session=False)
    db.session.delete(task)
    db.session.commit()
