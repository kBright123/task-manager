#!/usr/bin/env python

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
"""待办提醒邮件后台进程(单实例)。

- 会议/培训/考试待办截止前 1 小时提醒对应负责人
- 工作日每日 9:00 发送待办日报(跳过周六/周日,周末到期并入周一)
"""
import html
import logging
import os
import time
from datetime import datetime, timedelta

if os.environ.get('TZ'):
    try:
        time.tzset()
    except Exception:
        pass

from app import (EmailLog, Task, TaskAssignment, User, app, db, send_email,
                 apply_sensitive_log_filter)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger('reminder_worker')
apply_sensitive_log_filter()

INTERVAL = int(os.environ.get('REMINDER_INTERVAL', '300'))
DEADLINE_CATEGORIES = ('会议', '培训', '考试')
DONE_STATUS = ('completed', 'approved')


def _mail_ready():
    return bool(app.config.get('MAIL_SERVER') and app.config.get('MAIL_USERNAME'))


def _already_sent(key):
    return db.session.query(EmailLog.key).filter_by(key=key).first() is not None


def _mark_sent(key):
    db.session.add(EmailLog(key=key))
    db.session.commit()


def _remind_deadline_tasks(now):
    """会议/培训/考试待办,剩余时间落入 (0, 1h] 窗口时提醒未完成负责人。"""
    upper = now + timedelta(hours=1)
    tasks = Task.query.filter(
        Task.category.in_(DEADLINE_CATEGORIES),
        Task.end_time > now,
        Task.end_time <= upper,
    ).all()
    for task in tasks:
        assigns = task.assignments.filter(
            TaskAssignment.status.notin_(DONE_STATUS)
        ).all()
        for a in assigns:
            user = a.user
            if not user or not user.email or not user.email_verified:
                continue
            if user.api_token:
                continue
            key = 'deadline:%d:%d:%s' % (task.id, user.id, now.strftime('%Y%m%d%H'))
            if _already_sent(key):
                continue
            mins = max(1, int((task.end_time - now).total_seconds() // 60))
            subject = '【知行合一】待办即将截止:「%s」' % task.title
            text = (
                '待办「%s」(%s类)即将在 %d 分钟后截止。\n'
                '截止时间: %s\n'
                '描述: %s\n'
                '请及时处理,以免逾期。'
            ) % (task.title, task.category, mins,
                 task.end_time.strftime('%Y-%m-%d %H:%M'), task.description or '')
            html = (
                '<div style="font-family:Microsoft YaHei,Arial,sans-serif;font-size:14px;color:#1e293b;">'
                '<p>待办 <b>「%s」</b>(%s类)即将在 <b>%d 分钟</b>后截止。</p>'
                '<p>截止时间:<b>%s</b></p>'
                '<p style="color:#94a3b8;font-size:12px;">请及时处理,以免逾期。</p></div>'
            ) % (html.escape(task.title), html.escape(task.category), mins,
                 task.end_time.strftime('%Y-%m-%d %H:%M'))
            ok, err = send_email(user.email, subject, html, text, category='deadline')
            if ok:
                _mark_sent(key)
                logger.info('deadline reminder sent task=%s user=%s', task.id, user.id)
            else:
                logger.warning('deadline reminder failed task=%s user=%s: %s',
                               task.id, user.id, err)


_WEEKDAY_CN = '一二三四五六日'


def _weekday_cn(d):
    return '周%s' % _WEEKDAY_CN[d.weekday()]


def _summary_html(lines):
    """把日报纯文本行转成带分区配色的 HTML。"""
    parts = []
    for line in lines:
        esc = html.escape(line)
        if line.startswith('【已逾期'):
            parts.append('<p style="margin:12px 0 2px;color:#dc2626;font-weight:bold;">%s</p>' % esc)
        elif line.startswith('【周末到期'):
            parts.append('<p style="margin:12px 0 2px;color:#c2410c;font-weight:bold;">%s</p>' % esc)
        elif line.startswith('【今日截止'):
            parts.append('<p style="margin:12px 0 2px;color:#065f46;font-weight:bold;">%s</p>' % esc)
        elif line.startswith('【未来'):
            parts.append('<p style="margin:12px 0 2px;color:#1d4ed8;font-weight:bold;">%s</p>' % esc)
        elif line.startswith('【'):
            parts.append('<p style="margin:12px 0 2px;font-weight:bold;">%s</p>' % esc)
        elif line.startswith('- '):
            parts.append('<p style="margin:2px 0 0 14px;color:#334155;">%s</p>' % esc)
        elif line.startswith('——'):
            parts.append('<p style="margin:12px 0 0;color:#94a3b8;font-size:12px;">%s</p>' % esc)
        else:
            parts.append('<p style="margin:2px 0;">%s</p>' % esc)
    return ('<div style="font-family:Microsoft YaHei,Arial,sans-serif;'
            'font-size:14px;color:#1e293b;">' + ''.join(parts) + '</div>')


def _delta_text(d):
    if d > 0:
        return '↑%d' % d
    if d < 0:
        return '↓%d' % -d
    return '—'


def _send_daily_summary(now, target_user_id=None):
    """工作日 9:00-9:10 向每个绑定邮箱的用户发送日报。

    周六/周日不发送;周一日报单列【周末到期】,把上个周六/周日截止的
    待办并入,避免与【已逾期】重复。
    邮件内容包含:概览统计、今日待办、本周待办。
    target_user_id: 指定只给某个用户发送(管理员手动触发),否则全量。"""
    today = now.strftime('%Y-%m-%d')
    today_fmt = now.strftime('%Y/%m/%d')
    is_monday = now.weekday() == 0
    sat_start = mon_start = None
    if is_monday:
        mon_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        sat_start = mon_start - timedelta(days=2)
    query = User.query.filter(
        User.email != '',
        User.email_verified.is_(True),
        User.is_disabled.is_(False),
    )
    if target_user_id:
        query = query.filter(User.id == target_user_id)
    else:
        query = query.filter(User.api_token.is_(None))
    users = query.all()
    if target_user_id and not users:
        logger.warning('daily summary target user=%s not found', target_user_id)
        return
    for user in users:
        key = 'summary:%s:%d' % (today, user.id)
        if _already_sent(key):
            continue
        assigns = TaskAssignment.query.filter_by(user_id=user.id).all()
        pending_all = [a for a in assigns if a.status not in DONE_STATUS]
        if not pending_all:
            continue
        total = len(assigns)
        done = total - len(pending_all)
        rate = int(done / total * 100) if total else 0

        weekend_due = []
        if is_monday:
            weekend_due = [a for a in pending_all
                           if sat_start <= a.task.end_time < mon_start]
            weekend_ids = {id(a) for a in weekend_due}
        else:
            weekend_ids = set()
        pending = [a for a in pending_all if id(a) not in weekend_ids]
        overdue = [a for a in pending if a.task.end_time < now]
        upcoming = [a for a in pending
                    if a.task.end_time.date() > now.date()
                    and a.task.end_time <= now + timedelta(days=3)]

        # ---- 首页数据:今日/本周/后续/最近完成 ----
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        week_start = today_start - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=6, hours=23, minutes=59,
                                           seconds=59)
        today_tasks = [a for a in pending
                       if today_start <= a.task.end_time <= today_end]
        today_ids = {id(a) for a in today_tasks}
        week_other = [a for a in pending
                      if week_start <= a.task.end_time <= week_end
                      and id(a) not in today_ids]
        week_ids = {id(a) for a in week_other}
        other_pending = [a for a in pending
                         if id(a) not in today_ids and id(a) not in week_ids]
        recent = sorted([a for a in assigns if a.completed_at],
                        key=lambda a: a.completed_at, reverse=True)[:5]

        # ---- 首页统计卡:待处理/随手记/知识库(较前日趋势) ----
        yesterday_start = today_start - timedelta(days=1)
        day_before_start = yesterday_start - timedelta(days=1)
        new_tasks_yesterday = sum(1 for a in pending_all
                                  if yesterday_start <= a.task.created_at < today_start)
        new_tasks_prev = sum(1 for a in pending_all
                             if day_before_start <= a.task.created_at < yesterday_start)
        tasks_delta = new_tasks_yesterday - new_tasks_prev
        note_count = new_notes_yesterday = new_notes_prev = 0
        try:
            from routes.notes import Note
            if Note is not None:
                note_count = Note.query.filter_by(
                    user_id=user.id).count()
                new_notes_yesterday = Note.query.filter(
                    Note.user_id == user.id,
                    Note.created_at >= yesterday_start,
                    Note.created_at < today_start).count()
                new_notes_prev = Note.query.filter(
                    Note.user_id == user.id,
                    Note.created_at >= day_before_start,
                    Note.created_at < yesterday_start).count()
        except Exception:
            pass
        notes_delta = new_notes_yesterday - new_notes_prev
        kb_count = new_docs_yesterday = new_docs_prev = 0
        try:
            from kb.knowledge import KbDocument
            if KbDocument is not None:
                kb_count = KbDocument.query.filter_by(
                    uploaded_by=user.id).count()
                new_docs_yesterday = KbDocument.query.filter(
                    KbDocument.created_at >= yesterday_start,
                    KbDocument.created_at < today_start).count()
                new_docs_prev = KbDocument.query.filter(
                    KbDocument.created_at >= day_before_start,
                    KbDocument.created_at < yesterday_start).count()
        except Exception:
            pass
        docs_delta = new_docs_yesterday - new_docs_prev

        def _sec(title, items, fmt):
            if not items:
                return
            lines.append('【%s】%d 项:' % (title, len(items)))
            for a in sorted(items, key=lambda x: x.task.end_time):
                lines.append('- ' + fmt(a))
            lines.append('')

        def _mk(a):
            over = ' · 已逾期' if a.task.end_time < now else ''
            return '%s(%s类,截止 %s)%s' % (
                a.task.title, a.task.category,
                a.task.end_time.strftime('%m-%d %H:%M'), over)

        lines = ['%s 的日报(%s %s)' % (user.name or user.username,
                                       today_fmt, _weekday_cn(now)), '']
        lines.append('【概览】')
        lines.append('- 待处理任务 %d 项(较前日 %s)' % (
            len(pending_all), _delta_text(tasks_delta)))
        lines.append('- 已完成 %d 项, 完成率 %d%%' % (done, rate))
        lines.append('- 随手记 %d 条(较前日 %s)' % (
            note_count, _delta_text(notes_delta)))
        lines.append('- 知识库条目 %d 条(较前日 %s)' % (
            kb_count, _delta_text(docs_delta)))
        lines.append('')
        _sec('今日', today_tasks, _mk)
        _sec('本周', week_other, _mk)
        lines.append('')
        lines.append('—— 知行合一 · 待办系统自动发送,请勿回复')

        text = '\n'.join(lines)
        html = _summary_html(lines)
        ok, err = send_email(user.email, '【知行合一】%s 日报' % today_fmt,
                             html, text, category='summary')
        if ok:
            _mark_sent(key)
            logger.info('daily summary sent user=%s', user.id)
        else:
            logger.warning('daily summary failed user=%s: %s', user.id, err)


def main():
    last_summary_day = None
    while True:
        if not _mail_ready():
            logger.warning('MAIL_SERVER 未配置,邮件提醒已禁用')
            time.sleep(300)
            continue
        try:
            with app.app_context():
                now = datetime.now()
                _remind_deadline_tasks(now)
                day = now.strftime('%Y-%m-%d')
                if now.weekday() < 5 and now.hour == 9 and last_summary_day != day:
                    _send_daily_summary(now)
                    last_summary_day = day
        except Exception:
            logger.exception('reminder_worker iteration failed')
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
