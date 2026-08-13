import re
import hmac
import secrets
import logging
import contextlib
from datetime import datetime, timedelta, date
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_from_directory, g, session, abort)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         login_required, logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, case
from cachetools import TTLCache
import os
import time

VERSION = 'v0.7.0'

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


_SENSITIVE_LOG_RE = re.compile(
    r'("(?:code|password|token)"\s*:\s*)(?:"[^"]*"|\d{4,6})',
    re.IGNORECASE)


class SensitiveDataFilter(logging.Filter):
    """日志脱敏: 将 code/password/token 字段值替换为 ***。"""

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _SENSITIVE_LOG_RE.sub(r'\1"***"', record.msg)
        if record.args:
            try:
                rendered = record.msg % record.args
            except (TypeError, ValueError, KeyError):
                return True
            masked = _SENSITIVE_LOG_RE.sub(r'\1"***"', rendered)
            if masked != rendered:
                record.msg = masked
                record.args = ()
        return True


def apply_sensitive_log_filter():
    """把脱敏过滤器绑定到 root logger 及其全部 handler。

    basicConfig 只在 root 上建 handler, 各 worker 模块会再次 basicConfig
    新增 handler, 因此统一在 root 上挂过滤器(传播到所有 logger), 并覆盖
    现有 handler; worker 模块在自身 basicConfig 之后再调用一次本函数。
    """
    root = logging.getLogger()
    if not any(isinstance(f, SensitiveDataFilter) for f in root.filters):
        root.addFilter(SensitiveDataFilter())
    for h in list(root.handlers) + list(logger.handlers):
        if not any(isinstance(f, SensitiveDataFilter) for f in h.filters):
            h.addFilter(SensitiveDataFilter())


apply_sensitive_log_filter()

app = Flask(__name__)

try:
    from flask_compress import Compress
    Compress(app)
    # 压缩阈值:>=512B 才压缩;压缩级别 6(省 CPU)
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'application/javascript', 'application/json',
        'application/xml', 'image/svg+xml', 'text/plain']
    app.config['COMPRESS_MIN_SIZE'] = 512
    app.config['COMPRESS_LEVEL'] = 6
    app.config['COMPRESS_ALGORITHM'] = ['gzip']
except Exception:
    pass  # 未安装 Flask-Compress 时静默跳过,不影响启动

def _get_or_create_secret_key(root_path):
    """Persist a random SECRET_KEY in instance/ so sessions survive restarts,
    unless SECRET_KEY is provided via env (docker-compose already sets one)."""
    key_path = os.path.join(root_path, 'instance', '.secret_key')
    try:
        with open(key_path) as f:
            existing = f.read().strip()
            if existing:
                return existing
    except OSError:
        pass
    import secrets
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        with open(key_path, 'w') as f:
            f.write(key)
        os.chmod(key_path, 0o600)
    except OSError:
        logger.warning('Could not persist SECRET_KEY to %s', key_path)
    return key

app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', _get_or_create_secret_key(app.root_path))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
# SQLite 单写连接无需 pool_size;启用 pre_ping 检测失效连接,避免复用坏连接报错
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'instance', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 604800  # 静态资源缓存 7 天
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 24 * 7
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
# 生产关闭模板自动重载(启用 Jinja2 模板缓存);开发(FLASK_DEBUG/KB_AUTO_RELOAD)才实时读盘
app.config['TEMPLATES_AUTO_RELOAD'] = (
    os.environ.get('FLASK_DEBUG') == '1'
    or os.environ.get('KB_AUTO_RELOAD', '0') == '1')

# 邮件(SMTP)配置,用于邮箱绑定验证码;未配置时校验码仅写入日志
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', '')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '465'))
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', '1') == '1'
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', '0') == '1'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_FROM'] = os.environ.get('MAIL_FROM', '')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@app.before_request
def _req_timing_start():
    g._req_start = time.monotonic()


@app.after_request
def _req_timing_log(resp):
    start = getattr(g, '_req_start', None)
    if start is not None:
        dur = time.monotonic() - start
        if dur > 1.0:
            logger.warning('slow request %.1fs %s %s -> %s',
                           dur, request.method, request.path, resp.status_code)
    return resp


_CACHE_IMMUTABLE = 'public, max-age=31536000, immutable'
_CACHE_PRIVATE = 'private, max-age=31536000'
_CACHE_REVALIDATE = 'no-cache, must-revalidate, max-age=0'


@app.after_request
def _cdn_cache_policy(resp):
    """统一 CDN 缓存策略(所有页面/资源生效):

    - /static/* 静态资源(所有页面共用): 不可变长缓存 1 年,
      配合 mtime 版本号(staticv)保证内容更新必然换 URL, 不会被缓存到旧文件。
    - /uploads/ 与 /notes/attachments/ 用户私有媒体: 浏览器/私有缓存 1 年,
      CDN 不公开缓存(避免他人 403 的私有图片被缓存泄露)。
    - 其余动态页面/API: 不缓存, 始终回源校验。
    """
    path = request.path
    if path.startswith('/static/'):
        resp.headers['Cache-Control'] = _CACHE_IMMUTABLE
        resp.headers['Vary'] = 'Accept-Encoding'
    elif path.startswith(('/uploads/', '/notes/attachments/')):
        resp.headers['Cache-Control'] = _CACHE_PRIVATE
    else:
        resp.headers['Cache-Control'] = _CACHE_REVALIDATE
    return resp


@app.after_request
def _security_headers(resp):
    """基础安全响应头。CSP 依赖内联脚本注入, 暂不启用。"""
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    return resp


@app.after_request
def _commit_pending_changes(resp):
    """请求成功结束后统一提交本请求累积的改动(如操作日志),
    配合 log_operation 的 flush 策略减少重复 commit。"""
    try:
        if db.session.new or db.session.dirty or db.session.deleted:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('pending commit failed: %s', e)
    return resp


def csrf_token():
    """生成/复用当前会话的 CSRF token(惰性写入 session)。"""
    tok = session.get('_csrf_token')
    if not tok:
        tok = secrets.token_urlsafe(32)
        session['_csrf_token'] = tok
    return tok


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def _csrf_protect():
    """全站 CSRF 校验: 所有非安全方法(POST/PUT/PATCH/DELETE)必须携带
    session 内 token(表单字段 _csrf_token 或请求头 X-CSRF-Token)。
    表单 token 由 base.html 的 JS 自动注入, AJAX 由全局 fetch 包装注入。"""
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        supplied = (request.form.get('_csrf_token')
                    or request.headers.get('X-CSRF-Token') or '')
        expected = session.get('_csrf_token', '')
        if not expected or not supplied or not hmac.compare_digest(supplied, expected):
            abort(400, description='CSRF 校验失败，请刷新页面后重试')


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def _http_error(e):
    if request.path.startswith(('/api/', '/kb/api/', '/notes/api/')):
        return jsonify({'ok': False, 'error': getattr(e, 'description', '') or e.name}), e.code
    return render_template('error.html', code=getattr(e, 'code', 400),
                           message=getattr(e, 'description', '') or e.name), e.code


@app.errorhandler(500)
def _internal_error(e):
    db.session.rollback()
    logger.error('Internal error: %s %s -> %s', request.method, request.path, e)
    if request.path.startswith(('/api/', '/kb/api/', '/notes/api/')):
        return jsonify({'ok': False, 'error': '服务器内部错误'}), 500
    return render_template('error.html', code=500, message='服务器内部错误'), 500


from knowledge import init_models, enable_sqlite_wal, kb_bp, \
    _resolve_stored_path, file_content_matches
init_models(db)
app.register_blueprint(kb_bp)

from notes import init_models as notes_init_models, notes_bp
notes_init_models(db)
app.register_blueprint(notes_bp)


_STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

_STATIC_MTIME_TTL = 30.0
_static_mtime_cache = {}  # {filename: (version, fetched_at)}


def _static_mtime_version(filename):
    """静态文件 mtime 版本号: 内容变化自动换 URL 版本, 支持不可变缓存。

    版本号带 30s TTL 缓存:一次页面渲染会为多个资源调用本函数,避免每个
    静态文件每次请求都做一次 stat;开发期改文件最迟 30s 内生效。"""
    now = time.time()
    cached = _static_mtime_cache.get(filename)
    if cached is not None and now - cached[1] < _STATIC_MTIME_TTL:
        return cached[0]
    try:
        version = int(os.path.getmtime(
            os.path.join(_STATIC_ROOT, filename)))
    except OSError:
        version = 0
    _static_mtime_cache[filename] = (version, now)
    return version


@app.context_processor
def inject_globals():
    if current_user.is_authenticated:
        cached = _get_cached_notifications(current_user.id)
        if cached is not None:
            unread_count, recent = cached
        else:
            unread_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False).count()
            rows = Notification.query.filter_by(
                user_id=current_user.id).order_by(
                Notification.created_at.desc()).limit(10).all()
            recent = [{
                'id': n.id, 'type': n.type, 'message': n.message,
                'is_read': n.is_read, 'task_id': n.task_id,
                'created_at': n.created_at,
            } for n in rows]
            _set_cached_notifications(current_user.id, (unread_count, recent))
        return {'now': datetime.now, 'today_str': datetime.now().strftime(
            '%Y年%m月%d日 %A'), 'timedelta': timedelta,
                'VERSION': VERSION,
                'staticv': _static_mtime_version,
                'unread_notifications': unread_count,
                'recent_notifications': recent}
    return {'now': datetime.now, 'today_str': datetime.now().strftime(
        '%Y年%m月%d日 %A'), 'timedelta': timedelta, 'VERSION': VERSION,
            'staticv': _static_mtime_version}


import markupsafe

_url_re = re.compile(r'(https?://[^\s<>"\')\]，。、！？）]+)')

@app.template_filter('linkify')
def linkify_filter(text):
    if not text:
        return text
    escaped = markupsafe.escape(text)
    linked = _url_re.sub(r'<a href="\1" target="_blank" rel="noopener" style="color:var(--primary);text-decoration:underline;">\1</a>', str(escaped))
    return markupsafe.Markup(linked)


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    creator = db.relationship('User', backref='created_tasks')
    assignments = db.relationship('TaskAssignment', backref='task',
                                  lazy='dynamic', cascade='all, delete-orphan')
    groups = db.relationship('Group', secondary='task_group',
                             backref=db.backref('tasks', lazy='dynamic'))


class TaskAssignment(db.Model):
    __tablename__ = 'task_assignment'
    __table_args__ = (
        db.Index('ix_task_assignment_user_status', 'user_id', 'status'),
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
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)


class EmailRecord(db.Model):
    __tablename__ = 'email_record'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    subject = db.Column(db.String(200), default='')
    category = db.Column(db.String(30), default='')
    status = db.Column(db.String(20), default='sent')
    error = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SysSetting(db.Model):
    """系统设置键值对(如定时任务执行时间配置)。"""
    __tablename__ = 'sys_setting'
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, default='')


# 定时任务默认配置
JOB_SCHEDULE_DEFAULTS = {
    'job_organize_enabled': '1',
    'job_organize_weekday': '5',
    'job_organize_hour': '22',
    'job_cleanup_enabled': '1',
    'job_cleanup_weekday': '6',
    'job_cleanup_hour': '3',
    'job_cleanup_terms': '',
    'job_backup_enabled': '1',
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
    server = app.config['MAIL_SERVER']
    port = app.config['MAIL_PORT']
    username = app.config['MAIL_USERNAME']
    password = app.config['MAIL_PASSWORD']
    mail_from = app.config['MAIL_FROM'] or username
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
            if port == 465 or app.config['MAIL_USE_SSL']:
                smtp = smtplib.SMTP_SSL(server, port, timeout=15)
            else:
                smtp = smtplib.SMTP(server, port, timeout=15)
                if app.config['MAIL_USE_TLS']:
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
    user.email_code_expires_at = datetime.utcnow() + timedelta(minutes=10)
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
    if not ok and not app.config['MAIL_SERVER']:
        logger.info('邮件服务未配置,校验码(%s) 已写入日志,目标邮箱: %s', code, email)
        return False, '邮件服务未配置,校验码已写入服务器日志', code
    return ok, err, ''


@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, int(user_id))
    if u is not None and (u.is_disabled or u.status != 'approved'):
        return None
    return u


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
    from notes import Note
    if Note is None:
        return 0
    return Note.query.filter_by(user_id=current_user.id).count()


def _count_kb():
    """统计当前用户上传的知识库文档数(含全部状态)。"""
    from knowledge import KbDocument
    if KbDocument is None:
        return 0
    return KbDocument.query.filter_by(uploaded_by=current_user.id).count()


try:
    import fcntl
except ImportError:
    fcntl = None


@contextlib.contextmanager
def db_init_lock():
    """Serialize init_db/seed_demo_data across gunicorn workers so concurrent
    startup cannot double-insert demo rows and trip the UNIQUE constraint."""
    if fcntl is None:
        yield
        return
    lock_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'instance', '.db_init.lock')
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    f = open(lock_path, 'a+')
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _repair_doc_file_paths(c):
    """把 kb_document.file_path 修正到原始文件实际所在的位置。

    upload 目录或卷挂载路径在历史版本间发生过迁移,DB 中记录的绝对路径
    可能已不存在;这里按文件名在 instance/uploads 与 static/uploads 两种
    布局下兜底查找,找到就回写正确路径(每次启动都会执行,具备自愈能力)。"""
    rows = c.execute('SELECT id, file_path FROM kb_document').fetchall()
    fixed = 0
    for doc_id, fp in rows:
        if not fp:
            continue
        resolved = _resolve_stored_path(fp)
        if resolved != fp and os.path.exists(resolved):
            c.execute('UPDATE kb_document SET file_path=? WHERE id=?',
                      (resolved, doc_id))
            fixed += 1
    return fixed


def _run_sqlite_migrations():
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'tasks.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('PRAGMA table_info(user)')
        cols = [r[1] for r in c.fetchall()]
        if 'name' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN name TEXT DEFAULT ""')
        if 'email' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN email VARCHAR(120) DEFAULT ""')
        if 'email_verified' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN email_verified BOOLEAN DEFAULT 0')
        if 'pending_email' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN pending_email VARCHAR(120) DEFAULT ""')
        if 'email_code' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN email_code VARCHAR(6) DEFAULT ""')
        if 'email_code_expires_at' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN email_code_expires_at DATETIME')
        if 'status' not in cols:
            c.execute("ALTER TABLE user ADD COLUMN status VARCHAR(20) DEFAULT 'approved'")
        if 'failed_login_count' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN failed_login_count INTEGER DEFAULT 0')
        if 'locked_until' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN locked_until DATETIME')
        if 'unlock_code' not in cols:
            c.execute("ALTER TABLE user ADD COLUMN unlock_code VARCHAR(6) DEFAULT ''")
        if 'unlock_code_expires_at' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN unlock_code_expires_at DATETIME')
        if 'registration_ip' not in cols:
            c.execute("ALTER TABLE user ADD COLUMN registration_ip VARCHAR(64) DEFAULT ''")
        c.execute('PRAGMA table_info(task)')
        cols = [r[1] for r in c.fetchall()]
        if 'category' not in cols:
            c.execute('ALTER TABLE task ADD COLUMN category TEXT DEFAULT "工作"')
        c.execute('PRAGMA table_info(task_assignment)')
        cols = [r[1] for r in c.fetchall()]
        if 'abandoned_at' not in cols:
            c.execute('ALTER TABLE task_assignment ADD COLUMN abandoned_at DATETIME')
        c.execute('PRAGMA table_info(kb_document)')
        cols = [r[1] for r in c.fetchall()]
        if 'collection_id' not in cols:
            c.execute('ALTER TABLE kb_document ADD COLUMN collection_id INTEGER')
        if 'attempts' not in cols:
            c.execute('ALTER TABLE kb_document ADD COLUMN attempts INTEGER DEFAULT 0')
        for col, ddl in [('last_recognition_at', 'DATETIME'),
                           ('last_recognition_type', 'VARCHAR(20)'),
                           ('last_recognition_result', 'VARCHAR(20)'),
                           ('recognition_count', 'INTEGER DEFAULT 0'),
                           ('cancel', 'INTEGER DEFAULT 0'),
                           ('auto_classified', 'INTEGER DEFAULT 0')]:
            if col not in cols:
                c.execute(f'ALTER TABLE kb_document ADD COLUMN {col} {ddl}')
        c.execute('PRAGMA table_info(kb_collection)')
        cols = [r[1] for r in c.fetchall()]
        if 'visibility' not in cols:
            c.execute("ALTER TABLE kb_collection ADD COLUMN visibility VARCHAR(10) DEFAULT 'private'")
        if 'owner_id' not in cols:
            c.execute('ALTER TABLE kb_collection ADD COLUMN owner_id INTEGER')
        c.execute('PRAGMA table_info(kb_point)')
        cols = [r[1] for r in c.fetchall()]
        if 'tags' not in cols:
            c.execute("ALTER TABLE kb_point ADD COLUMN tags TEXT DEFAULT '[]'")
        if 'summary' not in cols:
            c.execute("ALTER TABLE kb_point ADD COLUMN summary TEXT DEFAULT ''")
        if 'refined_at' not in cols:
            c.execute('ALTER TABLE kb_point ADD COLUMN refined_at DATETIME')
        c.execute('PRAGMA table_info(note)')
        cols = [r[1] for r in c.fetchall()]
        if 'refined_at' not in cols:
            c.execute('ALTER TABLE note ADD COLUMN refined_at DATETIME')
        c.execute('PRAGMA table_info(note_job)')
        cols = [r[1] for r in c.fetchall()]
        if 'cancel' not in cols:
            c.execute('ALTER TABLE note_job ADD COLUMN cancel INTEGER DEFAULT 0')
        if 'phase' not in cols:
            c.execute("ALTER TABLE note_job ADD COLUMN phase VARCHAR(50) DEFAULT ''")
        if 'updated_at' not in cols:
            c.execute('ALTER TABLE note_job ADD COLUMN updated_at DATETIME')
        c.execute('PRAGMA table_info(kb_document)')
        cols = [r[1] for r in c.fetchall()]
        if 'refined_at' not in cols:
            c.execute('ALTER TABLE kb_document ADD COLUMN refined_at DATETIME')
        c.execute(
            "CREATE TABLE IF NOT EXISTS kb_collection_group ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "collection_id INTEGER NOT NULL, "
            "group_id INTEGER NOT NULL)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS kb_point_group ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "point_id INTEGER NOT NULL, "
            "group_id INTEGER NOT NULL)")
        c.execute(
            "CREATE TABLE IF NOT EXISTS sys_setting ("
            "key VARCHAR(100) PRIMARY KEY, "
            "value TEXT DEFAULT '')")
        c.execute('CREATE INDEX IF NOT EXISTS ix_kbcg_coll '
                  'ON kb_collection_group(collection_id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_kbcg_group '
                  'ON kb_collection_group(group_id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_kbpg_point '
                  'ON kb_point_group(point_id)')
        c.execute('CREATE INDEX IF NOT EXISTS ix_kbpg_group '
                  'ON kb_point_group(group_id)')
        c.execute(
            "UPDATE kb_document SET last_recognition_at=updated_at, "
            "last_recognition_type='upload', "
            "last_recognition_result=CASE WHEN status='done' THEN 'success' "
            "ELSE 'failed' END, recognition_count=1 "
            "WHERE last_recognition_at IS NULL")
        fixed = _repair_doc_file_paths(c)
        if fixed:
            print(f'[migration] 修正 {fixed} 个文档的文件路径')
        for sql in [
            'CREATE INDEX IF NOT EXISTS ix_task_creator_end ON task (creator_id, end_time)',
            'CREATE INDEX IF NOT EXISTS ix_task_start ON task (start_time)',
            'CREATE INDEX IF NOT EXISTS ix_task_creator ON task (creator_id)',
            'CREATE INDEX IF NOT EXISTS ix_task_category ON task (category)',
            'CREATE INDEX IF NOT EXISTS ix_task_created ON task (created_at)',
            'CREATE INDEX IF NOT EXISTS ix_task_assignment_user_status ON task_assignment (user_id, status)',
            'CREATE INDEX IF NOT EXISTS ix_task_assignment_task ON task_assignment (task_id)',
            'CREATE INDEX IF NOT EXISTS ix_task_assignment_user ON task_assignment (user_id)',
            'CREATE INDEX IF NOT EXISTS ix_notification_user_read ON notification (user_id, is_read)',
            'CREATE INDEX IF NOT EXISTS ix_notification_user ON notification (user_id)',
            'CREATE INDEX IF NOT EXISTS ix_notification_task ON notification (task_id)',
            'CREATE INDEX IF NOT EXISTS ix_kb_document_collection ON kb_document (collection_id)',
            'CREATE INDEX IF NOT EXISTS ix_kb_document_uploaded ON kb_document (uploaded_by)',
            'CREATE INDEX IF NOT EXISTS ix_operation_log_created ON operation_log (created_at)',
            'CREATE INDEX IF NOT EXISTS ix_operation_log_user ON operation_log (user_id)',
            'CREATE INDEX IF NOT EXISTS ix_operation_log_action ON operation_log (action)',
            'DROP TABLE IF EXISTS kb_triple',
            'DROP TABLE IF EXISTS kb_entity',
        ]:
            c.execute(sql)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'Migration note: {e}')


def init_db():
    with db_init_lock():
        db.create_all()
        _run_sqlite_migrations()
        enable_sqlite_wal()
        fresh = not User.query.filter_by(username='bright').first()
        if fresh:
            admin = User(username='bright', role='admin')
            admin.set_password('Bright@wangzhan')
            db.session.add(admin)
            db.session.commit()
        try:
            seed_demo_data(force=fresh)
        except IntegrityError:
            db.session.rollback()
            logger.warning('Demo seeding skipped: another worker seeded first')


def seed_demo_data(force=False):
    """Seed demo data only when force=True (fresh DB or explicit reset).
    Restarts never restore demo users deleted by the admin."""
    if not force:
        return
    print('Seeding demo data...')
    users_data = [
        ('zhangsan', '张三'), ('lisi', '李四'), ('wangwu', '王五'),
        ('zhaoliu', '赵六'), ('sunqi', '孙七'),
    ]
    users = []
    for uname, name in users_data:
        u = User(username=uname, name=name, role='user')
        u.set_password('123456')
        db.session.add(u)
        users.append(u)
    db.session.flush()

    groups_data = [
        ('技术部', '技术开发团队', ['zhangsan', 'wangwu', 'sunqi']),
        ('产品部', '产品设计团队', ['lisi', 'zhaoliu']),
        ('市场部', '市场营销团队', ['zhangsan', 'lisi']),
    ]
    for gname, gdesc, member_names in groups_data:
        g = Group(name=gname, description=gdesc)
        db.session.add(g)
        db.session.flush()
        for uname in member_names:
            u = User.query.filter_by(username=uname).first()
            if u:
                g.members.append(u)

    db.session.flush()

    now = datetime.now()
    today_start = now.replace(hour=9, minute=0, second=0, microsecond=0)

    demo_tasks = [
        {'title': '完成Q2项目汇报PPT', 'category': '工作', 'assign': 'all',
         'start': today_start - timedelta(days=2), 'end': today_start + timedelta(days=3, hours=9),
         'desc': '请各处室准备Q2项目汇报材料，周五前提交PPT'},
        {'title': '学习Python异步编程', 'category': '个人', 'assign': 'zhangsan',
         'start': today_start, 'end': today_start + timedelta(days=5, hours=8)},
        {'title': '整理部门周报', 'category': '工作', 'assign': 'zhangsan',
         'start': today_start - timedelta(days=1), 'end': today_start + timedelta(hours=3)},
        {'title': '健身计划-每周3次跑步', 'category': '个人', 'assign': 'lisi',
         'start': today_start - timedelta(days=3), 'end': today_start + timedelta(days=20)},
        {'title': '阅读《系统设计面试》', 'category': '个人', 'assign': 'zhangsan',
         'start': today_start, 'end': today_start + timedelta(days=14)},
        {'title': '开发登录模块', 'category': '工作', 'assign': 'wangwu',
         'start': today_start - timedelta(days=5), 'end': today_start - timedelta(days=1)},
        {'title': '生日聚会筹备', 'category': '个人', 'assign': 'zhaoliu',
         'start': today_start + timedelta(days=3), 'end': today_start + timedelta(days=4, hours=6)},
        {'title': '数据库备份脚本优化', 'category': '工作', 'assign': 'sunqi',
         'start': today_start - timedelta(days=1), 'end': today_start + timedelta(days=2)},
        {'title': '在线课程-数据结构', 'category': '个人', 'assign': 'zhangsan',
         'start': today_start, 'end': today_start + timedelta(days=30)},
        {'title': '客户需求评审会议', 'category': '工作', 'assign': 'all',
         'start': today_start + timedelta(hours=2), 'end': today_start + timedelta(hours=4)},
        {'title': '周末短途旅行计划', 'category': '个人', 'assign': 'wangwu',
         'start': today_start + timedelta(days=4), 'end': today_start + timedelta(days=5, hours=12)},
        {'title': 'API接口文档编写', 'category': '工作', 'assign': 'zhangsan',
         'start': today_start - timedelta(days=4), 'end': today_start + timedelta(days=1)},
        {'title': '每月读书总结', 'category': '个人', 'assign': 'lisi',
         'start': today_start - timedelta(days=10), 'end': today_start - timedelta(days=3)},
        {'title': '服务器安全加固', 'category': '工作', 'assign': 'zhangsan',
         'start': today_start + timedelta(days=1), 'end': today_start + timedelta(days=4)},
        {'title': '技术部Sprint评审', 'category': '工作', 'group': '技术部',
         'start': today_start, 'end': today_start + timedelta(days=2, hours=8),
         'desc': '技术部本迭代代码评审与总结'},
        {'title': '产品部需求评审', 'category': '工作', 'group': '产品部',
         'start': today_start + timedelta(days=1), 'end': today_start + timedelta(days=3),
         'desc': '产品部下季度需求优先级评审'},
    ]

    for td in demo_tasks:
        task = Task(title=td['title'], description=td.get('desc', ''),
                    category=td['category'],
                    start_time=td['start'], end_time=td['end'],
                    creator_id=users[0].id, is_all=(td.get('assign') == 'all'))
        db.session.add(task)
        db.session.flush()
        if td.get('assign') == 'all':
            target_users = users
        elif td.get('assign') == 'guest':
            target_users = []
        elif td.get('assign'):
            target_users = [u for u in users if u.username == td['assign']]
        else:
            target_users = []
        for u in target_users:
            db.session.add(TaskAssignment(task_id=task.id, user_id=u.id))
            create_notification(u.id, 'task_assigned',
                                f'你收到一个新待办：「{td["title"]}」', task.id)
        if td.get('group'):
            g = Group.query.filter_by(name=td['group']).first()
            if g:
                task.groups.append(g)
                for m in g.members:
                    if m.id not in [u.id for u in target_users]:
                        db.session.add(TaskAssignment(task_id=task.id, user_id=m.id))
                        create_notification(m.id, 'task_assigned',
                                            f'你收到一个新待办：「{td["title"]}」', task.id)

    # Mark some as completed with varying progress
    completed_tasks_data = [
        {'title': '开发登录模块', 'user': 'wangwu', 'progress': 100},
        {'title': '每月读书总结', 'user': 'lisi', 'progress': 100},
        {'title': '完成Q2项目汇报PPT', 'user': 'zhangsan', 'progress': 60},
        {'title': '学习Python异步编程', 'user': 'zhangsan', 'progress': 30},
    ]
    for ctd in completed_tasks_data:
        task = Task.query.filter_by(title=ctd['title']).first()
        if task:
            u = User.query.filter_by(username=ctd['user']).first()
            if u:
                a = TaskAssignment.query.filter_by(task_id=task.id, user_id=u.id).first()
                if a:
                    a.progress = ctd['progress']
                    if ctd['progress'] == 100:
                        a.status = 'completed'
                        a.completed_at = now - timedelta(hours=2)

    db.session.commit()
    print('Demo data seeded successfully')


WEEKDAY_MAP = {
    '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6
}


def parse_chinese_datetime(text):
    now = datetime.now()
    result_date = now
    result_time = None

    hour = None
    minute = 0
    is_pm = None

    def set_time_from_text(t):
        nonlocal hour, minute, is_pm
        m = re.search(r'(上午|早上|早晨|凌晨)?(\d+)[:：](\d+)', t)
        if m:
            is_pm = True if m.group(1) in ['下午', '晚上'] else False
            hour = int(m.group(2))
            minute = int(m.group(3))
            if is_pm and hour < 12:
                hour += 12
            return
        m = re.search(r'(上午|早上|早晨|凌晨|下午|晚上)?(\d+)[点时](\d+)?[分]?', t)
        if m:
            if m.group(1) in ['下午', '晚上']:
                is_pm = True
            elif m.group(1) in ['上午', '早上', '早晨', '凌晨']:
                is_pm = False
            hour = int(m.group(2))
            if m.group(3):
                minute = int(m.group(3))
            else:
                minute = 0
            if is_pm and hour < 12:
                hour += 12
            return
        m = re.search(r'(\d+)[:：](\d+)', t)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            return

    if '大后天' in text:
        result_date = now + timedelta(days=3)
    elif '后天' in text:
        result_date = now + timedelta(days=2)
    elif '明天' in text:
        result_date = now + timedelta(days=1)
    elif '今天' in text:
        result_date = now
    elif '下下' in text:
        m = re.search(r'下下[周星期]([一二三四五六日天])', text)
        if m:
            target = WEEKDAY_MAP.get(m.group(1), 0)
            days_ahead = target - now.weekday()
            if days_ahead <= 0:
                days_ahead += 14
            else:
                days_ahead += 7
            result_date = now + timedelta(days=days_ahead)
    elif '下' in text:
        m = re.search(r'下[周星期]([一二三四五六日天])', text)
        if m:
            target = WEEKDAY_MAP.get(m.group(1), 0)
            days_ahead = target - now.weekday() + 7
            result_date = now + timedelta(days=days_ahead)
    elif '这' in text or '本' in text:
        m = re.search(r'(这|本)[周星期]([一二三四五六日天])', text)
        if m:
            target = WEEKDAY_MAP.get(m.group(2), 0)
            days_ahead = target - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            result_date = now + timedelta(days=days_ahead)
    else:
        m = re.search(r'(\d{4})[年-](\d{1,2})[月-](\d{1,2})[日号]?', text)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                result_date = datetime(y, mo, d)
            except (ValueError, OverflowError):
                pass
        else:
            m = re.search(r'(\d{1,2})月(\d{1,2})[日号]?', text)
            if m:
                try:
                    mo, d = int(m.group(1)), int(m.group(2))
                    y = now.year
                    result_date = datetime(y, mo, d)
                    if result_date < datetime(y, now.month, now.day):
                        result_date = datetime(y + 1, mo, d)
                except (ValueError, OverflowError):
                    pass

    set_time_from_text(text)

    try:
        if hour is not None:
            h = max(0, min(23, hour))
            m = max(0, min(59, minute))
            result_date = result_date.replace(hour=h, minute=m,
                                              second=0, microsecond=0)
        else:
            result_date = result_date.replace(hour=9, minute=0,
                                              second=0, microsecond=0)
    except (ValueError, OverflowError):
        result_date = datetime.now().replace(hour=9, minute=0,
                                             second=0, microsecond=0)

    return result_date


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


WEEK_KEYS = ['本周', '这周', '本星期', '这个星期']
NEXT_WEEK_KEYS = ['下周', '下星期']


def _parse_time(text):
    """Extract (hour, minute) from a time expression in text. Returns None if no match."""
    m = re.search(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text)
    if m:
        period = m.group(1)
        h = int(m.group(2))
        minute = int(m.group(3)) if m.group(3) else 0
        if period and period in ('下午', '晚上'):
            h = h if h >= 12 else h + 12
        elif period and period == '上午':
            h = h if h < 12 else h - 12
        elif h < 7:
            h += 12
        return (h, minute)
    cm = re.search(r'(\d{1,2}):(\d{2})', text)
    if cm:
        h, m = int(cm.group(1)), int(cm.group(2))
        if h < 24 and m < 60:
            return (h, m)
    return None


def _find_all_datetime_candidates(text):
    """Find all (datetime, date_text) candidates from time expressions in text.
    Returns list sorted by datetime ascending."""
    now = datetime.now()
    candidates = []

    # find all date references and their positions
    date_refs = []

    # 明天/后天/今天
    for rel, delta in [('今天', 0), ('今[天日]', 0), ('明天', 1), ('明[天日]', 1), ('后天', 2), ('后[天日]', 2)]:
        for m in re.finditer(rel, text):
            date_refs.append((m.start(), 'relative', delta))

    # X月X日
    for m in re.finditer(r'(\d+)月(\d+)日', text):
        try:
            mo, d = int(m.group(1)), int(m.group(2))
            date_refs.append((m.start(), 'date', (mo, d)))
        except Exception:
            pass

    # 本周/下周
    if re.search(r'本(?:周|星期)|这(?:周|星期)', text):
        next_weekday = now + timedelta(days=(6 - now.weekday()))
        # generate candidates for each time in the remaining text
        for tm in re.finditer(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text):
            t = _parse_time(tm.group())
            if t:
                dt = next_weekday.replace(hour=t[0], minute=t[1], second=0)
                if dt < now:
                    dt += timedelta(weeks=1)
                candidates.append(dt)

    if re.search(r'下(?:周|星期)', text):
        next_weekday = now + timedelta(days=(13 - now.weekday()))
        for tm in re.finditer(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text):
            t = _parse_time(tm.group())
            if t:
                dt = next_weekday.replace(hour=t[0], minute=t[1], second=0)
                if dt < now:
                    dt += timedelta(weeks=1)
                candidates.append(dt)

    # find all time expressions with their positions
    time_exprs = []
    for m in re.finditer(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text):
        t = _parse_time(m.group())
        if t:
            time_exprs.append((m.start(), t))
    for m in re.finditer(r'(\d{1,2}):(\d{2})', text):
        t = _parse_time(m.group())
        if t:
            time_exprs.append((m.start(), t))

    if not time_exprs:
        return candidates

    # for each date ref, pair with each time expression that comes after it (or all if no clear split)
    # if there's a "到" keyword, split text into before/after
    split_pos = None
    for kw in ['到', '截止', '至', '—', '~']:
        pos = text.find(kw)
        if pos >= 0:
            split_pos = pos
            break

    for date_pos, date_type, date_val in date_refs:
        # determine which times pair with this date
        for time_pos, (h, m) in time_exprs:
            if date_pos < time_pos:
                if date_type == 'relative':
                    dt = (now + timedelta(days=date_val)).replace(hour=h, minute=m, second=0)
                else:
                    mo, d = date_val
                    y = now.year
                    dt = datetime(y, mo, d, h, m, 0)
                    if dt < now:
                        dt = dt.replace(year=y + 1)
                if dt > now:
                    candidates.append(dt)

    # also generate candidates from time expressions alone (no date) paired with today
    for _, (h, m) in time_exprs:
        dt = now.replace(hour=h, minute=m, second=0)
        if dt <= now:
            dt = now.replace(hour=h, minute=m, second=0) + timedelta(days=1)
        candidates.append(dt)

    return sorted(set(candidates))


def detect_deadline_from_text(text):
    now = datetime.now()

    # find time that appears AFTER deadline keywords (到/截止/至/-)
    end_text = text
    for kw in ['到', '截止', '至', '—', '~']:
        idx = text.find(kw)
        if idx >= 0:
            after = text[idx+1:]
            if after.strip():
                end_text = after
                break

    hour, minute = 18, 0
    time_m = re.search(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', end_text)
    if time_m:
        period = time_m.group(1)
        h = int(time_m.group(2))
        m = int(time_m.group(3)) if time_m.group(3) else 0
        if period and period in ('下午', '晚上'):
            h = h if h >= 12 else h + 12
        elif period and period == '上午':
            h = h if h < 12 else h - 12
        elif h < 7:
            h += 12
        hour, minute = h, m
    else:
        colon_m = re.search(r'(\d{1,2}):(\d{2})', end_text)
        if colon_m:
            h, m = int(colon_m.group(1)), int(colon_m.group(2))
            if h < 24 and m < 60:
                hour, minute = h, m

    if re.search(r'本(?:周|星期)|这(?:周|星期)', text):
        end_of_week = now + timedelta(days=(6 - now.weekday()))
        return (end_of_week.replace(hour=hour, minute=minute, second=0), hour, minute)

    if re.search(r'下(?:周|星期)', text):
        end_of_next = now + timedelta(days=(13 - now.weekday()))
        return (end_of_next.replace(hour=hour, minute=minute, second=0), hour, minute)

    m = re.search(r'(\d+)月(\d+)日', end_text)
    if m:
        try:
            mo, d = int(m.group(1)), int(m.group(2))
            y = now.year
            dt = datetime(y, mo, d, hour, minute, 0)
            if dt < now:
                dt = dt.replace(year=y + 1)
            return (dt, hour, minute)
        except Exception:
            pass

    m = re.search(r'(\d{4})[年-](\d{1,2})[月-](\d{1,2})', text)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return (datetime(y, mo, d, hour, minute, 0), hour, minute)
        except Exception:
            pass

    # no date found, but return the extracted time for downstream use
    return (None, hour, minute)


def extract_assignees_from_text(text):
    result = {'assignees': [], 'is_all': False}

    if any(kw in text for kw in ['@所有人', '@all', '@All', '@ALL',
                                  '全员', '所有人', '全部人']):
        result['is_all'] = True
        return result

    at_mentions = re.findall(r'@([\w\u4e00-\u9fff]+)', text)
    if at_mentions:
        result['assignees'] = [n for n in at_mentions if n not in ['所有人', 'all', 'All', 'ALL']]

    assignee_match = re.search(
        r'(?:发给|分配给|给|指派给)[：:]?\s*'
        r'([\w\u4e00-\u9fff]+(?:[、,，\s]+[\w\u4e00-\u9fff]+)*)',
        text
    )
    if assignee_match:
        names = [n.strip() for n in re.split(r'[、,，\s]+', assignee_match.group(1)) if n.strip()]
        result['assignees'] = [n for n in names if n not in ['全员', '所有人', '全部人']]

    return result


TITLE_BLOCK_WORDS = ['反馈', '链接', '腾讯文档', 'https', 'http',
                      '通知', '请各位', '请各处室', '请提醒',
                      '请传达到位', '请确认', '请各部门', '请各单位']

TITLE_CLEAN_PREFIX = re.compile(r'^请[各全].{1,10}[，,。]')

def extract_title_from_text(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        lines = [text]

    QUOTE_CHARS = '\u201c\u201d\u300c\u300d"'
    QUOTE_PAT = re.compile(r'[' + QUOTE_CHARS + r']([^' + QUOTE_CHARS + r']{4,60})[' + QUOTE_CHARS + r']')

    # 优先取【】中的名称,如【分中心项目委会议时间】→ 分中心项目委会议时间
    for line in lines:
        m = re.search(r'【([^】]{2,60})】', line)
        if m:
            name = m.group(1).strip()
            if name and not any(kw in name for kw in TITLE_BLOCK_WORDS):
                return name[:80]

    considered = []
    for line in lines:
        clean = re.sub(r'https?://\S+', '', line).strip()
        clean = re.sub(r'【[^】]*】', '', clean).strip()
        clean = re.sub(r'@所有人|@all|@All|@all', '', clean).strip()
        clean = re.sub(r'[：:].*$', '', clean).strip()
        if clean:
            considered.append(clean)

    for c in considered:
        quoted = QUOTE_PAT.findall(c)
        for q in quoted:
            if not any(kw in q for kw in TITLE_BLOCK_WORDS):
                return q[:80]

    for c in considered:
        for sep in ['。', '！', '，', ',', '；', ';', '——', '—', '\n']:
            if sep in c:
                parts = [p.strip() for p in c.split(sep) if p.strip()]
                for part in parts:
                    part_clean = re.sub(r'https?://\S+', '', part).strip()
                    part_clean = re.sub(r'【[^】]*】', '', part_clean).strip()
                    part_clean = re.sub(r'@\S+', '', part_clean).strip()
                    part_clean = re.sub(r'[「」""]', '', part_clean).strip()
                    part_clean = TITLE_CLEAN_PREFIX.sub('', part_clean).strip()
                    if 4 <= len(part_clean) <= 60 and \
                       not any(kw in part_clean for kw in TITLE_BLOCK_WORDS):
                        return part_clean[:80]

    for c in considered:
        cleaned = re.sub(r'(从|到|截止|提交|发给|给|指派给|分配[给到]|完成[于截至]).*', '', c).strip()
        cleaned = re.sub(r'[，,。！？\s]{2,}', '', cleaned).strip()
        cleaned = TITLE_CLEAN_PREFIX.sub('', cleaned).strip()
        if 4 <= len(cleaned) <= 60 and \
           not any(kw in cleaned for kw in TITLE_BLOCK_WORDS):
            return cleaned[:80]

    for c in considered:
        cleaned = TITLE_CLEAN_PREFIX.sub('', c).strip()
        if len(cleaned) >= 5 and not any(kw in cleaned for kw in TITLE_BLOCK_WORDS):
            return cleaned[:80]

    for c in considered:
        if len(c) >= 5 and not any(kw in c for kw in TITLE_BLOCK_WORDS):
            return c[:80]

    for c in considered:
        if c and len(c) >= 3 and not any(kw in c for kw in TITLE_BLOCK_WORDS):
            return c[:80]

    return '未命名待办'


def parse_task_from_text(text):
    now = datetime.now()

    result = {
        'title': extract_title_from_text(text),
        'description': text,
        'category': '工作',
        'start_time': now,
        'end_time': None,
        'assignees': [],
        'is_all': False
    }

    # auto-detect category
    category_keywords = {
        '考试': ['考试', '测验', '笔试', '月考', '中考', '高考', '期中考', '期末考', '考级', '考核', '答辩'],
        '培训': ['培训', '训练', '课程', '集训', '学习班', '研修班', '岗前培训', '入职培训', '技能提升', '培训会'],
        '会议': ['会议', '开会', '例会', '晨会', '周会', '月会', '评审会', '研讨会', '复盘', '站会'],
        '工作': ['工作', '项目', '待办', '报告', '汇报', '方案', '开发', '测试', '上线', '需求', '周报', '月报'],
        '个人': ['个人', '学习', '读书', '运动', '健身', '购物', '家务', '休息', '娱乐', '游戏', '电影', '旅游'],
    }
    for cat, keywords in category_keywords.items():
        if any(kw in text for kw in keywords):
            result['category'] = cat
            break

    assign_info = extract_assignees_from_text(text)
    result['assignees'] = assign_info['assignees']
    result['is_all'] = assign_info['is_all']

    # start_time is always now
    result['start_time'] = now

    # end_time: find all datetime candidates, pick the farthest future one
    candidates = _find_all_datetime_candidates(text)
    if candidates:
        best = candidates[-1]
    else:
        # fallback to detect_deadline_from_text
        deadline_dt, dl_hour, dl_minute = detect_deadline_from_text(text)
        if deadline_dt:
            best = deadline_dt
        else:
            m = re.search(r'(\d+)([天周])', text)
            if m:
                num = int(m.group(1))
                unit = m.group(2)
                if unit == '天':
                    best = now + timedelta(days=num)
                elif unit == '周':
                    best = now + timedelta(weeks=num)
            else:
                best = (now + timedelta(days=7)).replace(hour=18, minute=0, second=0)

    result['end_time'] = best

    # detect recurring pattern
    result['recurrence'] = None
    result['recurrence_text'] = ''
    result['recurrence_count'] = 0
    result['recurrence_interval_days'] = 0
    rec_text = text.replace('两', '2')
    rec_m = re.search(r'每(\d*)(周|个?月|年)', rec_text)
    if rec_m:
        num_str = rec_m.group(1)
        unit = rec_m.group(2)
        num = int(num_str) if num_str else 1
        if unit == '周':
            result['recurrence'] = 'weekly'
            result['recurrence_interval_days'] = num * 7
            result['recurrence_count'] = 4
            result['recurrence_text'] = f'每{num}周' if num > 1 else '每周'
        elif '月' in unit:
            result['recurrence'] = 'monthly'
            result['recurrence_interval_days'] = num * 30
            result['recurrence_count'] = 3
            result['recurrence_text'] = f'每{num}个月' if num > 1 else '每月'
        elif '年' in unit:
            result['recurrence'] = 'yearly'
            result['recurrence_interval_days'] = num * 365
            result['recurrence_count'] = 2
            result['recurrence_text'] = f'每{num}年' if num > 1 else '每年'

    return result






















# ---- 路由模块加载(自单文件拆分, 保持 endpoint 名称不变) ----
# 各模块内函数体引用的 app 级名称(模型/辅助函数/数据库会话/工具等)
# 在下方统一注入到模块命名空间; 模块顶部只需显式导入装饰器名称。
import routes_auth
import routes_admin
import routes_tasks
import routes_search
import routes_notify

for _routes_module in (routes_auth, routes_admin, routes_tasks,
                       routes_search, routes_notify):
    _routes_module.__dict__.update(globals())
