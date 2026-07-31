import json
import logging
import re
import time

import requests

from .config import (KB_LLM_DISABLED, KB_OPENCODE_BASE_URL,
                     KB_OPENCODE_MODEL, KB_OPENCODE_PROVIDER,
                     KB_OPENCODE_TIMEOUT)

logger = logging.getLogger(__name__)

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


def ask(question, sources):
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
