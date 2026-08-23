# -*- coding: utf-8 -*-
"""应用业务辅助层: 系统设置/操作日志/邮件/通知/敏感词/相似任务检测等.

不依赖 app 模块(配置经 current_app 获取), 供路由与 worker 复用.
"""
import os
import re
import secrets
import logging

import markupsafe
from cachetools import TTLCache
from flask import request, current_app
from flask_login import current_user
from sqlalchemy import func

from datetime import timedelta

from core.extensions import db, login_manager
from core.timeutil import cn_now
from core.models import (User, Task, TaskAssignment, Group, Notification,
                    OperationLog, SysSetting, EmailRecord, user_group, task_group)

logger = logging.getLogger(__name__)


JOB_SCHEDULE_DEFAULTS = {
    'job_organize_enabled': '1',
    'job_organize_weekday': '5',
    'job_organize_hour': '22',
    'job_cleanup_enabled': '1',
    'job_cleanup_weekday': '6',
    'job_cleanup_hour': '3',
    'job_cleanup_terms': '',
    'job_cleanup_keep_days': '7',
    'job_backup_enabled': '1',
    'job_backup_weekday': '1',
    'job_backup_hour': '3',
    'job_backup_minute': '0',
    'job_backup_keep': '14',
}

def get_job_setting(key, default=None):
    row = db.session.get(SysSetting, key)
    if row is None or row.value == '':
        return default if default is not None else JOB_SCHEDULE_DEFAULTS.get(key, '')
    return row.value

def set_job_setting(key, value):
    row = db.session.get(SysSetting, key)
    if row is None:
        db.session.add(SysSetting(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.session.commit()

def client_ip():
    try:
        return request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or ''
    except Exception:
        return ''

def log_operation(action, target='', detail='', user=None):
    """记录一条用户操作日志。user 缺省取当前登录用户。
    仅 flush 不立即 commit, 由请求结束时统一提交, 减少每请求多次 commit。"""
    try:
        u = user or (current_user if current_user.is_authenticated else None)
        entry = OperationLog(
            user_id=getattr(u, 'id', None),
            username=(getattr(u, 'name', '') or getattr(u, 'username', '')) or '',
            action=action,
            target=(target or '')[:200],
            detail=(detail or '')[:1000],
            ip=client_ip(),
        )
        db.session.add(entry)
        db.session.flush()
    except Exception as e:
        logger.warning('log_operation failed: %s', e)

COMMON_EMAIL_SUFFIXES = ['qq.com', '163.com', '126.com', 'gmail.com',
                         'outlook.com', 'hotmail.com', 'foxmail.com',
                         'sina.com', 'sohu.com', '139.com', '189.cn',
                         'aliyun.com', 'icloud.com', 'yahoo.com']

def normalize_email(value):
    """规范化邮箱地址;不合法返回 None。"""
    value = (value or '').strip().lower()
    if len(value) > 120:
        return None
    if not re.match(r'^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$', value):
        return None
    return value

def send_email(to, subject, html_body, text_body='', category=''):
    """通过 SMTP 发送邮件。返回 (ok, error),并记录发送结果到 email_record。"""
    server = current_app.config['MAIL_SERVER']
    port = current_app.config['MAIL_PORT']
    username = current_app.config['MAIL_USERNAME']
    password = current_app.config['MAIL_PASSWORD']
    mail_from = current_app.config['MAIL_FROM'] or username
    ok = False
    err = ''
    if not server or not username:
        err = '邮件服务未配置'
    else:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            from email.header import Header
            msg = MIMEMultipart('alternative')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = mail_from
            msg['To'] = to
            if text_body:
                msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
            if html_body:
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))
            if port == 465 or current_app.config['MAIL_USE_SSL']:
                smtp = smtplib.SMTP_SSL(server, port, timeout=15)
            else:
                smtp = smtplib.SMTP(server, port, timeout=15)
                if current_app.config['MAIL_USE_TLS']:
                    smtp.starttls()
            with smtp:
                smtp.login(username, password)
                smtp.sendmail(mail_from, [to], msg.as_string())
            ok = True
        except Exception as e:
            logger.warning('send_email failed: %s', e)
            err = str(e)
    try:
        db.session.add(EmailRecord(
            email=to or '', subject=subject or '',
            category=category or '',
            status='sent' if ok else 'failed',
            error=(err or '')[:500]))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return ok, err

def generate_verify_code():
    import secrets
    return f'{secrets.randbelow(1000000):06d}'

def send_verify_code(user, email):
    """生成校验码并发送邮件。返回 (ok, error, dev_code)。"""
    code = generate_verify_code()
    user.pending_email = email
    user.email_code = code
    user.email_code_expires_at = cn_now() + timedelta(minutes=10)
    db.session.commit()
    text = (f'您正在绑定邮箱 {email}。\n'
            f'您的校验码为: {code}\n'
            f'校验码 10 分钟内有效,请勿泄露给他人。\n'
            f'如非本人操作,请忽略本邮件。')
    html = (f'<div style="font-family:Microsoft YaHei,Arial,sans-serif;font-size:14px;color:#1e293b;">'
            f'<p>您正在绑定邮箱 <b>{email}</b>。</p>'
            f'<p>您的校验码为:</p>'
            f'<p style="font-size:24px;font-weight:700;letter-spacing:4px;color:#4f46e7;">{code}</p>'
            f'<p>校验码 <b>10 分钟</b>内有效,请勿泄露给他人。</p>'
            f'<p style="color:#94a3b8;font-size:12px;">如非本人操作,请忽略本邮件。</p></div>')
    ok, err = send_email(email, '【知行合一】邮箱绑定校验码', html, text, category='verify')
    if not ok and not current_app.config['MAIL_SERVER']:
        logger.info('邮件服务未配置,校验码(%s) 已写入日志,目标邮箱: %s', code, email)
        return False, '邮件服务未配置,校验码已写入服务器日志', code
    return ok, err, ''

@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, int(user_id))
    if u is not None and (u.is_disabled or u.status != 'approved'):
        return None
    return u

def _api_token_user():
    """根据 Authorization: Bearer <token> 解析 API 令牌用户(供第三方接口调用)。
    返回 User 或 None。"""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[len('Bearer '):].strip()
    if not token:
        return None
    u = User.query.filter_by(api_token=token).first()
    if u is None or u.is_disabled or u.status != 'approved':
        return None
    return u

@login_manager.request_loader
def _load_user_from_api_token(request):
    """第三方接口可通过 API 令牌(Bearer)免 Cookie 登录。"""
    return _api_token_user()

TASK_COMPLETION_DAYS = 30

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx',
                      'xls', 'xlsx', 'zip', 'rar', 'txt'}

def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_notification(user_id, type, message, task_id=None):
    note = Notification(user_id=user_id, type=type, message=message, task_id=task_id)
    db.session.add(note)
    _clear_cached_notifications(user_id)

_NOTIFY_CACHE = TTLCache(maxsize=200, ttl=60)

def _get_cached_notifications(user_id):
    return _NOTIFY_CACHE.get(user_id)

def _set_cached_notifications(user_id, data):
    _NOTIFY_CACHE[user_id] = data

def _clear_cached_notifications(user_id=None):
    if user_id is None:
        _NOTIFY_CACHE.clear()
    else:
        _NOTIFY_CACHE.pop(user_id, None)

def get_same_group_users(user):
    if user.role == 'admin':
        return User.query.filter(User.is_disabled == False,
                                 User.status == 'approved',
                                 User.id != user.id).all()
    group_ids = [g.id for g in user.groups]
    if not group_ids:
        return []
    return User.query.filter(
        User.id != user.id,
        User.is_disabled == False,
        User.status == 'approved',
        User.groups.any(Group.id.in_(group_ids))
    ).distinct().all()

def _count_notes():
    """统计当前用户的随手记条数(含自动整理生成的报告)。"""
    from routes.notes import Note
    if Note is None:
        return 0
    return Note.query.filter_by(user_id=current_user.id).count()

def _count_kb():
    """统计当前用户上传的知识库文档数(含全部状态)。"""
    from kb.knowledge import KbDocument
    if KbDocument is None:
        return 0
    try:
        return KbDocument.query.filter_by(uploaded_by=current_user.id).count()
    except Exception:
        # 数据库旧版本未添加 visibility 列时的兜底
        from sqlalchemy import func
        return db.session.query(func.count(KbDocument.id)).filter(
            KbDocument.uploaded_by == current_user.id).scalar() or 0


try:
    import fcntl
except ImportError:
    fcntl = None

SENSITIVE_WORDS = ['法轮功', '六四', '天安门事件', '台独', '藏独', '疆独', '邪教',
                   '敏感词示例1', '敏感词示例2']

def check_sensitive_words(text):
    found = []
    for w in SENSITIVE_WORDS:
        if w in text:
            found.append(w)
    return found

def highlight_sensitive_words(text):
    safe = str(markupsafe.escape(text))
    for w in SENSITIVE_WORDS:
        ew = markupsafe.escape(w)
        safe = safe.replace(
            ew,
            f'<mark style="color:var(--danger);background:#fecaca;padding:0 2px;border-radius:2px;">{ew}</mark>')
    return markupsafe.Markup(safe)

def find_similar_tasks(title, description='', category='', start_time=None, end_time=None, exclude_id=None, threshold=0.70, unfinished_only=False):
    from difflib import SequenceMatcher
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload
    results = []
    query = Task.query.options(joinedload(Task.creator))
    if exclude_id:
        query = query.filter(Task.id != exclude_id)
    if unfinished_only:
        # 仅与“未完成待办”比较:存在未完成分配(pending/rejected)即视为未完成
        query = query.filter(Task.assignments.any(
            TaskAssignment.status.in_(['pending', 'rejected'])))
    # SQL pre-filter: only compare against tasks sharing a 2-char token with the
    # input title, so the expensive SequenceMatcher runs on a small candidate set.
    title_lower = title.lower()
    bigrams = sorted({title_lower[i:i + 2] for i in range(len(title_lower) - 1)})
    if bigrams:
        like_conds = [Task.title.ilike(f'%{g}%') for g in bigrams[:5]]
        query = query.filter(or_(*like_conds))
    tasks = query.all()
    for t in tasks:
        title_sim = SequenceMatcher(None, title.lower(), t.title.lower()).ratio()
        if title_sim >= 0.95:
            results.append({
                'task': t, 'similarity': round(title_sim * 100),
                'title_sim': round(title_sim * 100), 'desc_sim': 0,
                'match_type': '标题完全匹配',
            })
            continue
        desc_sim = 0
        if description and t.description:
            desc_sim = SequenceMatcher(None, description.lower(), t.description.lower()).ratio()
        cat_sim = 1.0 if category and t.category and category == t.category else 0
        time_sim = 0
        if start_time and end_time and t.start_time and t.end_time:
            overlap_start = max(start_time, t.start_time)
            overlap_end = min(end_time, t.end_time)
            if overlap_start < overlap_end:
                overlap = (overlap_end - overlap_start).total_seconds()
                union = (max(end_time, t.end_time) - min(start_time, t.start_time)).total_seconds()
                time_sim = overlap / union if union > 0 else 0
        combined = title_sim * 0.45 + desc_sim * 0.25 + cat_sim * 0.15 + time_sim * 0.15
        if combined >= threshold:
            match_type = []
            if title_sim >= 0.7:
                match_type.append('标题')
            if desc_sim >= 0.6:
                match_type.append('描述')
            if cat_sim >= 0.9:
                match_type.append('类型')
            if time_sim >= 0.5:
                match_type.append('时间重叠')
            results.append({
                'task': t,
                'similarity': round(combined * 100),
                'title_sim': round(title_sim * 100),
                'desc_sim': round(desc_sim * 100),
                'match_type': '、'.join(match_type) if match_type else '综合',
            })
    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:5]
