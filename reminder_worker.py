#!/usr/bin/env python
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

from app import (EmailLog, Task, TaskAssignment, User, app, db, send_email)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger('reminder_worker')

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
            ) % (task.title, task.category, mins, task.end_time.strftime('%Y-%m-%d %H:%M'))
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


def _send_daily_summary(now):
    """工作日 9:00-9:10 向每个绑定邮箱的用户发送待办日报。

    周六/周日不发送;周一日报单列【周末到期】,把上个周六/周日截止的
    待办并入,避免与【已逾期】重复。"""
    today = now.strftime('%Y-%m-%d')
    is_monday = now.weekday() == 0
    sat_start = mon_start = None
    if is_monday:
        mon_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        sat_start = mon_start - timedelta(days=2)
    users = User.query.filter(
        User.email != '',
        User.email_verified.is_(True),
        User.is_disabled.is_(False),
    ).all()
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
        due_today = [a for a in pending
                     if a.task.end_time.strftime('%Y-%m-%d') == today]
        upcoming = [a for a in pending
                    if a.task.end_time.date() > now.date()
                    and a.task.end_time <= now + timedelta(days=3)]

        def _sec(title, items, fmt):
            if not items:
                return
            lines.append('【%s】%d 项:' % (title, len(items)))
            for a in sorted(items, key=lambda x: x.task.end_time):
                lines.append('- ' + fmt(a))
            lines.append('')

        lines = ['%s 的待办日报(%s %s)' % (user.name or user.username,
                                          today, _weekday_cn(now)), '']
        lines.append('共有待办 %d 项,已完成 %d 项,完成率 %d%%。' % (total, done, rate))
        lines.append('')
        _sec('已逾期', overdue, lambda a: '%s(%s类,截止 %s,已逾期 %d 天)' % (
            a.task.title, a.task.category,
            a.task.end_time.strftime('%m-%d %H:%M'),
            max(1, (now.date() - a.task.end_time.date()).days)))
        _sec('周末到期', weekend_due, lambda a: '%s(%s类,%s截止 %s)' % (
            a.task.title, a.task.category, _weekday_cn(a.task.end_time),
            a.task.end_time.strftime('%H:%M')))
        _sec('今日截止', due_today, lambda a: '%s(%s类,截止 %s)' % (
            a.task.title, a.task.category,
            a.task.end_time.strftime('%H:%M')))
        _sec('未来 3 天', upcoming, lambda a: '%s(%s类,截止 %s)' % (
            a.task.title, a.task.category,
            a.task.end_time.strftime('%m-%d %H:%M')))
        _sec('未完成', sorted(pending, key=lambda x: x.task.end_time)[:20],
             lambda a: '%s(%s类,截止 %s)' % (
                 a.task.title, a.task.category,
                 a.task.end_time.strftime('%m-%d %H:%M')))
        lines.append('')
        lines.append('—— 知行合一 · 待办系统自动发送,请勿回复')

        text = '\n'.join(lines)
        html = _summary_html(lines)
        ok, err = send_email(user.email, '【知行合一】待办日报 %s' % today,
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
