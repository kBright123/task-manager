"""FastText 文档自动分类模块。

功能:
- 有监督: 以已有合集(collection)名称作为类别标签,基于文档标题+OCR 文本
  训练 fastText 分类器,识别完成后自动归类并归档。
- 零样本兜底: 无模型或置信度不足时,用内置类别种子关键词打分(冷启动可用)。
- 两级分类: 一级=粗类别(精简,用于展示:制度规范/财务商务/技术研发/人事行政/
  市场运营/项目法务/学习培训/会议汇报),二级=从标题提取的具体主题(如
  「重大活动信息系统保障方案编制规范」->「制度规范·重大活动信息系统保障方案」),
  标题提不出主题时回退固定类型词(合同/发票/纪要…),自动集合按完整层级标签命名。
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
# 二级兜底固定类型词:标题提不出具体主题时使用(合同/发票/纪要…)。
# 关键词用特征化短语,避免"分析/结论"这类泛词造成误判。
SEED_CATEGORIES = {
    '合同': ['甲方', '乙方', '合同编号', '违约责任', '签署日期', '合同期限',
            '签字盖章', '合同条款', '合同约定', '付款方式', '一式两份'],
    '发票': ['增值税发票', '发票号码', '发票代码', '开票日期', '价税合计',
            '税额', '收款人', '报销单', '发票章'],
    '简历': ['求职意向', '期望薪资', '教育经历', '工作经历', '技能特长',
            '自我评价', '应聘岗位', '联系电话', '学历背景'],
    '会议纪要': ['会议纪要', '参会人员', '会议议程', '会议决议', '讨论要点',
                '下一步计划', '主持人', '纪要'],
    '通知公告': ['特此通知', '请遵照执行', '自发布之日起', '现将有关',
                '通知如下', '特此公告', '各部门'],
    '报告': ['调研报告', '工作总结', '年度报告', '情况汇报', '可行性分析',
             '述职', '报告'],
    '论文': ['参考文献', '引言', '研究方法', '实验数据', '论文摘要',
            '学术期刊', '研究背景'],
    '教程': ['操作步骤', '使用说明', '安装教程', '入门指南', '功能说明',
            '配置方法', '点击'],
    '方案': ['实施方案', '技术方案', '设计方案', '建设方案', '总体思路',
            '推进计划', '需求分析'],
    '制度': ['管理制度', '规章制度', '考核办法', '实施细则', '本条例',
            '本办法', '罚则', '违反规定'],
    '证书': ['证书编号', '发证机关', '有效期限', '资格认证', '考核成绩',
            '成绩合格'],
    '邮件': ['此致敬礼', '主题', '抄送', '收件人', '发件人', '回复邮件'],
    '笔记': ['笔记', '知识点', '复习要点', '概念整理', '学习心得'],
}

# 一级类别(粗,用于展示与浏览,保持精简)。
# 每类聚合常见文档类型与主题关键词;二级具体主题优先从标题提取,提取不出时
# 回退到 SEED_CATEGORIES(固定类型词)。标签形如 `制度规范·重大活动信息系统
# 保障方案`、`财务商务·合同`、`人事行政·简历`。
PRIMARY_CATEGORIES = {
    '制度规范': [
        '编制规范', '编制指南', '管理办法', '实施细则', '规章制度', '考核办法',
        '暂行规定', '管理规定', '管理规范', '工作规范', '操作规程', '岗位职责',
        '行为准则', '工作流程', '审批流程', '办事流程', '管理制度', '本条例',
        '本办法', '本细则', '本规定', '内控', '问责', '罚则', '自查', '制度',
        '规范', '办法', '规定', '细则', '准则', '流程', '章程', '条例', '导则',
        '纪律', '特此通知', '通知如下', '特此公告', '请遵照执行',
        '自发布之日起', '现将有关', '各部门',
    ],
    '财务商务': [
        '发票', '报销', '预算', '税务', '税率', '成本', '营收', '利润', '对账',
        '付款', '收款', '审计', '财报', '资产负债表', '现金流量', '差旅费',
        '经费', '工资', '社保', '公积金', '财务', '价税合计', '发票号码',
        '开票日期', '税额', '税号', '甲方', '乙方', '合同编号', '违约责任',
        '合同条款', '签署日期', '合同期限', '盖章', '订单', '报价', '签单',
        '投标', '招标', '商业计划',
    ],
    '技术研发': [
        '代码', '接口', '数据库', '部署', '测试', '需求', '架构', '版本',
        '研发', '系统', '服务器', '前端', '后端', '算法', '技术方案', 'bug',
        '技术文档', '需求文档', '设计文档', '开发指南', '运维', '数据', '统计',
        '指标', '报表', 'KPI', '可视化', '建模', '趋势', '增长率',
    ],
    '人事行政': [
        '招聘', '面试', '入职', '离职', '绩效', '考勤', '请假', '调休',
        '加班', '晋升', '薪酬', '福利', '劳动合同', '试用期', '转正', '人事',
        '求职意向', '期望薪资', '教育经历', '工作经历', '技能特长',
        '自我评价', '应聘岗位', '行政', '办公用品', '固定资产', '仓库',
        '车辆', '门禁', '物业', '会务', '接待', '印章',
    ],
    '市场运营': [
        '客户', '订单', '销售', '营销', '推广', '品牌', '渠道', '报价',
        '商务', '签单', '线索', '成交', '佣金', '市场', '投放', '活动',
    ],
    '项目法务': [
        '项目', '进度', '里程碑', '排期', '交付', '验收', '风险', '迭代',
        '负责人', '延期', '需求评审', '法律', '法规', '合规', '诉讼', '仲裁',
        '知识产权', '商标', '专利', '监管', '政策',
    ],
    '学习培训': [
        '学习', '培训', '课程', '考试', '知识点', '复习', '教学', '讲义',
        '考核', '认证', '教程', '指南', '手册', '入门', '笔记', '心得',
        '安装教程', '配置方法', '操作步骤', '使用说明', '论文', '参考文献',
        '研究方法', '实验数据', '期刊', '证书编号', '资格认证', '有效期限',
    ],
    '会议汇报': [
        '会议纪要', '参会人员', '会议议程', '会议决议', '讨论要点',
        '下一步计划', '主持人', '纪要', '工作总结', '年度报告', '情况汇报',
        '述职', '调研报告', '会议', '汇报',
    ],
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


_snapshot_cache = None      # (mtime_ns, data)


def _read_snapshot():
    """读取训练快照,带 mtime 缓存:文件未变化时避免重复读盘。

    分类/归档在 worker 中逐文档调用,快照 JSON 每次重新读取是明显的 IO
    浪费;以文件 mtime 做失效判断,与写入方(_write_snapshot)解耦。"""
    try:
        st = os.stat(SNAPSHOT_PATH)
    except OSError:
        return {}
    if _snapshot_cache is not None and _snapshot_cache[0] == st.st_mtime_ns:
        return _snapshot_cache[1]
    try:
        with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
    except Exception:
        return {}
    _snapshot_cache = (st.st_mtime_ns, data)
    return data


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

_MODEL_RETRY_INTERVAL = 60.0


def _get_model():
    """加载 fastText 模型(惰性)。

    加载失败/模型缺失时置 _model_failed 并记录失败时刻;_train() 训练完成
    会重置 _model_failed。为避免文件短暂缺失(如训练写入中)后永久降级,
    失败超过 _MODEL_RETRY_INTERVAL 秒会再次尝试加载。"""
    global _model, _model_failed
    if _model is None:
        if not _model_failed:
            if os.path.exists(MODEL_PATH):
                try:
                    import fasttext
                    _model = fasttext.load_model(MODEL_PATH)
                except Exception as e:
                    _model_failed = time.time()
                    logger.warning('load fastText model failed: %s', e)
            else:
                _model_failed = time.time()
        elif time.time() - _model_failed > _MODEL_RETRY_INTERVAL:
            _model_failed = False
            return _get_model()
    return _model


def _kw_score(content, keywords):
    """按关键词出现次数×短语长度加权打分(短语越长越有区分度)。"""
    score = 0
    for kw in keywords:
        n = content.count(kw)
        if n:
            score += n * len(kw)
    return score


def _keyword_type(content):
    """一级:文档类型。"""
    best, best_score = None, 0
    for cat, kws in SEED_CATEGORIES.items():
        s = _kw_score(content, kws)
        if s > best_score:
            best, best_score = cat, s
    return best, best_score


def _keyword_primary(content):
    """一级:粗类别(精简集合,用于展示)。"""
    best, best_score = None, 0
    for cat, kws in PRIMARY_CATEGORIES.items():
        s = _kw_score(content, kws)
        if s > best_score:
            best, best_score = cat, s
    return best, best_score


# 标题主题提取:末尾文档格式尾缀词(长词优先,每次只剥离最外层一个)。
_SUBJECT_SUFFIXES = [
    '编制规范', '实施细则', '考核办法', '管理办法', '暂行规定', '管理规定',
    '管理规范', '工作规范', '操作规程', '行为准则', '工作指引', '申报指南',
    '会议纪要', '会议简报', '会议决议', '建设方案', '实施方案', '工作计划',
    '工作总结', '编制方案', '应急方案', '整改方案', '整治方案', '活动方案',
    '工作方案', '宣传方案', '保障方案', '培训方案', '技术方案', '设计方案',
    '总体方案', '评估方案', '处置预案', '应急预案', '应对方案', '救援方案',
    '建设规划', '发展规划', '战略规划', '专项规划', '总体规划', '指导意见',
    '实施意见', '操作指南', '使用说明', '管理手册', '工作手册', '员工手册',
    '操作手册', '培训手册', '编制办法', '工作规程', '管理规程', '管理准则',
    '规章制度', '岗位职责', '办事流程', '审批流程', '工作流程', '操作流程',
    '管理流程',
    '通知', '公告', '纪要', '总结', '报告', '方案', '办法', '规定', '制度',
    '规范', '细则', '准则', '流程', '指南', '手册', '说明', '规划', '计划',
    '预案', '意见', '建议', '须知', '标准', '导则', '措施', '条例', '章程',
]

# 标准编号(如 JR∕T 0323—2023、GB/T 222-2018、YD∕T 0149-2016、
# Q／YB 0058.3—2023、DB11/1234-2024 等)的无效字符
_STD_CODE_RE = re.compile(
    r'[A-Z]{1,4}\d{0,4}\s*[/∕／]\s*[A-Z]{0,4}\s*\d{2,}(?:\.\d+)*\s*[-—–－]\s*\d{2,4}'
    r'|[A-Z]{1,4}\s*[/∕／]\s*[A-Z]{0,4}\s*\d{2,}(?:\.\d+)*\s*[-—–－]?')

# 标题末尾的重复下载/版本后缀(浏览器或网盘对同名文件自动追加),
# 如「技术规范-1」「技术规范(1)」「技术规范_2」「技术规范-1.pdf」。
# 只匹配 1-2 位数字,避免误伤 4 位年份(如「规范-2026」)与标准编号。
_VERSION_SUFFIX_RE = re.compile(
    r'(?:[-_—–－]\d{1,2}|\d{1,2}[)）]|[（(]\d{1,2}[)）]|[._][a-z0-9]{1,5})$')


def _strip_version_suffix(s):
    """循环剥离标题末尾的版本/重复下载后缀,返回剥离后的文本。"""
    while True:
        t = _VERSION_SUFFIX_RE.sub('', s)
        if t == s:
            return t
        s = t

# 二级主题展示最大长度(超出截断加省略号)
_SUBJECT_MAX_CHARS = 12


def clean_subject_text(s):
    """清理主题文本:去除标准编号(JR∕T 0323—2023 等)、版本后缀与孤立标点。"""
    if not s:
        return ''
    s = _STD_CODE_RE.sub('', s)
    s = re.sub(r'\s+', '', s)
    s = _strip_version_suffix(s)
    s = s.strip('、，。的·,;；:：/∕／-—–－|｜_()（）〔〕【】《》[]「」‘’“”"\'')
    return s


def short_subject(s):
    """缩减二级主题展示:清理无效字符并截断到 _SUBJECT_MAX_CHARS 字。"""
    s = clean_subject_text(s)
    if len(s) > _SUBJECT_MAX_CHARS:
        s = s[:max(_SUBJECT_MAX_CHARS - 1, 1)] + '…'
    return s


def _extract_subject(title):
    """从标题提取二级具体主题。

    去掉开头「关于…」、括号文档标记与末尾文档格式尾缀词,保留剩余短语。
    例如「关于做好2026年汛期安全生产工作的通知」->「做好2026年汛期安全生产」;
    「重大活动信息系统保障方案编制规范」->「重大活动信息系统保障方案」。
    剩余内容过短(<3 字)或标题为空时返回 None(由调用方回退固定类型词)。"""
    if not title:
        return None
    t = title.strip()
    for pre in ('关于印发', '关于进一步做好', '关于认真做好', '关于进一步',
                '关于做好', '关于对', '关于'):
        if t.startswith(pre) and len(t) > len(pre):
            t = t[len(pre):]
            break
    m = re.search(r'《([^》]{3,})》', t)
    if m:
        t = m.group(1)
    for suf in _SUBJECT_SUFFIXES:
        if t.endswith(suf) and len(t) > len(suf) + 2:
            t = t[:-len(suf)]
            break
    t = clean_subject_text(t)
    if len(t) < 3:
        return None
    return t


def _seed_classify(content, title=''):
    """零样本兜底:一级类别(粗)+ 二级主题,组成 `类别·主题`。

    二级优先从标题提取具体主题(如「重大活动信息系统保障方案编制规范」
    ->「制度规范·重大活动信息系统保障方案」);标题提不出主题时回退到固定
    类型词(合同/发票/纪要…)。仅命中一个层级时用该层级作为标签;
    都未命中返回 (None, 0.0)。"""
    p, ps = _keyword_primary(content)
    subject = _extract_subject(title)
    t, ts = _keyword_type(content)
    if p is None and subject is None and t is None:
        return None, 0.0
    label = p or ''
    second = subject or t
    if second:
        label = f'{label}·{second}' if label else second
    conf = min(0.5 + 0.03 * (ps + (ts if subject is None else 0)), 0.95)
    return label, conf


def classify(text, title=''):
    """分类文档文本,返回 (label or None, confidence)。

    优先用 fastText 有监督模型;置信度低于阈值或无模型时,回退到内置
    种子关键词(一级类别 + 二级主题)。标签形式为 `类别·主题`。
    两者都未命中返回 (None, 0.0)。"""
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
                    if '·' not in name:
                        label, _ = _seed_classify(content, title)
                        if label and '·' in label:
                            return label, conf
                    return name, conf
        except Exception as e:
            logger.warning('fastText predict failed: %s', e)
    return _seed_classify(content, title)


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
