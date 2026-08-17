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

"""个人笔记模块(单文件版)。

组成:
- 模型: Note / Thread / NoteRule / NoteJob (由 app.py 调用 init_models(db) 注入)
- 存储: Markdown 文件按 年/月/日 分片,结构化元数据写入 SQLite(tasks.db)
- 管道: 写入时继承上下文 -> 规则命中 -> 相似度(SIMHash)提醒 -> 持久化
- 视图: Flask Blueprint(笔记页 + REST API)
- 组织: 定期/手动整理由 job_worker.py 消费 NoteJob 队列

避免循环导入:模型与 db 通过 init_models(database) 注入,与 knowledge.py 同模式。
"""
import datetime
import hashlib
import json
import logging
import os
import re
import uuid

from flask import (Blueprint, jsonify, render_template, request,
                   send_from_directory)
from flask_login import current_user, login_required
from sqlalchemy import or_

logger = logging.getLogger(__name__)

_NOTES_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'instance', 'notes')

_NOTE_ATTACH_DIR = os.path.join(_NOTES_ROOT, 'attachments')
_NOTE_IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
_NOTE_ATTACH_EXT = (
    '.doc', '.docx', '.ppt', '.pptx', '.pdf', '.xls', '.xlsx',
    '.txt', '.md', '.csv', '.zip', '.rar', '.7z', '.tar', '.gz',
)

db = None
Note = None
Thread = None
NoteRule = None
NoteJob = None


def init_models(database):
    global db, Note, Thread, NoteRule, NoteJob
    db = database

    class Thread_(database.Model):
        """对话上下文(项目/标签组),笔记继承其上下文。"""
        __tablename__ = 'thread'
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, database.ForeignKey(
            'user.id'), nullable=True, index=True)
        name = database.Column(database.String(200), nullable=False)
        parent_id = database.Column(database.Integer, nullable=True)
        color = database.Column(database.String(20), default='#4f46e7')
        created_at = database.Column(database.DateTime,
                                    default=datetime.datetime.utcnow)

    class Note_(database.Model):
        __tablename__ = 'note'
        __table_args__ = (
            database.Index('ix_note_user_created', 'user_id', 'created_at'),
            database.Index('ix_note_thread', 'thread_id'),
        )
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, database.ForeignKey(
            'user.id'), nullable=True, index=True)
        thread_id = database.Column(database.Integer, database.ForeignKey(
            'thread.id'), nullable=True, index=True)
        title = database.Column(database.String(300), default='')
        content = database.Column(database.Text, default='')
        tags = database.Column(database.String(1000), default='[]')
        version = database.Column(database.Integer, default=0)
        simhash = database.Column(database.String(64), default='', index=True)
        refined_at = database.Column(database.DateTime)
        created_at = database.Column(database.DateTime,
                                    default=datetime.datetime.utcnow)
        updated_at = database.Column(
            database.DateTime, default=datetime.datetime.utcnow,
            onupdate=datetime.datetime.utcnow)

        thread = database.relationship(Thread_, backref=database.backref(
            'notes', lazy='dynamic', cascade='all, delete-orphan'))

    class NoteRule_(database.Model):
        __tablename__ = 'note_rule'
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, nullable=True, index=True)
        name = database.Column(database.String(200), default='')
        match_field = database.Column(database.String(20), default='content')
        match_type = database.Column(database.String(20), default='keyword')
        keyword = database.Column(database.String(200), default='')
        add_tags = database.Column(database.String(1000), default='[]')
        move_thread = database.Column(database.String(200), default='')
        enabled = database.Column(database.Boolean, default=True)
        sort = database.Column(database.Integer, default=0)

    class NoteJob_(database.Model):
        __tablename__ = 'note_job'
        __table_args__ = (
            database.Index('ix_note_job_status', 'status'),
            database.Index('ix_note_job_created', 'created_at'),
        )
        id = database.Column(database.Integer, primary_key=True)
        scope = database.Column(database.String(20), default='all')
        target = database.Column(database.String(1000), default='')
        status = database.Column(database.String(20), default='queued')
        trigger = database.Column(database.String(20), default='manual')
        progress = database.Column(database.Integer, default=0)
        phase = database.Column(database.String(50), default='')
        cancel = database.Column(database.Integer, default=0)
        result = database.Column(database.Text, default='')
        error = database.Column(database.Text, default='')
        created_by = database.Column(database.Integer, nullable=True)
        created_at = database.Column(database.DateTime,
                                    default=datetime.datetime.utcnow)
        started_at = database.Column(database.DateTime)
        finished_at = database.Column(database.DateTime)
        updated_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow,
                                     onupdate=datetime.datetime.utcnow)

    Note, Thread, NoteRule, NoteJob = Note_, Thread_, NoteRule_, NoteJob_
    # 表由 app.py init_db() 的 db.create_all() 统一创建,无需在此 create_all
    return {'Note': Note, 'Thread': Thread, 'NoteRule': NoteRule,
            'NoteJob': NoteJob}


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def parse_tags_json(raw):
    if raw is None:
        return []
    try:
        return json.loads(raw if isinstance(raw, str) else json.dumps(raw))
    except Exception:
        return []


def build_tag_list(tags):
    if isinstance(tags, str):
        return parse_tags_json(tags)
    return list(tags or [])


def build_frontmatter(title, tags, **kwargs):
    lines = ['---', f'title: "{title}"',
             f"tags: [{', '.join(repr(str(t)) for t in tags or [])}]"]
    for k, v in kwargs.items():
        if v is None or v == '':
            continue
        lines.append(f'{k}: "{v}"')
    lines.append('---\n')
    return '\n'.join(lines)


def _note_md_path(note):
    if not getattr(note, 'created_at', None):
        return None
    dt = note.created_at
    return os.path.join(_NOTES_ROOT, str(dt.year), f'{dt.month:02d}',
                        f'{dt.day:02d}', f'note-{note.id:06d}.md')


def persist_md(note):
    """提交后把笔记写为带 frontmatter 的 Markdown 文件(双写)。"""
    try:
        path = _note_md_path(note)
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        thr = getattr(note, 'thread', None)
        body = build_frontmatter(
            note.title, parse_tags_json(note.tags),
            date=note.created_at.strftime('%Y-%m-%d') if note.created_at
            else '', folder=thr.name if thr else '')
        body += (note.content or '').strip() + '\n'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)
    except Exception as e:
        logger.warning('note md write failed: %s', e)


def extract_title(content, fallback='未命名笔记'):
    content = (content or '').strip()
    for line in content.splitlines():
        s = line.strip()
        m = re.match(r'^#{1,2}\s+(.+)$', s)
        if m:
            return m.group(1).strip()[:200]
    first = [l.strip() for l in content.splitlines() if l.strip()]
    if first:
        return first[0][:80]
    return fallback


def simhash(text):
    """64 位 SIMHash(按中文/英文 token)。空文本返回 0。"""
    tokens = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9_]{2,}', text or '')
    if not tokens:
        return 0
    vec = [0] * 64
    for t in tokens:
        h = hashlib.md5(t.encode('utf-8')).digest()
        v = int.from_bytes(h[:8], 'big')
        for i in range(64):
            bit = (v >> (63 - i)) & 1
            vec[i] += 1 if bit else -1
    val = 0
    for i in range(64):
        if vec[i] > 0:
            val |= 1 << (63 - i)
    return val


def _hamming(a, b):
    return bin(a ^ b).count('1')


def find_duplicates(note, lookback_days=7, threshold=0.70, limit=5):
    """与最近 lookback 天内同账号笔记比对,返回疑似重复候选。

    SIMHash 对中文的区分度有限,近义长文本动态相似约 0.7 上下;阈值取
    0.75,且仅对内容词数 >= 3 的笔记做检测,避免过短文本随机碰撞。"""
    if not note or not note.simhash or note.simhash in ('0', 'None'):
        return []
    tokens = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9_]{2,}',
                        note.content or '')
    if len(tokens) < 3:
        return []
    since = datetime.datetime.utcnow() - datetime.timedelta(
        days=lookback_days)
    q = Note.query.filter(Note.id != note.id, Note.simhash != '',
                          Note.created_at >= since)
    if note.user_id is not None:
        q = q.filter(Note.user_id == note.user_id)
    out = []
    for other in q.all():
        try:
            sim = 1 - _hamming(int(note.simhash), int(other.simhash)) / 64.0
        except Exception:
            continue
        if sim >= threshold:
            out.append({'id': other.id, 'title': other.title,
                        'similarity': round(sim * 100, 1),
                        'date': other.created_at.strftime('%Y-%m-%d') if
                        other.created_at else ''})
    out.sort(key=lambda x: -x['similarity'])
    return out[:limit]


NOTE_MERGE_THRESHOLD = float(os.environ.get('NOTE_MERGE_THRESHOLD', '0.78'))
NOTE_MERGE_BATCH = int(os.environ.get('NOTE_MERGE_BATCH', '200'))


def merge_duplicate_notes(limit=None, threshold=None):
    """批量合并重复笔记:内容高度相似(仅同账号)的保留内容最长的一条,
    其余删除并删除对应 md 文件。返回 (合并条数, 剩余条数)。

    按账号分批处理全部笔记(不设总条数上限,避免漏掉历史重复);
    复用 SIMHash 相似度机制,不做大模型调用,避免误合并近义但不重复的笔记。
    """
    limit = limit or NOTE_MERGE_BATCH
    threshold = threshold if threshold is not None else NOTE_MERGE_THRESHOLD
    user_ids = [r[0] for r in db.session.query(Note.user_id).distinct()]
    merged = 0
    scanned = 0
    for uid in user_ids:
        q = Note.query.order_by(Note.created_at.desc())
        if uid is not None:
            q = q.filter(Note.user_id == uid)
        else:
            q = q.filter(Note.user_id.is_(None))
        offset = 0
        while True:
            batch = q.offset(offset).limit(limit).all()
            if not batch:
                break
            offset += limit
            group = [n for n in batch if n.simhash and n.simhash not in
                     ('0', 'None') and len(re.findall(
                         r'[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9_]{2,}',
                         n.content or '')) >= 3]
            scanned += len(group)
            group.sort(key=lambda x: -len(x.content or ''))
            removed = set()
            for i, keeper in enumerate(group):
                if keeper.id in removed:
                    continue
                for j, other in enumerate(group):
                    if j == i or other.id in removed:
                        continue
                    if len(other.content or '') < 10:
                        continue
                    try:
                        sim = 1 - _hamming(int(keeper.simhash),
                                           int(other.simhash)) / 64.0
                    except Exception:
                        continue
                    if sim >= threshold:
                        keeper.tags = json.dumps(
                            list(dict.fromkeys(parse_tags_json(keeper.tags) +
                                               parse_tags_json(other.tags))),
                            ensure_ascii=False)
                        p = _note_md_path(other)
                        if p and os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                        db.session.delete(other)
                        removed.add(other.id)
                        merged += 1
    if merged:
        db.session.commit()
    return merged, max(0, scanned - merged)


def apply_rules(note):
    """遍历 NoteRule,命中则追加标签/移动上下文。返回变更描述列表。"""
    changes = []
    if NoteRule is None:
        return changes
    rules = NoteRule.query.filter(
        or_(NoteRule.user_id == note.user_id, NoteRule.user_id.is_(None))
    ).order_by(NoteRule.sort, NoteRule.id).all()
    if not rules:
        return changes
    tags = parse_tags_json(note.tags)
    text = (note.title or '') + '\n' + (note.content or '')
    for r in rules:
        if not r.enabled:
            continue
        field_text = text if r.match_field != 'title' else (note.title or '')
        if r.match_type == 'regex':
            try:
                hit = bool(re.search(r.keyword, field_text))
            except Exception:
                hit = False
        else:
            hit = bool(r.keyword and (r.keyword in field_text))
        if not hit:
            continue
        for t in parse_tags_json(r.add_tags):
            if t and t not in tags:
                tags.append(t)
                changes.append(f'#{t}')
        if r.move_thread:
            base = Thread.query.filter_by(name=r.move_thread)
            target = base.filter_by(user_id=note.user_id).first() \
                if note.user_id else base.first()
            if target and note.thread_id != target.id:
                note.thread_id = target.id
                changes.append(f'移至[{r.move_thread}]')
    if changes:
        note.tags = json.dumps(tags, ensure_ascii=False)
    return changes


def _thread_note_counts(thread_ids, user_id):
    """批量统计各线程笔记数,替代 _thread_dict 中逐线程 count 的 N+1。"""
    ids = [t for t in (thread_ids or []) if t is not None]
    if not ids:
        return {}
    from sqlalchemy import func
    try:
        rows = db.session.query(
            Note.thread_id, func.count(Note.id)
        ).filter(Note.thread_id.in_(ids), Note.user_id == user_id).group_by(
            Note.thread_id).all()
    except Exception:
        return {}
    return dict(rows)


def _visible_threads(user_id):
    return Thread.query.filter(
        or_(Thread.user_id == user_id, Thread.user_id.is_(None))
    ).order_by(Thread.id).all()


def _note_dict(note, user_id=None):
    thr = getattr(note, 'thread', None)
    return {
        'id': note.id,
        'title': note.title,
        'content': note.content,
        'tags': parse_tags_json(note.tags),
        'thread_id': note.thread_id,
        'thread': thr.name if thr else '',
        'version': note.version,
        'created_at': note.created_at.strftime('%Y-%m-%d %H:%M') if
        note.created_at else '',
    }


# ---------------------------------------------------------------------------
# 蓝图
# ---------------------------------------------------------------------------

notes_bp = Blueprint('notes', __name__, url_prefix='/notes')


@notes_bp.route('/')
@login_required
def index():
    threads = _visible_threads(current_user.id)
    recent = Note.query.filter_by(user_id=current_user.id).order_by(
        Note.created_at.desc()).limit(120).all()
    rules = NoteRule.query.filter(
        or_(NoteRule.user_id == current_user.id,
            NoteRule.user_id.is_(None))
    ).order_by(NoteRule.sort).all()
    note_id = request.args.get('note_id', type=int)
    return render_template('notes.html', threads=threads, recent=recent,
                           rules=rules, note_id=note_id)


@notes_bp.route('/api/threads')
@login_required
def api_threads():
    threads = _visible_threads(current_user.id)
    counts = _thread_note_counts([t.id for t in threads], current_user.id)
    return jsonify({'ok': True, 'threads': [
        {'id': t.id, 'name': t.name, 'color': t.color,
         'note_count': counts.get(t.id, 0)} for t in threads]})


@notes_bp.route('/api/threads', methods=['POST'])
@login_required
def api_thread_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': '请输入名称'}), 400
    existing = Thread.query.filter_by(user_id=current_user.id,
                                      name=name).first()
    if existing:
        return jsonify({'ok': True, 'id': existing.id, 'created': False})
    t = Thread(user_id=current_user.id, name=name)
    db.session.add(t)
    db.session.commit()
    return jsonify({'ok': True, 'id': t.id, 'name': t.name, 'created': True})


@notes_bp.route('/api/notes', methods=['POST'])
@login_required
def api_create_note():
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': '内容不能为空'}), 400
    title = (data.get('title') or '').strip() or extract_title(content)
    tid = data.get('thread_id')
    tags = build_tag_list(data.get('tags') or [])

    thread = None
    if tid:
        thread = Thread.query.filter(
            or_(Thread.user_id == current_user.id, Thread.user_id.is_(None))
        ).filter_by(id=int(tid)).first()
    note = Note(user_id=current_user.id,
                thread_id=thread.id if thread else None,
                title=title, content=content,
                tags=json.dumps(tags, ensure_ascii=False), version=1)
    changes = apply_rules(note)
    note.simhash = str(simhash(content))
    db.session.add(note)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': '保存失败'}), 500
    persist_md(note)
    dups = find_duplicates(note)
    warnings = ['检测到疑似重复笔记,点击查看'] if dups else []
    try:
        from app import log_operation
        extra = ('(' + ';'.join(changes) + ')') if changes else ''
        log_operation('note_create', note.title,
                      f'新建笔记 id={note.id} {extra}')
    except Exception:
        pass
    d = _note_dict(note)
    d['duplicates'] = dups
    return jsonify({'ok': True, 'note': d, 'warnings': warnings,
                    'duplicates': dups})


@notes_bp.route('/api/notes')
@login_required
def api_note_list():
    tid = request.args.get('thread_id', type=int)
    tag = request.args.get('tag', '')
    q = request.args.get('q', '').strip()
    query = Note.query.filter_by(user_id=current_user.id)
    if tid:
        query = query.filter_by(thread_id=tid)
    if tag:
        like_raw = f'%"{tag}"%'
        try:
            like_esc = '%' + json.dumps([tag])[1:-1] + '%'
        except Exception:
            like_esc = like_raw
        query = query.filter(or_(Note.tags.like(like_raw),
                                 Note.tags.like(like_esc)))
    if q:
        pat = f'%{q}%'
        query = query.filter(or_(Note.title.like(pat), Note.content.like(pat)))
    items = query.order_by(Note.created_at.desc()).limit(400).all()
    return jsonify({'ok': True, 'notes': [_note_dict(n, current_user.id)
                                          for n in items]})


@notes_bp.route('/api/notes/<int:note_id>', methods=['DELETE'])
@login_required
def api_del_note(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first()
    if not note:
        return jsonify({'ok': False, 'error': '笔记不存在'}), 404
    try:
        p = _note_md_path(note)
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass
    db.session.delete(note)
    db.session.commit()
    return jsonify({'ok': True})


@notes_bp.route('/api/notes/<int:note_id>', methods=['PUT'])
@login_required
def api_update_note(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first()
    if not note:
        return jsonify({'ok': False, 'error': '笔记不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'content' in data:
        note.content = data['content']
    if 'title' in data:
        note.title = data['title']
    if 'tags' in data:
        note.tags = json.dumps(build_tag_list(data['tags']), ensure_ascii=False)
    if 'thread_id' in data:
        note.thread_id = data['thread_id'] or None
    db.session.commit()
    persist_md(note)
    return jsonify({'ok': True, 'note': _note_dict(note)})


@notes_bp.route('/api/notes/<int:note_id>/dup')
@login_required
def api_note_dup(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first()
    dups = find_duplicates(note) if note else []
    return jsonify({'ok': True, 'duplicates': dups})


@notes_bp.route('/api/upload_image', methods=['POST'])
@login_required
def api_upload_note_image():
    """粘贴/拖拽图片:保存到 instance/notes/attachments/<uid>/,返回可引用 URL。"""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': '未获取到图片'}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _NOTE_IMAGE_EXT:
        mime = (f.mimetype or '').lower()
        if not mime.startswith('image/'):
            return jsonify({'ok': False, 'error': '仅支持图片文件'}), 400
        ext = '.png'
    try:
        from PIL import Image
        probe = Image.open(f.stream)
        probe.verify()
        f.stream.seek(0)
        if probe.format and ('.' + probe.format.lower()) in _NOTE_IMAGE_EXT:
            ext = '.' + probe.format.lower()
    except Exception:
        pass
    uid = str(current_user.id)
    target_dir = os.path.join(_NOTE_ATTACH_DIR, uid)
    try:
        os.makedirs(target_dir, exist_ok=True)
        name = uuid.uuid4().hex + ext
        f.save(os.path.join(target_dir, name))
    except Exception as e:
        logger.warning('note image save failed: %s', e)
        return jsonify({'ok': False, 'error': '图片保存失败'}), 500
    url = f'/notes/attachments/{uid}/{name}'
    return jsonify({'ok': True, 'url': url})


@notes_bp.route('/api/upload_attachment', methods=['POST'])
@login_required
def api_upload_note_attachment():
    """上传普通附件(word/ppt/pdf/excel/txt等),保存到 instance/notes/attachments/<uid>/。

    仅作为笔记附件保存,不入知识库;返回可引用/下载 URL。"""
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': '未获取到文件'}), 400
    orig_name = os.path.basename(f.filename) or 'attachment'
    ext = os.path.splitext(orig_name)[1].lower()
    if ext not in _NOTE_ATTACH_EXT:
        return jsonify({'ok': False,
                        'error': '不支持该文件类型,仅支持 doc/docx/ppt/pptx/pdf/xls/xlsx/txt/md/csv/zip 等'}), 400
    uid = str(current_user.id)
    target_dir = os.path.join(_NOTE_ATTACH_DIR, uid)
    try:
        os.makedirs(target_dir, exist_ok=True)
        name = uuid.uuid4().hex + ext
        f.save(os.path.join(target_dir, name))
    except Exception as e:
        logger.warning('note attachment save failed: %s', e)
        return jsonify({'ok': False, 'error': '文件保存失败'}), 500
    url = f'/notes/attachments/{uid}/{name}'
    return jsonify({'ok': True, 'url': url, 'name': orig_name})


@notes_bp.route('/attachments/<int:user_id>/<filename>')
@login_required
def serve_note_attachment(user_id, filename):
    """仅允许访问本人的笔记图片/附件。"""
    if user_id != current_user.id:
        return '', 403
    return send_from_directory(os.path.join(_NOTE_ATTACH_DIR, str(user_id)),
                               filename)