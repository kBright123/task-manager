"""FastText 文档自动分类模块。

功能:
- 有监督: 以已有合集(collection)名称作为类别标签,基于文档标题+OCR 文本
  训练 fastText 分类器,识别完成后自动归类并归档。
- 零样本兜底: 无模型或置信度不足时,用内置类别种子关键词打分(冷启动可用)。
- 自动建合集: 预测出类别名后,若不存在同名合集则自动创建(私有),再归档。

无 fasttext 环境时自动降级为关键词分类,不影响文档识别主流程。
模型文件与训练快照存放在 instance/kb_data/ 下。

环境变量:
- KB_CLASSIFIER_ENABLED   是否启用自动分类(默认 1)
- KB_CLASSIFIER_MODEL_PATH   模型文件路径(默认 instance/kb_data/classifier.bin)
- KB_CLASSIFIER_CONFIDENCE   fastText 接受阈值(默认 0.3)
- KB_CLASSIFIER_MIN_SAMPLES 有监督训练最少样本数(默认 3)
- KB_CLASSIFIER_MAX_TEXT_CHARS 每篇文档用于训练的字符上限(默认 3000)
- KB_CLASSIFIER_RETRAIN_INTERVAL 最短重训间隔秒数(默认 3600)
"""
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import time

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

ENABLED = os.environ.get('KB_CLASSIFIER_ENABLED', '1') == '1'
MODEL_DIR = os.environ.get(
    'KB_CLASSIFIER_MODEL_DIR',
    os.path.join(_PROJECT_ROOT, 'instance', 'kb_data'))
MODEL_PATH = os.environ.get(
    'KB_CLASSIFIER_MODEL_PATH',
    os.path.join(MODEL_DIR, 'classifier.bin'))
SNAPSHOT_PATH = os.environ.get(
    'KB_CLASSIFIER_SNAPSHOT_PATH',
    os.path.join(MODEL_DIR, 'classifier_train.json'))

CONFIDENCE = float(os.environ.get('KB_CLASSIFIER_CONFIDENCE', '0.3'))
MIN_SAMPLES = int(os.environ.get('KB_CLASSIFIER_MIN_SAMPLES', '3'))
MAX_SAMPLES_PER_LABEL = int(
    os.environ.get('KB_CLASSIFIER_MAX_SAMPLES_PER_LABEL', '300'))
MAX_TEXT_CHARS = int(os.environ.get('KB_CLASSIFIER_MAX_TEXT_CHARS', '3000'))
RETRAIN_INTERVAL = int(os.environ.get('KB_CLASSIFIER_RETRAIN_INTERVAL', '3600'))

# 自动创建合集使用的颜色池
_COLORS = ['#4f46e7', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444',
           '#8b5cf6', '#ec4899', '#f97316', '#14b8a6', '#6366f1']

# 内置零样本类别种子(冷启动/模型缺失时的兜底)
SEED_CATEGORIES = {
    '合同': ['合同', '协议', '甲方', '乙方', '条款', '签署', '违约责任', '盖章'],
    '发票': ['发票', '税号', '增值税', '开票', '报销', '税额', '收款'],
    '简历': ['简历', '求职', '应聘', '工作经验', '教育背景', '技能', '个人简介'],
    '报告': ['报告', '总结', '调研', '分析', '结论', '汇报', '季度'],
    '笔记': ['笔记', '知识点', '复习', '重点', '概念', '整理'],
    '会议纪要': ['会议', '纪要', '议程', '参会', '决议', '讨论', '发言人'],
    '教程': ['教程', '指南', '手册', '操作步骤', '入门', '使用说明', '安装'],
    '证书': ['证书', '认证', '资格证', '颁发', '考试'],
    '论文': ['论文', '摘要', '参考文献', '研究方法', '引言', '结论'],
    '通知': ['通知', '公告', '通告', '注意事项'],
}

# 模块级模型缓存(worker 单进程内复用)
_model = None
_model_failed = False
_last_train_at = 0.0


# ---------------------------------------------------------------------------
# 文本处理
# ---------------------------------------------------------------------------

def _tokenize(text):
    """中文逐字空格切分 + 英文/数字保留为词,适配 fastText 子词 n-gram。"""
    if not text:
        return ''
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff])',
                  r' \1 ', text)
    return ' '.join(text.split())


def _sanitize_label(name):
    """fastText 标签不能含空白/换行,统一替换为下划线。"""
    label = re.sub(r'\s+', '_', name or '').strip('_')
    return label or '未分类'


def _pick_color(name):
    idx = int(hashlib.md5(name.encode('utf-8')).hexdigest(), 16) % len(_COLORS)
    return _COLORS[idx]


# ---------------------------------------------------------------------------
# 训练数据
# ---------------------------------------------------------------------------

def _load_training_samples(conn):
    """从已有合集构建有监督训练样本 list[(label, text)]。

    label 取合集名;text 取文档标题 + 各页 OCR 文本;每类最多保留最新
    MAX_SAMPLES_PER_LABEL 篇,单篇正文截取 MAX_TEXT_CHARS。"""
    rows = conn.execute(
        "SELECT c.name, d.id, d.title FROM kb_document d "
        "JOIN kb_collection c ON c.id = d.collection_id "
        "WHERE d.status='done' AND d.collection_id IS NOT NULL "
        "ORDER BY c.name, d.id DESC").fetchall()
    per_label = {}
    for name, doc_id, title in rows:
        name = (name or '').strip()
        if not name:
            continue
        if len(per_label.get(name, [])) >= MAX_SAMPLES_PER_LABEL:
            continue
        per_label.setdefault(name, []).append((doc_id, title))
    samples = []
    for name, items in per_label.items():
        for doc_id, title in items:
            pages = conn.execute(
                "SELECT text FROM kb_page WHERE doc_id=? "
                "AND text IS NOT NULL AND text<>'' ORDER BY page_no",
                (doc_id,)).fetchall()
            body = ' '.join(r[0] for r in pages)
            content = f'{title or ""} {body}'.strip()
            if content:
                samples.append((name, content[:MAX_TEXT_CHARS]))
    return samples


def _training_hash(conn):
    """按 (合集名, 文档数) 计算哈希,用于判断是否需要重训。"""
    rows = conn.execute(
        "SELECT c.name, COUNT(*) FROM kb_document d "
        "JOIN kb_collection c ON c.id = d.collection_id "
        "WHERE d.status='done' AND d.collection_id IS NOT NULL "
        "GROUP BY c.name ORDER BY c.name").fetchall()
    if not rows:
        return ''
    payload = '|'.join(f'{name}:{cnt}' for name, cnt in rows)
    return hashlib.md5(payload.encode('utf-8')).hexdigest()


def _read_snapshot():
    try:
        with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_snapshot(data):
    os.makedirs(os.path.dirname(SNAPSHOT_PATH) or '.', exist_ok=True)
    try:
        with open(SNAPSHOT_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as e:
        logger.warning('write classifier snapshot failed: %s', e)


# ---------------------------------------------------------------------------
# 训练 / 重训
# ---------------------------------------------------------------------------

def _train(conn, train_hash):
    samples = _load_training_samples(conn)
    if len(samples) < MIN_SAMPLES:
        return False
    import fasttext
    mapping = {}
    lines = []
    for name, text in samples:
        flabel = _sanitize_label(name)
        mapping[flabel] = name
        lines.append(f'__label__{flabel} {_tokenize(text)}')
    fd, tmp = tempfile.mkstemp(suffix='.txt', prefix='kb_cls_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        model = fasttext.train_supervised(
            input=tmp, lr=0.5, epoch=25, wordNgrams=2,
            minn=1, maxn=3, dim=50, minCount=1,
            bucket=2000000, loss='softmax', thread=2)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    os.makedirs(os.path.dirname(MODEL_PATH) or '.', exist_ok=True)
    model.save_model(MODEL_PATH)
    _write_snapshot({
        'hash': train_hash,
        'mapping': mapping,
        'labels': sorted(set(mapping.values())),
        'built_at': time.time(),
    })
    global _model, _model_failed
    _model = None
    _model_failed = False
    logger.info('fastText classifier trained: %d labels, %d samples',
                len(mapping), len(samples))
    return True


def maybe_retrain(conn):
    """按需重训:模型缺失 / 训练数据哈希变化 / 超过重训间隔。"""
    global _last_train_at
    if not ENABLED:
        return
    now = time.time()
    if os.path.exists(MODEL_PATH) and (now - _last_train_at) < RETRAIN_INTERVAL:
        return
    try:
        train_hash = _training_hash(conn)
        snap = _read_snapshot()
        if (snap.get('hash') == train_hash and os.path.exists(MODEL_PATH)):
            _last_train_at = now
            return
        if _train(conn, train_hash):
            _last_train_at = now
    except ImportError:
        logger.info('fasttext 未安装,自动分类降级为关键词匹配')
    except Exception as e:
        logger.warning('fastText classifier retrain failed: %s', e)


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------

def _get_model():
    global _model, _model_failed
    if _model is None and not _model_failed:
        if os.path.exists(MODEL_PATH):
            try:
                import fasttext
                _model = fasttext.load_model(MODEL_PATH)
            except Exception as e:
                _model_failed = True
                logger.warning('load fastText model failed: %s', e)
        else:
            _model_failed = True
    return _model


def _seed_classify(content):
    """零样本兜底:按内置类别种子关键词出现次数打分。"""
    best, best_score = None, 0
    for cat, kws in SEED_CATEGORIES.items():
        score = sum(content.count(kw) for kw in kws)
        if score > best_score:
            best, best_score = cat, score
    if best is None:
        return None, 0.0
    return best, min(0.5 + 0.05 * best_score, 0.95)


def classify(text, title=''):
    """分类文档文本,返回 (label or None, confidence)。

    优先用 fastText 有监督模型;置信度低于阈值或无模型时,回退到内置
    种子关键词;两者都未命中返回 (None, 0.0)。"""
    if not ENABLED:
        return None, 0.0
    content = f'{title or ""} {text or ""}'.strip()
    if not content:
        return None, 0.0
    model = _get_model()
    if model is not None:
        try:
            labels, probs = model.predict(_tokenize(content), k=1)
            if labels:
                flabel = labels[0].replace('__label__', '')
                conf = float(probs[0]) if probs else 0.0
                snap = _read_snapshot() or {}
                name = snap.get('mapping', {}).get(flabel) or flabel
                if conf >= CONFIDENCE:
                    return name, conf
        except Exception as e:
            logger.warning('fastText predict failed: %s', e)
    return _seed_classify(content)


# ---------------------------------------------------------------------------
# 自动归档
# ---------------------------------------------------------------------------

def _ensure_collection(conn, name, owner_id):
    """找到或创建指定名称的合集,返回 (collection_id, created)。"""
    row = conn.execute(
        'SELECT id FROM kb_collection WHERE name=?', (name,)).fetchone()
    if row:
        return row[0], False
    color = _pick_color(name)
    try:
        cur = conn.execute(
            'INSERT INTO kb_collection (name, color, visibility, owner_id, '
            "created_at) VALUES (?, ?, 'private', ?, datetime('now'))",
            (name, color, owner_id))
        return cur.lastrowid, True
    except sqlite3.IntegrityError:
        conn.rollback()
        row = conn.execute(
            'SELECT id FROM kb_collection WHERE name=?', (name,)).fetchone()
        if not row:
            raise
        return row[0], False


def auto_archive(conn, doc_id, uploaded_by, title, text):
    """对文档做自动分类并归档到对应合集。

    仅在满足以下条件时改动:
    - 文档尚未归档(collection_id IS NULL) -> 分类并归档;
    - 文档此前由自动分类归档(auto_classified=1) -> 重识别后预测类别变化则迁移。
    返回 (created_collection, label, confidence) 或 None。"""
    if not ENABLED:
        return None
    try:
        label, conf = classify(text, title)
    except Exception as e:
        logger.warning('classify doc %s failed: %s', doc_id, e)
        return None
    if not label:
        return None
    row = conn.execute(
        'SELECT collection_id, uploaded_by, title, COALESCE(auto_classified,0) '
        'FROM kb_document WHERE id=?', (doc_id,)).fetchone()
    if not row:
        return None
    collection_id, _owner, _title, auto_classified = row
    if collection_id is None:
        cid, created = _ensure_collection(conn, label, uploaded_by)
        conn.execute(
            'UPDATE kb_document SET collection_id=?, auto_classified=1 '
            'WHERE id=?', (cid, doc_id))
        conn.commit()
        return created, label, conf
    if auto_classified:
        current = conn.execute(
            'SELECT name FROM kb_collection WHERE id=?',
            (collection_id,)).fetchone()
        if current and current[0] != label:
            cid, created = _ensure_collection(conn, label, uploaded_by)
            conn.execute(
                'UPDATE kb_document SET collection_id=? WHERE id=?',
                (cid, doc_id))
            conn.commit()
            return created, label, conf
    return None
