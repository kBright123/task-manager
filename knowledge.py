"""个人知识库模块(单文件版)。

组成:
- 配置: 路径/opencode 端点/模型,环境变量可覆盖
- OCR:  RapidOCR + pypdfium2 文本识别
- 嵌入: fastembed 中文向量
- 存储: SochDB 持久化/检索/图谱封装
- LLM:  opencode serve 客户端(三元组抽取 + 问答)
- 视图: Flask Blueprint 路由
- Worker: 后台处理进程(python knowledge.py)

模型类由 app.py 调用 init_models(db) 注入,避免循环导入。
"""
import json
import logging
import os
import re
import sqlite3
import sys
import time

import requests
from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

KB_ROOT = os.path.join(_PROJECT_ROOT, 'instance', 'kb_data')
KB_SOCHDB_PATH = os.environ.get('KB_SOCHDB_PATH', os.path.join(KB_ROOT, 'kb.soch'))
KB_NAMESPACE = 'kb'
KB_PAGES_COLLECTION = 'pages'

KB_EMBED_MODEL = os.environ.get('KB_EMBED_MODEL', 'BAAI/bge-small-zh-v1.5')

KB_OPENCODE_BASE_URL = os.environ.get('KB_OPENCODE_BASE_URL', 'http://127.0.0.1:4096')
KB_OPENCODE_PROVIDER = os.environ.get('KB_OPENCODE_PROVIDER', 'opencode')
KB_OPENCODE_MODEL = os.environ.get('KB_OPENCODE_MODEL', 'deepseek-v4-flash-free')
KB_OPENCODE_TIMEOUT = int(os.environ.get('KB_OPENCODE_TIMEOUT', '180'))
KB_LLM_DISABLED = os.environ.get('KB_LLM_DISABLED', '0') == '1'

KB_OCR_DPI_SCALE = float(os.environ.get('KB_OCR_DPI_SCALE', '2.0'))
KB_POLL_INTERVAL = float(os.environ.get('KB_POLL_INTERVAL', '3'))
KB_EXTRACT_PAGE_MAX_CHARS = int(os.environ.get('KB_EXTRACT_PAGE_MAX_CHARS', '2000'))
KB_ASK_TOP_K = int(os.environ.get('KB_ASK_TOP_K', '6'))
KB_ASK_GRAPH_DEPTH = int(os.environ.get('KB_ASK_GRAPH_DEPTH', '2'))
KB_ASK_TOKEN_LIMIT = int(os.environ.get('KB_ASK_TOKEN_LIMIT', '4000'))

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tif',
                      '.tiff', '.webp'}

STATUS_QUEUED = 'queued'
STATUS_OCR = 'ocr'
STATUS_EMBED = 'embedding'
STATUS_GRAPH = 'graphing'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'

# ---------------------------------------------------------------------------
# 模型(由 init_models(database) 注入,避免循环导入)
# ---------------------------------------------------------------------------

db = None
KbDocument = None
KbPage = None
KbEntity = None
KbTriple = None


def init_models(database):
    global db, KbDocument, KbPage, KbEntity, KbTriple
    db = database

    class _KbDocument(database.Model):
        __tablename__ = 'kb_document'
        id = database.Column(database.Integer, primary_key=True)
        title = database.Column(database.String(300), nullable=False)
        filename = database.Column(database.String(500), nullable=False)
        file_path = database.Column(database.String(500), nullable=False)
        file_type = database.Column(database.String(20), default='')
        file_size = database.Column(database.Integer, default=0)
        page_count = database.Column(database.Integer, default=0)
        status = database.Column(database.String(20), default=STATUS_QUEUED,
                                 index=True)
        error = database.Column(database.Text)
        uploaded_by = database.Column(database.Integer,
                                      database.ForeignKey('user.id'))
        created_at = database.Column(database.DateTime,
                                     default=__import__('datetime').datetime.utcnow)
        updated_at = database.Column(database.DateTime,
                                     default=__import__('datetime').datetime.utcnow,
                                     onupdate=__import__('datetime').datetime.utcnow)

        pages = database.relationship('_KbPage', backref='document',
                                      lazy='dynamic',
                                      cascade='all, delete-orphan')
        triples = database.relationship('_KbTriple', backref='document',
                                        lazy='dynamic',
                                        cascade='all, delete-orphan')

    class _KbPage(database.Model):
        __tablename__ = 'kb_page'
        id = database.Column(database.Integer, primary_key=True)
        doc_id = database.Column(database.Integer,
                                 database.ForeignKey('kb_document.id'),
                                 nullable=False, index=True)
        page_no = database.Column(database.Integer, nullable=False)
        text = database.Column(database.Text, default='')
        char_count = database.Column(database.Integer, default=0)

    class _KbEntity(database.Model):
        __tablename__ = 'kb_entity'
        id = database.Column(database.Integer, primary_key=True)
        name = database.Column(database.String(200), unique=True,
                               nullable=False)
        node_type = database.Column(database.String(50), default='entity')
        doc_id = database.Column(database.Integer,
                                 database.ForeignKey('kb_document.id'))
        created_at = database.Column(database.DateTime,
                                     default=__import__('datetime').datetime.utcnow)

    class _KbTriple(database.Model):
        __tablename__ = 'kb_triple'
        id = database.Column(database.Integer, primary_key=True)
        doc_id = database.Column(database.Integer,
                                 database.ForeignKey('kb_document.id'),
                                 nullable=False, index=True)
        page_no = database.Column(database.Integer, default=0)
        head = database.Column(database.String(200), nullable=False)
        rel = database.Column(database.String(200), nullable=False)
        tail = database.Column(database.String(200), nullable=False)
        head_type = database.Column(database.String(50), default='')
        tail_type = database.Column(database.String(50), default='')

    KbDocument, KbPage, KbEntity, KbTriple = _KbDocument, _KbPage, _KbEntity, _KbTriple


def enable_sqlite_wal():
    @event.listens_for(db.engine, 'connect')
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=10000')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.close()


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr import RapidOCR
        logging.getLogger('RapidOCR').setLevel(logging.WARNING)
        logger.info('loading RapidOCR engine...')
        _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_image(pil_image):
    import numpy as np
    arr = np.array(pil_image.convert('RGB'))
    result = _get_ocr_engine()(arr)
    if result is None:
        return ''
    return '\n'.join(t for t in result.txts if t and t.strip())


def render_pdf_pages(pdf_path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_path)
    n = len(pdf)
    for page_no in range(n):
        page = pdf[page_no]
        image = page.render(scale=KB_OCR_DPI_SCALE).to_pil()
        yield page_no + 1, image
    pdf.close()


def ocr_file(file_path):
    lower = file_path.lower()
    pages = []
    if lower.endswith('.pdf'):
        for page_no, image in render_pdf_pages(file_path):
            pages.append((page_no, ocr_image(image)))
    else:
        from PIL import Image
        image = Image.open(file_path)
        image.load()
        pages.append((1, ocr_image(image)))
    return pages


# ---------------------------------------------------------------------------
# 嵌入
# ---------------------------------------------------------------------------

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        logger.info('loading embedding model %s ...', KB_EMBED_MODEL)
        _embedder = TextEmbedding(model_name=KB_EMBED_MODEL)
    return _embedder


def embed_texts(texts):
    return [v.tolist() for v in get_embedder().embed(list(texts))]


def embed_text(text):
    return embed_texts([text])[0]


# ---------------------------------------------------------------------------
# SochDB 存储/检索/图谱
# ---------------------------------------------------------------------------

_sochdb = None


def get_db():
    global _sochdb
    if _sochdb is None:
        from sochdb.database import Database
        os.makedirs(os.path.dirname(KB_SOCHDB_PATH) or '.', exist_ok=True)
        _sochdb = Database.open_concurrent(KB_SOCHDB_PATH)
    return _sochdb


def ensure_schema():
    dbh = get_db()
    try:
        dbh.create_namespace(KB_NAMESPACE)
    except Exception:
        pass
    ns = dbh.namespace(KB_NAMESPACE)
    if KB_PAGES_COLLECTION not in ns.list_collections():
        from sochdb.namespace import CollectionConfig
        col = CollectionConfig(name=KB_PAGES_COLLECTION, dimension=512,
                               enable_hybrid_search=True,
                               content_field='text')
        ns.create_collection(col)
        logger.info('created collection %s', KB_PAGES_COLLECTION)
    return ns


def page_doc_id(doc_id, page_no):
    return f'd{doc_id}p{page_no}'


def doc_node_id(doc_id):
    return f'doc:{doc_id}'


def entity_node_id(name):
    return name.strip()


def upsert_page(doc_id, page_no, title, filename, text):
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    vec = embed_text(text or ' ')
    col.insert(id=page_doc_id(doc_id, page_no), vector=vec, content=text,
               metadata={
                   'text': text,
                   'doc_id': str(doc_id),
                   'page_no': str(page_no),
                   'title': title,
                   'filename': filename,
               })


def delete_page(doc_id, page_no):
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    try:
        col.delete(page_doc_id(doc_id, page_no))
    except Exception as e:
        logger.warning('delete_page %s failed: %s',
                       page_doc_id(doc_id, page_no), e)


def search_pages(query, k=10, alpha=0.5):
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    vec = embed_text(query)
    results = col.hybrid_search(vec, text_query=query, k=k, alpha=alpha)
    out = []
    for r in results.results:
        meta = r.metadata or {}
        out.append({
            'id': r.id,
            'score': r.score,
            'doc_id': int(meta.get('doc_id', 0) or 0),
            'page_no': int(meta.get('page_no', 0) or 0),
            'title': meta.get('title', ''),
            'filename': meta.get('filename', ''),
            'text': meta.get('text', ''),
        })
    return out


def add_doc_node(doc_id, title):
    get_db().add_node(KB_NAMESPACE, doc_node_id(doc_id), 'doc',
                      {'title': title, 'doc_id': str(doc_id)})


def add_entity_node(name, node_type, doc_id):
    get_db().add_node(KB_NAMESPACE, entity_node_id(name), node_type or 'entity',
                      {'doc_id': str(doc_id)})


def add_triple_edge(doc_id, page_no, triple):
    dbh = get_db()
    head = entity_node_id(triple['head'])
    tail = entity_node_id(triple['tail'])
    dbh.add_node(KB_NAMESPACE, head, triple.get('headType') or 'entity',
                 {'doc_id': str(doc_id)})
    dbh.add_node(KB_NAMESPACE, tail, triple.get('tailType') or 'entity',
                 {'doc_id': str(doc_id)})
    dbh.add_edge(KB_NAMESPACE, head, triple['rel'], tail,
                 {'doc_id': str(doc_id), 'page_no': str(page_no)})
    dbh.add_edge(KB_NAMESPACE, head, 'appears_in', doc_node_id(doc_id),
                 {'doc_id': str(doc_id)})
    dbh.add_edge(KB_NAMESPACE, tail, 'appears_in', doc_node_id(doc_id),
                 {'doc_id': str(doc_id)})


def delete_doc_graph(doc_id, triples):
    dbh = get_db()
    for t in triples:
        try:
            dbh.delete_edge(entity_node_id(t['head']), t['rel'],
                            entity_node_id(t['tail']), KB_NAMESPACE)
        except Exception as e:
            logger.warning('delete_edge failed: %s', e)
        try:
            dbh.delete_edge(entity_node_id(t['head']), 'appears_in',
                            doc_node_id(doc_id), KB_NAMESPACE)
        except Exception:
            pass
        try:
            dbh.delete_edge(entity_node_id(t['tail']), 'appears_in',
                            doc_node_id(doc_id), KB_NAMESPACE)
        except Exception:
            pass
    try:
        dbh.delete_node(doc_node_id(doc_id), KB_NAMESPACE)
    except Exception:
        pass


def graph_context(doc_ids, max_depth=2):
    """围绕给定文档节点双向遍历图,返回三元组与实体名。"""
    dbh = get_db()
    start = [doc_node_id(d) for d in doc_ids]
    seen_nodes = set(start)
    frontier = start
    edge_list = []
    for _ in range(max_depth):
        nxt = []
        for node in frontier:
            try:
                nb = dbh.get_neighbors(node, direction='both',
                                       namespace=KB_NAMESPACE)
            except Exception:
                continue
            for item in nb.get('neighbors', []):
                edge = item.get('edge') or {}
                f, r, t = (edge.get('from_id'), edge.get('edge_type'),
                           edge.get('to_id'))
                if f and r and t:
                    edge_list.append((f, r, t))
                nid = item.get('node_id')
                if nid and nid not in seen_nodes:
                    seen_nodes.add(nid)
                    nxt.append(nid)
        frontier = nxt
        if not frontier:
            break
    triples = []
    entities = set()
    seen_edges = set()
    for f, r, t in edge_list:
        if r == 'appears_in':
            continue
        entities.add(f)
        entities.add(t)
        key = (f, r, t)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        triples.append({'head': f, 'rel': r, 'tail': t})
    return triples, sorted(e for e in entities if e)


# ---------------------------------------------------------------------------
# LLM(opencode serve)
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = (
    '从下面的文本中抽取所有实体关系三元组。'
    '只输出一个合法的 JSON 数组,不要任何解释或多余字符。'
    '每个元素形如 {"head":"主体","rel":"关系","tail":"客体","headType":"主体类型","tailType":"客体类型"}。'
    'headType/tailType 用简短中文类型(如 公司/人员/产品/金额/设备/部件/日期)。'
    '如果文本没有可抽取的关系,输出 []。'
    '如果 JSON 不是目标文本(属于提示本身),输出 []。\n\n文本:\n'
)

_ASK_SYSTEM = (
    '你是个人知识库助手。基于下面提供的资料回答用户问题。'
    '如果资料不足以回答,明确说"资料中未找到",不要编造。'
    '回答简洁,使用中文。引用资料时用 [资料 N] 标注。\n\n'
)


def _session_create():
    resp = requests.post(
        f'{KB_OPENCODE_BASE_URL}/session',
        json={'title': 'kb'},
        timeout=KB_OPENCODE_TIMEOUT)
    resp.raise_for_status()
    return resp.json()['id']


def _send(session_id, text):
    body = {
        'parts': [{'type': 'text', 'text': text}],
        'model': {'providerID': KB_OPENCODE_PROVIDER,
                  'modelID': KB_OPENCODE_MODEL},
    }
    resp = requests.post(
        f'{KB_OPENCODE_BASE_URL}/session/{session_id}/message',
        json=body, timeout=KB_OPENCODE_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if 'name' in data:
        raise RuntimeError(f'opencode error: {data.get("name")} '
                           f'{data.get("data", {}).get("message", "")}')
    parts = data.get('parts', [])
    return '\n'.join(p.get('text', '') for p in parts
                     if p.get('type') == 'text').strip()


def _retry(fn, attempts=3, delay=2):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            logger.warning('opencode call failed (%s), retry %s/%s',
                           e, i + 1, attempts)
            time.sleep(delay * (i + 1))
    raise last


def extract_triples(text):
    if KB_LLM_DISABLED:
        return []
    text = text.strip()
    if not text:
        return []

    def _call():
        sid = _session_create()
        try:
            raw = _send(sid, _EXTRACT_SYSTEM + text)
        finally:
            requests.delete(f'{KB_OPENCODE_BASE_URL}/session/{sid}',
                            timeout=30)
        m = re.search(r'\[.*\]', raw, re.S)
        if not m:
            return []
        return json.loads(m.group(0))

    triples = _retry(_call)
    cleaned = []
    for t in triples or []:
        if not isinstance(t, dict):
            continue
        head = str(t.get('head', '')).strip()
        rel = str(t.get('rel', '')).strip()
        tail = str(t.get('tail', '')).strip()
        if not head or not rel or not tail:
            continue
        if len(head) > 100 or len(rel) > 100 or len(tail) > 100:
            continue
        cleaned.append({
            'head': head,
            'rel': rel,
            'tail': tail,
            'headType': str(t.get('headType', '实体')).strip() or '实体',
            'tailType': str(t.get('tailType', '实体')).strip() or '实体',
        })
    return cleaned


def llm_ask(question, sources):
    if KB_LLM_DISABLED:
        return 'LLM 服务已禁用(环境变量 KB_LLM_DISABLED=1)。'
    blocks = []
    for i, src in enumerate(sources, 1):
        blocks.append(f'[资料 {i}] {src.get("title", "")} '
                      f'(第{src.get("page", "-")}页):\n{src.get("text", "")}')
    prompt = _ASK_SYSTEM + '\n\n'.join(blocks) + f'\n\n问题:{question}\n'

    def _call():
        sid = _session_create()
        try:
            return _send(sid, prompt)
        finally:
            requests.delete(f'{KB_OPENCODE_BASE_URL}/session/{sid}',
                            timeout=30)

    return _retry(_call)


# ---------------------------------------------------------------------------
# Flask 蓝图
# ---------------------------------------------------------------------------

kb_bp = Blueprint('kb', __name__, url_prefix='/kb')


def _kb_upload_dir():
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'kb')
    os.makedirs(path, exist_ok=True)
    return path


@kb_bp.route('/')
@login_required
def index():
    docs = (KbDocument.query.order_by(KbDocument.created_at.desc())
            .limit(200).all())
    total_pages = db.session.query(
        db.func.sum(KbPage.char_count)).scalar() or 0
    triple_count = KbTriple.query.count()
    entity_count = KbEntity.query.count()
    return render_template('kb/index.html', docs=docs,
                           total_pages=total_pages, triple_count=triple_count,
                           entity_count=entity_count,
                           status_queued=STATUS_QUEUED)


@kb_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        flash('未选择文件', 'danger')
        return redirect(url_for('kb.index'))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        flash(f'不支持的文件类型 {ext}(支持: PDF/图片)', 'danger')
        return redirect(url_for('kb.index'))
    store_name = __import__('uuid').uuid4().hex + ext
    target = os.path.join(_kb_upload_dir(), store_name)
    f.save(target)
    title = os.path.splitext(f.filename)[0] or '未命名文档'
    doc = KbDocument(title=title, filename=f.filename, file_path=target,
                     file_type=ext.lstrip('.'), file_size=os.path.getsize(target),
                     status=STATUS_QUEUED, uploaded_by=current_user.id)
    db.session.add(doc)
    db.session.commit()
    flash(f'已加入识别队列: {title}', 'success')
    return redirect(url_for('kb.doc_detail', doc_id=doc.id))


@kb_bp.route('/<int:doc_id>')
@login_required
def doc_detail(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    pages = (KbPage.query.filter_by(doc_id=doc.id)
             .order_by(KbPage.page_no).all())
    triples = (KbTriple.query.filter_by(doc_id=doc.id)
               .order_by(KbTriple.id).all())
    entities = (KbEntity.query.filter_by(doc_id=doc.id)
                .order_by(KbEntity.id).all())
    return render_template('kb/doc_detail.html', doc=doc, pages=pages,
                           triples=triples, entities=entities)


@kb_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def doc_delete(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if doc:
        prior = [{'head': t.head, 'rel': t.rel, 'tail': t.tail,
                  'headType': t.head_type, 'tailType': t.tail_type}
                 for t in doc.triples]
        try:
            delete_doc_graph(doc.id, prior)
        except Exception:
            pass
        for p in doc.pages:
            delete_page(doc.id, p.page_no)
        if os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except OSError:
                pass
        db.session.delete(doc)
        db.session.commit()
        flash('文档已删除', 'success')
    return redirect(url_for('kb.index'))


@kb_bp.route('/<int:doc_id>/reprocess', methods=['POST'])
@login_required
def doc_reprocess(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if doc:
        doc.status = STATUS_QUEUED
        doc.error = None
        doc.updated_at = __import__('datetime').datetime.utcnow()
        db.session.commit()
        flash('已重新加入识别队列', 'info')
    return redirect(url_for('kb.doc_detail', doc_id=doc_id))


@kb_bp.route('/search')
@login_required
def search():
    q = (request.args.get('q') or '').strip()
    results = []
    triples = []
    if q:
        try:
            results = search_pages(q, k=20, alpha=0.5)
        except Exception as e:
            flash(f'搜索失败: {e}', 'danger')
        doc_ids = {r['doc_id'] for r in results[:8]}
        if doc_ids:
            triples, _ = graph_context(doc_ids, KB_ASK_GRAPH_DEPTH)
    return render_template('kb/search.html', q=q, results=results,
                           triples=triples)


@kb_bp.route('/ask', methods=['GET', 'POST'])
@login_required
def ask():
    question = ''
    answer = ''
    sources = []
    triples = []
    error = None
    if request.method == 'POST':
        question = (request.form.get('question') or '').strip()
        if not question:
            error = '请输入问题'
        else:
            try:
                hits = search_pages(question, k=KB_ASK_TOP_K, alpha=0.5)
                doc_ids = {r['doc_id'] for r in hits[:6]}
                triples, _ = graph_context(doc_ids, KB_ASK_GRAPH_DEPTH)
                sources = [{'title': h['title'], 'page': h['page_no'],
                            'text': h['text']} for h in hits]
                answer = llm_ask(question, sources)
            except Exception as e:
                error = f'问答失败: {e}'
    return render_template('kb/ask.html', question=question, answer=answer,
                           sources=sources, triples=triples, error=error)


@kb_bp.route('/status/<int:doc_id>')
@login_required
def status(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        return jsonify({'ok': False})
    return jsonify({'ok': True, 'status': doc.status, 'error': doc.error,
                    'page_count': doc.page_count})


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

DB_PATH = os.path.join(_PROJECT_ROOT, 'instance', 'tasks.db')


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def _claim_next(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute(
            "SELECT id, file_path, title, filename FROM kb_document "
            "WHERE status IN ('queued','failed') "
            "ORDER BY created_at ASC LIMIT 1").fetchone()
        if row:
            conn.execute(
                "UPDATE kb_document SET status=?, updated_at=datetime('now') "
                "WHERE id=?", (STATUS_OCR, row[0]))
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise


def _update_status(conn, doc_id, status, error=None, page_count=None):
    sql = "UPDATE kb_document SET status=?, updated_at=datetime('now')"
    params = [status]
    if error is not None:
        sql += ", error=?"
        params.append(error)
    if page_count is not None:
        sql += ", page_count=?"
        params.append(page_count)
    sql += " WHERE id=?"
    params.append(doc_id)
    conn.execute(sql, params)
    conn.commit()


def _process_document(conn, row):
    doc_id, file_path, title, filename = row
    try:
        _update_status(conn, doc_id, STATUS_OCR)
        logger.info('[doc %s] OCR: %s', doc_id, filename)
        pages = ocr_file(file_path)
        page_count = len(pages)

        _update_status(conn, doc_id, STATUS_EMBED, page_count=page_count)
        conn.execute("DELETE FROM kb_page WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM kb_triple WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM kb_entity WHERE doc_id=?", (doc_id,))
        conn.commit()

        for page_no, text in pages:
            if text.strip():
                upsert_page(doc_id, page_no, title, filename, text)
                conn.execute(
                    "INSERT INTO kb_page (doc_id, page_no, text, char_count) "
                    "VALUES (?,?,?,?)",
                    (doc_id, page_no, text, len(text)))
        conn.commit()

        _update_status(conn, doc_id, STATUS_GRAPH)
        all_triples = []
        for page_no, text in pages:
            snippet = text[:KB_EXTRACT_PAGE_MAX_CHARS].strip()
            if len(snippet) < 8:
                continue
            try:
                triples = extract_triples(snippet)
            except Exception as e:
                logger.warning('[doc %s] extract failed page %s: %s',
                               doc_id, page_no, e)
                triples = []
            for t in triples:
                conn.execute(
                    "INSERT INTO kb_triple (doc_id, page_no, head, rel, tail,"
                    " head_type, tail_type) VALUES (?,?,?,?,?,?,?)",
                    (doc_id, page_no, t['head'], t['rel'], t['tail'],
                     t['headType'], t['tailType']))
                conn.execute(
                    "INSERT OR IGNORE INTO kb_entity "
                    "(name, node_type, doc_id) VALUES (?,?,?)",
                    (t['head'], t['headType'], doc_id))
                conn.execute(
                    "INSERT OR IGNORE INTO kb_entity "
                    "(name, node_type, doc_id) VALUES (?,?,?)",
                    (t['tail'], t['tailType'], doc_id))
                all_triples.append(t)
        conn.commit()

        if all_triples:
            add_doc_node(doc_id, title)
            for t in all_triples:
                add_triple_edge(doc_id, 0, t)
            logger.info('[doc %s] graph: %d triples', doc_id,
                        len(all_triples))

        _update_status(conn, doc_id, STATUS_DONE)
        logger.info('[doc %s] done: %d pages, %d triples', doc_id,
                    page_count, len(all_triples))
    except Exception as e:
        logger.exception('[doc %s] failed', doc_id)
        _update_status(conn, doc_id, STATUS_FAILED, error=str(e))


def main():
    ensure_schema()
    conn = _connect()
    logger.info('knowledge.worker started, polling every %.1fs',
                KB_POLL_INTERVAL)
    while True:
        try:
            row = _claim_next(conn)
            if row:
                _process_document(conn, row)
            else:
                time.sleep(KB_POLL_INTERVAL)
        except Exception as e:
            logger.error('worker loop error: %s', e)
            time.sleep(KB_POLL_INTERVAL)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
