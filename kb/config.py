import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}

STATUS_QUEUED = 'queued'
STATUS_OCR = 'ocr'
STATUS_EMBED = 'embedding'
STATUS_GRAPH = 'graphing'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
