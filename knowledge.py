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
import datetime
import hashlib
import io
import json
import logging
import os
import re
import sqlite3
import sys
import time
import uuid
import zipfile

import requests
import markupsafe
from PIL import Image, ImageEnhance, ImageOps
from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask import Response
from flask import send_file
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
KB_OCR_MIN_SIDE = int(os.environ.get('KB_OCR_MIN_SIDE', '1200'))
KB_PDF_TEXT_MIN_CHARS = int(os.environ.get('KB_PDF_TEXT_MIN_CHARS', '20'))
KB_POLL_INTERVAL = float(os.environ.get('KB_POLL_INTERVAL', '3'))
KB_EXTRACT_PAGE_MAX_CHARS = int(os.environ.get('KB_EXTRACT_PAGE_MAX_CHARS', '2000'))
KB_ASK_TOP_K = int(os.environ.get('KB_ASK_TOP_K', '6'))
KB_ASK_TOKEN_LIMIT = int(os.environ.get('KB_ASK_TOKEN_LIMIT', '4000'))

KB_CACHE_PATH = os.environ.get('KB_CACHE_PATH',
                               os.path.join(KB_ROOT, 'cache.db'))
KB_SEARCH_CACHE_TTL = int(os.environ.get('KB_SEARCH_CACHE_TTL', '600'))
KB_ASK_CACHE_TTL = int(os.environ.get('KB_ASK_CACHE_TTL', '3600'))

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tif',
                      '.tiff', '.webp', '.txt', '.md', '.markdown'}

TEXT_EXTENSIONS = {'.txt', '.md', '.markdown'}

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
KbCollection = None


def init_models(database):
    global db, KbDocument, KbPage, KbEntity, KbTriple, KbCollection
    db = database

    class _KbCollection(database.Model):
        __tablename__ = 'kb_collection'
        id = database.Column(database.Integer, primary_key=True)
        name = database.Column(database.String(100), unique=True,
                               nullable=False)
        color = database.Column(database.String(20), default='#8b5cf6')
        created_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow)

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
        collection_id = database.Column(
            database.Integer, database.ForeignKey('kb_collection.id'))
        uploaded_by = database.Column(database.Integer,
                                      database.ForeignKey('user.id'))
        created_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow)
        updated_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow,
                                     onupdate=datetime.datetime.utcnow)

        collection = database.relationship('_KbCollection',
                                           backref='documents')
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
                                     default=datetime.datetime.utcnow)

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
    KbCollection = _KbCollection


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


def ocr_file(file_path):
    lower = file_path.lower()
    if lower.endswith('.pdf'):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(file_path)
        try:
            pages = []
            for page_no in range(len(pdf)):
                page = pdf[page_no]
                text = ''
                try:
                    tp = page.get_textpage()
                    text = (tp.get_text_range() or '').strip()
                    tp.close()
                except Exception as e:
                    logger.warning('pdf text extract page %s failed: %s',
                                   page_no + 1, e)
                if len(text.strip()) < KB_PDF_TEXT_MIN_CHARS:
                    image = page.render(scale=KB_OCR_DPI_SCALE).to_pil()
                    text = ocr_image(image)
                pages.append((page_no + 1, text))
            return pages
        finally:
            pdf.close()
    if lower.endswith(tuple(TEXT_EXTENSIONS)):
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return _chunk_text(content)
    image = Image.open(file_path)
    image.load()
    return [(1, ocr_image(image))]

def ocr_image(pil_image):
    import numpy as np
    engine = _get_ocr_engine()
    candidates = _ocr_candidates(pil_image)
    best, best_len, best_result = '', 0, None
    for cand in candidates:
        arr = np.array(cand.convert('RGB'))
        result = engine(arr)
        text = '' if result is None else '\n'.join(
            t for t in result.txts if t and t.strip())
        if len(text) > best_len:
            best, best_len, best_result = text, len(text), result
    marks = detect_option_marks(pil_image, best_result)
    if marks:
        annotation = '【选择题标记】 ' + ' '.join(
            f'{k}({v})' for k, v in sorted(marks.items()))
        best = (best + '\n\n' + annotation).strip()
    return best


def _ocr_candidates(pil_image):
    """生成多组 OCR 输入:原图(必要时放大) + 灰度 + 灰度对比度增强。"""
    img = pil_image.convert('RGB')
    width, height = img.size
    max_side = max(width, height)
    if max_side < KB_OCR_MIN_SIDE:
        scale = KB_OCR_MIN_SIDE / max_side
        img = img.resize((max(1, int(width * scale)),
                          max(1, int(height * scale))),
                         Image.LANCZOS)
    gray = ImageOps.grayscale(img)
    enhanced = ImageEnhance.Contrast(gray).enhance(1.8)
    candidates = [img, gray, enhanced]
    if width >= 1600 or height >= 1600:
        down = img.resize((max(1, width // 2), max(1, height // 2)),
                          Image.LANCZOS)
        candidates.append(down)
    return candidates


# ---------------------------------------------------------------------------
# 选择题勾选标记检测(✓/●/○/☑/√ 等)
# ---------------------------------------------------------------------------

_OPTION_RE = re.compile(r'^[A-Ha-h]\s*[.、)）:：]')

_MARKER_TEXT_CHARS = '✓✔√☑☒●◉○◎■□◆◇×✗✘'


def detect_option_marks(pil_image, result):
    """识别选择题选项前的勾选标记。

    对 OCR 识别出的每个"选项行"(如 A. xxx),在其文字框左侧区域内查找
    实心圆/勾等图形标记,返回 {选项字母: '勾选'|'实心圆'|'空心圆'} 字典。
    """
    if result is None:
        return {}
    boxes = getattr(result, 'boxes', None)
    txts = getattr(result, 'txts', None)
    if boxes is None or txts is None:
        return {}
    try:
        import numpy as np
        import cv2
    except ImportError:
        return {}
    gray = np.array(pil_image.convert('L'))
    marks = {}
    for box, txt in zip(boxes, txts):
        txt = (txt or '').strip()
        m = _OPTION_RE.match(txt)
        if not m:
            continue
        letter = txt[0].upper()
        pts = np.array(box, dtype=np.int32)
        x1, y1 = pts[:, 0].min(), pts[:, 1].min()
        x2, y2 = pts[:, 0].max(), pts[:, 1].max()
        h = max(2, y2 - y1)
        w = max(2, x2 - x1)
        margin = int(h * 0.4)
        marker = _find_marker(gray, x1 - int(h * 2.2), x1 + margin,
                              y1 - margin, y2 + margin, h)
        if marker is None and txt[1:2] in ' .、)）:：':
            marker = _find_marker(gray, x1, x1 + int(h * 1.4),
                                  y1 - margin, y2 + margin, h)
        if marker:
            marks[letter] = marker
    return marks


def _find_marker(gray, xa, xb, ya, yb, text_h):
    """在给定区域内查找实心圆/空心圆/勾标记,返回标记类型或 None。"""
    import numpy as np
    import cv2
    if xb <= xa or yb <= ya:
        return None
    xa = max(0, xa)
    ya = max(0, ya)
    region = gray[ya:yb, xa:xb]
    if region.size == 0:
        return None
    _, thresh = cv2.threshold(region, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, _, stats, _ = cv2.connectedComponentsWithStats(thresh, 8)
    best = None
    for i in range(1, n):
        cx, cy, cw, ch, area = stats[i]
        if area < 40:
            continue
        if ch < max(5, text_h * 0.5) or ch > text_h * 1.6:
            continue
        if cw < max(4, text_h * 0.4) or cw > text_h * 2.2:
            continue
        fill = area / max(1, cw * ch)
        if fill < 0.15:
            continue
        if best is None or area > best[0]:
            best = (area, cx, cy, cw, ch, fill)
    if best is None:
        return None
    area, cx, cy, cw, ch, fill = best
    aspect = cw / max(1, ch)
    if 0.6 <= aspect <= 1.6 and cw <= text_h * 1.4:
        if fill >= 0.5:
            return '实心圆'
        if fill >= 0.28:
            return '空心圆'
    return '勾选'


def _chunk_text(content, max_chars=1200):
    """把纯文本/Markdown 按段落切块,每页约 max_chars 字符。"""
    content = (content or '').strip()
    if not content:
        return []
    paragraphs = re.split(r'\n\s*\n', content)
    pages = []
    buf = ''
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= max_chars:
            buf = (buf + '\n\n' + para).strip() if buf else para
        else:
            if buf:
                pages.append(buf)
            buf = para
            while len(buf) > max_chars:
                pages.append(buf[:max_chars])
                buf = buf[max_chars:]
    if buf:
        pages.append(buf)
    return [(i + 1, text) for i, text in enumerate(pages)]


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


def make_snippet(text, query, radius=140):
    """截取 query 命中位置附近的文本片段,并高亮关键词。返回安全 HTML。"""
    text = text or ''
    terms = [t for t in query.split() if t] or [query]
    pos = -1
    for t in terms:
        idx = text.find(t)
        if idx >= 0 and (pos < 0 or idx < pos):
            pos = idx
    if pos < 0:
        start, end = 0, min(len(text), radius * 2)
        prefix = ''
    else:
        start = max(0, pos - radius)
        end = min(len(text), pos + len(terms[0]) + radius)
        prefix = '…' if start > 0 else ''
    snippet = prefix + text[start:end]
    if end < len(text):
        snippet += '…'
    escaped = markupsafe.escape(snippet)
    for t in terms:
        if not t:
            continue
        escaped = escaped.replace(
            markupsafe.escape(t),
            f'<mark>{markupsafe.escape(t)}</mark>')
    return markupsafe.Markup(escaped)


def group_results(results, query, max_pages_per_doc=3):
    """把分页结果按文档聚合,生成带高亮片段的展示结构。"""
    groups = {}
    for r in results:
        g = groups.setdefault(r['doc_id'], {
            'doc_id': r['doc_id'],
            'title': r['title'],
            'filename': r['filename'],
            'best_score': 0.0,
            'pages': [],
        })
        g['best_score'] = max(g['best_score'], r['score'] or 0)
        if len(g['pages']) < max_pages_per_doc:
            g['pages'].append({
                'page_no': r['page_no'],
                'score': r['score'],
                'snippet': make_snippet(r['text'], query),
            })
    groups = list(groups.values())
    groups.sort(key=lambda g: g['best_score'], reverse=True)
    for g in groups:
        g['pages'].sort(key=lambda p: p['score'], reverse=True)
    return groups


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


def build_graph_data(max_docs=200, max_triples=3000):
    """从知识库关系表收集实体/文档节点与关系边,构建前端图数据。"""
    nodes = []
    edges = []
    seen_edges = set()

    docs = (KbDocument.query.filter_by(status=STATUS_DONE)
            .order_by(KbDocument.created_at.desc()).limit(max_docs).all())
    doc_ids = [d.id for d in docs]
    for d in docs:
        nodes.append({'id': f'doc:{d.id}', 'label': d.title, 'type': 'doc',
                      'doc_id': d.id})

    triples = (KbTriple.query.filter(KbTriple.doc_id.in_(doc_ids))
               .order_by(KbTriple.id).limit(max_triples).all())
    nodes_by_name = {}

    def _ensure_entity(name):
        nid = name.strip()
        if not nid or nid in nodes_by_name:
            return nid
        ent = KbEntity.query.filter_by(name=nid).first()
        ntype = ent.node_type if ent else 'entity'
        nodes_by_name[nid] = True
        nodes.append({'id': nid, 'label': nid, 'type': ntype})
        return nid

    for t in triples:
        head = _ensure_entity(t.head)
        tail = _ensure_entity(t.tail)
        key = (head, t.rel, tail)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append({'from': head, 'to': tail, 'label': t.rel})
        edges.append({'from': head, 'to': f'doc:{t.doc_id}', 'label': '来源'})
        edges.append({'from': tail, 'to': f'doc:{t.doc_id}', 'label': '来源'})
    return {'nodes': nodes, 'edges': edges}


# ---------------------------------------------------------------------------
# 检索 / 问答缓存(SQLite 持久化,TTP 失效)
# ---------------------------------------------------------------------------

def _cache_conn():
    os.makedirs(os.path.dirname(KB_CACHE_PATH) or '.', exist_ok=True)
    conn = sqlite3.connect(KB_CACHE_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('CREATE TABLE IF NOT EXISTS kb_cache ('
                 'key TEXT PRIMARY KEY, value TEXT NOT NULL, '
                 'created_at REAL NOT NULL)')
    return conn


def cache_key(prefix, query):
    digest = hashlib.sha256(query.encode('utf-8')).hexdigest()
    return f'{prefix}:{digest}'


def cache_get(key, ttl):
    try:
        conn = _cache_conn()
        try:
            row = conn.execute(
                'SELECT value, created_at FROM kb_cache WHERE key=?',
                (key,)).fetchone()
            if not row:
                return None
            if time.time() - row[1] > ttl:
                conn.execute('DELETE FROM kb_cache WHERE key=?', (key,))
                conn.commit()
                return None
            return row[0]
        finally:
            conn.close()
    except Exception as e:
        logger.warning('cache_get failed: %s', e)
        return None


def cache_set(key, value):
    try:
        conn = _cache_conn()
        try:
            conn.execute(
                'INSERT OR REPLACE INTO kb_cache (key, value, created_at) '
                'VALUES (?,?,?)', (key, value, time.time()))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning('cache_set failed: %s', e)


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


def llm_ask(question, sources, system=None):
    if KB_LLM_DISABLED:
        return 'LLM 服务已禁用(环境变量 KB_LLM_DISABLED=1)。'
    blocks = []
    for i, src in enumerate(sources, 1):
        blocks.append(f'[资料 {i}] {src.get("title", "")} '
                      f'(第{src.get("page", "-")}页):\n{src.get("text", "")}')
    prompt = (system or _ASK_SYSTEM) + '\n\n'.join(blocks) + \
        f'\n\n问题:{question}\n'

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
    cid = request.args.get('collection', type=int)
    q = (request.args.get('q') or '').strip()
    page = request.args.get('page', 1, type=int)
    query = KbDocument.query
    if cid:
        query = query.filter_by(collection_id=cid)
    if q:
        like = f'%{q}%'
        query = query.filter(
            KbDocument.title.ilike(like) | KbDocument.filename.ilike(like))
    pagination = db.paginate(
        query.order_by(KbDocument.created_at.desc()),
        page=page, per_page=10, error_out=False)
    docs = pagination.items
    collections = KbCollection.query.order_by(KbCollection.name).all()

    doc_ids = [d.id for d in docs]
    previews = {}
    if doc_ids:
        for pid, text in (db.session.query(KbPage.doc_id, KbPage.text)
                          .filter(KbPage.doc_id.in_(doc_ids),
                                  KbPage.page_no == 1).all()):
            previews[pid] = text.strip()
    return render_template('kb/index.html', docs=docs,
                           q=q, page=page, pagination=pagination,
                           collections=collections, active_collection=cid,
                           previews=previews)


@kb_bp.route('/workbench')
@login_required
def workbench():
    q = (request.args.get('q') or '').strip()
    return render_template('kb/workbench.html', q=q)


@kb_bp.route('/api/ask', methods=['POST'])
@login_required
def api_ask():
    """工作台 AI 回答:检索 + LLM 生成 Markdown 答案与引用来源(带缓存)。"""
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'ok': False, 'error': '请输入问题'}), 400
    key = cache_key('ask', question)
    cached = cache_get(key, KB_ASK_CACHE_TTL)
    if cached is not None:
        return jsonify({'ok': True, 'cached': True,
                        **json.loads(cached)})
    try:
        hits = search_pages(question, k=KB_ASK_TOP_K, alpha=0.5)
        sources = [{'title': h['title'], 'page': h['page_no'],
                    'doc_id': h['doc_id'], 'text': h['text']} for h in hits]
        answer = llm_ask(question, sources)
        payload = {'answer': answer, 'sources': sources[:5]}
        cache_set(key, json.dumps(payload, ensure_ascii=False))
        return jsonify({'ok': True, 'cached': False, **payload})
    except Exception as e:
        logger.exception('api_ask failed')
        return jsonify({'ok': False, 'error': str(e)}), 500


@kb_bp.route('/api/search', methods=['POST'])
@login_required
def api_search():
    """工作台关键词检索:按文档分组的 JSON 结果(含高亮片段,带缓存)。"""
    data = request.get_json(silent=True) or {}
    q = (data.get('q') or '').strip()
    if not q:
        return jsonify({'ok': False, 'error': '请输入关键词'}), 400
    key = cache_key('search', q)
    cached = cache_get(key, KB_SEARCH_CACHE_TTL)
    if cached is not None:
        return jsonify({'ok': True, 'cached': True,
                        **json.loads(cached)})
    try:
        results = search_pages(q, k=30, alpha=0.5)
        groups = group_results(results, q)
        payload = {'groups': groups}
        cache_set(key, json.dumps(payload, ensure_ascii=False))
        return jsonify({'ok': True, 'cached': False, **payload})
    except Exception as e:
        logger.exception('api_search failed')
        return jsonify({'ok': False, 'error': str(e)}), 500


@kb_bp.route('/api/suggest')
@login_required
def api_suggest():
    """搜索框自动补全:实体名 + 文档标题。"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'items': []})
    like = f'%{q}%'
    names = (KbEntity.query.filter(KbEntity.name.like(like))
             .order_by(KbEntity.name).limit(8).all())
    titles = (KbDocument.query.filter(KbDocument.title.like(like))
              .order_by(KbDocument.created_at.desc()).limit(4).all())
    items = [n.name for n in names] + [t.title for t in titles]
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return jsonify({'items': out[:12]})


@kb_bp.route('/api/queue')
@login_required
def api_queue():
    """后台处理队列统计(供批量导入状态轮询)。"""
    rows = db.session.query(KbDocument.status, db.func.count()).group_by(
        KbDocument.status).all()
    counts = {s: 0 for s in [STATUS_QUEUED, STATUS_OCR, STATUS_EMBED,
                              STATUS_GRAPH, STATUS_DONE, STATUS_FAILED]}
    for status, n in rows:
        counts[status] = n
    processing = sum(counts[s] for s in [STATUS_QUEUED, STATUS_OCR,
                                         STATUS_EMBED, STATUS_GRAPH])
    return jsonify({'ok': True, 'counts': counts, 'processing': processing,
                    'total': sum(counts.values())})


@kb_bp.route('/api/entity')
@login_required
def api_entity():
    """实体详情:类型 + 相关三元组 + 关联文档。"""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': '缺少实体名'}), 400
    ent = KbEntity.query.filter_by(name=name).first()
    triples = (KbTriple.query.filter(
        (KbTriple.head == name) | (KbTriple.tail == name))
        .order_by(KbTriple.id.desc()).limit(50).all())
    triple_list = [{'head': t.head, 'rel': t.rel, 'tail': t.tail,
                    'head_type': t.head_type, 'tail_type': t.tail_type}
                   for t in triples]
    doc_ids = {t.doc_id for t in triples}
    docs = (KbDocument.query.filter(KbDocument.id.in_(doc_ids))
            .all() if doc_ids else [])
    return jsonify({'ok': True, 'name': name,
                    'node_type': ent.node_type if ent else 'entity',
                    'triples': triple_list,
                    'docs': [{'id': d.id, 'title': d.title} for d in docs]})


# ---------------------------------------------------------------------------
# 集合(Collection)管理
# ---------------------------------------------------------------------------

@kb_bp.route('/api/collections')
@login_required
def api_collections():
    cols = (KbCollection.query.order_by(KbCollection.name).all())
    out = []
    for c in cols:
        doc_count = KbDocument.query.filter_by(
            collection_id=c.id).count()
        out.append({'id': c.id, 'name': c.name, 'color': c.color,
                    'doc_count': doc_count})
    return jsonify({'ok': True, 'collections': out})


@kb_bp.route('/api/collections', methods=['POST'])
@login_required
def api_collection_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    color = (data.get('color') or '#8b5cf6').strip()
    if not name:
        return jsonify({'ok': False, 'error': '请输入集合名称'}), 400
    if KbCollection.query.filter_by(name=name).first():
        return jsonify({'ok': False, 'error': '集合名称已存在'}), 400
    c = KbCollection(name=name, color=color)
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'collection': {'id': c.id, 'name': c.name,
                                               'color': c.color,
                                               'doc_count': 0}})


@kb_bp.route('/api/collections/<int:cid>', methods=['PUT'])
@login_required
def api_collection_update(cid):
    c = db.session.get(KbCollection, cid)
    if not c:
        return jsonify({'ok': False, 'error': '集合不存在'}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or c.name).strip()
    color = (data.get('color') or c.color).strip()
    dup = KbCollection.query.filter(KbCollection.name == name,
                                    KbCollection.id != cid).first()
    if dup:
        return jsonify({'ok': False, 'error': '集合名称已存在'}), 400
    c.name, c.color = name, color
    db.session.commit()
    return jsonify({'ok': True, 'collection': {'id': c.id, 'name': c.name,
                                               'color': c.color}})


@kb_bp.route('/api/collections/<int:cid>', methods=['DELETE'])
@login_required
def api_collection_delete(cid):
    c = db.session.get(KbCollection, cid)
    if not c:
        return jsonify({'ok': False, 'error': '集合不存在'}), 404
    KbDocument.query.filter_by(collection_id=cid).update(
        {KbDocument.collection_id: None})
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})


@kb_bp.route('/api/collections/assign', methods=['POST'])
@login_required
def api_collection_assign():
    data = request.get_json(silent=True) or {}
    doc_ids = [int(x) for x in (data.get('doc_ids') or [])]
    collection_id = data.get('collection_id')
    if not doc_ids:
        return jsonify({'ok': False, 'error': '请选择文档'}), 400
    if collection_id is not None:
        c = db.session.get(KbCollection, collection_id)
        if not c:
            return jsonify({'ok': False, 'error': '集合不存在'}), 404
    KbDocument.query.filter(KbDocument.id.in_(doc_ids)).update(
        {KbDocument.collection_id: collection_id})
    db.session.commit()
    return jsonify({'ok': True})


@kb_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    files = request.files.getlist('file')
    files = [f for f in files if f and f.filename]
    if not files:
        flash('未选择文件', 'danger')
        return redirect(url_for('kb.index'))
    added = []
    rejected = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            rejected.append(f'{f.filename}({ext})')
            continue
        store_name = uuid.uuid4().hex + ext
        target = os.path.join(_kb_upload_dir(), store_name)
        f.save(target)
        title = os.path.splitext(f.filename)[0] or '未命名文档'
        doc = KbDocument(title=title, filename=f.filename, file_path=target,
                         file_type=ext.lstrip('.'),
                         file_size=os.path.getsize(target),
                         status=STATUS_QUEUED, uploaded_by=current_user.id)
        db.session.add(doc)
        added.append(title)
    db.session.commit()
    if added:
        flash(f'已加入识别队列 {len(added)} 个文件: {", ".join(added)}', 'success')
    if rejected:
        flash(f'跳过不支持的文件: {", ".join(rejected)}'
              '(仅支持 PDF/图片/Markdown/文本)', 'warning')
    return redirect(url_for('kb.index'))


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
        doc.updated_at = datetime.datetime.utcnow()
        db.session.commit()
        flash('已重新加入识别队列', 'info')
    return redirect(url_for('kb.doc_detail', doc_id=doc_id))


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

def _doc_text(doc):
    pages = (KbPage.query.filter_by(doc_id=doc.id)
             .order_by(KbPage.page_no).all())
    if doc.file_type in ('txt', 'md', 'markdown'):
        head = [f'# {doc.title}\n\n']
    else:
        head = []
    body = [f'\n\n<!-- 第 {p.page_no} 页 -->\n\n{p.text}' for p in pages]
    return ''.join(head) + ''.join(body)


def _safe_filename(name):
    name = re.sub(r'[^\w\u4e00-\u9fff\-\. ]+', '_', name)
    return (name or 'document').strip() or 'document'


@kb_bp.route('/export/<int:doc_id>')
@login_required
def export_doc(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    text = _doc_text(doc)
    ext = 'md' if doc.file_type in ('md', 'markdown') else 'txt'
    resp = Response(text, mimetype='text/plain; charset=utf-8')
    resp.headers['Content-Disposition'] = (
        f'attachment; filename="{_safe_filename(doc.title)}.{ext}"')
    return resp


@kb_bp.route('/export/graph')
@login_required
def export_graph():
    data = build_graph_data(max_docs=500, max_triples=20000)
    payload = {
        'exported_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'entity_count': len(data['nodes']),
        'relation_count': len(data['edges']),
        'nodes': data['nodes'],
        'edges': data['edges'],
    }
    resp = Response(json.dumps(payload, ensure_ascii=False, indent=2),
                    mimetype='application/json')
    resp.headers['Content-Disposition'] = (
        'attachment; filename="knowledge-graph.json"')
    return resp


@kb_bp.route('/export/all')
@login_required
def export_all():
    docs = KbDocument.query.order_by(KbDocument.id).all()
    payload = {'exported_at':
               datetime.datetime.utcnow().isoformat() + 'Z',
               'documents': [{
                   'id': d.id, 'title': d.title, 'filename': d.filename,
                   'file_type': d.file_type, 'page_count': d.page_count,
                   'status': d.status, 'created_at':
                   d.created_at.isoformat() + 'Z' if d.created_at else None,
                   'collection': d.collection.name if d.collection else None,
                   'text': _doc_text(d)} for d in docs]}
    resp = Response(json.dumps(payload, ensure_ascii=False, indent=2),
                    mimetype='application/json')
    resp.headers['Content-Disposition'] = (
        'attachment; filename="knowledge-export.json"')
    return resp


@kb_bp.route('/export/txt')
@login_required
def export_txt():
    """批量导出所选文档的 OCR 识别结果,每篇一个 .txt 打包为 zip。"""
    ids = request.args.get('ids', '')
    doc_ids = [int(x) for x in ids.split(',') if x.strip().isdigit()]
    if not doc_ids:
        flash('请选择文档', 'warning')
        return redirect(url_for('kb.index'))
    docs = (KbDocument.query.filter(KbDocument.id.in_(doc_ids))
            .order_by(KbDocument.id).all())
    if not docs:
        flash('所选文档不存在', 'warning')
        return redirect(url_for('kb.index'))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for d in docs:
            name = f'{d.id}_{_safe_filename(d.title)}.txt'
            zf.writestr(name, _doc_text(d))
    buf.seek(0)
    resp = Response(buf.getvalue(), mimetype='application/zip')
    resp.headers['Content-Disposition'] = (
        'attachment; filename="knowledge-ocr-txt.zip"')
    return resp


# ---------------------------------------------------------------------------
# 批量操作
# ---------------------------------------------------------------------------

@kb_bp.route('/bulk', methods=['POST'])
@login_required
def bulk():
    data = request.get_json(silent=True) or {}
    action = data.get('action') or ''
    doc_ids = [int(x) for x in (data.get('doc_ids') or [])]
    if not doc_ids:
        return jsonify({'ok': False, 'error': '请选择文档'}), 400
    docs = (KbDocument.query.filter(KbDocument.id.in_(doc_ids))
            .all())
    if action == 'delete':
        for doc in docs:
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
        return jsonify({'ok': True, 'deleted': len(docs)})
    if action == 'reprocess':
        now = datetime.datetime.utcnow()
        for doc in docs:
            doc.status = STATUS_QUEUED
            doc.error = None
            doc.updated_at = now
        db.session.commit()
        return jsonify({'ok': True, 'requeued': len(docs)})
    if action == 'export':
        payload = {'exported_at':
                   datetime.datetime.utcnow().isoformat() + 'Z',
                   'documents': [{
                       'id': d.id, 'title': d.title, 'filename': d.filename,
                       'file_type': d.file_type, 'page_count': d.page_count,
                       'status': d.status, 'created_at':
                       d.created_at.isoformat() + 'Z' if d.created_at else None,
                       'collection': d.collection.name
                       if d.collection else None,
                       'text': _doc_text(d)} for d in docs]}
        resp = Response(json.dumps(payload, ensure_ascii=False, indent=2),
                        mimetype='application/json')
        resp.headers['Content-Disposition'] = (
            'attachment; filename="knowledge-selection.json"')
        return resp
    return jsonify({'ok': False, 'error': f'未知操作: {action}'}), 400


@kb_bp.route('/search')
@login_required
def search():
    q = (request.args.get('q') or '').strip()
    return redirect(url_for('kb.workbench', q=q))


@kb_bp.route('/ask', methods=['GET', 'POST'])
@login_required
def ask():
    q = (request.form.get('question') or
         request.args.get('q') or '').strip()
    return redirect(url_for('kb.workbench', q=q))


@kb_bp.route('/status/<int:doc_id>')
@login_required
def status(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        return jsonify({'ok': False})
    return jsonify({'ok': True, 'status': doc.status, 'error': doc.error,
                    'page_count': doc.page_count})


@kb_bp.route('/preview/<int:doc_id>')
@login_required
def preview(doc_id):
    """原始文件预览:图片返回原图,PDF 渲染指定页为图片,文本返回原文。"""
    doc = db.session.get(KbDocument, doc_id)
    if not doc or not os.path.exists(doc.file_path):
        return jsonify({'ok': False, 'error': '文件不存在'}), 404
    ftype = (doc.file_type or '').lower()
    if ftype in ('pdf',):
        page = max(1, request.args.get('page', 1, type=int))
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(doc.file_path)
        try:
            if page > len(pdf):
                return jsonify({'ok': False, 'error': '页码超出范围'}), 400
            image = pdf[page - 1].render(scale=2.0).to_pil()
        finally:
            pdf.close()
        buf = io.BytesIO()
        image.convert('RGB').save(buf, format='PNG')
        buf.seek(0)
        return Response(buf, mimetype='image/png',
                        headers={'Cache-Control': 'public, max-age=3600'})
    if ftype in TEXT_EXTENSIONS:
        with open(doc.file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        resp = Response(content, mimetype='text/plain; charset=utf-8')
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp
    return send_file(doc.file_path, conditional=True)


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
