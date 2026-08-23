# -*- coding: utf-8 -*-
"""数据模型层: 全部 SQLAlchemy 模型与关联表(自 app.py 抽离).

依赖仅 extensions/timeutil/登录安全工具, 不反向依赖应用层.
"""
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from core.extensions import db
from core.timeutil import cn_now


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(80), default='')
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')
    is_disabled = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='approved')
    failed_login_count = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    unlock_code = db.Column(db.String(6), default='')
    unlock_code_expires_at = db.Column(db.DateTime)
    email = db.Column(db.String(120), default='', index=True)
    email_verified = db.Column(db.Boolean, default=False)
    pending_email = db.Column(db.String(120), default='')
    email_code = db.Column(db.String(6), default='')
    email_code_expires_at = db.Column(db.DateTime)
    api_token = db.Column(db.String(64), default='', index=True)
    api_token_created_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=cn_now)
    registration_ip = db.Column(db.String(64), default='', index=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Task(db.Model):
    __tablename__ = 'task'
    __table_args__ = (
        db.Index('ix_task_creator_end', 'creator_id', 'end_time'),
        db.Index('ix_task_start', 'start_time'),
    )
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), default='工作', index=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    is_all = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=cn_now, index=True)
    # 软删除: 非空即已入回收站(全局查询过滤见 app.py do_orm_execute)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    creator = db.relationship('User', backref='created_tasks')
    assignments = db.relationship('TaskAssignment', backref='task',
                                  lazy='dynamic', cascade='all, delete-orphan')
    groups = db.relationship('Group', secondary='task_group',
                             backref=db.backref('tasks', lazy='dynamic'))


class TaskAssignment(db.Model):
    __tablename__ = 'task_assignment'
    __table_args__ = (
        db.Index('ix_task_assignment_user_status', 'user_id', 'status'),
        db.Index('ix_assignment_user_completed', 'user_id', 'completed_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending')
    progress = db.Column(db.Integer, default=0)
    note = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)
    abandoned_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    attachment = db.Column(db.String(500))

    user = db.relationship('User', backref='task_assignments')


class EmailLog(db.Model):
    __tablename__ = 'email_log'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), unique=True, nullable=False, index=True)
    sent_at = db.Column(db.DateTime, default=cn_now)


class EmailRecord(db.Model):
    __tablename__ = 'email_record'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    subject = db.Column(db.String(200), default='')
    category = db.Column(db.String(30), default='')
    status = db.Column(db.String(20), default='sent')
    error = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=cn_now, index=True)


user_group = db.Table('user_group',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

task_group = db.Table('task_group',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)


class Group(db.Model):
    __tablename__ = 'group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=cn_now)

    members = db.relationship('User', secondary=user_group, backref=db.backref('groups', lazy='dynamic'))


class Notification(db.Model):
    __tablename__ = 'notification'
    __table_args__ = (
        db.Index('ix_notification_user_read', 'user_id', 'is_read'),
        db.Index('ix_notification_created', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True,
                       index=True)
    type = db.Column(db.String(50), default='task_assigned')
    message = db.Column(db.String(500), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=cn_now)

    user = db.relationship('User', backref='notifications')


class OperationLog(db.Model):
    """用户关键操作日志(登录、知识库管理操作等)。"""
    __tablename__ = 'operation_log'
    __table_args__ = (
        db.Index('ix_operation_log_created', 'created_at'),
        db.Index('ix_operation_log_user', 'user_id'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    username = db.Column(db.String(80), default='', index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    target = db.Column(db.String(200), default='')
    detail = db.Column(db.String(1000), default='')
    ip = db.Column(db.String(64), default='')
    created_at = db.Column(db.DateTime, default=cn_now, index=True)


class SysSetting(db.Model):
    """系统设置键值对(如定时任务执行时间配置)。"""
    __tablename__ = 'sys_setting'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, default='')
