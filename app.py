import re
import logging
import contextlib
from datetime import datetime, timedelta, date
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_from_directory)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         login_required, logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, case
import os

VERSION = 'v0.7.0'

logging.basicConfig(
    level=os.environ.get('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

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

from knowledge import init_models, enable_sqlite_wal, kb_bp, \
    _resolve_stored_path
init_models(db)
app.register_blueprint(kb_bp)

from notes import init_models as notes_init_models, notes_bp
notes_init_models(db)
app.register_blueprint(notes_bp)


@app.context_processor
def inject_globals():
    if current_user.is_authenticated:
        unread_count = Notification.query.filter_by(
            user_id=current_user.id, is_read=False).count()
        recent_notifications = Notification.query.filter_by(
            user_id=current_user.id).order_by(
            Notification.created_at.desc()).limit(10).all()
        return {'now': datetime.now, 'today_str': datetime.now().strftime(
            '%Y年%m月%d日 %A'), 'timedelta': timedelta,
                'VERSION': VERSION,
                'unread_notifications': unread_count,
                'recent_notifications': recent_notifications}
    return {'now': datetime.now, 'today_str': datetime.now().strftime(
        '%Y年%m月%d日 %A'), 'timedelta': timedelta, 'VERSION': VERSION}


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
    email = db.Column(db.String(120), default='', index=True)
    email_verified = db.Column(db.Boolean, default=False)
    pending_email = db.Column(db.String(120), default='')
    email_code = db.Column(db.String(6), default='')
    email_code_expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    category = db.Column(db.String(50), default='工作')
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    is_all = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True)
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


def client_ip():
    try:
        return request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or ''
    except Exception:
        return ''


def log_operation(action, target='', detail='', user=None):
    """记录一条用户操作日志。user 缺省取当前登录用户。"""
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
        db.session.commit()
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
    if u is not None and u.is_disabled:
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


def get_same_group_users(user):
    if user.role == 'admin':
        return User.query.filter(User.is_disabled == False, User.id != user.id).all()
    group_ids = [g.id for g in user.groups]
    if not group_ids:
        return []
    return User.query.filter(
        User.id != user.id,
        User.is_disabled == False,
        User.groups.any(Group.id.in_(group_ids))
    ).distinct().all()


def _count_notes():
    """统计当前用户的随手记条数(含自动整理生成的报告)。"""
    from notes import Note
    if Note is None:
        return 0
    return Note.query.count()


def _count_kb():
    """统计知识库文档总数(含全部状态)。"""
    from knowledge import KbDocument
    if KbDocument is None:
        return 0
    return KbDocument.query.count()


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
            'CREATE INDEX IF NOT EXISTS ix_task_assignment_user_status ON task_assignment (user_id, status)',
            'CREATE INDEX IF NOT EXISTS ix_task_assignment_task ON task_assignment (task_id)',
            'CREATE INDEX IF NOT EXISTS ix_task_assignment_user ON task_assignment (user_id)',
            'CREATE INDEX IF NOT EXISTS ix_notification_user_read ON notification (user_id, is_read)',
            'CREATE INDEX IF NOT EXISTS ix_notification_user ON notification (user_id)',
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
    guest = User(username='guest', name='体验用户', role='user')
    guest.set_password('guest123')
    db.session.add(guest)

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
    users.append(guest)
    db.session.flush()

    groups_data = [
        ('技术部', '技术开发团队', ['guest', 'zhangsan', 'wangwu', 'sunqi']),
        ('产品部', '产品设计团队', ['guest', 'lisi', 'zhaoliu']),
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
        {'title': '学习Python异步编程', 'category': '个人', 'assign': 'guest',
         'start': today_start, 'end': today_start + timedelta(days=5, hours=8)},
        {'title': '整理部门周报', 'category': '工作', 'assign': 'zhangsan',
         'start': today_start - timedelta(days=1), 'end': today_start + timedelta(hours=3)},
        {'title': '健身计划-每周3次跑步', 'category': '个人', 'assign': 'lisi',
         'start': today_start - timedelta(days=3), 'end': today_start + timedelta(days=20)},
        {'title': '阅读《系统设计面试》', 'category': '个人', 'assign': 'guest',
         'start': today_start, 'end': today_start + timedelta(days=14)},
        {'title': '开发登录模块', 'category': '工作', 'assign': 'wangwu',
         'start': today_start - timedelta(days=5), 'end': today_start - timedelta(days=1)},
        {'title': '生日聚会筹备', 'category': '个人', 'assign': 'zhaoliu',
         'start': today_start + timedelta(days=3), 'end': today_start + timedelta(days=4, hours=6)},
        {'title': '数据库备份脚本优化', 'category': '工作', 'assign': 'sunqi',
         'start': today_start - timedelta(days=1), 'end': today_start + timedelta(days=2)},
        {'title': '在线课程-数据结构', 'category': '个人', 'assign': 'guest',
         'start': today_start, 'end': today_start + timedelta(days=30)},
        {'title': '客户需求评审会议', 'category': '工作', 'assign': 'all',
         'start': today_start + timedelta(hours=2), 'end': today_start + timedelta(hours=4)},
        {'title': '周末短途旅行计划', 'category': '个人', 'assign': 'wangwu',
         'start': today_start + timedelta(days=4), 'end': today_start + timedelta(days=5, hours=12)},
        {'title': 'API接口文档编写', 'category': '工作', 'assign': 'zhangsan',
         'start': today_start - timedelta(days=4), 'end': today_start + timedelta(days=1)},
        {'title': '每月读书总结', 'category': '个人', 'assign': 'lisi',
         'start': today_start - timedelta(days=10), 'end': today_start - timedelta(days=3)},
        {'title': '服务器安全加固', 'category': '工作', 'assign': 'guest',
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
                    creator_id=guest.id, is_all=(td.get('assign') == 'all'))
        db.session.add(task)
        db.session.flush()
        if td.get('assign') == 'all':
            target_users = [guest] + users
        elif td.get('assign') == 'guest':
            target_users = [guest]
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
        {'title': '完成Q2项目汇报PPT', 'user': 'guest', 'progress': 60},
        {'title': '学习Python异步编程', 'user': 'guest', 'progress': 30},
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
    results = []
    query = Task.query
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


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('user_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if user.is_disabled:
                log_operation('login_fail', username, '账号已禁用')
                db.session.commit()
                flash('该账号已被禁用，请联系管理员', 'danger')
                return render_template('login.html')
            login_user(user)
            log_operation('login', username,
                          f'用户 {user.name or user.username} 登录成功')
            db.session.commit()
            flash('登录成功！', 'success')
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            return redirect(url_for('index'))
        log_operation('login_fail', username, '用户名或密码错误')
        db.session.commit()
        flash('用户名或密码错误！', 'danger')
    return render_template('login.html')


@app.route('/login-guest')
def login_guest():
    guest = User.query.filter_by(username='guest').first()
    if guest and not guest.is_disabled:
        login_user(guest)
        log_operation('login', 'guest', '体验账号登录')
        db.session.commit()
        flash('您已使用体验账号登录，数据仅供展示', 'info')
        return redirect(url_for('index'))
    if guest:
        log_operation('login_fail', 'guest', '体验账号已被禁用')
        db.session.commit()
        flash('体验账号已被禁用', 'danger')
    else:
        flash('体验账号不存在，请先创建', 'danger')
    return redirect(url_for('login'))


@app.route('/logout')
@login_required
def logout():
    log_operation('logout', current_user.username or '',
                  f'用户 {current_user.name or current_user.username} 退出登录')
    db.session.commit()
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))


@app.route('/profile', methods=['GET'])
@login_required
def profile():
    """个人信息页:展示账号信息与邮箱绑定状态。"""
    return render_template('profile.html')


@app.route('/profile/send-verify-code', methods=['POST'])
@login_required
def profile_send_verify_code():
    """发送邮箱绑定校验码。"""
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get('email'))
    if not email:
        return jsonify({'ok': False, 'error': '邮箱格式不正确,请检查后重试'})
    dup = User.query.filter(
        db.or_(User.email == email, User.pending_email == email),
        User.id != current_user.id).first()
    if dup:
        return jsonify({'ok': False, 'error': '该邮箱已被其他账号绑定'})
    ok, err, dev_code = send_verify_code(current_user, email)
    return jsonify({'ok': ok, 'error': err or '', 'dev_code': dev_code})


@app.route('/profile/verify-email', methods=['POST'])
@login_required
def profile_verify_email():
    """校验邮箱校验码并完成绑定。"""
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get('email'))
    code = (data.get('code') or '').strip()
    if not email:
        return jsonify({'ok': False, 'error': '邮箱格式不正确,请检查后重试'})
    if not code:
        return jsonify({'ok': False, 'error': '请输入校验码'})
    user = current_user
    if user.pending_email != email:
        return jsonify({'ok': False, 'error': '邮箱与发送校验码时不一致,请重新发送'})
    if user.email_code != code:
        return jsonify({'ok': False, 'error': '校验码不正确,请重新输入'})
    if not user.email_code_expires_at or user.email_code_expires_at < datetime.utcnow():
        return jsonify({'ok': False, 'error': '校验码已过期,请重新发送'})
    user.email = email
    user.email_verified = True
    user.pending_email = ''
    user.email_code = ''
    user.email_code_expires_at = None
    db.session.commit()
    log_operation('email_bind', email, f'用户 {user.name or user.username} 绑定邮箱')
    return jsonify({'ok': True})


@app.route('/profile/unbind-email', methods=['POST'])
@login_required
def profile_unbind_email():
    """解除邮箱绑定。"""
    user = current_user
    if not user.email:
        return jsonify({'ok': False, 'error': '当前未绑定邮箱'})
    email = user.email
    user.email = ''
    user.email_verified = False
    user.pending_email = ''
    user.email_code = ''
    user.email_code_expires_at = None
    db.session.commit()
    log_operation('email_unbind', email, f'用户 {user.name or user.username} 解除邮箱绑定')
    return jsonify({'ok': True})


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('需要管理员权限', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def get_completion_rate(task):
    total = task.assignments.count()
    if total == 0:
        return 0
    completed = task.assignments.filter_by(status='completed').count()
    return round(completed / total * 100, 1)


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



@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    stats = get_overall_stats()
    users = User.query.all()
    user_ids = [u.id for u in users]
    now = datetime.now()
    total_rows = dict(db.session.query(
        TaskAssignment.user_id, func.count(TaskAssignment.id)
    ).filter(TaskAssignment.user_id.in_(user_ids))
     .group_by(TaskAssignment.user_id).all())
    completed_rows = dict(db.session.query(
        TaskAssignment.user_id, func.count(TaskAssignment.id)
    ).filter(TaskAssignment.user_id.in_(user_ids),
             TaskAssignment.status == 'completed')
     .group_by(TaskAssignment.user_id).all())
    urgent_rows = dict(db.session.query(
        TaskAssignment.user_id, func.count(TaskAssignment.id)
    ).join(Task).filter(
        TaskAssignment.user_id.in_(user_ids),
        TaskAssignment.status == 'pending',
        Task.end_time <= now + timedelta(days=3),
        Task.end_time >= now
    ).group_by(TaskAssignment.user_id).all())
    overdue_rows = dict(db.session.query(
        TaskAssignment.user_id, func.count(TaskAssignment.id)
    ).join(Task).filter(
        TaskAssignment.user_id.in_(user_ids),
        TaskAssignment.status == 'pending',
        Task.end_time < now
    ).group_by(TaskAssignment.user_id).all())
    user_stats = []
    for u in users:
        total = total_rows.get(u.id, 0)
        completed = completed_rows.get(u.id, 0)
        rate = round(completed / total * 100, 1) if total > 0 else 0
        user_stats.append({
            'user': u, 'total': total, 'completed': completed,
            'rate': rate,
            'urgent': urgent_rows.get(u.id, 0),
            'overdue': overdue_rows.get(u.id, 0)
        })

    uid = current_user.id
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

    now_dt = datetime.now()
    week_start = now_dt - timedelta(days=now_dt.weekday())
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
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

    return render_template('dashboard.html', stats=stats, user_stats=user_stats,
                           total=total, completed=completed, pending=pending,
                           rejected=rejected, rate=rate, upcoming=upcoming,
                           overdue=overdue,
                           recent=recent, recent_tasks=recent_tasks,
                           today_tasks=today_tasks, week_tasks=week_tasks,
                           all_pending=all_pending,
                           now=now_dt,
                           is_admin=True,
                           users=get_same_group_users(current_user),
                           note_count=_count_notes(),
                           kb_count=_count_kb())


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
        since = datetime.utcnow() - timedelta(days=days)
        query = query.filter(OperationLog.created_at >= since)

    pagination = db.paginate(
        query.order_by(OperationLog.created_at.desc()),
        page=page, per_page=30, error_out=False)
    logs = pagination.items

    total_users = db.session.query(
        func.count(func.distinct(OperationLog.user_id))).scalar() or 0

    return render_template('admin/logs.html', logs=logs,
                           pagination=pagination, username=username,
                           action=action, days=days,
                           total_users=total_users,
                           total_logs=(db.session.query(OperationLog.id)
                                       .count()))


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


@app.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def admin_users():
    users = User.query.all()
    groups = Group.query.all()
    return render_template('admin/users.html', users=users, groups=groups, is_admin=True)


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
                           now=datetime.now())


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
    Notification.query.filter(
        Notification.task_id.in_(ids)).update(
        {Notification.task_id: None})
    db.session.execute(
        task_group.delete().where(task_group.c.task_id.in_(ids)))
    TaskAssignment.query.filter(
        TaskAssignment.task_id.in_(ids)).delete(
        synchronize_session=False)
    Task.query.filter(Task.id.in_(ids)).delete(
        synchronize_session=False)
    db.session.commit()
    flash(f'已删除 {len(ids)} 个待办', 'success')
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
    now = datetime.now()
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
    now = datetime.now()
    total = TaskAssignment.query.filter_by(user_id=current_user.id).count()
    completed = TaskAssignment.query.filter_by(
        user_id=current_user.id, status='completed'
    ).count()
    pending = TaskAssignment.query.filter_by(
        user_id=current_user.id, status='pending'
    ).count()
    rejected = TaskAssignment.query.filter_by(
        user_id=current_user.id, status='rejected'
    ).count()
    rate = round(completed / total * 100, 1) if total > 0 else 0

    upcoming = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status == 'pending',
        Task.end_time >= now,
        Task.end_time <= now + timedelta(days=7)
    ).order_by(Task.end_time).all()

    overdue = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status == 'pending',
        Task.end_time < now
    ).order_by(Task.end_time).all()

    recent = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.completed_at.isnot(None)
    ).order_by(TaskAssignment.completed_at.desc()).limit(5).all()

    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    today_tasks = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id, TaskAssignment.status == 'pending',
        Task.end_time >= today_start, Task.end_time <= today_end
    ).order_by(Task.end_time).all()
    week_tasks = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id, TaskAssignment.status == 'pending',
        Task.end_time >= week_start, Task.end_time <= week_end
    ).order_by(Task.end_time).all()
    all_pending = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id, TaskAssignment.status == 'pending'
    ).order_by(Task.end_time).all()

    return render_template('dashboard.html', total=total,
                           completed=completed, pending=pending,
                           rejected=rejected, rate=rate,
                           upcoming=upcoming, overdue=overdue,
                           recent=recent,
                           today_tasks=today_tasks, week_tasks=week_tasks,
                            all_pending=all_pending,
                            now=now,
                            is_admin=False,
                            users=get_same_group_users(current_user),
                            note_count=_count_notes(),
                            kb_count=_count_kb())


@app.route('/api/group-members')
@login_required
def api_group_members():
    members = get_same_group_users(current_user)
    result = [{'id': u.id, 'name': u.name or u.username, 'username': u.username}
              for u in members]
    return jsonify(result)


@app.route('/api/search-tasks')
@login_required
def api_search_tasks():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    filters = [TaskAssignment.user_id == current_user.id]
    if q:
        pattern = f'%{q}%'
        filters.append(db.or_(
            Task.title.like(pattern),
            Task.description.like(pattern),
            TaskAssignment.note.like(pattern)
        ))
    if category:
        filters.append(Task.category == category)
    assignments = TaskAssignment.query.join(Task).filter(
        *filters
    ).order_by(Task.end_time.desc()).limit(20).all()
    results = []
    for a in assignments:
        results.append({
            'task_id': a.task.id,
            'title': a.task.title,
            'description': a.task.description or '',
            'category': a.task.category,
            'status': a.status,
            'progress': a.progress,
            'start_time': a.task.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': a.task.end_time.strftime('%Y-%m-%d %H:%M'),
            'detail_url': url_for('user_task_detail', task_id=a.task.id),
        })
    return jsonify(results)


@app.route('/api/unified-search')
@login_required
def api_unified_search():
    """首页统一检索:待办 + 笔记 + 知识库,分类型返回。"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'ok': True, 'q': '', 'tasks': [], 'notes': [],
                        'kb': [], 'total': 0})
    pat = f'%{q}%'

    try:
        from knowledge import record_history
        record_history('unified', q)
    except Exception as _e:
        app.logger.warning('record unified history failed: %s', _e)

    # 待办(我参与的)
    filters = [TaskAssignment.user_id == current_user.id]
    filters.append(db.or_(
        Task.title.like(pat), Task.description.like(pat),
        TaskAssignment.note.like(pat)))
    assigns = TaskAssignment.query.join(Task).filter(
        *filters).order_by(Task.end_time.desc()).limit(20).all()
    tasks = [{
        'task_id': a.task.id,
        'title': a.task.title,
        'description': a.task.description or '',
        'category': a.task.category,
        'status': a.status,
        'end_time': a.task.end_time.strftime('%Y-%m-%d %H:%M'),
        'detail_url': url_for('user_task_detail', task_id=a.task.id),
    } for a in assigns]

    # 笔记(个人)
    from notes import Note, parse_tags_json
    notes = Note.query.filter(Note.user_id == current_user.id).filter(
        db.or_(Note.title.like(pat), Note.content.like(pat))
    ).order_by(Note.created_at.desc()).limit(20).all()
    note_rows = [{
        'id': n.id,
        'title': n.title,
        'content': (n.content or '')[:200],
        'tags': parse_tags_json(n.tags),
        'thread': n.thread.name if n.thread else '',
        'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if
        n.created_at else '',
        'detail_url': url_for('notes.index'),
    } for n in notes]

    # 知识库(关键词检索,按当前用户可见范围)
    kb = []
    try:
        import knowledge as _kb
        visible = _kb._visible_doc_ids()  # None=全部(管理员)
        res = _kb.keyword_search_pages(q, k=10)
        grouped = _kb.group_results(res, q, max_pages_per_doc=2)
        for g in grouped:
            if visible is not None and g['doc_id'] not in visible:
                continue
            kb.append({
                'doc_id': g['doc_id'],
                'title': g['title'],
                'filename': g['filename'],
                'score': round(g['best_score'] * 100),
                'pages': [{'page_no': p['page_no'],
                           'snippet': str(p['snippet'])}
                          for p in g['pages']],
                'preview_url': url_for('kb.preview', doc_id=g['doc_id']) if
                _has_preview(g['doc_id']) else '',
                'detail_url': url_for('kb.doc_detail', doc_id=g['doc_id']),
            })
    except Exception as _e:
        app.logger.warning('unified kb search failed: %s', _e)

    total = len(tasks) + len(notes) + len(kb)
    return jsonify({'ok': True, 'q': q, 'tasks': tasks, 'notes': note_rows,
                    'kb': kb, 'total': total})


@app.route('/api/unified-search/history')
@login_required
def api_unified_search_history():
    """首页统一检索的历史(当前用户最近 top5)。"""
    try:
        from knowledge import get_recent_unified
        items = get_recent_unified(current_user.id, 5)
    except Exception as _e:
        app.logger.warning('load unified history failed: %s', _e)
        items = []
    return jsonify({'ok': True, 'items': items})


def _has_preview(doc_id):
    """kub doc 预览链接一般均可用;做最小检出避免为每条再查询。"""
    from knowledge import KbDocument
    doc = db.session.get(KbDocument, doc_id)
    if not doc or not doc.file_path:
        return False
    from knowledge import _resolve_stored_path
    return os.path.exists(_resolve_stored_path(doc.file_path))


@app.route('/api/quick-task/preview', methods=['POST'])
@login_required
def api_quick_task_preview():
    """首页快速创建待办第一步：自然语言解析，返回待确认预览(与待办发布一致)。"""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if len(text) < 2:
        return jsonify({'ok': False, 'error': '待办描述至少 2 个字'}), 400
    try:
        parsed = parse_task_from_text(text)
    except Exception as e:
        logger.error('Quick task preview failed: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': '解析待办失败，请检查输入格式'}), 400
    title = (parsed.get('title') or '').strip()
    if not title or title == '未命名待办' or len(title) < 2:
        return jsonify({'ok': False, 'error': '无法提取待办标题（至少 2 个字）'}), 400

    # 解析出可编辑的初始值
    start = parsed.get('start_time') or datetime.now()
    end = parsed.get('end_time') or (start + timedelta(days=1))
    if end <= start:
        end = start + timedelta(hours=1)

    assignee_ids = []
    if current_user.role == 'admin' and parsed.get('is_all', False):
        is_all = True
    else:
        is_all = False
        for name in parsed.get('assignees') or []:
            u = User.query.filter(
                db.or_(User.name == name, User.username == name)).first()
            if u and not u.is_disabled and u.id != current_user.id:
                assignee_ids.append(u.id)
        assignee_ids.append(current_user.id)

    return jsonify({
        'ok': True,
        'title': title,
        'description': text,
        'category': parsed.get('category') or '工作',
        'start_time': start.strftime('%Y-%m-%dT%H:%M'),
        'end_time': end.strftime('%Y-%m-%dT%H:%M'),
        'is_all': is_all,
        'assignee_ids': assignee_ids,
        'recurrence_text': parsed.get('recurrence_text', ''),
        'recurrence': parsed.get('recurrence') or '',
        'recurrence_interval_days': parsed.get('recurrence_interval_days') or 0,
        'recurrence_count': parsed.get('recurrence_count') or 0,
        'text': text,
    })


@app.route('/api/quick-task', methods=['POST'])
@login_required
def api_quick_task():
    """首页快速创建待办第二步：确认后创建(与待办发布一致)。"""
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title or len(title) < 2:
        return jsonify({'ok': False, 'error': '待办标题至少 2 个字'}), 400
    dt_fmt = '%Y-%m-%dT%H:%M'
    try:
        start = datetime.strptime(data.get('start_time', ''), dt_fmt)
    except Exception:
        start = datetime.now()
    try:
        end = datetime.strptime(data.get('end_time', ''), dt_fmt)
    except Exception:
        end = start + timedelta(days=1)
    if end <= start:
        end = start + timedelta(hours=1)
    category = (data.get('category') or '').strip() or '工作'
    description = (data.get('description') or '').strip() or title

    is_all = current_user.role == 'admin' and bool(data.get('is_all'))
    recurrence_interval_days = int(data.get('recurrence_interval_days') or 0)
    recurrence_count = int(data.get('recurrence_count') or 0)
    total = recurrence_count if recurrence_interval_days and recurrence_count > 0 else 1

    assignee_ids = set()
    if not is_all:
        for uid in data.get('assignee_ids') or []:
            try:
                assignee_ids.add(int(uid))
            except (TypeError, ValueError):
                continue
        assignee_ids.add(current_user.id)

    created_titles = []
    try:
        for i in range(total):
            offset = timedelta(days=recurrence_interval_days * i)
            t_start = start + offset
            t_end = end + offset
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
                for uid in assignee_ids:
                    db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                    create_notification(uid, 'task_assigned',
                                        f'你收到一个新待办：「{t_title}」', task.id)
            created_titles.append(t_title)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error('Quick task creation failed: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': '创建失败'}), 500
    return jsonify({'ok': True, 'task_id': task.id,
                    'url': url_for('user_task_detail', task_id=task.id),
                    'created': created_titles})


@app.route('/api/quick-note', methods=['POST'])
@login_required
def api_quick_note():
    """首页随手记(走笔记自动整理管道)。"""
    from notes import (Note, parse_tags_json, apply_rules, simhash,
                       persist_md, find_duplicates, extract_title)
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': '内容不能为空'}), 400
    title = (data.get('title') or '').strip() or extract_title(content)
    tid = data.get('thread_id')
    from notes import Thread
    thread = None
    if tid:
        thread = Thread.query.filter_by(id=int(tid)).first()
    note = Note(user_id=current_user.id,
                thread_id=thread.id if thread else None,
                title=title, content=content, tags='[]', version=1)
    changes = apply_rules(note)
    note.simhash = str(simhash(content))
    db.session.add(note)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': '保存失败'}), 500
    persist_md(note)
    dup = find_duplicates(note)
    return jsonify({'ok': True, 'note_id': note.id, 'warnings': dup})


@app.route('/api/jobs')
@login_required
def api_jobs():
    """组织待办列表(管理页用,返回最近 job)。"""
    from notes import NoteJob
    jobs = NoteJob.query.order_by(NoteJob.created_at.desc()).limit(100).all()
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
    from notes import NoteJob
    scope = request.form.get('scope', 'all')
    target_ids = request.form.get('target', '').strip()
    if scope not in ('all', 'notes', 'kb'):
        scope = 'all'
    # target 形如 'note:1,2' / 'kb:3,4' / 'thread:1'
    job = NoteJob(scope=scope, target=target_ids, status='queued',
                  trigger='manual', created_by=current_user.id)
    db.session.add(job)
    db.session.commit()
    log_operation('job_trigger', f'{scope}:{target_ids}',
                  f'手动触发整理待办 #{job.id}')
    flash(f'已入队整理待办 #{job.id}({scope})', 'success')
    return redirect(url_for('admin_jobs'))


@app.route('/admin/jobs')
@admin_required
def admin_jobs():
    """后台管理:定时任务/整理记录。"""
    from notes import NoteJob
    jobs = NoteJob.query.order_by(NoteJob.created_at.desc()).limit(200).all()
    scope = request.args.get('scope', '')
    status = request.args.get('status', '')
    if scope:
        jobs = [j for j in jobs if j.scope == scope]
    if status:
        jobs = [j for j in jobs if j.status == status]
    return render_template('admin/jobs.html', jobs=jobs, scope=scope,
                           status=status)


@app.route('/admin/jobs/<int:job_id>/retry', methods=['POST'])
@admin_required
def admin_jobs_retry(job_id):
    from notes import NoteJob
    job = db.session.get(NoteJob, job_id)
    if not job:
        flash('待办不存在', 'danger')
        return redirect(url_for('admin_jobs'))
    job.status = 'queued'
    job.error = ''
    job.result = ''
    job.progress = 0
    job.created_at = datetime.utcnow()
    job.started_at = None
    job.finished_at = None
    db.session.commit()
    flash(f'已重新入队待办 #{job.id}', 'success')
    return redirect(url_for('admin_jobs'))


@app.route('/api/quick-upload', methods=['POST'])
@login_required
def api_quick_upload():
    """首页快速上传知识(入知识库识别队列)。"""
    import uuid as _uuid
    import knowledge as _kb
    from knowledge import KbDocument, STATUS_QUEUED
    files = request.files.getlist('file')
    files = [f for f in files if f and f.filename]
    if not files:
        return jsonify({'ok': False, 'error': '未选择文件'}), 400
    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'kb')
    os.makedirs(upload_dir, exist_ok=True)
    added, rejected = [], []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in _kb.ALLOWED_EXTENSIONS:
            rejected.append(f'{f.filename}({ext})')
            continue
        store_name = _uuid.uuid4().hex + ext
        target = os.path.join(upload_dir, store_name)
        f.save(target)
        title = os.path.splitext(f.filename)[0] or '未命名文档'
        doc = KbDocument(title=title, filename=f.filename, file_path=target,
                         file_type=ext.lstrip('.'), file_size=os.path.getsize(
                             target), status=STATUS_QUEUED,
                         uploaded_by=current_user.id,
                         last_recognition_type='upload')
        db.session.add(doc)
        added.append(title)
    db.session.commit()
    try:
        _kb._bump_data_version()
    except Exception:
        pass
    return jsonify({'ok': True, 'added': added,
                    'rejected': rejected,
                    'pending_url': url_for('kb.index')})


@app.route('/api/summary')
@login_required
def api_summary():
    period = request.args.get('period', 'month')
    date_str = request.args.get('date', '')
    now = datetime.now()

    if period == 'year':
        if date_str:
            year = int(date_str)
        else:
            year = now.year
        start = datetime(year, 1, 1)
        end = datetime(year, 12, 31, 23, 59, 59)
        label = f'{year}年'
    else:
        if date_str and '-' in date_str:
            parts = date_str.split('-')
            year, month = int(parts[0]), int(parts[1])
        else:
            year, month = now.year, now.month
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(year, month + 1, 1) - timedelta(seconds=1)
        label = f'{year}年{month}月'

    assignments = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id,
        Task.end_time >= start,
        Task.end_time <= end
    ).all()

    if not assignments:
        return jsonify({
            'period': period, 'date': date_str, 'label': label,
            'text': f'{label}暂无分配待办记录。',
            'total': 0, 'completed': 0, 'pending': 0,
            'abandoned': 0, 'rejected': 0, 'rate': 0, 'avg_progress': 0,
        })

    total = len(assignments)
    completed = [a for a in assignments if a.status in ('completed', 'approved')]
    pending = [a for a in assignments if a.status == 'pending']
    abandoned = [a for a in assignments if a.status == 'abandoned']
    rejected = [a for a in assignments if a.status == 'rejected']
    rate = round(len(completed) / total * 100, 1) if total else 0
    avg_progress = round(sum(a.progress for a in assignments) / total) if total else 0

    tasks_by_cat = {}
    for a in assignments:
        cat = a.task.category or '其他'
        tasks_by_cat.setdefault(cat, []).append(a)
    cat_order = ['工作', '个人', '会议', '培训', '考试']
    for cat in tasks_by_cat:
        if cat not in cat_order:
            cat_order.append(cat)

    def task_line(a):
        status_map = {
            'pending': '进行中', 'completed': '已完成',
            'approved': '已确认', 'rejected': '已驳回', 'abandoned': '已废弃'
        }
        s = status_map.get(a.status, a.status)
        desc_hint = ''
        if a.task.description and a.task.description != a.task.title:
            brief = a.task.description[:60].replace('\n', ' ')
            if len(a.task.description) > 60:
                brief += '…'
            desc_hint = f'（{brief}）'
        line = f'- {a.task.title}{desc_hint}，{s}'
        if a.status == 'pending' and a.progress > 0:
            line += f'，进度{a.progress}%'
        if a.note:
            note_brief = a.note[:40].replace('\n', ' ')
            if len(a.note) > 40:
                note_brief += '…'
            line += f'，备注：{note_brief}'
        return line

    lines = [f'{label}工作总结', '']

    lines.append(f'本期共分配待办{total}项，已完成{len(completed)}项，完成率{rate}%，平均进度{avg_progress}%。')
    lines.append('')

    overdue_in_period = [a for a in pending if a.task.end_time < now]
    if overdue_in_period:
        lines.append(f'当前仍有{len(overdue_in_period)}项待办逾期未完成。')
        lines.append('')

    for cat in cat_order:
        group = tasks_by_cat.get(cat)
        if not group:
            continue
        done = len([a for a in group if a.status in ('completed', 'approved')])
        lines.append(f'【{cat}类】共{len(group)}项，已完成{done}项。')
        for a in sorted(group, key=lambda x: x.task.end_time):
            lines.append(task_line(a))
        lines.append('')

    if rejected:
        lines.append(f'【驳回待办】{len(rejected)}项。')
        for a in rejected:
            reason = f'，原因：{a.rejection_reason}' if a.rejection_reason else ''
            lines.append(f'- {a.task.title}{reason}')
        lines.append('')

    if abandoned:
        lines.append(f'【废弃待办】{len(abandoned)}项。')
        for a in abandoned:
            lines.append(f'- {a.task.title}')
        lines.append('')

    next_period_date = ''
    if period == 'year':
        next_period_date = f'{year + 1}'
        prev_period_date = f'{year - 1}'
    else:
        nm, ny = month + 1, year
        if nm > 12:
            nm, ny = 1, year + 1
        pm, py = month - 1, year
        if pm < 1:
            pm, py = 12, year - 1
        next_period_date = f'{ny}-{nm:02d}'
        prev_period_date = f'{py}-{pm:02d}'

    return jsonify({
        'period': period, 'date': date_str, 'label': label,
        'text': '\n'.join(lines),
        'total': total, 'completed': len(completed), 'pending': len(pending),
        'abandoned': len(abandoned), 'rejected': len(rejected),
        'rate': rate, 'avg_progress': avg_progress,
        'next_date': next_period_date, 'prev_date': prev_period_date,
    })


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


def _assignment_counts_by_user():
    """{display name -> number of assigned tasks}, for the admin overview bar."""
    rows = db.session.query(
        func.coalesce(User.name, User.username).label('uname'),
        func.count(TaskAssignment.id)
    ).select_from(TaskAssignment).join(User, TaskAssignment.user_id == User.id) \
     .group_by(User.id).order_by(func.count(TaskAssignment.id).desc()).all()
    return {uname: n for uname, n in rows}


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
            ctx['assignment_counts'] = _assignment_counts_by_user()
        order = ['工作', '个人', '会议', '培训', '考试']
        seen = set()
        groups = {c: [] for c in order}
        all_t = list(my_tasks) + list(other_assigned or [])
        for t in all_t:
            if t.id in seen:
                continue
            seen.add(t.id)
            groups.setdefault(t.category, []).append(t)
        ctx['task_categories'] = [{'category': c, 'tasks': groups.get(c, [])}
                                  for c in order + [k for k in groups if k not in order]
                                  if groups.get(c)]
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
                'now': datetime.now(),
                'is_admin': current_user.role == 'admin',
                'sensitive_words': sensitive,
                'sensitive_text': highlight_sensitive_words(text),
                'original_text': text,
                'user_groups': user_groups,
                'duplicate_tasks': [],
            }
            if current_user.role == 'admin':
                template_data['all_tasks'] = Task.query.order_by(Task.created_at.desc()).all()
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
                if similar:
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
                        'now': datetime.now(),
                        'is_admin': current_user.role == 'admin',
                        'user_groups': user_groups,
                        'duplicate_tasks': similar,
                        'duplicate_blocked': True,
                    }
                    if current_user.role == 'admin':
                        template_data['all_tasks'] = Task.query.order_by(Task.created_at.desc()).all()
                    template_data.update(_stats_context())
                    return render_template('tasks.html', **template_data)
                created_titles = []
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
                        uid_set = set(int(x) for x in assignee_ids) if assignee_ids else set()
                        if group_ids:
                            selected_groups = Group.query.filter(Group.id.in_([int(gid) for gid in group_ids])).all()
                            for g in selected_groups:
                                for m in g.members:
                                    if not m.is_disabled:
                                        uid_set.add(m.id)
                                task.groups.append(g)
                        uid_set.add(current_user.id)
                        for uid in uid_set:
                            db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                            create_notification(uid, 'task_assigned',
                                                f'你收到一个新待办：「{t_title}」', task.id)
                    created_titles.append(t_title)
                db.session.commit()
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
            template_data = {
                'rejected_tasks': rejected_tasks,
                'preview': parsed, 'users': users,
                'my_tasks': my_tasks,
                'TaskAssignment': TaskAssignment,
                'now': datetime.now(),
                'is_admin': is_admin_user,
                'user_groups': user_groups,
                'duplicate_tasks': parsed_duplicates,
                'duplicate_blocked': bool(parsed_duplicates),
            }
            # tasks assigned to me by others
            my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter_by(user_id=current_user.id).all()}
            other_assigned = Task.query.filter(Task.id.in_(my_assigned_ids), Task.creator_id != current_user.id).order_by(Task.created_at.desc()).all() if my_assigned_ids else []
            template_data.update({
                'my_tasks': my_tasks,
                'other_assigned': other_assigned,
                'TaskAssignment': TaskAssignment,
                'now': datetime.now(),
                'is_admin': is_admin_user,
            })
            if is_admin_user:
                tasks = Task.query.order_by(Task.created_at.desc()).all()
                template_data['all_tasks'] = tasks
            template_data.update(_stats_context())
            return render_template('tasks.html', **template_data)
        except Exception as e:
            db.session.rollback()
            logger.error('User task parsing failed: %s', e, exc_info=True)
            flash('解析待办失败：请检查输入格式', 'danger')
            return redirect(url_for('user_tasks'))

    parsed = None
    is_admin_user = current_user.role == 'admin'
    my_assigned_ids = {a.task_id for a in TaskAssignment.query.filter_by(user_id=current_user.id).all()}
    other_assigned = Task.query.filter(Task.id.in_(my_assigned_ids), Task.creator_id != current_user.id).order_by(Task.created_at.desc()).all() if my_assigned_ids else []
    template_data = {
        'rejected_tasks': rejected_tasks,
        'preview': parsed, 'users': users,
        'my_tasks': my_tasks,
        'other_assigned': other_assigned,
        'TaskAssignment': TaskAssignment,
        'now': datetime.now(),
        'is_admin': is_admin_user,
        'user_groups': user_groups,
    }
    template_data.update(_stats_context())
    if is_admin_user:
        tasks = Task.query.order_by(Task.created_at.desc()).all()
        template_data['all_tasks'] = tasks
        _now = datetime.now()
        user_ids = [u.id for u in users]
        user_stats = []
        status_rows = db.session.query(
            TaskAssignment.user_id, TaskAssignment.status,
            func.count(TaskAssignment.id)
        ).filter(TaskAssignment.user_id.in_(user_ids)).group_by(
            TaskAssignment.user_id, TaskAssignment.status).all()
        per_status = {}
        for uid, status, n in status_rows:
            per_status.setdefault(uid, {})[status] = n
        if user_ids:
            urgent_rows = db.session.query(
                TaskAssignment.user_id, func.count(TaskAssignment.id)
            ).join(Task).filter(
                TaskAssignment.user_id.in_(user_ids),
                TaskAssignment.status == 'pending',
                Task.end_time <= _now
            ).group_by(TaskAssignment.user_id).all()
            overdue_rows = db.session.query(
                TaskAssignment.user_id, func.count(TaskAssignment.id)
            ).join(Task).filter(
                TaskAssignment.user_id.in_(user_ids),
                TaskAssignment.status == 'pending',
                Task.end_time < _now
            ).group_by(TaskAssignment.user_id).all()
        else:
            urgent_rows, overdue_rows = [], []
        urgent = dict(urgent_rows)
        overdue = dict(overdue_rows)
        for u in users:
            s = per_status.get(u.id, {})
            total = sum(s.values())
            completed_count = s.get('completed', 0) + s.get('approved', 0)
            rate = round(completed_count / total * 100, 1) if total > 0 else 0
            user_stats.append({
                'user': u, 'total': total, 'completed': completed_count,
                'rate': rate, 'urgent': urgent.get(u.id, 0),
                'overdue': overdue.get(u.id, 0)
            })
        template_data['user_stats'] = user_stats

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
    assignment.completed_at = datetime.now()
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
        assignment.completed_at = datetime.now()
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
    assignment.abandoned_at = datetime.now()
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
                           now=datetime.now())


@app.route('/api/task/<int:task_id>')
@login_required
def api_task_detail(task_id):
    """待办内联详情(JSON):供待办页右侧面板展示。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if current_user.role != 'admin' and \
            not TaskAssignment.query.filter_by(
                task_id=task.id, user_id=current_user.id).first():
        return jsonify({'ok': False, 'error': '无权查看'}), 403
    assignment = TaskAssignment.query.filter_by(
        user_id=current_user.id, task_id=task.id).first()
    assigns = TaskAssignment.query.filter(
        TaskAssignment.task_id == task.id).all()
    stats = _build_task_stats([task.id], current_user.id)[0].get(task.id, {})
    return jsonify({
        'ok': True,
        'task': {
            'id': task.id,
            'title': task.title,
            'description': task.description or '',
            'category': task.category,
            'status': assignment.status if assignment else '',
            'progress': assignment.progress if assignment else 0,
            'note': assignment.note if assignment else '',
            'start_time': task.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': task.end_time.strftime('%Y-%m-%d %H:%M'),
            'is_all': task.is_all,
            'creator': task.creator.name or task.creator.username,
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M')
                          if task.created_at else '',
            'assignments': [{
                'user': a.user.name or a.user.username,
                'status': a.status,
                'progress': a.progress,
                'note': a.note or '',
                'self': a.user_id == current_user.id,
            } for a in assigns],
            'stats': stats,
        }
    })


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
    if not title:
        flash('待办标题不能为空', 'danger')
        return redirect(request.referrer or url_for('user_dashboard'))
    try:
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
        db.session.commit()
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
                    original = f"upload_{int(datetime.now().timestamp())}.{ext}"
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
        assignment.completed_at = datetime.now()
        assignment.rejection_reason = None
        flash('恭喜，待办已完成！', 'success')
    elif progress is not None and progress < 100 and assignment.status == 'completed':
        assignment.status = 'pending'
        assignment.completed_at = None
        assignment.rejection_reason = None
    db.session.commit()
    flash('进度已更新', 'success')
    return redirect(request.referrer or url_for('user_tasks'))


@app.route('/notifications')
@login_required
def notifications():
    notes = Notification.query.filter_by(
        user_id=current_user.id).order_by(
        Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notes)


@app.route('/notifications/<int:note_id>/read', methods=['GET', 'POST'])
@login_required
def read_notification(note_id):
    note = db.session.get(Notification, note_id)
    if note and note.user_id == current_user.id:
        note.is_read = True
        db.session.commit()
        if note.task_id:
            return redirect(url_for('user_task_detail', task_id=note.task_id))
    return redirect(url_for('notifications'))


@app.route('/notifications/read-all', methods=['POST'])
@login_required
def read_all_notifications():
    Notification.query.filter_by(
        user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('所有通知已标记为已读', 'info')
    return redirect(request.referrer or url_for('notifications'))


@app.route('/uploads/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/admin/clear-data', methods=['POST'])
@login_required
@admin_required
def admin_clear_data():
    Notification.query.delete()
    TaskAssignment.query.delete()
    db.session.execute(task_group.delete())
    Task.query.delete()
    db.session.execute(user_group.delete())
    Group.query.delete()
    demo_users = User.query.filter(
        User.username.in_(['guest', 'zhangsan', 'lisi', 'wangwu', 'zhaoliu', 'sunqi'])
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


with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get('FLASK_DEBUG') == '1')
