# -*- coding: utf-8 -*-
"""大模型接入统一层(OpenAI 兼容 chat/completions)。

配置分层:
- 全局配置 SysSetting(llm_*) 由管理员在「后台管理 → 模型设置」维护, 视作
  “管理员的大模型”, 是全站默认;
- 个人配置 SysSetting(llm_{uid}_*) 由各用户在「个人信息 → 大模型设置」维护,
  优先级高于全局; 留空即跟随管理员配置。

后端解析: 个人配置优先 → 全局(管理员) → 默认 OpenAI 接口。
"""
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

from core.app_services import get_job_setting, set_job_setting  # noqa: E402

_MODE_API = 'api'

DEFAULT_BASE_URL_API = 'https://api.openai.com/v1'
DEFAULT_TIMEOUT = 180

_GLOBAL_KEYS = ('llm_api_key', 'llm_base_url', 'llm_model')


def _pkeys(uid):
    return tuple('llm_%d_%s' % (uid, k) for k in
                 ('api_key', 'base_url', 'model'))


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------
def get_global_config():
    """返回全局(管理员)大模型配置。"""
    return {
        'api_key': (get_job_setting('llm_api_key', '') or '').strip(),
        'base_url': (get_job_setting('llm_base_url', '') or '').strip(),
        'model': (get_job_setting('llm_model', '') or '').strip(),
    }


def save_global_config(cfg):
    """保存全局配置; 空值清除对应项。"""
    for key, field in zip(_GLOBAL_KEYS, ('api_key', 'base_url', 'model')):
        set_job_setting(key, (cfg.get(field) or '').strip())


def get_user_config(user):
    """返回某用户个人配置; 全空表示未配置。"""
    if user is None:
        return {}
    k, b, m = _pkeys(user.id)
    return {
        'api_key': (get_job_setting(k, '') or '').strip(),
        'base_url': (get_job_setting(b, '') or '').strip(),
        'model': (get_job_setting(m, '') or '').strip(),
    }


def save_user_config(user, cfg):
    """保存个人配置; 空值清除对应项(恢复“跟随管理员”)。"""
    k, b, m = _pkeys(user.id)
    for key, field in zip((k, b, m), ('api_key', 'base_url', 'model')):
        set_job_setting(key, (cfg.get(field) or '').strip())


def has_user_config(user):
    """用户是否配置了任何一项(存在个人覆盖)。"""
    return any(user and v for v in get_user_config(user).values())


def masked_key(key):
    """脱敏显示 API Key: 保留首4/末4位。"""
    key = (key or '').strip()
    if not key:
        return ''
    if len(key) <= 8:
        return key[0] + '*' * (len(key) - 1)
    return key[:4] + '*' * 8 + key[-4:]


# ---------------------------------------------------------------------------
# 用户解析(请求上下文 或 worker 线程上下文)
# ---------------------------------------------------------------------------
_context = threading.local()


def set_llm_context_user(user):
    """后台 worker 在无请求上下文时, 用作业创建者作为 LLM 归属用户。"""
    _context.user = user


def clear_llm_context_user():
    _context.user = None


def _effective_user(user=None):
    if user is not None:
        return user if getattr(user, 'is_authenticated', True) else None
    u = getattr(_context, 'user', None)
    if u is not None:
        return u
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            return current_user
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 决策
# ---------------------------------------------------------------------------
def resolve_config(user=None):
    """返回 (mode, cfg)。mode 固定为 'api'(OpenAI 兼容接口)。

    个人配置优先; 其次全局(管理员); 未配置 Key 时返回空 Key, 由调用方决定
    是否跳过或报错。
    """
    u = _effective_user(user)
    own = get_user_config(u) if u is not None else {}
    g = get_global_config()

    return (_MODE_API, {
        'mode': _MODE_API,
        'base_url': (own.get('base_url') or g.get('base_url') or
                     DEFAULT_BASE_URL_API),
        'model': own.get('model') or g.get('model') or '',
        'api_key': own.get('api_key') or g.get('api_key') or '',
    })


def _chat_endpoint(base):
    """构造 chat/completions 地址, 兼容带/不带 /v1 前缀的 base。"""
    base = (base or '').strip().rstrip('/')
    if not base:
        base = DEFAULT_BASE_URL_API
    if base.endswith('/chat/completions'):
        return base
    if re.search(r'/v\d+(\.\d+)?$', base):
        return base + '/chat/completions'
    return base + '/v1/chat/completions'


def masked(base):
    """本地工具: 预览 resolved base_url(供调试)。"""
    return base


# ---------------------------------------------------------------------------
# 调用
# ---------------------------------------------------------------------------
def _retry(fn, attempts=3, delay=2):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            logger.warning('LLM 调用失败(%s), 重试 %s/%s', e, i + 1, attempts)
            time.sleep(delay * (i + 1))
    raise last


def _api_chat(system, prompt, cfg, temperature=0.7, timeout=None,
              max_tokens=None):
    import requests
    url = _chat_endpoint(cfg.get('base_url'))
    messages = []
    if system and system.strip():
        messages.append({'role': 'system', 'content': system.strip()})
    messages.append({'role': 'user', 'content': prompt})
    body = {'model': cfg.get('model') or '', 'messages': messages,
            'temperature': temperature}
    if max_tokens:
        body['max_tokens'] = max_tokens

    def _call():
        resp = requests.post(
            url, json=body,
            headers={'Authorization': 'Bearer %s' % cfg.get('api_key', ''),
                     'Content-Type': 'application/json'},
            timeout=timeout or DEFAULT_TIMEOUT)
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code >= 400:
            msg = ((data.get('error') or {}).get('message')
                   if isinstance(data.get('error'), dict)
                   else (data.get('error') or ('HTTP %s' % resp.status_code)))
            raise RuntimeError('大模型接口错误(%s): %s' % (resp.status_code, msg))
        try:
            return (data['choices'][0]['message']['content'] or '').strip()
        except (KeyError, IndexError, TypeError):
            raise RuntimeError('大模型返回格式异常: %s'
                               % str(data)[:200])

    return _retry(_call)


def chat(system, prompt, user=None, temperature=0.7, timeout=None,
         max_tokens=None):
    """最外层统一入口: 自动解析归属用户(个人→管理员)后调用。"""
    _mode, cfg = resolve_config(user)
    if not cfg.get('api_key'):
        raise RuntimeError('未配置大模型 API Key')
    return _api_chat(system, prompt, cfg, temperature=temperature,
                     timeout=timeout, max_tokens=max_tokens)


def health(config=None):
    """返回配置摘要(不含完整 Key), 供设置页展示当前生效项。"""
    _mode, cfg = resolve_config(None) if config is None else (
        'api', config)
    return {
        'mode': _MODE_API,
        'masked_api_key': masked_key(cfg.get('api_key')),
        'base_url': cfg.get('base_url', ''),
        'model': cfg.get('model', ''),
        'configured': bool(cfg.get('api_key')),
    }