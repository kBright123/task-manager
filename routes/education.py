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

# -*- coding: utf-8 -*-
"""教育娱乐模式：前端学习乐园 + 独立后端数据库。

定位: 教育模式使用自己独立的数据库(edu.db), 不依赖也不写工作模式数据库,
仅支持已登录账号使用(数据按账号归属 u<id>)。

数据:
- 孩子档案(名字/出生年份/性别)
- 每个孩子的学习状态: 星星、答题记录、错题本、星愿、兑换记录、徽章、
  每日用量、连击、闯关进度 等(以 JSON 弹存储于 edu_data 表)。

页面由前端 JS 驱动, 本模块负责:
- 渲染页面骨架(/edu/)
- 提供 /edu/api/** REST 接口, 供前端读写数据。
"""
import gzip
import hashlib
import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from datetime import datetime

from contextlib import contextmanager

from flask import (Blueprint, jsonify, request, render_template, current_app,
                   abort, send_file, redirect, url_for)
from flask_login import current_user
from sqlalchemy import (create_engine, Column, Integer, String, Text, DateTime,
                        text, event)
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

education_bp = Blueprint('education', __name__, url_prefix='/edu')

# ---- 独立数据库(edu.db), 与工作模式 tasks.db 完全解耦 ----
_engine_lock = threading.Lock()
_engine = None
_Session = None
Base = declarative_base()

# 前端量较大的 JSON 用 Text 存; 记录/错题等整体随 state 一起存,减少表数量与同步复杂度
class EduProfile(Base):
    __tablename__ = 'edu_profile'
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False, index=True)
    name = Column(String(40), default='宝贝')
    birth_year = Column(Integer, default=2018)
    gender = Column(String(12), default='')
    sort = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class EduData(Base):
    __tablename__ = 'edu_data'
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False, index=True)
    profile_id = Column(Integer, nullable=False, index=True)
    dkey = Column(String(40), default='state')   # 'state' | 'levels' | 'workbench'
    payload = Column(Text, default='{}')
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class EduQBank(Base):
    """题目库: 按归属/学科/类型/难度存储, 支持去重、权重拉取、作答统计."""
    __tablename__ = 'edu_qbank'
    id = Column(Integer, primary_key=True)
    owner = Column(String(80), nullable=False, index=True)
    subj = Column(String(16), nullable=False, index=True)      # 'zh' | 'math' | 'en'
    type = Column(String(16), nullable=False, index=True)      # 'poem','zi','stroke','pinyin','yun','read','fan','liang','calc','judge','word','order','word','dialogue'
    difficulty = Column(Integer, default=3, index=True)        # 1~5
    prompt = Column(Text, nullable=False)                      # 题干(去重键的一部分)
    options = Column(Text, default='')                         # JSON 数组 [{v,label}]
    correct = Column(String(200), nullable=False)              # 正确答案
    note = Column(Text, default='')                            # 解析/备注
    used_count = Column(Integer, default=0)                    # 被出题次数
    wrong_count = Column(Integer, default=0)                   # 答错次数
    last_seen = Column(DateTime)                               # 最近出题/复现时间
    created_at = Column(DateTime)


def _db_path():
    return os.path.join(current_app.instance_path, 'edu.db')


def _sqlite_pragmas(dbapi_conn, _rec):
    """edu.db 并发加固: 与主库一致的 WAL + busy_timeout."""
    try:
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=5000')
        cur.close()
    except Exception:
        pass


def _session_factory():
    global _engine, _Session
    with _engine_lock:
        if _engine is None:
            path = _db_path()
            _engine = create_engine('sqlite:///' + path, echo=False)
            event.listen(_engine, 'connect', _sqlite_pragmas)
            Base.metadata.create_all(_engine)
            _migrate(_engine)
            _Session = sessionmaker(bind=_engine)
    return _Session


@contextmanager
def _session_scope():
    """请求级会话上下文: 异常回滚, 结束时保证关闭, 不残留跨请求状态."""
    s = _session_factory()()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _get_session():
    """一次性会话(旧调用兼容, 请优先改用 _session_scope() 上下文)."""
    return _session_factory()()


def _migrate(engine):
    """轻量迁移: 旧库补新增列(create_all 不会改已存在表)."""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(edu_data)")).fetchall()]
        if cols and 'created_at' not in cols:
            conn.execute(text("ALTER TABLE edu_data ADD COLUMN created_at DATETIME"))
        cols2 = [r[1] for r in conn.execute(text("PRAGMA table_info(edu_profile)")).fetchall()]
        if cols2 and 'created_at' not in cols2:
            conn.execute(text("ALTER TABLE edu_profile ADD COLUMN created_at DATETIME"))
        conn.commit()


@education_bp.before_request
def _edu_require_login():
    """教育乐园仅支持已登录账号使用(不再支持匿名/游客)."""
    if current_user and getattr(current_user, 'is_authenticated', False):
        return None
    if request.path.startswith('/edu/api/'):
        return jsonify({'ok': False, 'error': '请先登录'}), 401
    return redirect(url_for('login', next=request.path or None))


def _owner_id():
    """数据归属: 已登录按账号 id 归属(匿名已移除, 未登录由 before_request 拦截)."""
    if current_user and getattr(current_user, 'is_authenticated', False):
        return 'u' + str(current_user.id)
    abort(401)


def _kid_owned(sess, owner, pid):
    """校验孩子档案归属: 返回 True 表示该 pid 属于当前 owner, 可安全操作."""
    return sess.query(EduProfile).filter_by(id=pid, owner=owner).first() is not None


def _safe_int(value, default):
    """安全整数解析(供 user 输入的 diff/limit/birthYear 等)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _drop_profile_data(sess, owner, pid):
    """删除孩子档案及其所有数据弹(仅限归属内)."""
    sess.query(EduProfile).filter_by(id=pid, owner=owner).delete()
    sess.query(EduData).filter_by(owner=owner, profile_id=pid).delete()


def _merge_blob(base, ext):
    """把另一档案的 state/workbench JSON 弹归并进主档案(用于同账号下同名档案去重).

    规则(保守、不丢数据):
    - stars 取较大而非求和: stars 是各设备上的「累计余额/累计获得」, 同一段学习历史
      会被镜像到多个档案/设备; 若按运行合计求和, 重叠部分会被重复累加(出现虚假高星)。
      取较大保持幂等、只反映真实最高余额, 绝不伪造星星。
    - 数组(records/wrong/wishLog/redeemed/starLog/wishes 等): 按 JSON 去重并集
    - 对象(badges/adv/level/course/dailySecs/giftPrices 等): 键合并(账号优先, 匿名仅补缺);
      course 必须并入, 否则课程进度与里程碑发放标记丢失, 会触发重复发星
    - 计数器(maxCombo/submits): 取较大; usage 秒数/题数: 求和
    - settings/课程难度: 以账号端为准, 匿名不覆盖
    """
    if not isinstance(ext, dict):
        return base
    base = dict(base or {})
    try:
        base['stars'] = max(int(base.get('stars') or 0), int(ext.get('stars') or 0))
    except (TypeError, ValueError):
        pass
    for key in ('records', 'wrong', 'wishLog', 'redeemed', 'starLog', 'starAwards', 'wishes'):
        e = ext.get(key)
        if not isinstance(e, list):
            continue
        b = base.get(key)
        if not isinstance(b, list):
            b = []
        seen = set()
        for it in b:
            if it is None:
                continue
            try:
                seen.add(json.dumps(it, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
            except Exception:
                pass
        for it in e:
            if it is None:
                continue
            try:
                h = json.dumps(it, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            except Exception:
                h = None
            if h is not None and h in seen:
                continue
            if h is not None:
                seen.add(h)
            b.append(it)
        base[key] = b
    for key in ('badges', 'adv', 'level', 'course', 'dailySecs', 'giftPrices'):
        e = ext.get(key)
        if not isinstance(e, dict):
            continue
        b = base.get(key)
        if not isinstance(b, dict):
            b = {}
        for k, v in e.items():
            b.setdefault(k, v)
        base[key] = b
    for key in ('maxCombo', 'submits'):
        try:
            base[key] = max(int(base.get(key) or 0), int(ext.get(key) or 0))
        except (TypeError, ValueError):
            pass
    # usage: 新版为按天 map {dayKey:{secs,count,n}}, 旧版为扁平 {secs,n,count}; 均合并不丢
    usage = base.get('usage')
    eusage = ext.get('usage')
    if isinstance(usage, dict) and isinstance(eusage, dict):
        for day, e in eusage.items():
            if not isinstance(e, dict):
                continue
            b = usage.get(day)
            if not isinstance(b, dict):
                b = usage[day] = {}
            for k in ('secs', 'n', 'count'):
                try:
                    b[k] = int(b.get(k) or 0) + int(e.get(k) or 0)
                except (TypeError, ValueError):
                    pass
        # 兼容旧扁平格式的顶层 secs/n/count(仅当匿名端真有该字段时求和)
        for k in ('secs', 'n', 'count'):
            if k in eusage and isinstance(eusage[k], (int, float)):
                try:
                    usage[k] = int(usage.get(k) or 0) + int(eusage[k])
                except (TypeError, ValueError):
                    pass
        base['usage'] = usage
    # usageExtra: 按天取较大(各端各自解锁次数, 账号优先、只增不减, 防重复累加)
    eue = ext.get('usageExtra')
    if isinstance(eue, dict):
        bue = base.get('usageExtra')
        if not isinstance(bue, dict):
            bue = {}
        for day, c in eue.items():
            try:
                bue[day] = max(int(bue.get(day) or 0), int(c))
            except (TypeError, ValueError):
                pass
        base['usageExtra'] = bue
    return base


def _merge_star_ledger(base, ext):
    """stars 权威账本(dkey='stars')合并: 事件按 key 幂等去重, total 重新求和.

    state 弹里的 stars 只是展示镜像, 账本才是服务端唯一权威合计.
    匿名/去重归并时, 两端的「加/扣星星事件」只需取一次(O(重叠)), total=Σ事件.
    """
    base = dict(base or {})
    if not isinstance(ext, dict):
        return base
    seen = dict(base.get('seen') or {})
    log = list(base.get('log') or [])
    total = 0
    for ev in log:
        try:
            total += int(ev.get('amount') or 0)
        except (TypeError, ValueError):
            pass
    for ev in (ext.get('log') or []):
        if not isinstance(ev, dict):
            continue
        k = ev.get('key')
        if not k or k in seen:
            continue
        seen[k] = 1
        log.append(ev)
        try:
            total += int(ev.get('amount') or 0)
        except (TypeError, ValueError):
            pass
    base['seen'] = seen
    base['log'] = log
    base['total'] = total
    return base


def _dedup_profiles_in_owner(sess, owner):
    """同一归属下按 (姓名, 出生年, 性别) 合并重复宝贝档案.

    历史上(旧版收养/重复同步)可能出现同一账号下多个完全同名的宝贝,
    各自累积了数据。此函数保留 id 最小者为规范档案, 把其余同名档案的数据
    弹按 _merge_blob 规则并入规范档案, 再删除重复档案。
    返回 dict 重复profile_id -> 保留profile_id, 供前端把本地 dbId 纠正过来,
    避免 stale dbId 在下次同步时被当作新宝贝重建出重复。
    幂等: 无同名重复档案时为空操作。
    """
    rows = sess.query(EduProfile).filter_by(owner=owner).order_by(EduProfile.id).all()
    groups = {}
    for p in rows:
        key = (p.name, p.birth_year, p.gender)
        groups.setdefault(key, []).append(p)
    db_map = {}
    for profs in groups.values():
        if len(profs) < 2:
            continue
        canonical = profs[0]
        for dup in profs[1:]:
            for r in sess.query(EduData).filter_by(owner=owner, profile_id=dup.id).all():
                acc_row = sess.query(EduData).filter_by(
                    owner=owner, profile_id=canonical.id, dkey=r.dkey).first()
                if acc_row:
                    if r.dkey == 'stars':
                        try:
                            base = json.loads(acc_row.payload or '{}')
                        except Exception:
                            base = {}
                        try:
                            ext = json.loads(r.payload or '{}')
                        except Exception:
                            ext = {}
                        acc_row.payload = json.dumps(_merge_star_ledger(base, ext), ensure_ascii=False)
                        acc_row.updated_at = datetime.utcnow()
                        sess.delete(r)
                        continue
                    try:
                        base = json.loads(acc_row.payload or '{}')
                    except Exception:
                        base = {}
                    try:
                        ext = json.loads(r.payload or '{}')
                    except Exception:
                        ext = {}
                    acc_row.payload = json.dumps(_merge_blob(base, ext), ensure_ascii=False)
                    acc_row.updated_at = datetime.utcnow()
                    sess.delete(r)
                else:
                    r.owner = owner
                    r.profile_id = canonical.id
                    sess.add(r)
            sess.flush()
            sess.query(EduData).filter_by(owner=owner, profile_id=dup.id).delete()
            sess.query(EduProfile).filter_by(id=dup.id, owner=owner).delete()
            db_map[str(dup.id)] = str(canonical.id)
    if db_map:
        sess.commit()
    return db_map


@education_bp.route('/')
def index():
    """教育乐园首页：孩子管理 + 星愿进度。"""
    return render_template('edu_home.html')


@education_bp.route('/learn')
def learn():
    """学习中心：幼小衔接工作台 + 快乐乐园。"""
    return render_template('edu_learn.html')


@education_bp.route('/wish')
def wish():
    """星愿页面。"""
    return render_template('edu_wish.html')


@education_bp.route('/badges')
def badges():
    """荣誉墙页面。"""
    return render_template('edu_badges.html')





# ==================== API ====================

def _tts_lang(text):
    """粗略判断朗读语言: 汉字多→zh, 否则→en."""
    han = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    lat = sum(1 for c in text if ('a' <= c <= 'z') or ('A' <= c <= 'Z'))
    return 'zh' if han >= lat else 'en'


_EDGE_VOICE = {'zh': 'zh-CN-XiaoxiaoNeural', 'en': 'en-US-AnaNeural'}

# 可在「我的 → 朗读与音效」选择的音色(语文/中文朗读): 温和、慢速、儿童友好, 避免短促
_TTS_VOICES = {
    'xiaoxiao': {'voice': 'zh-CN-XiaoxiaoNeural', 'rate': '-4%', 'pitch': '+8Hz', 'label': '晓晓 · 温暖女声'},
    'xiaoyi':   {'voice': 'zh-CN-XiaoyiNeural',   'rate': '-2%', 'pitch': '+10Hz', 'label': '小艺 · 活泼'},
    'yunxi':    {'voice': 'zh-CN-YunxiNeural',    'rate': '-1%', 'pitch': '+2Hz',  'label': '云希 · 清晰'},
    'yunyang':  {'voice': 'zh-CN-YunyangNeural',  'rate': '-1%', 'pitch': '+2Hz',  'label': '云扬 · 沉稳'},
}
_TTS_VOICE_DEFAULT = 'xiaoxiao'


def _fetch_tts(text, le, vkey=None):
    """在线获取 mp3: 优先 edge-tts(微软在线, 质量高不限流), 失败回退有道词典 TTS."""
    data = None
    try:
        import asyncio
        import tempfile
        import edge_tts
        fd, tmp = tempfile.mkstemp(suffix='.mp3')
        os.close(fd)
        try:
            vconf = (vkey and le == 'zh' and _TTS_VOICES.get(vkey)) or None
            if vconf:
                voice, rate, pitch = vconf['voice'], vconf['rate'], vconf['pitch']
            else:
                voice = _EDGE_VOICE.get(le, 'zh-CN-XiaoxiaoNeural')
                rate = '-4%' if le == 'zh' else '0%'
                pitch = '+8Hz' if le == 'zh' else '0Hz'

            async def _run():
                c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
                await c.save(tmp)
            # 网络调用带超时, 避免单一请求挂起阻塞 dev server(single-thread), 也避免客户端长时间等待
            import asyncio as _asyncio
            # 瞬时网络抖动可能失败, 重试一次再放弃
            for _attempt in range(2):
                try:
                    _asyncio.run(_asyncio.wait_for(_run(), timeout=15))
                    with open(tmp, 'rb') as f:
                        data = f.read()
                    if len(data) > 500:
                        break
                except _asyncio.TimeoutError:
                    data = None
                except Exception:
                    data = None
                data = None
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    except Exception:
        logger.warning('edge-tts failed le=%s', le, exc_info=True)
    if data:
        return data
    # 回退: 有道词典 TTS(有反爬/限流, 不一定成功)
    url = 'https://dict.youdao.com/dictvoice?le=' + le + '&audio=' + urllib.parse.quote(text)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://dict.youdao.com/'})
        with urllib.request.urlopen(req, timeout=12) as r:
            if r.status != 200:
                return None
            data = r.read()
        return data if len(data) > 200 else None
    except Exception:
        logger.warning('youdao tts failed le=%s', le, exc_info=True)
        return None


@education_bp.route('/api/tts', methods=['GET'])
def tts():
    """语音朗读: 服务端拉取并返回同源 mp3(浏览器直接播放, 无跨域/无 Mixed Content).

    参数: text(要读的文字, ≤180 字符), le(zh|en, 缺省按内容判断)。
    结果按内容哈希缓存到 instance/tts/, 重复朗读不重复请求外网。
    """
    text = (request.args.get('text') or '').strip()
    if not text:
        abort(400, description='missing text')
    text = text[:180]
    le = request.args.get('le') or ''
    if le not in ('zh', 'en'):
        le = _tts_lang(text)
    vkey = request.args.get('v') or ''
    if vkey not in _TTS_VOICES:
        vkey = ''
    key = hashlib.sha1((le + '|' + vkey + '|' + text).encode('utf-8')).hexdigest()[:24]
    cache_dir = os.path.join(current_app.instance_path, 'tts')
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        cache_dir = None
    path = os.path.join(cache_dir, key + '.mp3') if cache_dir else None
    if not (path and os.path.isfile(path)):
        data = _fetch_tts(text=text, le=le, vkey=vkey or None)
        if not data:
            abort(502, description='TTS 服务不可用')
        if path:
            try:
                tmp = path + '.tmp'
                with open(tmp, 'wb') as f:
                    f.write(data)
                os.replace(tmp, path)
            except OSError:
                pass
    resp = send_file(path, mimetype='audio/mpeg')
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp

# ---- 首屏 JS 打包: 将 33 个依赖有序模块合并为一个请求 ----
# 手机端逐个串行请求这些模块会在移动 RTT 下累加数秒延迟; 合包后一次请求即可,
# 配合 mtime 版本号(gzip + 不可变缓存)兼顾更新与速度。
_EDU_JS_MODULES = [
    'edu-constants.js', 'edu-math-utils.js', 'edu-core.js', 'edu-speech.js',
    'edu-state.js', 'edu-parent.js', 'edu-quiz-engine.js', 'edu-engine.js',
    'edu-legacy.js', 'edu-zh.js', 'edu-math.js', 'edu-en.js', 'edu-go.js', 'edu-lit.js',
    'edu-paradise.js', 'edu-daily.js', 'edu-practice.js', 'edu-header.js',
    'edu-kids.js', 'edu-nav.js', 'edu-home.js',
    'edu-edit.js', 'edu-settings.js', 'edu-report.js',
    'edu-mask.js', 'edu-wish.js', 'edu-badges.js', 'edu-course.js',
    'edu-stats.js', 'edu-dash.js', 'edu-fab.js', 'edu-mine.js', 'edu-limit.js', 'edu-bootstrap.js',
]
_EDU_JS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'js', 'edu')
_bundle_lock = threading.Lock()
_bundle_cache = {'mtime': 0, 'body': b'', 'size': 0}

def _build_edu_bundle():
    """拼接模块(依赖顺序), 返回 (gzip_bytes, max_mtime). 未变时走内存缓存."""
    max_mt = 0.0
    paths = []
    for name in _EDU_JS_MODULES:
        p = os.path.join(_EDU_JS_DIR, name)
        paths.append(p)
        try:
            max_mt = max(max_mt, os.path.getmtime(p))
        except OSError:
            continue
    with _bundle_lock:
        if _bundle_cache['mtime'] == max_mt and _bundle_cache['body']:
            return _bundle_cache['body'], max_mt
        parts = []
        for p in paths:
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    parts.append(f.read())
            except OSError:
                continue
        raw = ('\n;\n'.join(parts)).encode('utf-8')
        body = gzip.compress(raw, compresslevel=6)
        _bundle_cache.update({'mtime': max_mt, 'body': body})
        return body, max_mt


@education_bp.route('/bundle.js')
def edu_bundle():
    """返回合并后的教育模块 JS(gzip). 版本号由模板 mtime 派生, 配合不可变缓存."""
    body, max_mt = _build_edu_bundle()
    resp = current_app.response_class(body, mimetype='application/javascript')
    resp.headers['Content-Encoding'] = 'gzip'
    resp.headers['Content-Length'] = str(len(body))
    resp.headers['ETag'] = '"edu-%d"' % int(max_mt * 1000)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    resp.headers['Vary'] = 'Accept-Encoding'
    return resp

@education_bp.route('/api/bootstrap', methods=['GET', 'POST'])
def bootstrap():
    """返回当前归属下的孩子档案列表(教育仅支持已登录账号).

    前台调用方仅需 kids; dbIdMap 用于把本地 stale dbId 收敛到去重后的保留档案。
    """
    with _session_scope() as sess:
        owner = _owner_id()
        # 同一归属下同名宝贝(旧版收养/多端同步可能产生重复)合并, 并把纠正后的 id 映射
        # 一并交给前端, 让本地 stale dbId 收敛到保留档案
        dedup_map = _dedup_profiles_in_owner(sess, owner)
        rows = sess.query(EduProfile).filter_by(owner=owner).order_by(EduProfile.sort).all()
        kids = [dict(id=p.id, name=p.name, birthYear=p.birth_year, gender=p.gender,
                     created=getattr(p, 'created_at', None).isoformat() if p.created_at else '')
                for p in rows]
        changed = bool(dedup_map)
        return jsonify(ok=True, owner=owner, kids=kids, adopted=False,
                       dbIdMap=dedup_map if changed else {})


@education_bp.route('/api/kids', methods=['POST'])
def save_kids():
    """整体同步孩子档案(前端把本地所有孩子发来做 upsert + 删除).

    body: { kids: [{clientId, name, birthYear, gender}], removedIds: [...] }
    返回 { kids: [{id, clientId, name, birthYear, gender}] }
    """
    data = request.get_json(silent=True) or {}
    with _session_scope() as sess:
        owner = _owner_id()
        out = []
        for i, k in enumerate(data.get('kids') or []):
            name = (k.get('name') or '宝贝')[:40]
            birth_year = _safe_int(k.get('birthYear'), 2018)
            gender = (k.get('gender') or '')[:12]
            pid = _safe_int(k.get('dbId'), 0) or None
            p = None
            if pid:
                p = sess.query(EduProfile).filter_by(id=pid, owner=owner).first()
            if p:
                p.name = name; p.birth_year = birth_year; p.gender = gender; p.sort = i
            else:
                p = EduProfile(owner=owner, name=name, birth_year=birth_year, gender=gender, sort=i)
                sess.add(p)
            sess.flush()
            pid2 = p.id
            out.append(dict(id=pid2, clientId=k.get('clientId'), name=p.name,
                            birthYear=p.birth_year, gender=p.gender))
        # 删除已移除的本地孩子(仅限归属内; 排除本批刚 upsert 的档案, 避免误删)
        upserted = set(k['id'] for k in out)
        for rid in data.get('removedIds') or []:
            try:
                rid = int(rid)
            except (TypeError, ValueError):
                continue
            if rid in upserted:
                continue
            _drop_profile_data(sess, owner, rid)
        sess.commit()
        return jsonify(ok=True, owner=owner, kids=out)


@education_bp.route('/api/kids/<int:pid>/delete', methods=['POST'])
def delete_kid(pid):
    with _session_scope() as sess:
        owner = _owner_id()
        _drop_profile_data(sess, owner, pid)
        sess.commit()
        return jsonify(ok=True)


def _merge_nodes(na, nb):
    """课程节点取并集: 大关 passStage/done/星级/重打次数 只增不减."""
    la = na if isinstance(na, list) else []
    lb = nb if isinstance(nb, list) else []
    out = []
    for i in range(max(len(la), len(lb))):
        a = la[i] if i < len(la) else None
        b = lb[i] if i < len(lb) else None
        if not isinstance(a, dict) and not isinstance(b, dict):
            out.append(a if isinstance(a, dict) else b)
            continue
        m = dict(a if isinstance(a, dict) else {})
        e = b if isinstance(b, dict) else {}
        try:
            m['passStage'] = max(int(m.get('passStage') or -1), int(e.get('passStage') or -1))
        except (TypeError, ValueError):
            pass
        m['done'] = bool(m.get('done') or e.get('done'))
        try:
            m['passedAt'] = max(int(m.get('passedAt') or 0), int(e.get('passedAt') or 0))
        except (TypeError, ValueError):
            pass
        try:
            m['tries'] = max(int(m.get('tries') or 0), int(e.get('tries') or 0))
        except (TypeError, ValueError):
            pass
        sa, sb = m.get('stars'), e.get('stars')
        if isinstance(sa, list) or isinstance(sb, list):
            la2 = sa if isinstance(sa, list) else []
            lb2 = sb if isinstance(sb, list) else []
            stars = []
            for i2 in range(max(len(la2), len(lb2))):
                try:
                    v = max(int(la2[i2] if i2 < len(la2) else 0), int(lb2[i2] if i2 < len(lb2) else 0))
                except (TypeError, ValueError):
                    v = 0
                stars.append(v)
            m['stars'] = stars
        out.append(m)
    return out


def _guard_write_payload(cur, incoming):
    """跨端全量覆盖写入时, 对「只增不减」字段做对齐, 其余字段以最新弹为准:
    - stars 取较大(累计余额, 防旧端覆盖吞星 / 防重复累加)
    - course.rewards(里程碑发放标记)取并集: 防旧弹擦掉标记导致重复发星
    - course 各大关 passStage/done/星级取较大: 防旧弹倒退进度导致重复发 +3 星
    """
    if not isinstance(cur, dict) or not isinstance(incoming, dict):
        return incoming
    out = dict(incoming)
    try:
        out['stars'] = max(int(cur.get('stars') or 0), int(incoming.get('stars') or 0))
    except (TypeError, ValueError):
        pass
    c0, c1 = cur.get('course'), incoming.get('course')
    if isinstance(c0, dict) and not isinstance(c1, dict):
        out['course'] = c0
        return out
    if not (isinstance(c0, dict) and isinstance(c1, dict)):
        return out
    merged = {}
    for subj in set(c0) | set(c1):
        a, b = c0.get(subj), c1.get(subj)
        if not isinstance(a, dict) and not isinstance(b, dict):
            continue
        base = dict(a if isinstance(a, dict) else {})
        ext = b if isinstance(b, dict) else {}
        if isinstance(a, dict) and isinstance(b, dict):
            for k in ('rewards', 'unlocked'):
                va, vb = a.get(k), b.get(k)
                if isinstance(va, dict) or isinstance(vb, dict):
                    r = dict(va if isinstance(va, dict) else {})
                    if isinstance(vb, dict):
                        for kk, vv in vb.items():
                            r.setdefault(kk, vv)
                    base[k] = r
                elif va is not None or vb is not None:
                    try:
                        base[k] = max(int(va or 0), int(vb or 0))
                    except (TypeError, ValueError):
                        base[k] = va if va is not None else vb
            base['done'] = bool(a.get('done') or b.get('done'))
            base['nodes'] = _merge_nodes(a.get('nodes'), b.get('nodes'))
        merged[subj] = base
    out['course'] = merged
    return out


@education_bp.route('/api/kids/<int:pid>/state', methods=['GET', 'POST'])
def kid_state(pid):
    """读写某个孩子的数据弹(state/levels 等).

    GET ?dkey=state  -> 返回 {data: {...}}
    POST body {dkey:'state', data:{...}} -> 保存
    """
    owner = _owner_id()
    dkey = (request.args.get('dkey') or request.values.get('dkey') or 'state')
    with _session_scope() as sess:
        if request.method == 'GET':
            row = sess.query(EduData).filter_by(owner=owner, profile_id=pid, dkey=dkey).first()
            payload = json.loads(row.payload) if row and row.payload else {}
            if dkey == 'state':
                # 服务端以 stars 权威账本为准覆盖展示值: 各设备提交的加/扣星星事件
                # 按 key 幂等去重后, 账本 total 才是真实合计, 避免跨设备/旧弹重复累加
                srow = sess.query(EduData).filter_by(
                    owner=owner, profile_id=pid, dkey='stars').first()
                if srow and srow.payload:
                    try:
                        ledger = json.loads(srow.payload)
                    except Exception:
                        ledger = {}
                    if isinstance(ledger, dict) and isinstance(ledger.get('total'), int):
                        payload['stars'] = ledger['total']
            return jsonify(ok=True, data=payload)
        # POST
        body = request.get_json(silent=True) or {}
        payload = body.get('data') or {}
        # 空弹不覆盖: 初始化空推({})不得清空两端已合并的成绩数据
        if not isinstance(payload, dict) or len(payload) == 0:
            return jsonify(ok=True, noop=True)
        # 写入前校验档案归属, 拒绝把数据写到他人/不存在的孩子名下
        if not _kid_owned(sess, owner, pid):
            return jsonify(ok=False, error='孩子不存在或无权访问'), 404
        row = sess.query(EduData).filter_by(owner=owner, profile_id=pid, dkey=dkey).first()
        now = datetime.utcnow()
        if row:
            # stars/课程进度/里程碑发放标记: 只增不减, 其余字段以最新弹为准,
            # 避免旧设备/旧数据覆盖把已挣星星吞掉、里程碑重复发星或关卡进度倒退
            try:
                cur = json.loads(row.payload or '{}')
            except Exception:
                cur = {}
            payload = _guard_write_payload(cur, payload) if isinstance(cur, dict) else payload
            row.payload = json.dumps(payload, ensure_ascii=False)
            row.updated_at = now
        else:
            sess.add(EduData(owner=owner, profile_id=pid, dkey=dkey,
                             payload=json.dumps(payload, ensure_ascii=False),
                             created_at=now, updated_at=now))
        sess.commit()
        return jsonify(ok=True)


@education_bp.route('/api/kids/<int:pid>/stars', methods=['POST'])
def kid_stars(pid):
    """星星权威账本: 逐笔「加/扣星星」同步到服务端.

    body: {events:[{key, amount, reason, ts}]}
    - 服务端按事件 key 幂等去重(网络重试/多设备回放不会重复累加);
    - total = Σ已入账事件, 是全局唯一权威星星数;
    - 首次收账前自动把旧 state 弹的历史余额迁移为 base 事件, 升级后星星不回退;
    - 返回 {ok, stars}: 前端展示以返回值为准。
    """
    body = request.get_json(silent=True) or {}
    events = body.get('events')
    if not isinstance(events, list) or not events:
        return jsonify(ok=True, noop=True)
    with _session_scope() as sess:
        owner = _owner_id()
        # 写入前校验档案归属
        if not _kid_owned(sess, owner, pid):
            return jsonify(ok=False, error='孩子不存在或无权访问'), 404
        row = sess.query(EduData).filter_by(owner=owner, profile_id=pid, dkey='stars').first()
        cur = {}
        if row:
            try:
                cur = json.loads(row.payload or '{}')
            except Exception:
                cur = {}
            if not isinstance(cur, dict):
                cur = {}
        if not isinstance(cur.get('seen'), dict):
            cur['seen'] = {}
        if not isinstance(cur.get('log'), list):
            cur['log'] = []
        now = datetime.utcnow()
        # 老数据迁移(窗口期): 账本还没有真实事件时, base 事件刻画「旧版累计余额」.
        # 期间若本端/另一设备晚同步的旧弹余额更高, base 只「取较大」补齐差额, 不重复;
        # 一旦有真实加/扣星事件入账, 窗口关闭, 此后合计完全由事件驱动(权威不再变),
        # 避免「先收事件、后写旧弹」或「多设备先后上传旧余额」被反复解析造成虚增.
        has_real = False
        for _ev in cur['log']:
            if isinstance(_ev, dict) and _ev.get('key') not in ('base', '__base'):
                has_real = True
                break
        if not has_real:
            blob_stars = 0
            st_row = sess.query(EduData).filter_by(owner=owner, profile_id=pid, dkey='state').first()
            if st_row and st_row.payload:
                try:
                    blob_stars = int((json.loads(st_row.payload) or {}).get('stars') or 0)
                except (TypeError, ValueError, AttributeError):
                    blob_stars = 0
            base_ev = None
            for _ev in cur['log']:
                if isinstance(_ev, dict) and _ev.get('key') == 'base':
                    base_ev = _ev
                    break
            if base_ev is None:
                if blob_stars:
                    cur['seen']['base'] = 1
                    cur['log'].append({'key': 'base', 'amount': blob_stars,
                                       'reason': '历史余额迁移', 'ts': str(int(now.timestamp()))})
            else:
                cur['seen']['base'] = 1
                if blob_stars > _safe_int(base_ev.get('amount'), 0):
                    base_ev['amount'] = blob_stars
        total = 0
        for ev in cur['log']:
            try:
                total += int(ev.get('amount') or 0)
            except (TypeError, ValueError):
                pass
        cur['total'] = total
        for ev in events:
            if not isinstance(ev, dict):
                continue
            k = ev.get('key')
            if not k or k in cur['seen']:
                continue
            try:
                amt = int(ev.get('amount') or 0)
            except (TypeError, ValueError):
                amt = 0
            cur['seen'][k] = 1
            cur['log'].append({'key': k, 'amount': amt,
                               'reason': ev.get('reason') or '',
                               'ts': ev.get('ts') or str(int(now.timestamp()))})
            total += amt
        if len(cur['log']) > 4000:
            cur['log'] = cur['log'][-4000:]
        cur['total'] = total
        payload = json.dumps(cur, ensure_ascii=False)
        if row:
            row.payload = payload
            row.updated_at = now
        else:
            sess.add(EduData(owner=owner, profile_id=pid, dkey='stars',
                             payload=payload, created_at=now, updated_at=now))
        sess.commit()
        return jsonify(ok=True, stars=total)


@education_bp.route('/api/reset', methods=['POST'])
def reset_all():
    """家长重置: 删除当前归属下所有孩子与数据."""
    with _session_scope() as sess:
        owner = _owner_id()
        ids = [p.id for p in sess.query(EduProfile).filter_by(owner=owner).all()]
        sess.query(EduProfile).filter_by(owner=owner).delete()
        if ids:
            sess.query(EduData).filter(
                EduData.owner == owner, EduData.profile_id.in_(ids)).delete(synchronize_session=False)
        sess.commit()
        return jsonify(ok=True)


# ==================== 题库 ====================

@education_bp.route('/api/qbank/ensure', methods=['POST'])
def qbank_ensure():
    """批量入库题目: 按 owner+subj+type+prompt 去重(仅首次入库).
    body: { subj, type, difficulty, items: [{prompt, options[], correct, note}] }
    """
    data = request.get_json(silent=True) or {}
    subj = data.get('subj')
    typ = data.get('type')
    diff = _safe_int(data.get('difficulty'), 3)
    items = data.get('items') or []
    if not (subj and typ and items):
        return jsonify(ok=False, error='missing fields'), 400
    with _session_scope() as sess:
        owner = _owner_id()
        added = 0
        for it in items:
            prompt = (it.get('prompt') or '').strip()
            if not prompt:
                continue
            exists = sess.query(EduQBank).filter_by(
                owner=owner, subj=subj, type=typ, prompt=prompt
            ).first()
            if exists:
                continue
            opts = it.get('options') or []
            row = EduQBank(
                owner=owner, subj=subj, type=typ, difficulty=diff,
                prompt=prompt, options=json.dumps(opts, ensure_ascii=False),
                correct=str(it.get('correct') or ''), note=it.get('note') or '',
                created_at=datetime.utcnow()
            )
            sess.add(row)
            added += 1
        sess.commit()
        return jsonify(ok=True, added=added)


@education_bp.route('/api/qbank/pull', methods=['POST'])
def qbank_pull():
    """按权重拉题: 答错优先 -> 做过少 -> 难度匹配.
    body: { subj, type, difficulty, limit, exclude: [prompts] }
    """
    data = request.get_json(silent=True) or {}
    subj = data.get('subj')
    typ = data.get('type')
    diff = max(1, min(5, _safe_int(data.get('difficulty'), 3)))
    limit = min(max(_safe_int(data.get('limit'), 10), 1), 50)
    exclude = set(data.get('exclude') or [])
    if not (subj and typ):
        return jsonify(ok=False, error='missing fields'), 400
    with _session_scope() as sess:
        owner = _owner_id()
        q = sess.query(EduQBank).filter_by(owner=owner, subj=subj, type=typ)
        # 难度优先: 同档 -> 相邻档
        rows = q.filter(EduQBank.difficulty.in_([diff, max(1,diff-1), min(5,diff+1)])).all()
        if not rows:
            return jsonify(ok=True, items=[])
        # 权重: wrong_count降序 -> used_count升序 -> 随机
        scored = []
        for r in rows:
            if r.prompt in exclude:
                continue
            w = (r.wrong_count or 0) * 1000 - (r.used_count or 0) * 10 + (100 - abs((r.difficulty or 3) - diff))
            scored.append((w, r))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, r in scored[:limit]:
            out.append(dict(
                id=r.id, subj=r.subj, type=r.type, difficulty=r.difficulty,
                prompt=r.prompt, options=json.loads(r.options or '[]'),
                correct=r.correct, note=r.note
            ))
        return jsonify(ok=True, items=out)


@education_bp.route('/api/qbank/learn', methods=['POST'])
def qbank_learn():
    """记录作答反馈: 用于更新 wrong_count/used_count/last_seen."""
    data = request.get_json(silent=True) or {}
    subj = data.get('subj')
    typ = data.get('type')
    prompt = (data.get('prompt') or '').strip()
    correct = data.get('correct')
    if not (subj and typ and prompt):
        return jsonify(ok=False, error='missing fields'), 400
    with _session_scope() as sess:
        owner = _owner_id()
        row = sess.query(EduQBank).filter_by(
            owner=owner, subj=subj, type=typ, prompt=prompt
        ).first()
        if row:
            row.used_count = (row.used_count or 0) + 1
            if correct is False:
                row.wrong_count = (row.wrong_count or 0) + 1
            row.last_seen = datetime.utcnow()
            sess.commit()
        return jsonify(ok=True)
