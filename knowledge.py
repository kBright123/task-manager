"""个人知识库模块(单文件版)。

组成:
- 配置: 路径/opencode 端点/模型,环境变量可覆盖
- OCR:  RapidOCR + pypdfium2 文本识别
- 嵌入: fastembed 中文向量
- 存储: SochDB 持久化/检索封装
- LLM:  opencode serve 客户端(问答)
- 视图: Flask Blueprint 路由
- Worker: 后台处理进程(python knowledge.py)

模型类由 app.py 调用 init_models(db) 注入,避免循环导入。
"""
import datetime
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import sys
import time
import uuid
from types import SimpleNamespace

import requests
import markupsafe
from PIL import Image, ImageOps
from flask import (Blueprint, Response, abort, current_app, flash, jsonify,
                   redirect, render_template, request, url_for)
from flask import send_file
from flask_login import current_user, login_required
from sqlalchemy import event, func

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
# 低资源模式:禁用 fastembed 向量嵌入 + SochDB 向量库,检索降级为 SQLite 关键词匹配
KB_VECTOR_DISABLED = os.environ.get('KB_VECTOR_DISABLED', '0') == '1'

KB_OCR_DPI_SCALE = float(os.environ.get('KB_OCR_DPI_SCALE', '2.0'))
KB_OCR_MIN_SIDE = int(os.environ.get('KB_OCR_MIN_SIDE', '1200'))
KB_OCR_MERGE_SHORT_MAX = int(
    os.environ.get('KB_OCR_MERGE_SHORT_MAX', '8'))
KB_PDF_TEXT_MIN_CHARS = int(os.environ.get('KB_PDF_TEXT_MIN_CHARS', '20'))
KB_POLL_INTERVAL = float(os.environ.get('KB_POLL_INTERVAL', '3'))
KB_SUMMARY_MAX_CHARS = int(os.environ.get('KB_SUMMARY_MAX_CHARS', '2000'))
KB_ASK_TOP_K = int(os.environ.get('KB_ASK_TOP_K', '6'))
KB_ASK_TOKEN_LIMIT = int(os.environ.get('KB_ASK_TOKEN_LIMIT', '4000'))
KB_MAX_DOC_ATTEMPTS = int(os.environ.get('KB_MAX_DOC_ATTEMPTS', '3'))
KB_STALE_QUEUE_HOURS = int(os.environ.get('KB_STALE_QUEUE_HOURS', '6'))

KB_CACHE_PATH = os.environ.get('KB_CACHE_PATH',
                               os.path.join(KB_ROOT, 'cache.db'))
KB_SEARCH_CACHE_TTL = int(os.environ.get('KB_SEARCH_CACHE_TTL', '600'))
KB_ASK_CACHE_TTL = int(os.environ.get('KB_ASK_CACHE_TTL', '3600'))
KB_AUTO_SUMMARY = os.environ.get('KB_AUTO_SUMMARY', '1') == '1'

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tif',
                      '.tiff', '.webp', '.txt', '.md', '.markdown', '.html', '.htm'}
TEXT_EXTENSIONS = {'.txt', '.md', '.markdown'}

# 常见文件魔数(文件头),用于拦截"伪装成图片/文档的可执行文件"。
_HEADER_SIGNATURES = {
    '.pdf': (b'%PDF',),
    '.png': (b'\x89PNG',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.gif': (b'GIF87a', b'GIF89a'),
    '.bmp': (b'BM',),
    '.tif': (b'II*\x00', b'MM\x00*'),
    '.tiff': (b'II*\x00', b'MM\x00*'),
    '.webp': (b'RIFF',),
    '.doc': (b'\xd0\xcf\x11\xe0', b'PK\x03\x04'),
    '.docx': (b'PK\x03\x04',),
    '.xls': (b'\xd0\xcf\x11\xe0',),
    '.xlsx': (b'PK\x03\x04',),
    '.zip': (b'PK\x03\x04',),
}
_TEXT_HEADER_EXTS = ('.txt', '.md', '.markdown', '.html', '.htm')


def file_content_matches(filename, head):
    """零依赖魔数校验:扩展名必须与文件内容一致。

    head: 文件头字节(建议读取 8KB,兼顾文本类 NUL 检查)。
    策略:
    - 文本类扩展名:前 8KB 含 NUL 字节视为二进制伪装,拒绝。
    - 有魔数定义的二进制类型:头部必须匹配,否则拒绝(拦截伪装可执行文件)。
    - 无法校验的扩展名(如 .rar):保持原扩展名白名单策略,放行。
    """
    ext = os.path.splitext(filename or '')[1].lower()
    if ext in _TEXT_HEADER_EXTS:
        return b'\x00' not in head
    if ext == '.webp':
        return head[:4] == b'RIFF' and head[8:12] == b'WEBP'
    sigs = _HEADER_SIGNATURES.get(ext)
    if not sigs:
        return True
    return any(head.startswith(s) for s in sigs)

STATUS_QUEUED = 'queued'
STATUS_OCR = 'ocr'
STATUS_EMBED = 'embedding'
# 图谱阶段已移除;STATUS_GRAPH 仅用于复位旧版本遗留的 graphing 状态文档
STATUS_GRAPH = 'graphing'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'

# ---------------------------------------------------------------------------
# 模型(由 init_models(database) 注入,避免循环导入)
# ---------------------------------------------------------------------------

db = None
KbDocument = None
KbPage = None
KbCollection = None
KbPoint = None
KbPointRel = None
KbPointRef = None


def init_models(database):
    global db, KbDocument, KbPage, KbCollection, KbPoint, KbPointRel, KbPointRef
    db = database

    class _KbCollection(database.Model):
        __tablename__ = 'kb_collection'
        id = database.Column(database.Integer, primary_key=True)
        name = database.Column(database.String(100), unique=True,
                               nullable=False)
        color = database.Column(database.String(20), default='#8b5cf6')
        visibility = database.Column(database.String(10),
                                       default='private')
        owner_id = database.Column(database.Integer,
                                     database.ForeignKey('user.id'))
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
        attempts = database.Column(database.Integer, default=0)
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
        last_recognition_at = database.Column(database.DateTime)
        last_recognition_type = database.Column(database.String(20))
        last_recognition_result = database.Column(database.String(20))
        recognition_count = database.Column(database.Integer, default=0)
        cancel = database.Column(database.Integer, default=0)
        auto_classified = database.Column(database.Integer, default=0)

        collection = database.relationship('_KbCollection',
                                           backref='documents')
        pages = database.relationship('_KbPage', backref='document',
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

    class _KbPoint(database.Model):
        __tablename__ = 'kb_point'
        id = database.Column(database.Integer, primary_key=True)
        doc_id = database.Column(database.Integer,
                                 database.ForeignKey('kb_document.id'),
                                 nullable=False, index=True)
        title = database.Column(database.String(300), nullable=False)
        content = database.Column(database.Text, default='')
        page_start = database.Column(database.Integer, default=0)
        page_end = database.Column(database.Integer, default=0)
        word_count = database.Column(database.Integer, default=0)
        sort_order = database.Column(database.Integer, default=0)
        created_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow)

    class _KbPointRel(database.Model):
        __tablename__ = 'kb_point_rel'
        id = database.Column(database.Integer, primary_key=True)
        src_point_id = database.Column(
            database.Integer, database.ForeignKey('kb_point.id'),
            nullable=False, index=True)
        dst_point_id = database.Column(
            database.Integer, database.ForeignKey('kb_point.id'),
            nullable=False, index=True)
        rel_type = database.Column(database.String(20), default='similar')
        score = database.Column(database.Float, default=0.0)
        created_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow)

    class _KbPointRef(database.Model):
        __tablename__ = 'kb_point_ref'
        id = database.Column(database.Integer, primary_key=True)
        point_id = database.Column(
            database.Integer, database.ForeignKey('kb_point.id'),
            nullable=False, index=True)
        target_type = database.Column(database.String(20), default='')
        target_id = database.Column(database.Integer, default=0)
        created_at = database.Column(database.DateTime,
                                     default=datetime.datetime.utcnow)

    KbDocument, KbPage = _KbDocument, _KbPage
    KbCollection = _KbCollection
    KbPoint = _KbPoint
    KbPointRel = _KbPointRel
    KbPointRef = _KbPointRef


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


def _html_to_text(content):
    """从 HTML 中提取可读正文:去掉 script/style/标签,块级标签换行。

    使用标准库 html.parser,避免引入额外依赖。
    """
    from html.parser import HTMLParser

    block_tags = {
        'p', 'div', 'br', 'li', 'ul', 'ol', 'tr', 'section', 'article',
        'header', 'footer', 'aside', 'nav', 'h1', 'h2', 'h3', 'h4', 'h5',
        'h6', 'blockquote', 'pre', 'table', 'figure', 'figcaption', 'hr',
        'form', 'table',
    }
    skip_tags = {'script', 'style', 'noscript', 'template'}

    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
            self.skip_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag in skip_tags:
                self.skip_depth += 1
                return
            if tag in block_tags:
                self.parts.append('\n')

        def handle_endtag(self, tag):
            if tag in skip_tags:
                if self.skip_depth:
                    self.skip_depth -= 1
                return
            if tag in block_tags:
                self.parts.append('\n')

        def handle_data(self, data):
            if self.skip_depth:
                return
            self.parts.append(data)

    parser = _Extractor()
    try:
        parser.feed(content)
        parser.close()
    except Exception:
        logger.warning('html parse fail, fallback to raw', exc_info=True)
    raw = ''.join(parser.parts)
    lines = [ln.strip() for ln in raw.split('\n')]
    lines = [ln for ln in lines if ln]
    return '\n'.join(lines)


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
    if lower.endswith(('.html', '.htm')):
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return _chunk_text(_html_to_text(content))
    image = Image.open(file_path)
    image.load()
    return [(1, ocr_image(image))]

def ocr_image(pil_image):
    import numpy as np
    engine = _get_ocr_engine()
    cand = _ocr_candidates(pil_image)[0]
    arr = np.array(cand.convert('RGB'))
    result = engine(arr)
    best = '' if result is None else '\n'.join(
        t for t in result.txts if t and t.strip())
    best = _dedupe_lines(best)
    marks = detect_option_marks(pil_image, result)
    if marks:
        annotation = '【选择题标记】 ' + ' '.join(
            f'{k}({v})' for k, v in sorted(marks.items()))
        best = (best + '\n\n' + annotation).strip()
    return best


def _dedupe_lines(text):
    """清理 OCR 行:去掉重复识别的行,并把连续短行合并成一行。

    截图类文档的状态栏/按钮等碎片文字(如 "13:445G"、"交卷")常被 OCR
    拆成多行,这里把彼此相邻的短行合并,减少碎片化换行;长段落保持原样。"""
    max_len = KB_OCR_MERGE_SHORT_MAX
    seen = set()
    out = []
    for raw in text.split('\n'):
        line = raw.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        if out and len(line) <= max_len and len(out[-1]) <= max_len:
            out[-1] = out[-1] + ' ' + line
        else:
            out.append(line)
    return '\n'.join(out)


def _ocr_candidates(pil_image):
    """生成 OCR 输入:原图(必要时放大)灰度化,单路候选。

    只跑一次 RapidOCR 推理,避免多候选(原图/灰度/增强)重复 ONNX 推理打满 CPU。"""
    img = pil_image.convert('RGB')
    width, height = img.size
    max_side = max(width, height)
    if max_side < KB_OCR_MIN_SIDE:
        scale = KB_OCR_MIN_SIDE / max_side
        img = img.resize((max(1, int(width * scale)),
                          max(1, int(height * scale))),
                         Image.LANCZOS)
    return [ImageOps.grayscale(img)]


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
# 知识点拆解(文档级 -> 知识点级)
# ---------------------------------------------------------------------------

KB_POINT_MIN_CHARS = int(os.environ.get('KB_POINT_MIN_CHARS', '150'))
KB_POINT_MAX_CHARS = int(os.environ.get('KB_POINT_MAX_CHARS', '2200'))
KB_POINT_SIM_THRESHOLD = float(os.environ.get('KB_POINT_SIM_THRESHOLD', '0.3'))
KB_POINT_MAX_REL = int(os.environ.get('KB_POINT_MAX_REL', '8'))

_MD_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s+(.*)$')
_NUM_HEADING_RE = re.compile(
    r'^\s*((?:第\s*[0-9一二三四五六七八九十百千]+[章节篇部分条卷项]'
    r')|[0-9]+[、.．](?!\d)|[一二三四五六七八九十]+[、.])\s*(.*)$')
_SENT_END = set('。；;！？!…—')

# ---- 题库/试卷类文档识别(单选题/多选题/判断/简答等按题号拆点) ----
_Q_SECT_RE = re.compile(
    r'^\s*(?:[0-9０-９一二三四五六七八九十]+[、.．]\s*)?'
    r'(单选题|单项选择题|多选题|多项选择题|判断题|填空题|简答题|问答题|'
    r'名词解释题?|案例分析题?|计算题|论述题|综合题|选择题|配伍题|写作题|阅读题)')
_Q_NUM_RE = re.compile(r'^\s*[0-9０-９]{1,3}\s*[、.．]\s*\S')
_Q_PAREN_RE = re.compile(r'^\s*[（(]\s*[0-9０-９]{1,3}\s*[）)]\s*\S')
_Q_CN_RE = re.compile(r'^\s*第\s*[0-9０-９一二三四五六七八九十百]{1,3}\s*题\s*\S')
_ANS_HEAD_RE = re.compile(
    r'^\s*[【\[]?\s*(参考答案|正确答案|标准答案|答案)\s*[】\]]?\s*[:：]?\s*$')
_ANS_INLINE_RE = re.compile(
    r'^\s*[【\[]?\s*(参考答案|正确答案|标准答案|答案)\s*[】\]]?\s*[:：]?\s*\S')
_ANS_PAIR_RE = re.compile(r'[0-9０-９]{1,3}\s*[、.．\-~]?\s*[A-Ha-h]+')
_ANS_OPT_RE = re.compile(r'^\s*[A-Ha-h]\s*[、.．]\s*\S')


def _is_heading_line(line):
    """判断一行是否像章节标题(结构识别:markdown 标题/编号标题/短行)。"""
    line = (line or '').strip()
    if not line or len(line) > 40:
        return False
    if _MD_HEADING_RE.match(line):
        return True
    m = _NUM_HEADING_RE.match(line)
    if m and m.group(2):
        return True
    # 纯短行且不以句末标点结尾,可作标题候选(需有下一行正文佐证)
    if len(line) <= 24 and line[-1] not in '。；;！？!、，,:.：:':
        return True
    return False


def _clean_heading(line):
    s = (line or '').strip()
    s = re.sub(r'^#+\s*', '', s)
    s = re.sub(r'^\s*[0-9]+[、.．]\s*|[一二三四五六七八九十]+[、.]\s*', '', s)
    s = re.sub(r'^第\s*[0-9一二三四五六七八九十百千]+[章节篇部分条卷项]\s*', '', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(' 　·:：.。')
    return _clean_point_title(s)


# 知识点标题前导噪音(截图/答题界面 OCR 残留):时间、信号/电量、页码进度、
# 题号编号、纯大写短串(如 CD/WIFI)、答题界面文字、分隔符
_LEAD_JUNK_TOKEN_RE = re.compile(
    r'^(?:'
    r'\d{1,2}[:：]\d{2}(?:[:：]\d{2})?'                 # 时间 11:45 / 00:27:14
    r'|(?:\.\d+|\d+(?:\.\d+)?)[Gg]'                    # 信号/流量 .5G / 4G
    r'|\d{1,3}%'                                       # 电量 80%
    r'|\d{1,3}[/|]\d{1,3}'                             # 页码/进度 4|6 / 4/6
    r'|[0-9０-９]{1,3}[、.．)）]'                      # 编号 1. 2、 (3)
    r'|第[0-9０-９一二三四五六七八九十]{1,3}[题页]'     # 第1题 / 第2页
    r'|[A-Z]{1,4}(?=[ 　])'                            # 纯大写短串 CD / WIFI
    r'|交卷|已交卷|上一题|下一题|答题卡|拍照|摄像头|加载中|'
    r'开始考试|开始答题|进入考试|考试中|已暂停|已结束|跳过|'
    r'提交答案|已作答'
    r'|[—–\-_=·|｜:：;；,，.。、]+'                    # 分隔符/标点
    r'|\s+'
    r')'
)


def _clean_point_title(title):
    """去除知识点标题前导噪音(编号/时间/信号电量/答题界面文字等)。"""
    s = (title or '').strip()
    prev = None
    while prev != s:
        prev = s
        s = _LEAD_JUNK_TOKEN_RE.sub('', s, count=1)
    s = s.strip(' 　·:：.。;；,，、|-—–_')
    if not s:
        return (title or '').strip()[:80] or '未命名知识点'
    return s[:80]


def _para_bigrams(text):
    """字符 2/3-gram 集合,用于无标题文档的语义边界检测与相似度。"""
    t = re.sub(r'\s+', '', (text or '').lower())
    grams = set()
    for k in (2, 3):
        for i in range(len(t) - k + 1):
            grams.add(t[i:i + k])
    return grams


# 高频功能字:含这些字的 bigram 降权,降低“的/了/在”等噪音
_STOP_CHARS = set(
    '的了在在与和或及为要需应可由对从到按经后前时中内上下第个项条'
    '每年月日之者也而并且是有不无须将被于啊哦嗯它他她这那并等两多'
    '起出所就都又很也都就个'.replace(' ', ''))


def _content_grams(text):
    """中文内容特征:清洗后取字符 bigram,含功能字者降权。"""
    t = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', (text or '').lower())
    grams = {}
    for i in range(len(t) - 1):
        g = t[i:i + 2]
        w = 1.0
        if g[0] in _STOP_CHARS:
            w *= 0.4
        if g[1] in _STOP_CHARS:
            w *= 0.4
        grams[g] = grams.get(g, 0.0) + w
    return grams


def _split_paragraphs(pages):
    """pages: [(page_no, text)] -> [(page_no, para)] 段落流(带页码)。"""
    out = []
    for pno, text in pages:
        for para in re.split(r'\n\s*\n', text or ''):
            para = para.strip()
            if para:
                out.append((pno, para))
    return out


def _texttiling_boundaries(paras, min_chars, max_chars):
    """TextTiling 简化版:按相邻段落 n-gram 重叠度找低相似边界,贪心分组。

    返回切分后的段落索引组(列表的列表)。保证每块 >= min_chars,尽量 <= max_chars。
    """
    if not paras:
        return []
    sizes = [len(t) for _, t in paras]
    grams = [_para_bigrams(t) for _, t in paras]
    # 相邻段落相似度(重叠率),低者更可能是边界
    overlap = [0.0] * (len(paras) - 1)
    for i in range(len(paras) - 1):
        a, b = grams[i], grams[i + 1]
        if not a or not b:
            continue
        inter = len(a & b)
        overlap[i] = inter / (len(a | b) or 1)
    groups = []
    start = 0
    cur = 0
    n = len(paras)
    while start < n:
        cur = start
        total = 0
        # 至少凑够 min_chars
        while cur < n and total < min_chars:
            total += sizes[cur]
            cur += 1
        if cur >= n:
            groups.append(list(range(start, n)))
            break
        end = cur
        total2 = sum(sizes[start:end])
        # 在 [start, n) 内尽量扩展至 max_chars,期间选最低重叠点为边界
        best = end  # 边界位于 best(段落号,边界=best-1|best)
        best_score = 1.0
        while end < n and total2 + sizes[end] <= max_chars:
            if overlap[end - 1] < best_score:
                best = end
                best_score = overlap[end - 1]
            total2 += sizes[end]
            end += 1
        if best <= start:
            best = min(end, n)
        groups.append(list(range(start, best)))
        start = best
    return groups


def _expand_lines(paras):
    """段落流展开为逐行流(题库识别需要按行判定题号/选项/答案)。"""
    out = []
    for pno, para in paras:
        for ln in para.split('\n'):
            ln = ln.strip()
            if ln:
                out.append((pno, ln))
    return out


def _question_bank_stats(lines):
    """统计题库特征:数字题号/括号题号/第N题/题型行/答案行。"""
    dot = paren = cn = sect = ans = 0
    for _, line in lines:
        s = line.strip()
        if not s:
            continue
        if _Q_NUM_RE.match(s):
            dot += 1
        elif _Q_PAREN_RE.match(s):
            paren += 1
        elif _Q_CN_RE.match(s):
            cn += 1
        if _Q_SECT_RE.match(s) and len(s) <= 30:
            sect += 1
        if _ANS_HEAD_RE.match(s) or _ANS_INLINE_RE.match(s):
            ans += 1
    return dot, paren, cn, sect, ans


def _looks_like_question_bank(lines):
    """题库/试卷特征判定:数字题号连续出现或题型+题号齐备。"""
    dot, paren, cn, sect, ans = _question_bank_stats(lines)
    if dot >= 3 or cn >= 3:
        return True
    if dot >= 2 and (sect >= 1 or ans >= 1):
        return True
    if sect >= 1 and (dot + paren) >= 3:
        return True
    return False


def _question_stem_head(line):
    return re.sub(r'\s{2,}', ' ', (line or '').strip())[:40]


def _split_questions(lines):
    """题库/试卷类文档:按题号切分,每题一个知识点(题干+选项+答案并入)。

    lines: [(page_no, line)]。题型行(单选题/多选题…)并入其后各题,集中
    「答案:1.A 2.C …」区整段跳过,避免把答案键误拆成题目。
    """
    points = []
    cur = []
    head_line = ''
    section = ''
    pending_section = ''
    preamble = []
    in_answer_key = False
    started = False

    def emit():
        nonlocal cur, head_line
        if not cur:
            return
        content = '\n'.join(t for _, t in cur).strip()
        if not content:
            cur, head_line = [], ''
            return
        pages_sorted = sorted(p for p, _ in cur)
        title = _clean_point_title(content[:36]) or '未命名知识点'
        if head_line:
            head = _clean_point_title(_question_stem_head(head_line))
            if head:
                title = _clean_point_title((section + ' ' + head).strip())[:44] or title
        points.append({
            'title': title,
            'content': content,
            'page_start': pages_sorted[0],
            'page_end': pages_sorted[-1],
            'word_count': len(content),
        })
        cur, head_line = [], ''

    for pno, line in lines:
        s = line.strip()
        if not s:
            continue
        # 集中答案区:「答案:」标题后的逐条答案/纯选项行整体跳过
        if in_answer_key:
            if _ANS_PAIR_RE.findall(s) or _ANS_OPT_RE.match(s) or len(s) <= 4:
                continue
            in_answer_key = False
        if _ANS_HEAD_RE.match(s):
            in_answer_key = True
            continue
        if _Q_NUM_RE.match(s) or _Q_PAREN_RE.match(s) or _Q_CN_RE.match(s):
            emit()
            if not started:
                cur = list(preamble)
                started = True
            if pending_section:
                section = pending_section
                pending_section = ''
            cur.append((pno, s))
            head_line = s
            continue
        if _Q_SECT_RE.match(s) and len(s) <= 30:
            pending_section = s
            if not started:
                preamble.append((pno, s))
            continue
        if not started:
            preamble.append((pno, s))
            continue
        cur.append((pno, s))

    emit()
    for i, pt in enumerate(points):
        pt['sort_order'] = i
    return points


def _split_knowledge_points(pages):
    """将文档页文本拆解为知识点列表。

    优先结构识别(markdown 标题/编号标题),无标题结构时退化为
    TextTiling 语义切分。返回 [{title, content, page_start, page_end,
    word_count, sort_order}]。
    """
    paras = _split_paragraphs(pages)
    if not paras:
        return []
    lines = _expand_lines(paras)
    if _looks_like_question_bank(lines):
        return _split_questions(lines)
    headings = [i for i, (_, t) in enumerate(paras) if _is_heading_line(t)]
    points = []

    def emit(lines):
        """lines: [(page_no, para)] -> 生成知识点 dict。"""
        if not lines:
            return
        content = '\n\n'.join(t for _, t in lines).strip()
        if not content:
            return
        title = None
        first = lines[0][1]
        if _is_heading_line(first):
            title = _clean_heading(first)
        pages_sorted = sorted(p for p, _ in lines)
        points.append({
            'title': title or _clean_point_title(content[:36]) or '未命名知识点',
            'content': content,
            'page_start': pages_sorted[0],
            'page_end': pages_sorted[-1],
            'word_count': len(content),
        })

    if headings:
        # 结构识别:以标题行为界
        cur = []
        for idx, (pno, para) in enumerate(paras):
            if _is_heading_line(para):
                # 结束上一个知识点
                emit(cur)
                cur = []
            cur.append((pno, para))
        emit(cur)
    else:
        # 语义切分兜底
        for group in _texttiling_boundaries(paras, KB_POINT_MIN_CHARS,
                                            KB_POINT_MAX_CHARS):
            lines = [paras[i] for i in group]
            content = '\n\n'.join(t for _, t in lines).strip()
            if not content:
                continue
            pages_sorted = sorted(p for p, _ in lines)
            points.append({
                'title': _clean_point_title(content[:36]) or '未命名知识点',
                'content': content,
                'page_start': pages_sorted[0],
                'page_end': pages_sorted[-1],
                'word_count': len(content),
            })

    # 结构模式下过滤过小碎片(与上一个合并),仅折叠极短残余(如 <40 字符的标题残留)
    merged = []
    for pt in points:
        if merged and pt['word_count'] < KB_POINT_MIN_CHARS // 4:
            prev = merged[-1]
            prev['content'] = prev['content'] + '\n\n' + pt['content']
            prev['word_count'] = len(prev['content'])
            prev['page_end'] = max(prev['page_end'], pt['page_end'])
        else:
            merged.append(pt)
    # 重算标题:内容空标题补充
    for pt in merged:
        if not pt['title'] or pt['title'] == '未命名知识点':
            pt['title'] = _clean_point_title(pt['content'][:36]) or '未命名知识点'
    for i, pt in enumerate(merged):
        pt['sort_order'] = i
    return merged


def _tfidf_cosine(points):
    """中文内容特征加权余弦相似度(纯 Python,无需分词库)。

    特征为清洗后的字符 bigram,含功能字的 bigram 降权;返回
    [(i, j, score)] 相似对(阈值过滤,每点最多 KB_POINT_MAX_REL 条)。
    """
    n = len(points)
    if n < 2:
        return []
    vectors = []
    for p in points:
        d = _content_grams(p.get('content') or '')
        vec = {}
        norm = 0.0
        for g, tf in d.items():
            vec[g] = tf
            norm += tf * tf
        norm = norm ** 0.5 or 1.0
        for g in vec:
            vec[g] /= norm
        vectors.append(vec)
    scores = {}
    for i in range(n):
        for j in range(i + 1, n):
            vi, vj = vectors[i], vectors[j]
            if len(vi) > len(vj):
                vi, vj = vj, vi
            s = 0.0
            for g, w in vi.items():
                wj = vj.get(g)
                if wj:
                    s += w * wj
            if s >= KB_POINT_SIM_THRESHOLD:
                scores[(i, j)] = s
    # 每点限流
    rels = []
    for (i, j), s in sorted(scores.items(), key=lambda kv: -kv[1]):
        rels.append((i, j, s))
    return rels


def _rebuild_points_for_doc(conn, doc_id, pages):
    """重建某文档的知识点与相似关联(供 worker 在识别后调用)。"""
    conn.execute('DELETE FROM kb_point_rel WHERE src_point_id IN '
                 '(SELECT id FROM kb_point WHERE doc_id=?) OR '
                 'dst_point_id IN (SELECT id FROM kb_point WHERE doc_id=?)',
                 (doc_id, doc_id))
    conn.execute('DELETE FROM kb_point_ref WHERE point_id IN '
                 '(SELECT id FROM kb_point WHERE doc_id=?)', (doc_id,))
    conn.execute('DELETE FROM kb_point WHERE doc_id=?', (doc_id,))
    points = _split_knowledge_points(pages)
    ids = []
    for pt in points:
        cur = conn.execute(
            'INSERT INTO kb_point (doc_id, title, content, page_start, '
            'page_end, word_count, sort_order, created_at) '
            'VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
            (doc_id, pt['title'], pt['content'], pt['page_start'],
             pt['page_end'], pt['word_count'], pt['sort_order']))
        ids.append(cur.lastrowid)
        conn.commit()
    try:
        rels = _tfidf_cosine(points)
        # 每点最多 KB_POINT_MAX_REL 条关联(取相似度最高的)
        per_point = {}
        for i, j, s in rels:
            per_point.setdefault(i, []).append((j, s))
            per_point.setdefault(j, []).append((i, s))
        keep = set()
        for i, cands in per_point.items():
            cands.sort(key=lambda kv: -kv[1])
            for j, s in cands[:KB_POINT_MAX_REL]:
                a, b = (i, j) if i < j else (j, i)
                keep.add((a, b, s))
        for i, j, s in sorted(keep, key=lambda t: (t[0], t[1])):
            conn.execute(
                'INSERT INTO kb_point_rel (src_point_id, dst_point_id, '
                'rel_type, score) VALUES (?,?,?,?)',
                (ids[i], ids[j], 'similar', round(s, 4)))
            conn.commit()
    except Exception as e:
        logger.warning('[doc %s] point similarity failed: %s', doc_id, e)
    return len(points)


_KB_POINT_DDL = [
    ('kb_point',
     'CREATE TABLE IF NOT EXISTS kb_point ('
     'id INTEGER PRIMARY KEY AUTOINCREMENT, '
     'doc_id INTEGER NOT NULL, '
     'title TEXT NOT NULL, '
     'content TEXT, '
     'page_start INTEGER DEFAULT 0, '
     'page_end INTEGER DEFAULT 0, '
     'word_count INTEGER DEFAULT 0, '
     'sort_order INTEGER DEFAULT 0, '
     'created_at DATETIME DEFAULT CURRENT_TIMESTAMP)'),
    ('kb_point_rel',
     'CREATE TABLE IF NOT EXISTS kb_point_rel ('
     'id INTEGER PRIMARY KEY AUTOINCREMENT, '
     'src_point_id INTEGER NOT NULL, '
     'dst_point_id INTEGER NOT NULL, '
     'rel_type TEXT DEFAULT \'similar\', '
     'score REAL DEFAULT 0, '
     'created_at DATETIME DEFAULT CURRENT_TIMESTAMP)'),
    ('kb_point_ref',
     'CREATE TABLE IF NOT EXISTS kb_point_ref ('
     'id INTEGER PRIMARY KEY AUTOINCREMENT, '
     'point_id INTEGER NOT NULL, '
     'target_type TEXT DEFAULT \'\', '
     'target_id INTEGER DEFAULT 0, '
     'created_at DATETIME DEFAULT CURRENT_TIMESTAMP)'),
]


def _ensure_point_tables(conn):
    """确保知识点相关表存在(worker 进程在 Flask create_all 之前也可运行)。"""
    for name, ddl in _KB_POINT_DDL:
        conn.execute(ddl)
    cols = [r[1] for r in conn.execute('PRAGMA table_info(kb_point)')]
    if 'doc_id' in cols and cols.index('doc_id') > 0:
        try:
            conn.execute('CREATE INDEX IF NOT EXISTS idx_kb_point_doc '
                         'ON kb_point(doc_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_kb_point_rel_src '
                         'ON kb_point_rel(src_point_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_kb_point_rel_dst '
                         'ON kb_point_rel(dst_point_id)')
        except Exception:
            pass
    if 'created_at' in cols:
        try:
            conn.execute('UPDATE kb_point SET created_at=CURRENT_TIMESTAMP '
                         'WHERE created_at IS NULL')
        except Exception:
            pass
    conn.commit()


# ---------------------------------------------------------------------------
# 嵌入
# ---------------------------------------------------------------------------

_embedder = None


def get_embedder():
    global _embedder
    if KB_VECTOR_DISABLED:
        raise RuntimeError('KB_VECTOR_DISABLED=1,embedding disabled')
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
# SochDB 存储/检索
# ---------------------------------------------------------------------------

_sochdb = None


def get_db():
    global _sochdb
    if KB_VECTOR_DISABLED:
        raise RuntimeError('KB_VECTOR_DISABLED=1 sochdb disabled')
    if _sochdb is None:
        from sochdb.database import Database
        os.makedirs(os.path.dirname(KB_SOCHDB_PATH) or '.', exist_ok=True)
        _sochdb = Database.open_concurrent(KB_SOCHDB_PATH)
    return _sochdb


_schema_ready = False


def ensure_schema():
    global _schema_ready
    if KB_VECTOR_DISABLED:
        return None
    dbh = get_db()
    if not _schema_ready:
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
        _schema_ready = True
    return dbh.namespace(KB_NAMESPACE)


def page_doc_id(doc_id, page_no):
    return f'd{doc_id}p{page_no}'


def upsert_page(doc_id, page_no, title, filename, text):
    if KB_VECTOR_DISABLED:
        return
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


def upsert_pages_batch(doc_id, title, filename, pages):
    """一次批量嵌入并写入多页向量(避免每页一次模型推理)。"""
    if KB_VECTOR_DISABLED:
        return
    valid = [(page_no, text) for page_no, text in pages
             if text and text.strip()]
    if not valid:
        return
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    texts = [text for _, text in valid]
    vecs = embed_texts(texts)
    for (page_no, text), vec in zip(valid, vecs):
        col.insert(id=page_doc_id(doc_id, page_no), vector=vec, content=text,
                   metadata={
                       'text': text,
                       'doc_id': str(doc_id),
                       'page_no': str(page_no),
                       'title': title,
                       'filename': filename,
                   })


def delete_page(doc_id, page_no):
    if KB_VECTOR_DISABLED:
        return
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    try:
        col.delete(page_doc_id(doc_id, page_no))
    except Exception as e:
        logger.warning('delete_page %s failed: %s',
                       page_doc_id(doc_id, page_no), e)


def _db_conn():
    os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def keyword_search_pages(query, k=40):
    """SQLite 关键词检索(LIKE 子串匹配)。

    中文无需分词,任意长度子串都能命中,数千页毫秒级;用作 hybrid 检索的
    关键词腿,替代 SochDB 里逐查询全表扫描的 BM25(数百毫秒)。"""
    conn = _db_conn()
    try:
        q = (query or '').strip()
        if not q:
            return []
        terms = [t for t in re.split(r'[，,。\s]+', q) if t] or [q]
        terms = terms[:5]
        clauses, params = [], []
        for t in terms:
            escaped = (t.replace('\\', '\\\\').replace('%', '\\%')
                       .replace('_', '\\_'))
            clauses.append('(p.text LIKE ? ESCAPE \'\\\' OR d.title LIKE ? '
                           'ESCAPE \'\\\')')
            pat = '%' + escaped + '%'
            params += [pat, pat]
        rows = conn.execute(
            'SELECT p.doc_id, p.page_no, COALESCE(d.title, \'\'), '
            'COALESCE(d.filename, \'\'), p.text FROM kb_page p '
            'LEFT JOIN kb_document d ON d.id = p.doc_id '
            'WHERE ' + ' AND '.join(clauses) +
            ' ORDER BY p.doc_id, p.page_no LIMIT ?',
            params + [k * 4]).fetchall()
        out = []
        for doc_id, page_no, title, filename, text in rows:
            hay = (title or '') + '\n' + (text or '')
            hits, first = 0, len(hay)
            for t in terms:
                idx = hay.find(t)
                if idx >= 0:
                    hits += 1
                    first = min(first, idx)
            out.append({'doc_id': doc_id, 'page_no': page_no,
                        'title': title, 'filename': filename,
                        'text': text, 'score': float(hits)})
        out.sort(key=lambda r: (-r['score'], r['doc_id'], r['page_no']))
        return out[:k]
    finally:
        conn.close()


def keyword_search_points(query, k=12):
    """知识点关键词检索(LIKE 子串匹配),标题命中权重更高。

    统一检索等场景优先返回知识点结果;返回字段含 point_id/doc_id/
    title(已清理前导杂讯)/content/page_start/collection_name/score。"""
    conn = _db_conn()
    try:
        q = (query or '').strip()
        if not q:
            return []
        terms = [t for t in re.split(r'[，,。\s]+', q) if t] or [q]
        terms = terms[:5]
        clauses, params = [], []
        for t in terms:
            escaped = (t.replace('\\', '\\\\').replace('%', '\\%')
                       .replace('_', '\\_'))
            clauses.append('(p.title LIKE ? ESCAPE \'\\\' OR p.content LIKE ? '
                           'ESCAPE \'\\\')')
            pat = '%' + escaped + '%'
            params += [pat, pat]
        rows = conn.execute(
            'SELECT p.id, p.doc_id, p.title, p.content, p.page_start, '
            'COALESCE(d.title, \'\'), COALESCE(d.filename, \'\'), '
            'COALESCE(c.name, \'\') FROM kb_point p '
            'LEFT JOIN kb_document d ON d.id = p.doc_id '
            'LEFT JOIN kb_collection c ON c.id = d.collection_id '
            'WHERE ' + ' AND '.join(clauses) +
            ' ORDER BY p.sort_order LIMIT ?',
            params + [k * 3]).fetchall()
        out = []
        for pid, doc_id, title, content, page_start, doc_title, \
                filename, cname in rows:
            title = title or ''
            content = content or ''
            hits = sum(content.count(t) for t in terms)
            title_hits = sum(title.count(t) for t in terms)
            out.append({
                'point_id': pid, 'doc_id': doc_id,
                'title': _clean_point_title(title) or title,
                'doc_title': doc_title, 'filename': filename,
                'content': content, 'page_start': page_start,
                'collection_name': cname,
                'score': float(hits + 5 * title_hits),
            })
        out.sort(key=lambda r: (-r['score'], r['doc_id'], r['point_id']))
        return out[:k]
    finally:
        conn.close()


def _visible_doc_ids():
    """当前用户可访问的文档 ID 列表:管理员为全部,其余为公共集合+自己的文档。"""
    if current_user.role == 'admin':
        return None
    visible_cols = db.session.query(KbCollection.id).filter(
        db.or_(
            KbCollection.visibility == 'public',
            KbCollection.owner_id == current_user.id
        )
    )
    rows = db.session.query(KbDocument.id).filter(
        db.or_(
            KbDocument.uploaded_by == current_user.id,
            KbDocument.collection_id.in_(visible_cols)
        )
    ).all()
    return [r.id for r in rows]


def _doc_ids_for_user(user_id):
    """指定用户的文档范围:其本人集合(含私有)+ 公共集合 + 其上传文档。

    用于分身问答 @ 其他用户时,基于对方知识库回答。
    """
    cols = db.session.query(KbCollection.id).filter(
        db.or_(
            KbCollection.visibility == 'public',
            KbCollection.owner_id == user_id
        )
    )
    rows = db.session.query(KbDocument.id).filter(
        db.or_(
            KbDocument.uploaded_by == user_id,
            KbDocument.collection_id.in_(cols)
        )
    ).all()
    return [r.id for r in rows]


def _resolve_avatar_user(target_id):
    """解析 @ 目标用户,返回 (user, avatar_name);无效则返回 (None, None)。"""
    if not target_id:
        return None, None
    try:
        from app import User
    except Exception:
        User = None
    if User is None:
        return None, None
    try:
        target = User.query.filter_by(id=int(target_id)).first()
    except Exception:
        return None, None
    if target is None or getattr(target, 'is_disabled', False):
        return None, None
    return target, (target.name or target.username)


def _kb_user_list():
    """系统内非禁用用户列表(分身问答 @ 选择用)。"""
    try:
        from app import User
    except Exception:
        User = None
    if User is None:
        return []
    users = User.query.filter(
        db.or_(User.is_disabled == False, User.is_disabled.is_(None))  # noqa: E712
    ).order_by(User.name, User.username).all()
    return [{'id': u.id, 'username': u.username,
             'name': u.name or u.username} for u in users]


def search_pages(query, k=10, alpha=0.5, doc_ids=None):
    kw_res = keyword_search_pages(query, k=k)
    if doc_ids is not None:
        kw_res = [r for r in kw_res if r['doc_id'] in doc_ids]
    if KB_VECTOR_DISABLED:
        return [{'id': page_doc_id(r['doc_id'], r['page_no']), 'score': r['score'],
                 'doc_id': r['doc_id'], 'page_no': r['page_no'], 'title': r['title'],
                 'filename': r['filename'], 'text': r['text']} for r in kw_res]
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    vec = embed_text(query)
    pool_k = max(k * 3, 20)
    vec_res = col.vector_search(vec, k=pool_k)
    kw_res = keyword_search_pages(query, k=pool_k)
    rrf_k = 60
    scores = {}
    for rank, r in enumerate(vec_res.results):
        meta = r.metadata or {}
        did = int(meta.get('doc_id', 0) or 0)
        if doc_ids is not None and did not in doc_ids:
            continue
        key = page_doc_id(did, int(meta.get('page_no', 0) or 0))
        scores[key] = [alpha / (rrf_k + rank + 1),
                       (did, int(meta.get('page_no', 0) or 0),
                        meta.get('title', ''), meta.get('filename', ''),
                        meta.get('text', ''))]
    for rank, r in enumerate(kw_res):
        if doc_ids is not None and r['doc_id'] not in doc_ids:
            continue
        key = page_doc_id(r['doc_id'], r['page_no'])
        contrib = (1 - alpha) / (rrf_k + rank + 1)
        if key in scores:
            scores[key][0] += contrib
        else:
            scores[key] = [contrib, (r['doc_id'], r['page_no'],
                                     r['title'], r['filename'], r['text'])]
    merged = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)[:k]
    out = []
    for key, (score, (did, pno, title, filename, text)) in merged:
        out.append({'id': key, 'score': score, 'doc_id': did, 'page_no': pno,
                    'title': title, 'filename': filename, 'text': text})
    return out


_OCR_NOISE_RE = re.compile(
    r'^(?:'
    r'\d{1,2}:\d{2}(?::\d{2})?$|'           # 时间戳 13:39 / 00:29:27
    r'\d{1,3}\s*[/|｜]\s*\d{1,3}$|'          # 页码 1/6 1|6
    r'第?\s*\d+\s*页$|'
    r'(?:上一题|下一题|题卡|交卷|上一页|下一页|返回|确定|取消|上一项|下一项|保存|退出|开始答题|提交答案|答题卡|查看解析|收起)[:：]?$|'
    r'[\[【][^\]】]{1,30}[\]】]$|'            # 标记符号 【选择题标记】
    r'(?:单选题|多选题|判断题|填空题|问答题|案例分析题|材料题)[:：]?\s*\d*\s*分?$|'
    r'[A-E]\.?\s*$|'                         # 孤立选项字母
    r'\d+\.?\s*$|'                           # 孤立数字
    r'\d+\s*分$|'                            # 孤立得分 15分
    r'[-—•·*]\s*$'                           # 孤立分隔符
    r')'
)

# 行内的界面残留词:整词删除(不留空格)
_OCR_INLINE_WORDS = re.compile(
    r'(?:\d{1,2}:\d{2}(?::\d{2})?\s*|'        # 行内时间戳
    r'\d{1,3}\s*[/|｜]\s*\d{1,3}\s*|'          # 行内页码 1/6 1|6
    r'第?\s*\d+\s*页\s*|'
    r'(?:上一题|下一题|题卡|交卷|上一页|下一页|返回|确定|取消|上一项|下一项|保存|退出|开始答题|提交答案|答题卡|查看解析|收起)\s*|'
    r'[\[【][^\]】]{1,30}[\]】]\s*|'            # 标记符号
    r'(?:单选题|多选题|判断题|填空题|问答题|案例分析题|材料题)\s*)'  # 题型标签
)

def _clean_snippet_line(line):
    """去除 OCR 界面噪音(时间戳/页码/按钮文字等),保留正文。

    整行都是噪音 → 丢弃;行内含正文 → 只去掉行内的噪音词。
    对超长行按中文标点断句,使片段更易读。
    """
    s = line.strip()
    if not s:
        return ''
    if _OCR_NOISE_RE.match(s):
        return ''
    s = _OCR_INLINE_WORDS.sub('', s)
    s = re.sub(r'\s{2,}', ' ', s)
    s = s.strip()
    if not s:
        return ''
    # 超过 80 字符的长行按中文标点断句
    if len(s) > 80:
        s = re.sub(r'([。！？；])\s*', r'\1\n', s)
        s = re.sub(r'\n+', '\n', s)
    return s


def make_snippet(text, query, radius=140):
    """截取 query 命中位置附近的文本片段,并高亮关键词。返回安全 HTML。

    以换行为基本单元过滤 OCR 界面噪音,使片段按原文段落呈现。
    """
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
    raw = text[start:end]

    # 以换行为单元过滤噪音,并做 trim
    lines = [l for l in raw.split('\n') if l.strip()]
    kept = []
    for l in lines:
        cl = _clean_snippet_line(l)
        if cl:
            kept.append(cl)
    if kept:
        snippet = prefix + '\n'.join(kept)
    else:
        snippet = prefix + raw.strip()
    if end < len(text):
        snippet += '…'

    escaped = markupsafe.escape(snippet).replace('\n', '<br>')
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
                'text': r['text'][:2000],
            })
    groups = list(groups.values())
    groups.sort(key=lambda g: g['best_score'], reverse=True)
    top = groups[0]['best_score'] if groups else 0
    if top > 0:
        for g in groups:
            g['best_score'] /= top
            for p in g['pages']:
                p['score'] /= top
    for g in groups:
        g['pages'].sort(key=lambda p: p['score'], reverse=True)
    return groups


# ---------------------------------------------------------------------------
# 检索 / 问答缓存(SQLite 持久化,TTP 失效)
# ---------------------------------------------------------------------------

def _cache_conn():
    os.makedirs(os.path.dirname(KB_CACHE_PATH) or '.', exist_ok=True)
    conn = sqlite3.connect(KB_CACHE_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute('PRAGMA synchronous=NORMAL')
    if not getattr(_cache_conn, 'inited', False):
        conn.execute('CREATE TABLE IF NOT EXISTS kb_cache ('
                     'key TEXT PRIMARY KEY, value TEXT NOT NULL, '
                     'created_at REAL NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS kb_meta ('
                     'key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        conn.execute('CREATE TABLE IF NOT EXISTS kb_history ('
                     'id INTEGER PRIMARY KEY AUTOINCREMENT,'
                     'kind TEXT NOT NULL,'
                     'query TEXT NOT NULL,'
                     'user_id INTEGER DEFAULT 0,'
                     'count INTEGER DEFAULT 1,'
                     'last_at REAL NOT NULL)')
        migrated = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_kb_history_kind_query'").fetchone()
        if migrated:
            conn.execute('DROP INDEX idx_kb_history_kind_query')
            conn.execute('UPDATE kb_history SET '
                         'count=(SELECT SUM(count) FROM kb_history h2 '
                         'WHERE h2.query = kb_history.query), '
                         'last_at=(SELECT MAX(last_at) FROM kb_history h2 '
                         'WHERE h2.query = kb_history.query) '
                         'WHERE id IN (SELECT MIN(id) FROM kb_history GROUP BY query)')
            conn.execute('DELETE FROM kb_history WHERE id NOT IN '
                         '(SELECT MIN(id) FROM kb_history GROUP BY query)')
            conn.commit()
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_history_query '
                     'ON kb_history(query)')
        _cache_conn.inited = True
    return conn


_VERSIONED_CACHE_PREFIXES = {'search', 'ask', 'avatar'}


def cache_key(prefix, query):
    digest = hashlib.sha256(query.encode('utf-8')).hexdigest()
    if prefix in _VERSIONED_CACHE_PREFIXES:
        return f'{prefix}:v{_data_version()}:{digest}'
    return f'{prefix}:{digest}'


def _data_version():
    """知识库数据版本:文档增删/重识别会递增,并入缓存键使旧缓存自然失效。

    检索/问答缓存仅按 TTL 过期,文档重识别后旧命中会残留 KB_SEARCH_CACHE_TTL
    秒;在键中加入版本号可让数据一变旧缓存立即作废。"""
    try:
        conn = _cache_conn()
        try:
            row = conn.execute(
                'SELECT value FROM kb_meta WHERE key=?', ('data_version',)).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as e:
        logger.warning('_data_version failed: %s', e)
        return 0


def _bump_data_version():
    try:
        conn = _cache_conn()
        try:
            conn.execute(
                'INSERT INTO kb_meta (key, value) VALUES (?, 1) '
                'ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1',
                ('data_version',))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning('_bump_data_version failed: %s', e)


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


def record_history(kind, query):
    """Record a search/ask query into the history table (upsert by query,
    bumping a hit count and refreshing last_at)."""
    query = (query or '').strip()
    if not query:
        return
    try:
        conn = _cache_conn()
        try:
            uid = 0
            try:
                uid = current_user.id if current_user.is_authenticated else 0
            except Exception:
                uid = 0
            now = time.time()
            cur = conn.execute(
                'UPDATE kb_history SET count=count+1, last_at=? '
                'WHERE query=?', (now, query))
            if cur.rowcount == 0:
                conn.execute(
                    'INSERT INTO kb_history (kind, query, user_id, count, last_at) '
                    'VALUES (?,?,?,1,?)', (kind, query, uid, now))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning('record_history failed: %s', e)


def get_recent_questions(limit=5):
    """Most recently asked questions (across search + ask kinds)."""
    try:
        conn = _cache_conn()
        try:
            rows = conn.execute(
                'SELECT query, count FROM kb_history '
                'ORDER BY last_at DESC LIMIT ?', (limit,)).fetchall()
            return [{'query': r[0], 'count': r[1]} for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.warning('get_recent_questions failed: %s', e)
        return []


def get_recent_unified(user_id, limit=5):
    """首页统一检索的历史(仅该用户,最近 top N)。"""
    try:
        conn = _cache_conn()
        try:
            rows = conn.execute(
                'SELECT query FROM kb_history '
                'WHERE kind=? AND user_id=? '
                'ORDER BY last_at DESC LIMIT ?',
                ('unified', user_id, limit)).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()
    except Exception as e:
        logger.warning('get_recent_unified failed: %s', e)
        return []


# ---------------------------------------------------------------------------
# LLM(opencode serve)
# ---------------------------------------------------------------------------

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


_SUMMARY_SYSTEM = '请用 2-3 句话总结以下文档的核心内容。'


def _generate_summary(text):
    if KB_LLM_DISABLED:
        return ''
    text = (text or '').strip()
    if not text:
        return ''

    def _call():
        sid = _session_create()
        try:
            raw = _send(sid, _SUMMARY_SYSTEM + text)
        finally:
            requests.delete(f'{KB_OPENCODE_BASE_URL}/session/{sid}',
                            timeout=30)
        return raw.strip()

    try:
        return _retry(_call)
    except Exception:
        return ''


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


def _resolve_stored_path(stored):
    """兜底定位原始文件:upload 目录或卷挂载路径变化后仍能找到文件。

    KB 文件先后位于 <root>/instance/uploads/kb/(当前配置) 与
    <root>/static/uploads/kb/(旧配置);DB 中记录的绝对路径可能因目录
    迁移/卷挂载不一致而不存在,这里在两种布局下按文件名回退查找。"""
    if not stored or os.path.exists(stored):
        return stored
    base = os.path.basename(stored)
    prefix = stored.split('/uploads/')[0]
    root = os.path.dirname(prefix)
    candidates = []
    for sub in ('instance', 'static'):
        for rel in ('kb', ''):
            p = os.path.join(root, sub, 'uploads', rel, base)
            if p not in candidates:
                candidates.append(p)
    for c in candidates:
        if os.path.exists(c):
            return c
    return stored


def _is_admin():
    return (current_user.is_authenticated
            and getattr(current_user, 'role', None) == 'admin')


def _admin_required():
    """Flash a warning and return False when the caller is not an admin."""
    if _is_admin():
        return True
    flash('权限不足：仅管理员可进行文档管理操作', 'danger')
    return False


def _admin_required_json():
    """Same as _admin_required but for JSON/API endpoints returning 403."""
    if _is_admin():
        return True
    return jsonify({'ok': False, 'error': '权限不足：仅管理员可进行该操作'}), 403


def _can_manage_doc(doc):
    """当前用户能否管理某文档:管理员或上传者本人。"""
    return _is_admin() or doc.uploaded_by == current_user.id


def _manage_docs_for_user(doc_ids):
    """非管理员仅返回自己上传的文档 id。"""
    if _is_admin():
        return doc_ids
    rows = KbDocument.query.filter(
        KbDocument.id.in_(doc_ids),
        KbDocument.uploaded_by == current_user.id).all()
    return [d.id for d in rows]


def _log_op(action, target='', detail=''):
    """记录一条操作日志(延迟导入避免循环依赖)。"""
    try:
        from app import log_operation
        log_operation(action, target, detail)
    except Exception as e:
        logger.warning('_log_op failed: %s', e)


def _collection_doc_counts():
    """一次 GROUP BY 统计各集合文档数,替代逐集合访问 c.documents 的 N+1 查询。"""
    rows = db.session.query(
        KbDocument.collection_id,
        db.func.count(KbDocument.id)).group_by(KbDocument.collection_id).all()
    return {cid: cnt for cid, cnt in rows if cid is not None}


def _collection_groups(collections, active_cid, active_group='',
                       doc_counts=None):
    """把集合按一级类别分组,便于侧边栏折叠展示。

    primary 取「一级·二级」名称的首段;无分隔的集合归入「未分类」组。
    二级展示名经 classifier.short_subject 清理无效字符(JR∕T 0323— 等)
    并缩减长度。active_cid/active_group 用于展开并高亮当前所在组。"""
    from classifier import short_subject
    doc_counts = doc_counts or {}
    groups = {}
    for c in collections:
        parts = [p for p in (c.name or '').strip().split('·') if p]
        if len(parts) > 1:
            primary = parts[0]
            subject = short_subject('·'.join(parts[1:]))
        else:
            primary = ''
            subject = short_subject((c.name or '').strip())
        groups.setdefault(primary, []).append(
            {'primary': primary, 'subject': subject, 'c': c})
    out = []
    for p, items in sorted(groups.items(),
                           key=lambda kv: (kv[0] == '', kv[0])):
        out.append({
            'primary': p or '未分类',
            'items': items,
            'total': sum(doc_counts.get(v['c'].id, 0) for v in items),
            'active': any(active_cid == v['c'].id for v in items)
                      or bool(active_group and (p or '未分类') == active_group),
        })
    return out


@kb_bp.route('/')
@login_required
def index():
    """旧入口:统一跳转到工作台(文档管理只保留导航栏指向的 kb.workbench)。"""
    cid = request.args.get('collection', type=int)
    group = (request.args.get('group') or '').strip()
    q = (request.args.get('q') or '').strip()
    return redirect(url_for('kb.workbench', collection=cid,
                            group=group or None, q=q or None))


def _build_docs_query(cid, group, q):
    """构建当前用户可见的文档查询(可叠加 集合/分组/关键词 过滤)。"""
    query = KbDocument.query
    if current_user.role != 'admin':
        query = query.filter(
            db.or_(
                KbDocument.uploaded_by == current_user.id,
                KbDocument.collection_id.in_(
                    db.session.query(KbCollection.id)
                    .filter(KbCollection.visibility == 'public')
                )
            )
        )
    if cid:
        query = query.filter_by(collection_id=cid)
    if group:
        if group == '未分类':
            sub = db.session.query(KbCollection.id).filter(
                ~KbCollection.name.contains('·'))
        else:
            sub = db.session.query(KbCollection.id).filter(
                db.or_(KbCollection.name == group,
                       KbCollection.name.like(f'{group}·%')))
        query = query.filter(KbDocument.collection_id.in_(sub))
    if q:
        like = f'%{q}%'
        query = query.filter(
            KbDocument.title.ilike(like) | KbDocument.filename.ilike(like))
    return query.order_by(KbDocument.created_at.desc())


_STATUS_LABELS = {
    'queued': '等待识别', 'ocr': 'OCR 中', 'embedding': '向量化中',
    'graphing': '图谱抽取中', 'done': '已完成', 'failed': '失败',
}


def _doc_row(d):
    """文档行序列化(虚拟滚动/实时搜索/重命名接口共用)。"""
    coll = d.collection
    return {
        'id': d.id,
        'title': d.title,
        'filename': d.filename,
        'file_type': (d.file_type or '').upper(),
        'page_count': d.page_count,
        'status': d.status,
        'status_label': _STATUS_LABELS.get(d.status, d.status),
        'created_at': d.created_at.strftime('%Y-%m-%d %H:%M')
        if d.created_at else '',
        'created_short': d.created_at.strftime('%m-%d %H:%M')
        if d.created_at else '',
        'collection_id': coll.id if coll else None,
        'collection_name': coll.name if coll else '',
        'collection_color': coll.color if coll else '',
        'can_manage': current_user.role == 'admin'
        or d.uploaded_by == current_user.id,
        'detail_url': url_for('kb.doc_detail', doc_id=d.id),
        'preview_url': url_for('kb.preview', doc_id=d.id),
    }


def _build_points_query(cid, group, q):
    """知识点列表查询(含来源文档/合集/相似关联/引用计数)。"""
    visible = _visible_doc_ids()
    query = db.session.query(
        KbPoint.id, KbPoint.title, KbPoint.word_count, KbPoint.page_start,
        KbPoint.page_end, KbPoint.sort_order, KbPoint.created_at,
        KbDocument.id.label('doc_id'), KbDocument.title.label('doc_title'),
        KbDocument.file_type, KbCollection.id.label('collection_id'),
        KbCollection.name.label('collection_name'),
        KbCollection.color.label('collection_color'))
    query = query.join(KbDocument, KbDocument.id == KbPoint.doc_id)
    query = query.outerjoin(KbCollection,
                            KbCollection.id == KbDocument.collection_id)
    if visible is not None:
        query = query.filter(KbPoint.doc_id.in_(visible))
    if cid:
        query = query.filter(KbDocument.collection_id == cid)
    if group:
        if group == '未分类':
            sub = db.session.query(KbCollection.id).filter(
                ~KbCollection.name.contains('·'))
        else:
            sub = db.session.query(KbCollection.id).filter(
                db.or_(KbCollection.name == group,
                       KbCollection.name.like(f'{group}·%')))
        query = query.filter(KbDocument.collection_id.in_(sub))
    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(KbPoint.title.ilike(like),
                   KbPoint.content.ilike(like),
                   KbDocument.title.ilike(like)))
    return query.order_by(KbDocument.created_at.desc(),
                          KbPoint.sort_order.asc()).limit(1000)


def _point_row(r, rel_counts, ref_counts, preview_text=''):
    """知识点行序列化(列表/详情共用)。"""
    return {
        'id': r.id,
        'title': _clean_point_title(r.title),
        'doc_id': r.doc_id,
        'doc_title': r.doc_title,
        'file_type': (r.file_type or '').upper(),
        'word_count': r.word_count,
        'page_start': r.page_start,
        'page_end': r.page_end,
        'created_at': r.created_at.strftime('%Y-%m-%d %H:%M')
        if r.created_at else '',
        'collection_name': r.collection_name or '',
        'collection_color': r.collection_color or '',
        'rel_count': rel_counts.get(r.id, 0),
        'ref_count': ref_counts.get(r.id, 0),
        'preview': preview_text or '',
        'detail_url': url_for('kb.point_detail', pid=r.id),
        'doc_url': url_for('kb.doc_detail', doc_id=r.doc_id),
    }


def _point_rel_counts(ids):
    """知识点相似关联计数 {point_id: n}。"""
    if not ids:
        return {}
    conn = _db_conn()
    try:
        ph = ','.join('?' * len(ids))
        rows = conn.execute(
            f'SELECT point_id, COUNT(*) FROM ('
            f'SELECT src_point_id point_id FROM kb_point_rel '
            f'WHERE src_point_id IN ({ph}) '
            f'UNION ALL '
            f'SELECT dst_point_id point_id FROM kb_point_rel '
            f'WHERE dst_point_id IN ({ph})'
            f') GROUP BY point_id', ids + ids).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


def _point_ref_counts(ids):
    """知识点引用计数 {point_id: n}。"""
    if not ids:
        return {}
    conn = _db_conn()
    try:
        ph = ','.join('?' * len(ids))
        rows = conn.execute(
            f'SELECT point_id, COUNT(*) FROM kb_point_ref '
            f'WHERE point_id IN ({ph}) GROUP BY point_id',
            ids).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


@kb_bp.route('/api/docs')
@login_required
def api_docs():
    """文档列表 JSON(前端虚拟滚动/实时搜索)。"""
    cid = request.args.get('collection', type=int)
    group = (request.args.get('group') or '').strip()
    q = (request.args.get('q') or '').strip()
    docs = _build_docs_query(cid, group, q).all()
    return jsonify({'ok': True, 'total': len(docs),
                    'docs': [_doc_row(d) for d in docs]})


@kb_bp.route('/api/docs/<int:doc_id>', methods=['PUT'])
@login_required
def api_doc_update(doc_id):
    """重命名文档标题(行菜单「编辑」)。"""
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        return jsonify({'ok': False, 'error': '文档不存在'}), 404
    if not _can_manage_doc(doc):
        return jsonify({'ok': False, 'error': '权限不足：仅可修改自己上传的文档'}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if title:
        doc.title = title[:200]
    db.session.commit()
    return jsonify({'ok': True, 'doc': _doc_row(doc)})


@kb_bp.route('/workbench')
@login_required
def workbench():
    cid = request.args.get('collection', type=int)
    group = (request.args.get('group') or '').strip()
    q = (request.args.get('q') or '').strip()
    view = (request.args.get('view') or 'docs').strip()
    docs = _build_docs_query(cid, group, q).all()
    if current_user.role == 'admin':
        collections = KbCollection.query.order_by(KbCollection.name).all()
    else:
        collections = KbCollection.query.filter(
            (KbCollection.visibility == 'public') |
            (KbCollection.owner_id == current_user.id)
        ).order_by(KbCollection.name).all()

    owner_names = {}
    if current_user.role == 'admin':
        owner_ids = {c.owner_id for c in collections if c.owner_id}
        if owner_ids:
            try:
                from app import User
            except Exception:
                User = None
            if User is not None:
                owner_names = {
                    u.id: (u.name or u.username)
                    for u in User.query.filter(User.id.in_(owner_ids)).all()}
    if current_user.role == 'admin':
        total_docs = KbDocument.query.count()
    else:
        total_docs = KbDocument.query.filter(
            db.or_(
                KbDocument.uploaded_by == current_user.id,
                KbDocument.collection_id.in_(
                    db.session.query(KbCollection.id)
                    .filter(KbCollection.visibility == 'public')
                )
            )
        ).count()
    collection_count = len(collections)
    doc_counts = _collection_doc_counts()
    point_rows = []
    if view == 'points':
        _rows = _build_points_query(cid, group, q).all()
        _ids = [r.id for r in _rows]
        _rel_c = _point_rel_counts(_ids)
        _ref_c = _point_ref_counts(_ids)
        point_rows = [_point_row(r, _rel_c, _ref_c) for r in _rows]
    return render_template('kb/workbench.html', docs=docs,
                           q=q,
                           view=view,
                           collections=collections, active_collection=cid,
                           group=group,
                           collection_groups=_collection_groups(
                               collections, cid, group, doc_counts),
                           doc_counts=doc_counts,
                           owner_names=owner_names,
                           total_docs=total_docs,
                           collection_count=collection_count,
                           point_rows=point_rows,
                           total_points=len(point_rows),
                           docs_json=json.dumps(
                               [_doc_row(d) for d in docs],
                               ensure_ascii=False))


@kb_bp.route('/point/<int:pid>')
@login_required
def point_detail(pid):
    """知识点独立详情页:正文/元数据/相关知识点/被引用次数。"""
    point = db.session.get(KbPoint, pid)
    if not point:
        abort(404)
    doc = db.session.get(KbDocument, point.doc_id)
    if not doc:
        abort(404)
    visible = _visible_doc_ids()
    if visible is not None and point.doc_id not in visible:
        abort(403)
    rel_ids = set()
    conn = _db_conn()
    try:
        rows = conn.execute(
            'SELECT src_point_id, dst_point_id, score FROM kb_point_rel '
            'WHERE src_point_id=? OR dst_point_id=?',
            (point.id, point.id)).fetchall()
        rel_map = {}
        for s, d, sc in rows:
            other = s if s != point.id else d
            rel_map[other] = sc
        ref_count = conn.execute(
            'SELECT COUNT(*) FROM kb_point_ref WHERE point_id=?',
            (point.id,)).fetchone()[0]
    finally:
        conn.close()
    related = []
    if rel_map:
        others = db.session.query(KbPoint).filter(
            KbPoint.id.in_(list(rel_map))).all()
        for op in others:
            odoc = db.session.get(KbDocument, op.doc_id)
            related.append({
                'id': op.id,
                'title': op.title,
                'doc_title': odoc.title if odoc else '',
                'doc_url': url_for('kb.doc_detail', doc_id=op.doc_id)
                if odoc else '',
                'score': rel_map.get(op.id, 0),
                'detail_url': url_for('kb.point_detail', pid=op.id),
            })
        related.sort(key=lambda x: -x['score'])
    return render_template(
        'kb/point_detail.html',
        point=point,
        doc=doc,
        can_manage=current_user.role == 'admin'
        or doc.uploaded_by == current_user.id,
        related=related,
        ref_count=ref_count)


@kb_bp.route('/api/point/<int:pid>/rename', methods=['POST'])
@login_required
def api_point_rename(pid):
    point = db.session.get(KbPoint, pid)
    if not point:
        return jsonify({'ok': False, 'error': '知识点不存在'}), 404
    doc = db.session.get(KbDocument, point.doc_id)
    if not doc or (current_user.role != 'admin'
                   and doc.uploaded_by != current_user.id):
        return jsonify({'ok': False, 'error': '权限不足'}), 403
    title = (request.form.get('title') or '').strip()
    if not title:
        return jsonify({'ok': False, 'error': '标题不能为空'}), 400
    point.title = title[:300]
    db.session.commit()
    return jsonify({'ok': True, 'title': point.title})


@kb_bp.route('/api/point/<int:pid>/delete', methods=['POST'])
@login_required
def api_point_delete(pid):
    point = db.session.get(KbPoint, pid)
    if not point:
        return jsonify({'ok': False, 'error': '知识点不存在'}), 404
    doc = db.session.get(KbDocument, point.doc_id)
    if not doc or (current_user.role != 'admin'
                   and doc.uploaded_by != current_user.id):
        return jsonify({'ok': False, 'error': '权限不足'}), 403
    db.session.delete(point)
    db.session.commit()
    try:
        conn = _db_conn()
        conn.execute(
            'DELETE FROM kb_point_rel WHERE src_point_id=? OR dst_point_id=?',
            (pid, pid))
        conn.execute('DELETE FROM kb_point_ref WHERE point_id=?', (pid,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning('clean rels for point %s failed: %s', pid, e)
    return jsonify({'ok': True})


@kb_bp.route('/api/point/<int:pid>/ref', methods=['POST'])
@login_required
def api_point_ref(pid):
    """记录一次知识点引用(复制引用链接/关联时调用)。"""
    point = db.session.get(KbPoint, pid)
    if not point:
        return jsonify({'ok': False, 'error': '知识点不存在'}), 404
    visible = _visible_doc_ids()
    if visible is not None and point.doc_id not in visible:
        return jsonify({'ok': False, 'error': '权限不足'}), 403
    target_type = (request.form.get('target_type') or 'manual').strip()[:20]
    target_id = 0
    conn = _db_conn()
    try:
        conn.execute(
            'INSERT INTO kb_point_ref (point_id, target_type, target_id) '
            'VALUES (?,?,?)', (pid, target_type, target_id))
        conn.commit()
        n = conn.execute(
            'SELECT COUNT(*) FROM kb_point_ref WHERE point_id=?',
            (pid,)).fetchone()[0]
    finally:
        conn.close()
    return jsonify({'ok': True, 'count': n})


@kb_bp.route('/graph')
@login_required
def graph():
    """知识图谱页:展示可见知识点及其相似关联。"""
    cid = request.args.get('collection', type=int)
    doc_id = request.args.get('doc', type=int)
    return render_template('kb/graph.html', cid=cid, doc_id=doc_id)


@kb_bp.route('/api/graph-data')
@login_required
def api_graph_data():
    """图谱数据 JSON:节点=知识点,连线=相似关联(最多 300 节点)。"""
    cid = request.args.get('collection', type=int)
    doc_id = request.args.get('doc', type=int)
    visible = _visible_doc_ids()
    conn = _db_conn()
    try:
        if doc_id:
            if visible is not None and doc_id not in visible:
                return jsonify({'ok': False, 'error': '权限不足'}), 403
            pts = conn.execute(
                'SELECT p.id, p.title, p.word_count, p.doc_id, '
                'd.title, c.name, c.color FROM kb_point p '
                'JOIN kb_document d ON d.id=p.doc_id '
                'LEFT JOIN kb_collection c ON c.id=d.collection_id '
                'WHERE p.doc_id=? ORDER BY p.sort_order LIMIT 300',
                (doc_id,)).fetchall()
        else:
            sql = ('SELECT p.id, p.title, p.word_count, p.doc_id, '
                   'd.title, c.name, c.color FROM kb_point p '
                   'JOIN kb_document d ON d.id=p.doc_id '
                   'LEFT JOIN kb_collection c ON c.id=d.collection_id ')
            params = []
            conds = []
            if visible is not None:
                ph = ','.join('?' * len(visible))
                conds.append(f'p.doc_id IN ({ph})')
                params += visible
            if cid:
                conds.append('d.collection_id=?')
                params.append(cid)
            if conds:
                sql += ' WHERE ' + ' AND '.join(conds)
            sql += ' ORDER BY p.doc_id, p.sort_order LIMIT 300'
            pts = conn.execute(sql, params).fetchall()
        ids = [r[0] for r in pts]
        nodes = []
        for r in pts:
            nodes.append({
                'id': r[0],
                'title': _clean_point_title(r[1]) or r[1],
                'word_count': r[2],
                'doc_id': r[3],
                'doc_title': r[4],
                'category': r[5] or '',
                'color': r[6] or '#8b5cf6',
            })
        edges = []
        if ids:
            ph = ','.join('?' * len(ids))
            rows = conn.execute(
                f'SELECT src_point_id, dst_point_id, score FROM kb_point_rel '
                f'WHERE src_point_id IN ({ph}) AND dst_point_id IN ({ph})',
                ids + ids).fetchall()
            id_set = set(ids)
            for s, d, sc in rows:
                if s in id_set and d in id_set:
                    edges.append({'source': s, 'target': d, 'score': sc})
        return jsonify({'ok': True, 'nodes': nodes, 'edges': edges})
    finally:
        conn.close()


@kb_bp.route('/api/ask', methods=['POST'])
@login_required
def api_ask():
    """分身问答:基于检索结果整理总结,生成 Markdown 答案与引用来源(带缓存)。

    前端已检索过(工作台左侧),可把命中页通过 sources 传入,后端直接据此
    整理总结;未传 sources 时自行检索兜底。支持 @ 其他用户:传入
    target_user_id 时基于对方知识库检索。"""
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'ok': False, 'error': '请输入问题'}), 400
    target_user, avatar_name = _resolve_avatar_user(
        data.get('target_user_id'))
    if data.get('target_user_id') and target_user is None:
        return jsonify({'ok': False, 'error': '目标用户不存在或已禁用'}), 404
    scope = target_user.id if target_user else current_user.id
    key = cache_key('ask', f'{scope}:{question}')
    cached = cache_get(key, KB_ASK_CACHE_TTL)
    if cached is not None:
        record_history('ask', question)
        return jsonify({'ok': True, 'cached': True,
                        'avatar_name': avatar_name,
                        **json.loads(cached)})
    try:
        supplied = data.get('sources')
        if supplied:
            sources = [{'title': s.get('title') or '',
                        'page': s.get('page_no') or 1,
                        'doc_id': s.get('doc_id') or 0,
                        'text': s.get('text') or ''}
                       for s in supplied if s.get('text')]
            sources = sources[:KB_ASK_TOP_K]
        else:
            if target_user is not None:
                doc_ids = _doc_ids_for_user(target_user.id)
            else:
                doc_ids = _visible_doc_ids()
            hits = search_pages(question, k=KB_ASK_TOP_K, alpha=0.5,
                                doc_ids=doc_ids)
            sources = [{'title': h['title'], 'page': h['page_no'],
                        'doc_id': h['doc_id'], 'text': h['text']} for h in hits]
        answer = llm_ask(question, sources)
        payload = {'answer': answer, 'sources': sources[:5],
                   'avatar_name': avatar_name}
        cache_set(key, json.dumps(payload, ensure_ascii=False))
        record_history('ask', question)
        return jsonify({'ok': True, 'cached': False, **payload})
    except Exception as e:
        logger.exception('api_ask failed')
        return jsonify({'ok': False, 'error': str(e)}), 500


@kb_bp.route('/api/search', methods=['POST'])
@login_required
def api_search():
    """工作台关键词检索:按文档分组的 JSON 结果(含高亮片段,带缓存)。

    支持 @ 其他用户:传入 target_user_id 时在其知识库范围内检索。"""
    data = request.get_json(silent=True) or {}
    q = (data.get('q') or '').strip()
    if not q:
        return jsonify({'ok': False, 'error': '请输入关键词'}), 400
    target_user, _ = _resolve_avatar_user(data.get('target_user_id'))
    scope = target_user.id if target_user else current_user.id
    key = cache_key('search', f'{scope}:{q}')
    cached = cache_get(key, KB_SEARCH_CACHE_TTL)
    if cached is not None:
        return jsonify({'ok': True, 'cached': True,
                        **json.loads(cached)})
    try:
        if target_user is not None:
            doc_ids = _doc_ids_for_user(target_user.id)
        else:
            doc_ids = _visible_doc_ids()
        results = search_pages(q, k=30, alpha=0.5, doc_ids=doc_ids)
        groups = group_results(results, q)
        payload = {'groups': groups}
        cache_set(key, json.dumps(payload, ensure_ascii=False))
        record_history('search', q)
        return jsonify({'ok': True, 'cached': False, **payload})
    except Exception as e:
        logger.exception('api_search failed')
        return jsonify({'ok': False, 'error': str(e)}), 500


@kb_bp.route('/api/suggest')
@login_required
def api_suggest():
    """搜索框自动补全:文档标题。"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'items': []})
    like = f'%{q}%'
    doc_query = KbDocument.query.filter(KbDocument.title.like(like))
    if current_user.role != 'admin':
        doc_query = doc_query.filter(
            KbDocument.id.in_(_visible_doc_ids() or []))
    titles = doc_query.order_by(KbDocument.created_at.desc()).limit(12).all()
    items = [t.title for t in titles]
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return jsonify({'items': out[:12]})


@kb_bp.route('/api/history')
@login_required
def api_history():
    """近期检索历史(最近 top5 问题)。"""
    return jsonify({'ok': True, 'items': get_recent_questions(5)})


@kb_bp.route('/api/history/answer')
@login_required
def api_history_answer():
    """给定问题,直接返回缓存的 AI 历史回答(不触发 LLM)。"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'ok': False, 'error': '缺少问题'}), 400
    target_user, avatar_name = _resolve_avatar_user(
        request.args.get('target_user_id'))
    scope = target_user.id if target_user else current_user.id
    cached = cache_get(cache_key('ask', f'{scope}:{q}'), KB_ASK_CACHE_TTL)
    if cached is None:
        return jsonify({'ok': False, 'error': '暂无历史回答'}), 404
    payload = json.loads(cached)
    if 'avatar_name' not in payload or payload.get('avatar_name') is None:
        payload['avatar_name'] = avatar_name
    return jsonify({'ok': True, 'cached': True, **payload})


@kb_bp.route('/api/queue')
@login_required
def api_queue():
    """后台处理队列统计(供批量导入状态轮询)。"""
    rows = db.session.query(KbDocument.status, db.func.count()).group_by(
        KbDocument.status).all()
    counts = {s: 0 for s in [STATUS_QUEUED, STATUS_OCR, STATUS_EMBED,
                              STATUS_DONE, STATUS_FAILED]}
    for status, n in rows:
        counts[status] = n
    processing = sum(counts[s] for s in [STATUS_QUEUED, STATUS_OCR,
                                         STATUS_EMBED])
    return jsonify({'ok': True, 'counts': counts, 'processing': processing,
                    'total': sum(counts.values())})


@kb_bp.route('/api/ids')
@login_required
def api_ids():
    """当前筛选(集合/搜索)下的全部文档 id,供跨页全选。"""
    cid = request.args.get('collection', type=int)
    q = (request.args.get('q') or '').strip()
    group = (request.args.get('group') or '').strip()
    query = KbDocument.query
    if current_user.role != 'admin':
        query = query.filter(KbDocument.uploaded_by == current_user.id)
    if cid:
        query = query.filter_by(collection_id=cid)
    if group:
        if group == '未分类':
            sub = db.session.query(KbCollection.id).filter(
                ~KbCollection.name.contains('·'))
        else:
            sub = db.session.query(KbCollection.id).filter(
                db.or_(KbCollection.name == group,
                       KbCollection.name.like(f'{group}·%')))
        query = query.filter(KbDocument.collection_id.in_(sub))
    if q:
        like = f'%{q}%'
        query = query.filter(
            KbDocument.title.ilike(like) | KbDocument.filename.ilike(like))
    ids = [d.id for d in query.order_by(KbDocument.created_at.desc()).all()]
    return jsonify({'ok': True, 'ids': ids, 'total': len(ids)})


# ---------------------------------------------------------------------------
# 数字分身 (Digital Avatar)
# ---------------------------------------------------------------------------


@kb_bp.route('/avatar')
@login_required
def avatar():
    return render_template('kb/avatar.html')


@kb_bp.route('/api/avatar/ask', methods=['POST'])
@login_required
def api_avatar_ask():
    """数字分身问答:基于知识库进行 RAG 检索与生成。

    支持 @ 其他用户:传入 target_user_id 时,基于对方知识库回答,
    返回中附带 avatar_name 供前端展示"姓名·分身"。"""
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'ok': False, 'error': '请输入问题'}), 400
    target_user, avatar_name = _resolve_avatar_user(
        data.get('target_user_id'))
    if data.get('target_user_id') and target_user is None:
        return jsonify({'ok': False, 'error': '目标用户不存在或已禁用'}), 404
    scope_user_id = target_user.id if target_user else current_user.id
    # 构建该用户可访问的文档 ID 列表:其本人上传文档 + 私有集合 + 公共集合。
    # 必须包含 uploaded_by 项,否则未分类/被分类器归到他人集合的文档会不可见,
    # 导致"明明有文档却提示知识库为空"。
    doc_ids = _doc_ids_for_user(scope_user_id)
    if not doc_ids:
        who = avatar_name or '你的'
        return jsonify({'ok': True, 'empty': True,
                        'answer': f'{who}的知识库暂时为空，'
                        '请先上传文档到知识库。', 'sources': [],
                        'avatar_name': avatar_name})
    key = cache_key('avatar',
                    f'{current_user.id}:{scope_user_id}:{question}')
    cached = cache_get(key, KB_ASK_CACHE_TTL)
    if cached is not None:
        return jsonify({'ok': True, 'cached': True,
                        'avatar_name': avatar_name,
                        **json.loads(cached)})
    try:
        hits = search_pages(question, k=KB_ASK_TOP_K, alpha=0.5,
                            doc_ids=doc_ids)
        sources = [{'title': h['title'], 'page': h['page_no'],
                    'doc_id': h['doc_id'], 'text': h['text']} for h in hits]
        answer = llm_ask(question, sources)
        payload = {'answer': answer, 'sources': sources[:5],
                   'avatar_name': avatar_name}
        cache_set(key, json.dumps(payload, ensure_ascii=False))
        return jsonify({'ok': True, 'cached': False, **payload})
    except Exception as e:
        logger.exception('api_avatar_ask failed')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# 集合(Collection)管理
# ---------------------------------------------------------------------------

@kb_bp.route('/api/collections')
@login_required
def api_collections():
    if current_user.role == 'admin':
        cols = KbCollection.query.order_by(KbCollection.name).all()
    else:
        cols = KbCollection.query.filter(
            (KbCollection.visibility == 'public') |
            (KbCollection.owner_id == current_user.id)
        ).order_by(KbCollection.name).all()
    out = []
    for c in cols:
        doc_count = KbDocument.query.filter_by(
            collection_id=c.id).count()
        out.append({'id': c.id, 'name': c.name, 'color': c.color,
                    'visibility': c.visibility,
                    'owner_id': c.owner_id,
                    'doc_count': doc_count})
    return jsonify({'ok': True, 'collections': out})


@kb_bp.route('/api/collections', methods=['POST'])
@login_required
def api_collection_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    color = (data.get('color') or '#8b5cf6').strip()
    visibility = (data.get('visibility') or 'private').strip()
    if not name:
        return jsonify({'ok': False, 'error': '请输入集合名称'}), 400
    if visibility not in ('public', 'private'):
        visibility = 'private'
    if visibility == 'public' and current_user.role != 'admin':
        return jsonify({'ok': False,
                        'error': '仅管理员可创建公共知识库'}), 403
    if KbCollection.query.filter_by(name=name).first():
        return jsonify({'ok': False, 'error': '集合名称已存在'}), 400
    c = KbCollection(name=name, color=color,
                       visibility=visibility,
                       owner_id=current_user.id)
    db.session.add(c)
    db.session.commit()
    _log_op('kb_collection_create', name, f'创建集合({visibility})')
    db.session.commit()
    return jsonify({'ok': True, 'collection': {'id': c.id, 'name': c.name,
                                                'color': c.color,
                                                'visibility': c.visibility,
                                                'owner_id': c.owner_id,
                                                'doc_count': 0}})


@kb_bp.route('/api/collections/<int:cid>', methods=['PUT'])
@login_required
def api_collection_update(cid):
    c = db.session.get(KbCollection, cid)
    if not c:
        return jsonify({'ok': False, 'error': '集合不存在'}), 404
    if c.visibility == 'public' and current_user.role != 'admin':
        return jsonify({'ok': False,
                        'error': '仅管理员可管理公共知识库'}), 403
    if c.visibility == 'private' and c.owner_id != current_user.id \
            and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '权限不足'}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or c.name).strip()
    color = (data.get('color') or c.color).strip()
    visibility = data.get('visibility', c.visibility)
    if visibility not in ('public', 'private'):
        visibility = c.visibility
    if visibility == 'public' and current_user.role != 'admin':
        return jsonify({'ok': False,
                        'error': '仅管理员可创建公共知识库'}), 403
    if name != c.name and KbCollection.query.filter(
            KbCollection.name == name,
            KbCollection.id != cid).first():
        return jsonify({'ok': False, 'error': '集合名称已存在'}), 400
    c.name, c.color, c.visibility = name, color, visibility
    db.session.commit()
    _log_op('kb_collection_update', name, f'更新集合 #{cid}')
    db.session.commit()
    return jsonify({'ok': True, 'collection': {'id': c.id, 'name': c.name,
                                                'color': c.color,
                                                'visibility': c.visibility,
                                                'owner_id': c.owner_id}})


@kb_bp.route('/api/collections/<int:cid>', methods=['DELETE', 'POST'])
@login_required
def api_collection_delete(cid):
    c = db.session.get(KbCollection, cid)
    if not c:
        if request.method == 'POST':
            flash('集合不存在', 'danger')
            return redirect(request.referrer or url_for('kb.index'))
        return jsonify({'ok': False, 'error': '集合不存在'}), 404
    if c.visibility == 'public' and current_user.role != 'admin':
        if request.method == 'POST':
            flash('仅管理员可管理公共知识库', 'danger')
            return redirect(request.referrer or url_for('kb.index'))
        return jsonify({'ok': False,
                        'error': '仅管理员可管理公共知识库'}), 403
    if c.visibility == 'private' and c.owner_id != current_user.id \
            and current_user.role != 'admin':
        if request.method == 'POST':
            flash('权限不足', 'danger')
            return redirect(request.referrer or url_for('kb.index'))
        return jsonify({'ok': False, 'error': '权限不足'}), 403
    try:
        name = c.name
        KbDocument.query.filter_by(collection_id=cid).update(
            {KbDocument.collection_id: None})
        db.session.delete(c)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error('api_collection_delete failed: %s', e)
        if request.method == 'POST':
            flash(f'删除失败: {e}', 'danger')
            return redirect(request.referrer or url_for('kb.index'))
        return jsonify({'ok': False,
                        'error': f'删除失败: {e}'}), 500
    _log_op('kb_collection_delete', name, f'删除集合 #{cid}')
    db.session.commit()
    if request.method == 'POST':
        flash(f'已删除集合「{name}」', 'success')
        return redirect(request.referrer or url_for('kb.index'))
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
        if c.visibility == 'public' and current_user.role != 'admin':
            return jsonify({'ok': False,
                            'error': '仅管理员可管理公共知识库'}), 403
        if c.visibility == 'private' and c.owner_id != current_user.id \
                and current_user.role != 'admin':
            return jsonify({'ok': False, 'error': '权限不足'}), 403
    if current_user.role != 'admin':
        doc_ids = [d.id for d in KbDocument.query.filter(
            KbDocument.id.in_(doc_ids),
            KbDocument.uploaded_by == current_user.id).all()]
    KbDocument.query.filter(KbDocument.id.in_(doc_ids)).update(
        {KbDocument.collection_id: collection_id})
    db.session.commit()
    _log_op('kb_collection_assign',
            f'{len(doc_ids)} 个文档',
            f'分配到集合 #{collection_id}' if collection_id is not None
            else '移出集合')
    db.session.commit()
    return jsonify({'ok': True})


@kb_bp.route('/api/collections/prune-empty', methods=['POST'])
@login_required
def api_collection_prune_empty():
    """批量删除空集合(集合内无任何文档)。

    仅删除当前用户有权限管理的集合:管理员可删公共及全部私有集合;
    普通用户仅可删本人私有集合。"""
    deletable = []
    for c in KbCollection.query.all():
        if KbDocument.query.filter_by(collection_id=c.id).count() > 0:
            continue
        if c.visibility == 'public' and current_user.role != 'admin':
            continue
        if c.visibility == 'private' and c.owner_id != current_user.id \
                and current_user.role != 'admin':
            continue
        deletable.append(c)
    names = [c.name for c in deletable]
    for c in deletable:
        db.session.delete(c)
    db.session.commit()
    _log_op('kb_collection_prune_empty', f'{len(deletable)} 个集合',
            '批量删除空集合')
    db.session.commit()
    return jsonify({'ok': True, 'deleted': len(deletable),
                    'names': names[:50]})


def _upload_wants_json():
    """上传请求是否期望 JSON 响应(前端 XHR 上传用,表单上传维持原行为)。"""
    return (request.accept_mimetypes.best == 'application/json'
            or request.form.get('_json') == '1')


def _validate_collection_upload(cid):
    """校验上传目标集合,返回错误信息(可上传则返回 None)。"""
    if cid is None:
        return None
    c = db.session.get(KbCollection, cid)
    if not c:
        return '集合不存在'
    if current_user.role != 'admin' and not (
            c.visibility == 'private' and c.owner_id == current_user.id):
        return '仅可上传到自己的私有集合'
    return None


def _ingest_file(path, filename, cid):
    """校验并入库一个已落盘的文件,返回 (title, None) 或 (None, 拒绝原因)。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, f'{filename}({ext})'
    try:
        with open(path, 'rb') as fh:
            head = fh.read(8192)
    except OSError:
        return None, f'{filename}(读取失败)'
    if not file_content_matches(filename, head):
        return None, f'{filename}(内容与扩展名不匹配)'
    store_name = uuid.uuid4().hex + ext
    target = os.path.join(_kb_upload_dir(), store_name)
    try:
        shutil.move(path, target)
    except OSError:
        return None, f'{filename}(保存失败)'
    title = os.path.splitext(filename)[0] or '未命名文档'
    doc = KbDocument(title=title, filename=filename, file_path=target,
                     file_type=ext.lstrip('.'),
                     file_size=os.path.getsize(target),
                     status=STATUS_QUEUED, uploaded_by=current_user.id,
                     collection_id=cid,
                     last_recognition_type='upload')
    db.session.add(doc)
    return title, None


@kb_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    cid = request.form.get('collection_id', type=int)
    wants_json = _upload_wants_json()
    err = _validate_collection_upload(cid)
    if err:
        if wants_json:
            return jsonify({'ok': False, 'error': err}), \
                (400 if err == '集合不存在' else 403)
        flash(err, 'danger')
        return redirect(url_for('kb.index'))
    files = request.files.getlist('file')
    files = [f for f in files if f and f.filename]
    if not files:
        if wants_json:
            return jsonify({'ok': False, 'error': '未选择文件'}), 400
        flash('未选择文件', 'danger')
        return redirect(url_for('kb.index'))
    added = []
    rejected = []
    incoming = os.path.join(_kb_upload_dir(), 'incoming')
    os.makedirs(incoming, exist_ok=True)
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        tmp = os.path.join(incoming, uuid.uuid4().hex + ext)
        try:
            f.save(tmp)
        except OSError:
            rejected.append(f'{f.filename}(保存失败)')
            continue
        title, rej = _ingest_file(tmp, f.filename, cid)
        if rej:
            rejected.append(rej)
            try:
                os.remove(tmp)
            except OSError:
                pass
        else:
            added.append(title)
    db.session.commit()
    if added:
        _bump_data_version()
        _log_op('kb_upload', ','.join(added),
                f'上传 {len(added)} 个文档' +
                (f' 到集合 #{cid}' if cid else ''))
        if wants_json:
            return jsonify({'ok': True, 'added': added, 'rejected': rejected,
                            'added_count': len(added),
                            'rejected_count': len(rejected)})
        flash(f'已加入识别队列 {len(added)} 个文件: {", ".join(added)}', 'success')
    if rejected:
        if wants_json:
            return jsonify({'ok': not not added, 'added': added,
                            'rejected': rejected,
                            'added_count': len(added),
                            'rejected_count': len(rejected)}), \
                (200 if added else 400)
        flash(f'跳过不支持的文件: {", ".join(rejected)}'
              '(仅支持 PDF/图片/Markdown/文本/HTML)', 'warning')
    return redirect(url_for('kb.index'))


MAX_CHUNKED_FILE_MB = 512


def _chunk_dir(upload_id):
    d = os.path.join(_kb_upload_dir(), 'chunks', str(upload_id))
    os.makedirs(d, exist_ok=True)
    return d


@kb_bp.route('/api/upload/chunk', methods=['POST'])
@login_required
def api_upload_chunk():
    """分片上传: 保存单个分片(规避 MAX_CONTENT_LENGTH)。"""
    upload_id = (request.form.get('upload_id') or '').strip()
    index = request.form.get('index', type=int)
    total = request.form.get('total', type=int)
    f = request.files.get('file')
    if not upload_id or index is None or total is None or not f \
            or index < 0 or index >= total:
        return jsonify({'ok': False, 'error': '分片参数不完整'}), 400
    f.save(os.path.join(_chunk_dir(upload_id), f'{index}.part'))
    return jsonify({'ok': True})


@kb_bp.route('/api/upload/complete', methods=['POST'])
@login_required
def api_upload_complete():
    """分片上传: 合并分片并入库。"""
    upload_id = (request.form.get('upload_id') or '').strip()
    filename = (request.form.get('filename') or '').strip()
    total = request.form.get('total', type=int)
    cid = request.form.get('collection_id', type=int)
    if not upload_id or not filename or not total:
        return jsonify({'ok': False, 'error': '参数不完整'}), 400
    err = _validate_collection_upload(cid)
    if err:
        return jsonify({'ok': False, 'error': err}), \
            (400 if err == '集合不存在' else 403)
    tmpdir = _chunk_dir(upload_id)
    incoming = os.path.join(_kb_upload_dir(), 'incoming')
    os.makedirs(incoming, exist_ok=True)
    merged = os.path.join(incoming, uuid.uuid4().hex)
    try:
        with open(merged, 'wb') as out:
            for i in range(total):
                part = os.path.join(tmpdir, f'{i}.part')
                with open(part, 'rb') as p:
                    shutil.copyfileobj(p, out, 1024 * 1024)
    except OSError as _e:
        try:
            os.remove(merged)
        except OSError:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({'ok': False, 'error': '合并分片失败，请重试'}), 500
    shutil.rmtree(tmpdir, ignore_errors=True)
    try:
        size = os.path.getsize(merged)
    except OSError:
        return jsonify({'ok': False, 'error': '合并分片失败，请重试'}), 500
    if size > MAX_CHUNKED_FILE_MB * 1024 * 1024:
        try:
            os.remove(merged)
        except OSError:
            pass
        return jsonify({'ok': False, 'error': '文件过大'}), 400
    title, rej = _ingest_file(merged, filename, cid)
    if rej:
        try:
            os.remove(merged)
        except OSError:
            pass
        return jsonify({'ok': False, 'error': rej}), 400
    db.session.commit()
    _bump_data_version()
    _log_op('kb_upload', title, f'上传 {filename}' +
            (f' 到集合 #{cid}' if cid else ''))
    return jsonify({'ok': True, 'added': [title], 'added_count': 1})


@kb_bp.route('/<int:doc_id>')
@login_required
def doc_detail(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    visible = _visible_doc_ids()
    if visible is not None and doc.id not in visible:
        flash('权限不足：无法查看该文档', 'danger')
        return redirect(url_for('kb.index'))
    pages = (KbPage.query.filter_by(doc_id=doc.id)
             .order_by(KbPage.page_no).all())
    if doc.file_type not in ('txt', 'md', 'markdown'):
        pages = [SimpleNamespace(
            page_no=p.page_no,
            text=_dedupe_lines(p.text),
            char_count=p.char_count) for p in pages]
    points = (KbPoint.query.filter_by(doc_id=doc.id)
              .order_by(KbPoint.sort_order).all())
    points = [SimpleNamespace(
        id=p.id, title=_clean_point_title(p.title), word_count=p.word_count,
        page_start=p.page_start, page_end=p.page_end) for p in points]
    return render_template('kb/doc_detail.html', doc=doc, pages=pages,
                           points=points,
                           can_manage=_can_manage_doc(doc))


@kb_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def doc_delete(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    if not _can_manage_doc(doc):
        flash('权限不足：仅可删除自己上传的文档', 'danger')
        return redirect(url_for('kb.index'))
    if doc:
        for p in doc.pages:
            delete_page(doc.id, p.page_no)
        try:
            conn = _db_conn()
            conn.execute(
                'DELETE FROM kb_point_rel WHERE src_point_id IN '
                '(SELECT id FROM kb_point WHERE doc_id=?) OR '
                'dst_point_id IN (SELECT id FROM kb_point WHERE doc_id=?)',
                (doc.id, doc.id))
            conn.execute(
                'DELETE FROM kb_point_ref WHERE point_id IN '
                '(SELECT id FROM kb_point WHERE doc_id=?)', (doc.id,))
            conn.execute('DELETE FROM kb_point WHERE doc_id=?', (doc.id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning('delete points for doc %s failed: %s', doc.id, e)
        if os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except OSError:
                pass
        db.session.delete(doc)
        db.session.commit()
        _bump_data_version()
        _log_op('kb_delete', doc.title, f'删除文档 #{doc_id}')
        flash('文档已删除', 'success')
    return redirect(url_for('kb.index'))


@kb_bp.route('/<int:doc_id>/reprocess', methods=['POST'])
@login_required
def doc_reprocess(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    if not _can_manage_doc(doc):
        flash('权限不足：仅可重新识别自己上传的文档', 'danger')
        return redirect(url_for('kb.index'))
    doc.status = STATUS_QUEUED
    doc.error = None
    doc.cancel = 0
    doc.attempts = 0
    doc.last_recognition_type = 'reprocess'
    doc.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    _bump_data_version()
    _log_op('kb_reprocess', doc.title, f'重新识别文档 #{doc_id}')
    flash('已重新加入识别队列', 'info')
    return redirect(url_for('kb.doc_detail', doc_id=doc_id))


@kb_bp.route('/<int:doc_id>/cancel', methods=['POST'])
@login_required
def doc_cancel(doc_id):
    """停止一个正在识别的文档:标记 cancel 并置为 failed(已由用户取消)。

    worker 在阶段边界会检查 cancel 并中断;已完成的文档不受影响。"""
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    if not _can_manage_doc(doc):
        flash('权限不足：仅可停止自己上传的文档', 'danger')
        return redirect(url_for('kb.index'))
    conn = _connect()
    conn.execute(
        "UPDATE kb_document SET cancel=1, status=?, attempts=?, error=?, "
        "updated_at=datetime('now') "
        "WHERE id=? AND status IN (?, ?, ?, ?)",
        (STATUS_FAILED, KB_MAX_DOC_ATTEMPTS, '已由用户取消', doc_id,
         STATUS_QUEUED, STATUS_OCR, STATUS_EMBED, STATUS_GRAPH))
    conn.commit()
    _log_op('kb_cancel', doc.title, f'停止识别文档 #{doc_id}')
    flash('已停止该文档的识别', 'info')
    return redirect(request.referrer or url_for('kb.index'))


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

def _doc_text(doc):
    pages = (KbPage.query.filter_by(doc_id=doc.id)
             .order_by(KbPage.page_no).all())
    if doc.file_type in ('txt', 'md', 'markdown'):
        head = [f'# {doc.title}\n\n']
        body = [f'\n\n<!-- 第 {p.page_no} 页 -->\n\n{p.text}' for p in pages]
    else:
        head = []
        body = [f'\n\n<!-- 第 {p.page_no} 页 -->\n\n{_dedupe_lines(p.text)}'
                for p in pages]
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
    if not _can_manage_doc(doc):
        flash('权限不足：仅可导出自己上传的文档', 'danger')
        return redirect(url_for('kb.index'))
    text = _doc_text(doc)
    ext = 'md' if doc.file_type in ('md', 'markdown') else 'txt'
    resp = Response(text, content_type='text/plain; charset=utf-8')
    resp.headers['Content-Disposition'] = (
        f'attachment; filename="{_safe_filename(doc.title)}.{ext}"')
    _log_op('kb_export', doc.title, f'导出文档 #{doc_id}')
    db.session.commit()
    return resp


@kb_bp.route('/export/txt')
@login_required
def export_txt():
    """批量导出所选文档的 OCR 识别结果,全部合并到一个 txt 文件。"""
    ids = request.args.get('ids', '')
    doc_ids = [int(x) for x in ids.split(',') if x.strip().isdigit()]
    if not doc_ids:
        flash('请选择文档', 'warning')
        return redirect(url_for('kb.index'))
    doc_ids = _manage_docs_for_user(doc_ids)
    docs = (KbDocument.query.filter(KbDocument.id.in_(doc_ids))
            .order_by(KbDocument.id).all())
    if not docs:
        flash('所选文档不存在或无权导出', 'warning')
        return redirect(url_for('kb.index'))
    parts = []
    for d in docs:
        text = _doc_text(d)
        parts.append(
            f'{"=" * 60}\n'
            f'文档: {d.title}\n'
            f'文件名: {d.filename}\n'
            f'类型: {d.file_type or "-"} | 页数: {d.page_count or "-"} | '
            f'状态: {d.status}\n'
            f'{"=" * 60}\n'
            f'{text}\n')
    resp = Response('\n'.join(parts), content_type='text/plain; charset=utf-8')
    resp.headers['Content-Disposition'] = (
        'attachment; filename="knowledge-ocr-selected.txt"')
    _log_op('kb_export', f'{len(docs)} 个文档', '批量导出识别结果')
    db.session.commit()
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
    doc_ids = _manage_docs_for_user(doc_ids)
    if not doc_ids:
        return jsonify({'ok': False, 'error': '无可操作的文档'}), 403
    docs = (KbDocument.query.filter(KbDocument.id.in_(doc_ids))
            .all())
    if action == 'delete':
        for doc in docs:
            for p in doc.pages:
                delete_page(doc.id, p.page_no)
            if os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except OSError:
                    pass
            db.session.delete(doc)
        db.session.commit()
        _bump_data_version()
        _log_op('kb_bulk_delete', f'{len(docs)} 个文档', '批量删除')
        db.session.commit()
        return jsonify({'ok': True, 'deleted': len(docs)})
    if action == 'reprocess':
        now = datetime.datetime.utcnow()
        for doc in docs:
            doc.status = STATUS_QUEUED
            doc.error = None
            doc.cancel = 0
            doc.attempts = 0
            doc.last_recognition_type = 'reprocess'
            doc.updated_at = now
        db.session.commit()
        _bump_data_version()
        _log_op('kb_bulk_reprocess', f'{len(docs)} 个文档', '批量重新识别')
        db.session.commit()
        return jsonify({'ok': True, 'requeued': len(docs)})
    if action == 'export':
        _log_op('kb_bulk_export', f'{len(docs)} 个文档', '批量导出 JSON')
        db.session.commit()
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
    if action == 'auto_archive':
        from classifier import classify, _pick_color
        archived, created_names, skipped, rebuilt = [], [], 0, 0
        processed_ids = []
        for doc in docs:
            if doc.status != STATUS_DONE:
                skipped += 1
                continue
            text = _doc_text(doc)
            if not text.strip():
                skipped += 1
                continue
            try:
                label, _conf = classify(text, doc.title or '')
            except Exception as e:
                logger.warning('auto_archive classify doc %s failed: %s',
                               doc.id, e)
                skipped += 1
                continue
            if not label:
                label = '未分类'
            # 与原 classifier.auto_archive 语义一致:
            # - 未归档 -> 分类并归档(auto_classified=1)
            # - 自动分类过且类别变化 -> 迁移
            # - 手动归档过 -> 不动
            if doc.collection_id is None:
                col = KbCollection.query.filter_by(name=label).first()
                if col is None:
                    col = KbCollection(name=label, color=_pick_color(label),
                                       visibility='private',
                                       owner_id=doc.uploaded_by)
                    db.session.add(col)
                    db.session.flush()
                    created_names.append(label)
                doc.collection_id = col.id
                doc.auto_classified = 1
                archived.append({'id': doc.id, 'label': label})
            elif doc.auto_classified:
                current = db.session.get(KbCollection, doc.collection_id)
                if current and current.name != label:
                    col = KbCollection.query.filter_by(name=label).first()
                    if col is None:
                        col = KbCollection(name=label,
                                           color=_pick_color(label),
                                           visibility='private',
                                           owner_id=doc.uploaded_by)
                        db.session.add(col)
                        db.session.flush()
                        created_names.append(label)
                    doc.collection_id = col.id
                    archived.append({'id': doc.id, 'label': label})
            processed_ids.append(doc.id)
        # 先提交归档变更,释放写锁;再逐文档重建知识点(题库按题号拆点)
        db.session.commit()
        for doc_id in processed_ids:
            try:
                pages = [(p.page_no, p.text or '') for p in
                         (KbPage.query.filter_by(doc_id=doc_id)
                          .order_by(KbPage.page_no).all())]
                conn = _connect()
                try:
                    _ensure_point_tables(conn)
                    _rebuild_points_for_doc(conn, doc_id, pages)
                finally:
                    conn.close()
                rebuilt += 1
            except Exception as e:
                logger.warning('auto_archive rebuild points doc %s failed: %s',
                               doc_id, e)
        _bump_data_version()
        _log_op('kb_bulk_auto_archive', f'{len(docs)} 个文档',
                f'自动归档成功 {len(archived)} 个,重建知识点 {rebuilt} 个' +
                (f'(跳过 {skipped} 个)' if skipped else ''))
        db.session.commit()
        return jsonify({'ok': True, 'archived': archived,
                        'created': created_names, 'skipped': skipped,
                        'rebuilt': rebuilt})
    if action == 'clear_archive':
        cleared, kept = [], 0
        for doc in docs:
            if doc.auto_classified and doc.collection_id is not None:
                doc.collection_id = None
                doc.auto_classified = 0
                cleared.append({'id': doc.id, 'title': doc.title})
            else:
                kept += 1
        db.session.commit()
        _bump_data_version()
        _log_op('kb_bulk_clear_archive', f'{len(docs)} 个文档',
                f'清除归档成功 {len(cleared)} 个' +
                (f'(跳过 {kept} 个)' if kept else ''))
        db.session.commit()
        return jsonify({'ok': True, 'cleared': cleared, 'skipped': kept})
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
    return render_template('kb/ask.html', q=q, kb_users=_kb_user_list())


@kb_bp.route('/api/users')
@login_required
def api_users():
    """系统内用户列表(分身问答 @ 选择用)。"""
    return jsonify({'ok': True, 'users': _kb_user_list()})


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
    file_path = _resolve_stored_path(doc.file_path if doc else '')
    if not doc or not os.path.exists(file_path):
        return jsonify({'ok': False, 'error': '文件不存在'}), 404
    ftype = (doc.file_type or '').lower()
    if ftype in ('pdf',):
        page = max(1, request.args.get('page', 1, type=int))
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(file_path)
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
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        resp = Response(content, mimetype='text/plain; charset=utf-8')
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp
    return send_file(file_path, conditional=True)


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


def _ensure_doc_columns(conn):
    cols = [r[1] for r in conn.execute('PRAGMA table_info(kb_document)')]
    if 'attempts' not in cols:
        conn.execute('ALTER TABLE kb_document ADD COLUMN attempts INTEGER DEFAULT 0')
    for col, ddl in [('last_recognition_at', 'DATETIME'),
                     ('last_recognition_type', 'VARCHAR(20)'),
                     ('last_recognition_result', 'VARCHAR(20)'),
                     ('recognition_count', 'INTEGER DEFAULT 0'),
                     ('cancel', 'INTEGER DEFAULT 0'),
                     ('auto_classified', 'INTEGER DEFAULT 0')]:
        if col not in cols:
            conn.execute(
                f'ALTER TABLE kb_document ADD COLUMN {col} {ddl}')
    conn.commit()


def _record_recognition(conn, doc_id, result):
    conn.execute(
        "UPDATE kb_document SET last_recognition_at=datetime('now'), "
        "last_recognition_result=?, "
        "recognition_count=COALESCE(recognition_count, 0) + 1 WHERE id=?",
        (result, doc_id))
    conn.commit()


def _requeue_stale(conn):
    conn.execute(
        "UPDATE kb_document SET status=?, error=NULL, updated_at=datetime('now') "
        "WHERE status IN (?, ?, ?) AND "
        "julianday('now') - julianday(updated_at) > ?",
        (STATUS_QUEUED, STATUS_OCR, STATUS_EMBED, STATUS_GRAPH,
         KB_STALE_QUEUE_HOURS))
    conn.commit()


def _reset_inflight(conn):
    """worker 启动时复位上次遗留的进行中文档(单 worker,重启前正在处理的
    文档已无人在跑,全部放回队列;取消中的文档保持 failed)。"""
    conn.execute(
        "UPDATE kb_document SET status=?, error=NULL, updated_at=datetime('now') "
        "WHERE cancel=0 AND status IN (?, ?, ?)",
        (STATUS_QUEUED, STATUS_OCR, STATUS_EMBED, STATUS_GRAPH))
    conn.commit()


def _claim_next(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute(
            "SELECT id, file_path, title, filename FROM kb_document "
            "WHERE status = ? OR (status = ? AND attempts < ?) "
            "ORDER BY created_at ASC LIMIT 1",
            (STATUS_QUEUED, STATUS_FAILED, KB_MAX_DOC_ATTEMPTS)).fetchone()
        if row:
            conn.execute(
                "UPDATE kb_document SET status=?, attempts=attempts+1, "
                "updated_at=datetime('now') WHERE id=?",
                (STATUS_OCR, row[0]))
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


class _DocCancelled(Exception):
    """用户在识别过程中请求停止该文档。"""


def _check_cancel(conn, doc_id):
    row = conn.execute(
        "SELECT cancel FROM kb_document WHERE id=?", (doc_id,)).fetchone()
    if row and row[0]:
        raise _DocCancelled()


def _auto_archive_document(conn, doc_id, pages):
    """识别完成后自动分类并归档到对应合集(见 classifier.auto_archive)。"""
    text = ' '.join(t for _, t in pages)
    if not text.strip():
        return
    row = conn.execute(
        'SELECT uploaded_by, title FROM kb_document WHERE id=?',
        (doc_id,)).fetchone()
    if not row:
        return
    from classifier import auto_archive
    result = auto_archive(conn, doc_id, row[0], row[1] or '', text)
    if result:
        created, label, conf = result
        logger.info('[doc %s] auto-classified -> %s (conf=%.2f, created=%s)',
                    doc_id, label, conf, created)


def _process_document(conn, row):
    doc_id, file_path, title, filename = row
    try:
        _update_status(conn, doc_id, STATUS_OCR)
        logger.info('[doc %s] OCR: %s', doc_id, filename)
        file_path = _resolve_stored_path(file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f'源文件丢失:{file_path} (uploads 目录可能被清空或路径迁移)')
        pages = ocr_file(file_path)
        _check_cancel(conn, doc_id)
        page_count = len(pages)

        _update_status(conn, doc_id, STATUS_EMBED, page_count=page_count)
        conn.execute("DELETE FROM kb_page WHERE doc_id=?", (doc_id,))
        conn.commit()

        upsert_pages_batch(doc_id, title, filename, pages)
        for page_no, text in pages:
            _check_cancel(conn, doc_id)
            if text.strip():
                conn.execute(
                    "INSERT INTO kb_page (doc_id, page_no, text, char_count) "
                    "VALUES (?,?,?,?)",
                    (doc_id, page_no, text, len(text)))
                conn.commit()

        _update_status(conn, doc_id, STATUS_DONE)
        _record_recognition(conn, doc_id, 'success')
        _bump_data_version()
        logger.info('[doc %s] done: %d pages', doc_id, page_count)
        try:
            _auto_archive_document(conn, doc_id, pages)
        except Exception as e:
            logger.warning('[doc %s] auto-classify/archive failed: %s',
                           doc_id, e)
        try:
            n_points = _rebuild_points_for_doc(conn, doc_id, pages)
            logger.info('[doc %s] knowledge points rebuilt: %d', doc_id,
                        n_points)
        except Exception as e:
            logger.warning('[doc %s] knowledge points failed: %s', doc_id, e)
        if KB_AUTO_SUMMARY:
            try:
                first_text = pages[0][1] if pages else ''
                if first_text.strip():
                    summary = _generate_summary(first_text[:KB_SUMMARY_MAX_CHARS])
                    if summary:
                        cache_set(cache_key('summary', str(doc_id)),
                                  json.dumps({'summary': summary},
                                             ensure_ascii=False))
            except Exception as e:
                logger.warning('[doc %s] summary failed: %s', doc_id, e)
    except _DocCancelled:
        logger.info('[doc %s] cancelled by user', doc_id)
        _update_status(conn, doc_id, STATUS_FAILED, error='已由用户取消')
        _record_recognition(conn, doc_id, 'failed')
    except Exception as e:
        logger.exception('[doc %s] failed', doc_id)
        _update_status(conn, doc_id, STATUS_FAILED, error=str(e))
        _record_recognition(conn, doc_id, 'failed')


def main():
    if not KB_VECTOR_DISABLED:
        ensure_schema()
    conn = _connect()
    _ensure_doc_columns(conn)
    _ensure_point_tables(conn)
    _reset_inflight(conn)
    _requeue_stale(conn)
    logger.info('knowledge.worker started, polling every %.1fs',
                KB_POLL_INTERVAL)
    last_retrain_check = 0.0
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
        try:
            if time.time() - last_retrain_check >= 60:
                from classifier import maybe_retrain
                maybe_retrain(conn)
                last_retrain_check = time.time()
        except Exception as e:
            logger.warning('classifier retrain check failed: %s', e)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
