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

import re
import hmac
import secrets
import sys
import logging
import contextlib
from datetime import datetime, timedelta, date, timezone


def cn_now():
    """当前北京时间(naive), 全项目统一时间源(与服务器时区无关)。"""
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


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

# 加载 .env(与 docker-compose 的 env 插值互补): 仅在变量未由外部环境设置时写入,
# 支持简单的 KEY=VALUE、引号与 # 注释; 由 entrypoint/gunicorn 直启时也会生效。
_DOTENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '.env')
if os.path.isfile(_DOTENV_PATH):
    try:
        with open(_DOTENV_PATH, 'r', encoding='utf-8') as _envf:
            for _line in _envf:
                _line = _line.strip()
                if not _line or _line.startswith('#'):
                    continue
                if '=' not in _line:
                    continue
                _key, _val = _line.split('=', 1)
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val
    except Exception as _e:
        logging.getLogger(__name__).warning('load .env failed: %s', _e)

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
# 登录会话最长 4 小时(配合登录时 session.permanent = True 生效),
# 超过则自动退出登录;所有登录会话共享该有效期。
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=5)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
# HTTPS 部署时设环境变量 COOKIE_SECURE=1: 会话 Cookie 仅经加密连接传输
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE') == '1'
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

# 授权校验(演示版本控制): 环境变量 born 必须等于 base64("MAIL_PASSWORD="+MAIL_USERNAME)
# 才允许业务数据写入; 否则视为演示版本, 拦截业务写入并提示授权升级。
# 登录/注册/解锁等认证相关写入放行, 避免管理员无法登录授权。
import base64 as _b64
_LICENSE_MSG = '当前为演示版本，请授权升级。'
_LICENSE_AUTH_PREFIXES = ('/login', '/register', '/logout', '/static/',
                          '/api/token')
# 统一检索/知识库问答等无业务写入的查询接口放行
_LICENSE_READ_PATHS = (
    '/api/unified-search', '/api/unified-search/history',
    '/api/quick-task/preview',
)


def is_licensed():
    """正式版判定: born 环境变量非空 且 === base64('MAIL_PASSWORD='+MAIL_USERNAME)。"""
    expected = _b64.b64encode(
        ('MAIL_PASSWORD=' + app.config.get('MAIL_USERNAME', '')).encode('utf-8')
    ).decode('ascii')
    return bool(os.environ.get('born')) and os.environ.get('born') == expected


# 体验客户账号(只读): role='guest', 登录后仅能查看, 禁止任何写操作
_GUEST_MSG = '体验客户账号仅可查看，不能修改或添加数据。'
_GUEST_ALLOW_PATHS = ('/login', '/logout', '/static/')


def _guest_before_request():
    """体验客户只读拦截: role='guest' 用户禁止所有写方法(POST/PUT/PATCH/DELETE),
    仅放行登录/退出等认证操作。"""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    if not (current_user.is_authenticated
            and getattr(current_user, 'role', '') == 'guest'):
        return
    path = request.path
    if path.startswith(_GUEST_ALLOW_PATHS):
        return
    if path in _LICENSE_READ_PATHS:
        return
    if path.startswith(('/api/', '/notes/api/', '/kb/api/')):
        return jsonify({'ok': False, 'error': _GUEST_MSG}), 403
    return render_template('error.html', code=403, message=_GUEST_MSG), 403


def _license_before_request():
    """演示版本拦截业务写入: 非安全方法(POST/PUT/PATCH/DELETE)中,
    认证相关与纯读取接口放行, 其余业务写入在未授权时拦截。"""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    if is_licensed():
        return
    path = request.path
    if path.startswith(_LICENSE_AUTH_PREFIXES):
        return
    if path in _LICENSE_READ_PATHS or path.startswith(('/kb/api/search',
                                                       '/kb/api/ask')):
        return
    if path.startswith(('/api/', '/notes/api/', '/kb/api/')):
        return jsonify({'ok': False, 'error': _LICENSE_MSG}), 403
    return render_template('error.html', code=403, message=_LICENSE_MSG), 403


os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.unauthorized_handler
def _unauthorized_log():
    """未登录访问受保护页面时记录一条操作日志, 再跳转登录页。"""
    try:
        if not request.path.startswith('/static/'):
            log_operation(
                'unauth_access',
                target=(request.path or '')[:200],
                detail=f'未登录访问 {request.method} {request.path}')
    except Exception:
        pass
    return redirect(url_for('login', next=request.path or None))


@app.before_request
def _req_timing_start():
    g._req_start = time.monotonic()


app.before_request(_license_before_request)
app.before_request(_guest_before_request)


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

_GZIP_TYPES = ('text/html', 'text/css', 'text/javascript',
               'application/javascript', 'application/json', 'image/svg+xml')
_COMPRESS_MIN_SIZE = 500


@app.after_request
def _gzip_response(resp):
    """轻量 gzip 压缩(无 nginx 前置时降低 HTML/JS/JSON 传输体积约 70%)。

    跳过: 客户端不支持、已压缩(Content-Encoding 存在)、流式响应、小响应。
    """
    if (resp.status_code < 200 or resp.status_code >= 300
            or resp.headers.get('Content-Encoding')
            or 'gzip' not in (request.headers.get('Accept-Encoding') or '')):
        return resp
    ctype = (resp.mimetype or '').split(';')[0].strip()
    if ctype not in _GZIP_TYPES:
        return resp
    if resp.direct_passthrough:
        # send_file 流式直通(静态资源): 关闭后读取内容统一压缩
        resp.direct_passthrough = False
    data = resp.get_data()
    if len(data) < _COMPRESS_MIN_SIZE:
        return resp
    import gzip as _gzip_mod
    resp.set_data(_gzip_mod.compress(data, compresslevel=6))
    resp.headers['Content-Encoding'] = 'gzip'
    resp.headers['Content-Length'] = str(len(resp.get_data()))
    return resp


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
    表单 token 由 base.html 的 JS 自动注入, AJAX 由全局 fetch 包装注入。
    /api/token 令牌获取接口与 API 令牌鉴权请求(Bearer)跳过 CSRF。"""
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if request.path == '/api/token' or _api_token_user() is not None:
            return
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

from pet import init_models as pet_init_models, pet_bp
pet_init_models(db)
app.register_blueprint(pet_bp)


@app.route('/sw.js')
def service_worker_js():
    """根路径提供 SW(保证默认 scope=/ 覆盖页面), 仅做静态资源缓存。"""
    resp = send_from_directory(app.static_folder, 'sw.js')
    resp.headers['Content-Type'] = 'application/javascript'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/pet')
@login_required
def pet_page():
    """电子宠物独立页面(双击导航栏 logo 打开)。"""
    return render_template('pet.html')


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
        return {'now': cn_now, 'today_str': cn_now().strftime(
            '%Y年%m月%d日 %A'), 'timedelta': timedelta,
                'VERSION': VERSION,
                'staticv': _static_mtime_version,
                'unread_notifications': unread_count,
                'recent_notifications': recent}
    return {'now': cn_now, 'today_str': cn_now().strftime(
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


# 定时任务默认配置
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
    from notes import Note
    if Note is None:
        return 0
    return Note.query.filter_by(user_id=current_user.id).count()


def _count_kb():
    """统计当前用户上传的知识库文档数(含全部状态)。"""
    from knowledge import KbDocument
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
        if 'api_token' not in cols:
            c.execute("ALTER TABLE user ADD COLUMN api_token VARCHAR(64) DEFAULT ''")
        if 'api_token_created_at' not in cols:
            c.execute('ALTER TABLE user ADD COLUMN api_token_created_at DATETIME')
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
        c.execute('PRAGMA table_info(pet)')
        cols = [r[1] for r in c.fetchall()]
        if cols:
            if 'level' not in cols:
                c.execute('ALTER TABLE pet ADD COLUMN level INTEGER DEFAULT 1')
            if 'exp' not in cols:
                c.execute('ALTER TABLE pet ADD COLUMN exp INTEGER DEFAULT 0')
            if 'stars' not in cols:
                c.execute('ALTER TABLE pet ADD COLUMN stars INTEGER DEFAULT 0')
            if 'equipped_house' not in cols:
                c.execute("ALTER TABLE pet ADD COLUMN equipped_house VARCHAR(40) DEFAULT 'none'")
            if 'equipped_bowl' not in cols:
                c.execute("ALTER TABLE pet ADD COLUMN equipped_bowl VARCHAR(40) DEFAULT 'none'")
            if 'equipped_clothes' not in cols:
                c.execute("ALTER TABLE pet ADD COLUMN equipped_clothes VARCHAR(40) DEFAULT 'none'")
            if 'last_feed_at' not in cols:
                c.execute('ALTER TABLE pet ADD COLUMN last_feed_at DATETIME')
            if 'last_sleep_at' not in cols:
                c.execute('ALTER TABLE pet ADD COLUMN last_sleep_at DATETIME')
            if 'last_clean_at' not in cols:
                c.execute('ALTER TABLE pet ADD COLUMN last_clean_at DATETIME')
        c.execute('PRAGMA table_info(pet_record)')
        cols = [r[1] for r in c.fetchall()]
        if cols and 'stars' not in cols:
            c.execute('ALTER TABLE pet_record ADD COLUMN stars INTEGER DEFAULT 0')
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
                'CREATE INDEX IF NOT EXISTS ix_assignment_user_completed ON task_assignment (user_id, completed_at)',
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
                "ALTER TABLE kb_document ADD COLUMN visibility TEXT DEFAULT 'private'",
            ]:
                c.execute(sql)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'Migration note: {e}')


# 旧数据由 datetime.utcnow(UTC) 写入, 统一迁移为北京时间(+8h)。
# 幂等: 以 sys_setting 键做一次性标记, 重复启动不会二次偏移。
_TZ_MIGRATE_TABLES = [
    ('user', ('created_at', 'api_token_created_at')),
    ('task', ('created_at',)),
    ('email_log', ('sent_at',)),
    ('email_record', ('created_at',)),
    ('group', ('created_at',)),
    ('notification', ('created_at',)),
    ('operation_log', ('created_at',)),
    ('note', ('created_at', 'updated_at')),
    ('thread', ('created_at',)),
    ('note_job', ('created_at', 'started_at', 'finished_at')),
    ('kb_collection', ('created_at',)),
    ('kb_document', ('created_at', 'updated_at')),
    ('kb_point', ('created_at',)),
    ('kb_point_rel', ('created_at',)),
    ('kb_point_ref', ('created_at',)),
]


def _migrate_utc_to_cn_time():
    """历史 UTC 时间戳一次性 +8h 迁移(跳过 locked_until 等短时效字段)。
    BEGIN IMMEDIATE 串行化多 worker 并发, 幂等键防止二次偏移。"""
    try:
        conn = db.engine.raw_connection()
        try:
            cur = conn.cursor()
            cur.execute('BEGIN IMMEDIATE')
            cur.execute(
                "SELECT value FROM sys_setting WHERE key='tz_migrated_v1'")
            if cur.fetchone():
                conn.rollback()
                return
            for table, cols in _TZ_MIGRATE_TABLES:
                for col in cols:
                    try:
                        cur.execute(
                            f'UPDATE "{table}" SET {col} = '
                            f"datetime({col}, '+8 hours') "
                            f'WHERE {col} IS NOT NULL')
                    except Exception as e:
                        print(f'[tz-migrate] 跳过 {table}.{col}: {e}')
            cur.execute(
                "INSERT OR REPLACE INTO sys_setting(key,value) "
                "VALUES('tz_migrated_v1', ?)",
                (cn_now().strftime('%Y-%m-%d %H:%M:%S'),))
            conn.commit()
            print('[tz-migrate] 历史 UTC 时间已迁移为北京时间(+8h)')
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        print(f'[tz-migrate] 迁移失败(不影响启动): {e}')


def init_db():
    with db_init_lock():
        db.create_all()
        _run_sqlite_migrations()
        enable_sqlite_wal()
        _migrate_utc_to_cn_time()
        fresh = not User.query.filter_by(username='bright').first()
        if fresh:
            admin = User(username='bright', role='admin')
            admin.set_password('Bright@wangzhan')
            db.session.add(admin)
            db.session.commit()
        # 体验客户只读账号: 始终保证存在(role='guest', 仅可查看不可写)
        if not User.query.filter_by(username='guest').first():
            guest = User(username='guest', name='体验客户', role='guest')
            guest.set_password('guest123')
            db.session.add(guest)
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

    now = cn_now()
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
    now = cn_now()
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
        result_date = cn_now().replace(hour=9, minute=0,
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
    """Extract (hour, minute) from a time expression in text. Returns None if no match.

    冒号格式(X:XX)按 24 小时制处理, 不做上下午猜测;
    「点/时」格式识别 上午/早上/早晨/凌晨/下午/晚上。
    """
    m = re.search(r'(上[午]|下[午]|晚[上]|早[上晨]|凌[晨])?\s*(\d{1,2})\s*[：:]\s*(\d{1,2})', text)
    if m:
        h = int(m.group(2))
        mi = int(m.group(3))
        if h < 24 and mi < 60:
            return (h, mi)
    m = re.search(r'(上[午]|下[午]|晚[上]|早[上晨]|凌[晨])?(\d{1,2})[点时](半|\d{1,2})?分?(?:钟)?', text)
    if m:
        period = m.group(1)
        h = int(m.group(2))
        minute = 30 if m.group(3) == '半' else int(m.group(3) or 0)
        if period in ('下午', '晚上'):
            h = h if h >= 12 else h + 12
        elif period in ('上午', '早上', '早晨', '凌晨'):
            h = 0 if h == 12 else h
        elif not period and h < 7:
            h += 12
        return (h % 24, min(59, max(0, minute)))
    cm = re.search(r'(\d{1,2}):(\d{2})', text)
    if cm:
        h, mm = int(cm.group(1)), int(cm.group(2))
        if h < 24 and mm < 60:
            return (h, mm)
    return None


def _find_all_datetime_candidates(text):
    """Find all (datetime, date_text) candidates from time expressions in text.
    Returns list sorted by datetime ascending."""
    now = cn_now()
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
    now = cn_now()

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


_JIO = None
_AUTOPIP_STATE = {'started': False}


def _pip_install_cmd():
    """构造 pip 安装命令; KB_PIP_MIRROR 指定镜像源(默认清华, 设空串禁用)。"""
    cmd = [sys.executable, '-m', 'pip', 'install',
           '--no-cache-dir', '--quiet']
    mirror = os.environ.get('KB_PIP_MIRROR')
    if mirror is None:
        mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    if mirror:
        cmd += ['-i', mirror, '--trusted-host', 'pypi.tuna.tsinghua.edu.cn']
    return cmd + ['jionlp>=1.5.29']


def _try_install_jionlp(timeout_s):
    """同步安装 jionlp(供懒加载与后台预装共用); 成功返回 True。"""
    import subprocess
    log = logging.getLogger(__name__)
    log.warning('jionlp 未安装, 尝试自动 pip 安装(超时 %ss)...', timeout_s)
    try:
        subprocess.run(_pip_install_cmd(), timeout=timeout_s, check=False)
    except Exception as e:
        log.warning('jionlp 自动安装失败(%s), 时间字段回退旧正则解析; '
                    '建议重建镜像内置依赖或配置 KB_PIP_MIRROR', e)
        return False
    import io as _io
    import contextlib as _cl
    buf = _io.StringIO()
    try:
        with _cl.redirect_stdout(buf):
            import jionlp as jio_mod
        if jio_mod:
            log.warning('jionlp 自动安装完成, 时间语义解析已启用')
            return True
    except Exception:
        pass
    return False


def _get_jionlp():
    """懒加载 jionlp(未安装时尝试自动 pip 安装一次; 失败返回 None 走旧正则)。

    KB_AUTOPIP=0 关闭自动安装; KB_TIME_PARSER=legacy 整体回退(见调用方);
    KB_AUTOPIP_TIMEOUT 秒数(默认600)。
    """
    global _JIO
    if _JIO is None:
        jio_mod = None
        try:
            import io as _io
            import contextlib as _cl
            b = _io.StringIO()
            with _cl.redirect_stdout(b):
                import jionlp as jio_mod
        except Exception:
            jio_mod = None
        if jio_mod is None and os.environ.get('KB_AUTOPIP', '1') != '0':
            try:
                timeout_s = float(os.environ.get(
                    'KB_AUTOPIP_TIMEOUT', '600') or 600)
            except ValueError:
                timeout_s = 600.0
            if _try_install_jionlp(timeout_s):
                try:
                    import io as _io
                    import contextlib as _cl
                    with _cl.redirect_stdout(_io.StringIO()):
                        import jionlp as jio_mod
                except Exception:
                    jio_mod = None
        _JIO = jio_mod if jio_mod else False
    return _JIO or None


def ensure_jionlp_async():
    """启动后台守护线程预装 jionlp, 避免首次解析被安装阻塞。"""
    if _AUTOPIP_STATE['started']:
        return
    if os.environ.get('KB_AUTOPIP', '1') == '0' \
            or os.environ.get('KB_TIME_PARSER') == 'legacy':
        return
    import threading

    def _bg():
        try:
            import io as _io
            import contextlib as _cl
            with _cl.redirect_stdout(_io.StringIO()):
                import jionlp  # noqa: F401
            return  # 已安装, 无需处理
        except Exception:
            pass
        try:
            timeout_s = float(os.environ.get(
                'KB_AUTOPIP_TIMEOUT', '600') or 600)
        except ValueError:
            timeout_s = 600.0
        if _try_install_jionlp(timeout_s):
            global _JIO
            _JIO = None  # 重置缓存, 下次 _get_jionlp 重新导入
    _AUTOPIP_STATE['started'] = True
    threading.Thread(target=_bg, daemon=True,
                     name='jionlp-autopip').start()


def _parse_timespan_jionlp(text):
    """基于 JioNLP 的时间解析(KB_TIME_PARSER=legacy 回退旧正则)。

    返回 {'start': datetime|None, 'end': datetime|None}; 无有效时间返回 None。
    策略: 显式区间(X-Y点)给出 start+end; 截止式(...前/截止)给 end;
    其余取最远未来为 end。标题【】内与纯年份实体视为噪声剔除。
    """
    if os.environ.get('KB_TIME_PARSER') == 'legacy':
        return None
    jio = _get_jionlp()
    if not jio:
        return None
    try:
        ents = jio.ner.extract_time(text)
    except Exception:
        return None

    def _dt(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return None

    now = cn_now()
    cands = []
    for ent in ents or []:
        txt = (ent.get('text') or '').strip()
        off = ent.get('offset') or [0, 0]
        if not txt or re.fullmatch(r'\d{4}年?', txt):
            continue
        seg = text[max(0, off[0] - 80):off[0]]
        if '【' in seg and '】' not in seg.split('【')[-1]:
            continue
        d = ent.get('detail') or {}
        t = d.get('time')
        s = _dt(t[0]) if isinstance(t, list) and t else None
        e = _dt(t[1]) if isinstance(t, list) and len(t) > 1 else None
        if not s:
            continue
        has_tod = bool(re.search(r'\d{1,2}[点时：:]', txt))
        kind = ('range' if re.search(r'\d{1,2}[：:]\d{2}\s*[-—~至]\s*\d{1,2}[：:]\d{2}', txt)
                else ('deadline' if re.search(r'前$|之前|截止', txt) else 'point'))
        if e and e.second == 59:
            e = e.replace(second=0)
        if s.second == 59:
            s = s.replace(second=0)
        if not has_tod and kind == 'point':
            s = s.replace(hour=9, minute=0)
            if e:
                e = e.replace(hour=17, minute=0)
        cands.append({'txt': txt, 's': s, 'e': e, 'kind': kind})
    if not cands:
        return None
    out = {'start': None, 'end': None}
    rngs = [c for c in cands if c['kind'] == 'range']
    dls = [c for c in cands if c['kind'] == 'deadline']
    if rngs:
        r0 = min(rngs, key=lambda c: c['s'])
        out['start'] = r0['s']
        out['end'] = max((c['e'] or c['s']) for c in rngs)
    elif dls:
        out['end'] = max((c['e'] or c['s']) for c in dls)
        pts = [c for c in cands if c['kind'] == 'point']
        fpts = [c for c in pts if c['s'] > now]
        if fpts and min(c['s'] for c in fpts) < out['end']:
            out['start'] = min(c['s'] for c in fpts)
    else:
        out['end'] = max((c['e'] or c['s']) for c in cands)
        fs = [c['s'] for c in cands if c['s'] > now]
        if fs:
            out['start'] = min(fs)
    if out['end'] and out['end'] < now:
        out['end'] = None
    return out if (out['start'] or out['end']) else None


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

    # 优先取第一个【】中的内容,如【分中心项目委会议时间】→ 分中心项目委会议时间
    for line in lines:
        m = re.search(r'【([^】]+)】', line)
        if m:
            name = m.group(1).strip()
            if name:
                return name[:80]

    considered = []
    for line in lines:
        clean = re.sub(r'https?://\S+', '', line).strip()
        clean = re.sub(r'【[^】]*】', '', clean).strip()
        clean = re.sub(r'@所有人|@all|@All|@all', '', clean).strip()
        if clean:
            considered.append(clean)

    # 「动词:内容」结构优先取冒号后内容(如 提醒:明天交周报 → 明天交周报)
    for c in considered:
        m2c = re.search(r'^[^【】\n]{1,10}[：:]\s*(.+)$', c)
        if m2c:
            tail = m2c.group(1).strip()
            tail = re.sub(r'@\S+', '', tail).strip()
            if 4 <= len(tail) <= 60 and \
               not any(kw in tail for kw in TITLE_BLOCK_WORDS):
                return tail[:80]

    considered = [re.sub(r'[：:].*$', '', c).strip() or c for c in considered]

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
    now = cn_now()

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
    # 分类: 关键词命中计数投票(平票按定义顺序优先), 替代首中即停
    cat_scores = {}
    for cat, keywords in category_keywords.items():
        sc = sum(1 for kw in keywords if kw in text)
        if sc:
            cat_scores[cat] = sc
    if cat_scores:
        result['category'] = max(cat_scores.items(), key=lambda x: x[1])[0]

    assign_info = extract_assignees_from_text(text)
    result['assignees'] = assign_info['assignees']
    result['is_all'] = assign_info['is_all']
    # 人名校验: 仅保留系统中真实存在的姓名/用户名, 滤除「交给领导审批」类误抓
    try:
        _valid = set()
        for u in User.query.all():
            if u.name:
                _valid.add(u.name)
            if u.username:
                _valid.add(u.username)
    except Exception:
        _valid = set()
    if _valid and result['assignees']:
        result['assignees'] = [n for n in result['assignees'] if n in _valid]

    # 时间: 优先 JioNLP 语义解析(可给出未来开始时间); 失败回退旧候选链
    span = _parse_timespan_jionlp(text)
    parse_task_from_text._last_time_parser = 'jionlp' if span else 'legacy'
    best = None
    if span:
        if span.get('end'):
            best = span['end']
        if span.get('start') and span['start'] > now:
            result['start_time'] = span['start']

    # end_time: JioNLP 未命中时回退旧候选链
    if best is None:
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
    # 每天/每日/天天
    if re.search(r'每[天日]|天天', text):
        result['recurrence'] = 'daily'
        result['recurrence_interval_days'] = 1
        result['recurrence_count'] = 10
        result['recurrence_text'] = '每天'
    else:
        # 每周X: 区间7天, 起点由时间解析落在对应星期
        wm = re.search(r'每(?:周|星期)([一二三四五六日天])', rec_text)
        if wm:
            result['recurrence'] = 'weekly'
            result['recurrence_interval_days'] = 7
            result['recurrence_count'] = 4
            result['recurrence_text'] = '每周' + wm.group(1)
        else:
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

# ---- 启动即执行一次性 UTC→北京时间历史数据迁移(幂等, 多 worker 安全) ----
with app.app_context():
    _migrate_utc_to_cn_time()

# 后台预装 jionlp(容器缺依赖时不阻塞首次解析; 已装则立即返回)
try:
    ensure_jionlp_async()
except Exception:
    pass
