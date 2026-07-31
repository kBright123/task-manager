"""知识库模块包。

模块划分:
- config.py  配置(路径/opencode 端点/模型,环境变量可覆盖)
- models.py  SQLite 模型(KbDocument/KbPage/KbEntity/KbTriple)
- ocr.py     RapidOCR + pypdfium2 文本识别
- embed.py   fastembed 中文向量
- store.py   SochDB 持久化/检索/图谱封装
- llm.py     opencode serve 客户端(三元组抽取 + 问答)
- views.py   Flask Blueprint 路由
- worker.py  后台处理进程(python -m kb.worker)
"""

from .config import (ALLOWED_EXTENSIONS, KB_ASK_GRAPH_DEPTH, KB_ASK_TOP_K,
                     KB_EMBED_MODEL, KB_LLM_DISABLED, KB_NAMESPACE,
                     KB_OPENCODE_BASE_URL, KB_OPENCODE_MODEL,
                     KB_OPENCODE_PROVIDER, KB_OPENCODE_TIMEOUT,
                     KB_PAGES_COLLECTION, KB_ROOT, KB_SOCHDB_PATH, STATUS_DONE,
                     STATUS_EMBED, STATUS_FAILED, STATUS_GRAPH, STATUS_OCR,
                     STATUS_QUEUED)

__all__ = [
    'ALLOWED_EXTENSIONS', 'KB_ASK_GRAPH_DEPTH', 'KB_ASK_TOP_K',
    'KB_EMBED_MODEL', 'KB_LLM_DISABLED', 'KB_NAMESPACE',
    'KB_OPENCODE_BASE_URL', 'KB_OPENCODE_MODEL', 'KB_OPENCODE_PROVIDER',
    'KB_OPENCODE_TIMEOUT', 'KB_PAGES_COLLECTION', 'KB_ROOT', 'KB_SOCHDB_PATH',
    'STATUS_DONE', 'STATUS_EMBED', 'STATUS_FAILED', 'STATUS_GRAPH',
    'STATUS_OCR', 'STATUS_QUEUED',
]


def __getattr__(name):
    if name == 'kb_bp':
        from .views import kb_bp
        return kb_bp
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
