# -*- coding: utf-8 -*-
"""自然语言解析层: 中文日期/时间段解析 + jionlp 自愈安装 + 待办字段抽取.

纯文本处理, 不触碰数据库与会话; 时间源统一来自 timeutil.cn_now.
"""
import os
import re
import sys
import time
import logging
import subprocess
import threading
from datetime import datetime, timedelta

from core.timeutil import cn_now
from core.models import User

logger = logging.getLogger(__name__)


WEEKDAY_MAP = {
    '一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6
}

def parse_chinese_datetime(text):
    now = cn_now()
    result_date = now
    result_time = None

    hour = None
    minute = 0
    is_pm = None

    def set_time_from_text(t):
        nonlocal hour, minute, is_pm
        m = re.search(r'(上午|早上|早晨|凌晨)?(\d+)[:：](\d+)', t)
        if m:
            is_pm = True if m.group(1) in ['下午', '晚上'] else False
            hour = int(m.group(2))
            minute = int(m.group(3))
            if is_pm and hour < 12:
                hour += 12
            return
        m = re.search(r'(上午|早上|早晨|凌晨|下午|晚上)?(\d+)[点时](\d+)?[分]?', t)
        if m:
            if m.group(1) in ['下午', '晚上']:
                is_pm = True
            elif m.group(1) in ['上午', '早上', '早晨', '凌晨']:
                is_pm = False
            hour = int(m.group(2))
            if m.group(3):
                minute = int(m.group(3))
            else:
                minute = 0
            if is_pm and hour < 12:
                hour += 12
            return
        m = re.search(r'(\d+)[:：](\d+)', t)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            return

    if '大后天' in text:
        result_date = now + timedelta(days=3)
    elif '后天' in text:
        result_date = now + timedelta(days=2)
    elif '明天' in text:
        result_date = now + timedelta(days=1)
    elif '今天' in text:
        result_date = now
    elif '下下' in text:
        m = re.search(r'下下[周星期]([一二三四五六日天])', text)
        if m:
            target = WEEKDAY_MAP.get(m.group(1), 0)
            days_ahead = target - now.weekday()
            if days_ahead <= 0:
                days_ahead += 14
            else:
                days_ahead += 7
            result_date = now + timedelta(days=days_ahead)
    elif '下' in text:
        m = re.search(r'下[周星期]([一二三四五六日天])', text)
        if m:
            target = WEEKDAY_MAP.get(m.group(1), 0)
            days_ahead = target - now.weekday() + 7
            result_date = now + timedelta(days=days_ahead)
    elif '这' in text or '本' in text:
        m = re.search(r'(这|本)[周星期]([一二三四五六日天])', text)
        if m:
            target = WEEKDAY_MAP.get(m.group(2), 0)
            days_ahead = target - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            result_date = now + timedelta(days=days_ahead)
    else:
        m = re.search(r'(\d{4})[年-](\d{1,2})[月-](\d{1,2})[日号]?', text)
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                result_date = datetime(y, mo, d)
            except (ValueError, OverflowError):
                pass
        else:
            m = re.search(r'(\d{1,2})月(\d{1,2})[日号]?', text)
            if m:
                try:
                    mo, d = int(m.group(1)), int(m.group(2))
                    y = now.year
                    result_date = datetime(y, mo, d)
                    if result_date < datetime(y, now.month, now.day):
                        result_date = datetime(y + 1, mo, d)
                except (ValueError, OverflowError):
                    pass

    set_time_from_text(text)

    try:
        if hour is not None:
            h = max(0, min(23, hour))
            m = max(0, min(59, minute))
            result_date = result_date.replace(hour=h, minute=m,
                                              second=0, microsecond=0)
        else:
            result_date = result_date.replace(hour=9, minute=0,
                                              second=0, microsecond=0)
    except (ValueError, OverflowError):
        result_date = cn_now().replace(hour=9, minute=0,
                                             second=0, microsecond=0)

    return result_date

WEEK_KEYS = ['本周', '这周', '本星期', '这个星期']

NEXT_WEEK_KEYS = ['下周', '下星期']

def _parse_time(text):
    """Extract (hour, minute) from a time expression in text. Returns None if no match.

    冒号格式(X:XX)按 24 小时制处理, 不做上下午猜测;
    「点/时」格式识别 上午/早上/早晨/凌晨/下午/晚上。
    """
    m = re.search(r'(上[午]|下[午]|晚[上]|早[上晨]|凌[晨])?\s*(\d{1,2})\s*[：:]\s*(\d{1,2})', text)
    if m:
        h = int(m.group(2))
        mi = int(m.group(3))
        if h < 24 and mi < 60:
            return (h, mi)
    m = re.search(r'(上[午]|下[午]|晚[上]|早[上晨]|凌[晨])?(\d{1,2})[点时](半|\d{1,2})?分?(?:钟)?', text)
    if m:
        period = m.group(1)
        h = int(m.group(2))
        minute = 30 if m.group(3) == '半' else int(m.group(3) or 0)
        if period in ('下午', '晚上'):
            h = h if h >= 12 else h + 12
        elif period in ('上午', '早上', '早晨', '凌晨'):
            h = 0 if h == 12 else h
        elif not period and h < 7:
            h += 12
        return (h % 24, min(59, max(0, minute)))
    cm = re.search(r'(\d{1,2}):(\d{2})', text)
    if cm:
        h, mm = int(cm.group(1)), int(cm.group(2))
        if h < 24 and mm < 60:
            return (h, mm)
    return None

def _find_all_datetime_candidates(text):
    """Find all (datetime, date_text) candidates from time expressions in text.
    Returns list sorted by datetime ascending."""
    now = cn_now()
    candidates = []

    # find all date references and their positions
    date_refs = []

    # 明天/后天/今天
    for rel, delta in [('今天', 0), ('今[天日]', 0), ('明天', 1), ('明[天日]', 1), ('后天', 2), ('后[天日]', 2)]:
        for m in re.finditer(rel, text):
            date_refs.append((m.start(), 'relative', delta))

    # X月X日
    for m in re.finditer(r'(\d+)月(\d+)日', text):
        try:
            mo, d = int(m.group(1)), int(m.group(2))
            date_refs.append((m.start(), 'date', (mo, d)))
        except Exception:
            pass

    # 本周/下周
    if re.search(r'本(?:周|星期)|这(?:周|星期)', text):
        next_weekday = now + timedelta(days=(6 - now.weekday()))
        # generate candidates for each time in the remaining text
        for tm in re.finditer(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text):
            t = _parse_time(tm.group())
            if t:
                dt = next_weekday.replace(hour=t[0], minute=t[1], second=0)
                if dt < now:
                    dt += timedelta(weeks=1)
                candidates.append(dt)

    if re.search(r'下(?:周|星期)', text):
        next_weekday = now + timedelta(days=(13 - now.weekday()))
        for tm in re.finditer(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text):
            t = _parse_time(tm.group())
            if t:
                dt = next_weekday.replace(hour=t[0], minute=t[1], second=0)
                if dt < now:
                    dt += timedelta(weeks=1)
                candidates.append(dt)

    # find all time expressions with their positions
    time_exprs = []
    for m in re.finditer(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', text):
        t = _parse_time(m.group())
        if t:
            time_exprs.append((m.start(), t))
    for m in re.finditer(r'(\d{1,2}):(\d{2})', text):
        t = _parse_time(m.group())
        if t:
            time_exprs.append((m.start(), t))

    if not time_exprs:
        return candidates

    # for each date ref, pair with each time expression that comes after it (or all if no clear split)
    # if there's a "到" keyword, split text into before/after
    split_pos = None
    for kw in ['到', '截止', '至', '—', '~']:
        pos = text.find(kw)
        if pos >= 0:
            split_pos = pos
            break

    for date_pos, date_type, date_val in date_refs:
        # determine which times pair with this date
        for time_pos, (h, m) in time_exprs:
            if date_pos < time_pos:
                if date_type == 'relative':
                    dt = (now + timedelta(days=date_val)).replace(hour=h, minute=m, second=0)
                else:
                    mo, d = date_val
                    y = now.year
                    dt = datetime(y, mo, d, h, m, 0)
                    if dt < now:
                        dt = dt.replace(year=y + 1)
                if dt > now:
                    candidates.append(dt)

    # also generate candidates from time expressions alone (no date) paired with today
    for _, (h, m) in time_exprs:
        dt = now.replace(hour=h, minute=m, second=0)
        if dt <= now:
            dt = now.replace(hour=h, minute=m, second=0) + timedelta(days=1)
        candidates.append(dt)

    return sorted(set(candidates))

def detect_deadline_from_text(text):
    now = cn_now()

    # find time that appears AFTER deadline keywords (到/截止/至/-)
    end_text = text
    for kw in ['到', '截止', '至', '—', '~']:
        idx = text.find(kw)
        if idx >= 0:
            after = text[idx+1:]
            if after.strip():
                end_text = after
                break

    hour, minute = 18, 0
    time_m = re.search(r'(上[午]|下[午]|晚[上])?(\d{1,2})[：:点](\d{2})?(?:分)?', end_text)
    if time_m:
        period = time_m.group(1)
        h = int(time_m.group(2))
        m = int(time_m.group(3)) if time_m.group(3) else 0
        if period and period in ('下午', '晚上'):
            h = h if h >= 12 else h + 12
        elif period and period == '上午':
            h = h if h < 12 else h - 12
        elif h < 7:
            h += 12
        hour, minute = h, m
    else:
        colon_m = re.search(r'(\d{1,2}):(\d{2})', end_text)
        if colon_m:
            h, m = int(colon_m.group(1)), int(colon_m.group(2))
            if h < 24 and m < 60:
                hour, minute = h, m

    if re.search(r'本(?:周|星期)|这(?:周|星期)', text):
        end_of_week = now + timedelta(days=(6 - now.weekday()))
        return (end_of_week.replace(hour=hour, minute=minute, second=0), hour, minute)

    if re.search(r'下(?:周|星期)', text):
        end_of_next = now + timedelta(days=(13 - now.weekday()))
        return (end_of_next.replace(hour=hour, minute=minute, second=0), hour, minute)

    m = re.search(r'(\d+)月(\d+)日', end_text)
    if m:
        try:
            mo, d = int(m.group(1)), int(m.group(2))
            y = now.year
            dt = datetime(y, mo, d, hour, minute, 0)
            if dt < now:
                dt = dt.replace(year=y + 1)
            return (dt, hour, minute)
        except Exception:
            pass

    m = re.search(r'(\d{4})[年-](\d{1,2})[月-](\d{1,2})', text)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return (datetime(y, mo, d, hour, minute, 0), hour, minute)
        except Exception:
            pass

    # no date found, but return the extracted time for downstream use
    return (None, hour, minute)

_JIO = None

_AUTOPIP_STATE = {'started': False}

def _pip_install_cmd():
    """构造 pip 安装命令; KB_PIP_MIRROR 指定镜像源(默认清华, 设空串禁用)。"""
    cmd = [sys.executable, '-m', 'pip', 'install',
           '--no-cache-dir', '--quiet']
    mirror = os.environ.get('KB_PIP_MIRROR')
    if mirror is None:
        mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    if mirror:
        cmd += ['-i', mirror, '--trusted-host', 'pypi.tuna.tsinghua.edu.cn']
    return cmd + ['jionlp>=1.5.29']

def _try_install_jionlp(timeout_s):
    """同步安装 jionlp(供懒加载与后台预装共用); 成功返回 True。

    完整 pip 输出追加到 instance/jionlp_pip.log; 日志区分 超时(网络慢) 与 失败(无法下载)。
    """
    import subprocess
    log = logging.getLogger(__name__)
    cmd = _pip_install_cmd()
    log.warning('[jionlp] 未安装, 开始自动安装(超时%.0fs): %s', timeout_s, ' '.join(cmd))
    logf = None
    try:
        _inst = os.path.join(os.getcwd(), 'instance')
        os.makedirs(_inst, exist_ok=True)
        logf = open(os.path.join(_inst, 'jionlp_pip.log'), 'a', encoding='utf-8')
        logf.write('\n== %s %s ==\n' % (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ' '.join(cmd)))
    except Exception:
        logf = None
    t0 = time.time()
    try:
        r = subprocess.run(cmd, timeout=timeout_s, check=False,
                           stdout=(logf or subprocess.DEVNULL),
                           stderr=subprocess.STDOUT)
        dt = time.time() - t0
        if r.returncode == 0:
            log.warning('[jionlp] 安装成功, 耗时%.1fs', dt)
            return True
        log.warning('[jionlp] 安装失败 rc=%s 耗时%.1fs → 无法下载(DNS/源/权限), '
                    '详见 instance/jionlp_pip.log', r.returncode, dt)
        return False
    except subprocess.TimeoutExpired:
        log.warning('[jionlp] 安装超时(上限%.0fs) → 网络过慢, '
                    '详见 instance/jionlp_pip.log', timeout_s)
        return False
    except Exception as e:
        log.warning('[jionlp] 安装异常(%s)', e)
        return False
    finally:
        if logf:
            try:
                logf.close()
            except Exception:
                pass

def _get_jionlp():
    """懒加载 jionlp(未安装时尝试自动 pip 安装一次; 失败返回 None 走旧正则)。

    KB_AUTOPIP=0 关闭自动安装; KB_TIME_PARSER=legacy 整体回退(见调用方);
    KB_AUTOPIP_TIMEOUT 秒数(默认600)。
    """
    global _JIO
    if _JIO is None:
        jio_mod = None
        try:
            import jionlp as jio_mod
        except Exception:
            jio_mod = None
        if jio_mod is None and os.environ.get('KB_AUTOPIP', '1') != '0':
            try:
                timeout_s = float(os.environ.get(
                    'KB_AUTOPIP_TIMEOUT', '600') or 600)
            except ValueError:
                timeout_s = 600.0
            if _try_install_jionlp(timeout_s):
                try:
                    import jionlp as jio_mod
                except Exception:
                    jio_mod = None
        _JIO = jio_mod if jio_mod else False
    return _JIO or None

def ensure_jionlp_async():
    """启动后台守护线程预装 jionlp, 避免首次解析被安装阻塞。"""
    if _AUTOPIP_STATE['started']:
        return
    if os.environ.get('KB_AUTOPIP', '1') == '0' \
            or os.environ.get('KB_TIME_PARSER') == 'legacy':
        return
    import threading

    def _bg():
        try:
            import jionlp  # noqa: F401
            return  # 已安装, 无需处理
        except Exception:
            pass
        try:
            timeout_s = float(os.environ.get(
                'KB_AUTOPIP_TIMEOUT', '600') or 600)
        except ValueError:
            timeout_s = 600.0
        if _try_install_jionlp(timeout_s):
            global _JIO
            _JIO = None  # 重置缓存, 下次 _get_jionlp 重新导入
    _AUTOPIP_STATE['started'] = True
    threading.Thread(target=_bg, daemon=True,
                     name='jionlp-autopip').start()

def jionlp_ready():
    """智能解析是否可用; KB_TIME_PARSER=legacy 或 jionlp 已加载视为就绪。"""
    if os.environ.get('KB_TIME_PARSER') == 'legacy':
        return True
    try:
        return bool(_get_jionlp())
    except Exception:
        return False

def _parse_timespan_jionlp(text):
    """基于 JioNLP 的时间解析(KB_TIME_PARSER=legacy 回退旧正则)。

    返回 {'start': datetime|None, 'end': datetime|None}; 无有效时间返回 None。
    策略: 显式区间(X-Y点)给出 start+end; 截止式(...前/截止)给 end;
    其余取最远未来为 end。标题【】内与纯年份实体视为噪声剔除。
    """
    if os.environ.get('KB_TIME_PARSER') == 'legacy':
        return None
    jio = _get_jionlp()
    if not jio:
        return None
    try:
        ents = jio.ner.extract_time(text)
    except Exception:
        return None

    def _dt(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return None

    now = cn_now()
    cands = []
    for ent in ents or []:
        txt = (ent.get('text') or '').strip()
        off = ent.get('offset') or [0, 0]
        if not txt or re.fullmatch(r'\d{4}年?', txt):
            continue
        seg = text[max(0, off[0] - 80):off[0]]
        if '【' in seg and '】' not in seg.split('【')[-1]:
            continue
        d = ent.get('detail') or {}
        t = d.get('time')
        s = _dt(t[0]) if isinstance(t, list) and t else None
        e = _dt(t[1]) if isinstance(t, list) and len(t) > 1 else None
        if not s:
            continue
        is_blur = d.get('definition') == 'blur'
        # 时间线索: 显式「X点/X:XX」或时段词(上午/下午/晚上等); 全天单独判断
        has_tod = bool(re.search(r'\d{1,2}[点时：:]', txt)) or \
            bool(re.search(r'上午|早上|早晨|凌晨|中午|下午|晚上|晚间|傍晚', txt))
        is_allday_tok = bool(re.fullmatch(r'[全整]天|一天', txt))
        kind = ('range' if re.search(r'\d{1,2}[：:]\d{2}\s*[-—~至]\s*\d{1,2}[：:]\d{2}', txt)
                else ('deadline' if re.search(r'前$|之前|截止', txt) else 'point'))
        if e and e.second == 59:
            e = e.replace(second=0)
        if s.second == 59:
            s = s.replace(second=0)
        if not has_tod and kind == 'point':
            s = s.replace(hour=9, minute=0)
            if e:
                e = e.replace(hour=17, minute=0)
        # 「周X/星期X」指向已过去的时间且无"上周"等回看词 → 顺延到下一个未来;
        # 但「8月25日（周二）」这类显式日期中的星期仅为注释, 以日期为准不顺延
        _WD = re.search(r'(上?周|星期|礼拜)[一二三四五六日天末]', txt)
        if (_WD and not re.search(r'\d{4}年|\d{1,2}月\d{1,2}[日号]|\d{1,2}[日号]', txt)
                and not re.search(r'上周|上星期|上礼拜|之前|以前', txt)):
            while s <= now:
                s += timedelta(days=7)
                if e and e > s - timedelta(days=7):
                    e += timedelta(days=7)
        cands.append({'txt': txt, 's': s, 'e': e, 'kind': kind,
                      'allday': is_allday_tok, 'blur': is_blur})
    if not cands:
        return None
    # 显式区间补救: jionlp 有时将「15:00 - 16:00」拆为两个独立点实体,
    # 第二个被关联到错误日期(如昨天), 导致结束时间=开始时间。扫描原文补救
    if not [c for c in cands if c['kind'] == 'range']:
        _rm = re.search(
            r'(\d{4}-\d{2}-\d{2})[^-\d]{0,20}'
            r'(\d{1,2}[：:]\d{2})\s*[-—~至]\s*(\d{1,2}[：:]\d{2})', text)
        if _rm:
            _d = _rm.group(1)
            _t1 = _rm.group(2).replace('：', ':')
            _t2 = _rm.group(3).replace('：', ':')
            _s = _dt(f'{_d} {_t1}:00')
            _e = _dt(f'{_d} {_t2}:00')
            if _s and _e and _e > _s:
                cands = [c for c in cands
                         if not (c['s'].date() == _s.date()
                                 and c['s'].hour == _s.hour
                                 and c['kind'] == 'point')]
                cands.append({'txt': _rm.group(0), 's': _s, 'e': _e,
                              'kind': 'range', 'allday': False,
                              'blur': False})
    # 模糊时段词(中期/年底/年初等): jionlp 标记 definition=blur,
    # 其宽泛跨度(如"中期"=本季度末)会在合并时用 max() 覆盖明确日期
    # (回归: 通知含"8月28日前反馈"+"中期检查"误得截止9-30)。存在
    # 准确实体时剔除模糊实体; 仅模糊时保留兜底。
    _acc = [c for c in cands if not c.get('blur')]
    if _acc and len(_acc) < len(cands):
        cands = _acc
    # 独立「全天」实体(jio 会给它挂当前日期): 并入日期最近的实体并扩为全天
    _allday = [c for c in cands if c['allday']]
    if _allday and len(cands) > len(_allday):
        rest = [c for c in cands if not c['allday']]
        for a in _allday:
            tgt = min(rest, key=lambda c: abs((c['s'].date() - a['s'].date()).days))
            tgt['s'] = tgt['s'].replace(hour=0, minute=0, second=0)
            tgt['e'] = (tgt['e'] or tgt['s']).replace(hour=23, minute=59, second=0)
        cands = rest
    out = {'start': None, 'end': None}
    rngs = [c for c in cands if c['kind'] == 'range']
    dls = [c for c in cands if c['kind'] == 'deadline']
    if rngs:
        r0 = min(rngs, key=lambda c: c['s'])
        out['start'] = r0['s']
        out['end'] = max((c['e'] or c['s']) for c in rngs)
        # 显式起止区间(如「8月25日08:40-10:00」)为权威时间,
        # 即使会议已开始/已结束也原样保留, 不得置空或顺延
        out['explicit'] = True
    elif dls:
        out['end'] = max((c['e'] or c['s']) for c in dls)
        pts = [c for c in cands if c['kind'] == 'point']
        fpts = [c for c in pts if c['s'] > now]
        if fpts and min(c['s'] for c in fpts) < out['end']:
            out['start'] = min(c['s'] for c in fpts)
    else:
        out['end'] = max((c['e'] or c['s']) for c in cands)
        fs = [c['s'] for c in cands if c['s'] > now]
        if fs:
            out['start'] = min(fs)
    explicit_rng = bool(out.get('explicit'))
    if out.get('end') and out['end'] < now and not explicit_rng:
        out['end'] = None
    return out if (out['start'] or out['end']) else None

_CN_DIG = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9}


def _cn_to_int(s):
    """中文数字(一~九十九)或阿拉伯数字转 int; 无法解析返回 None。"""
    s = (s or '').strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == '十':
        return 10
    m = re.fullmatch(r'([一二三四五六七八九]?)十([一二三四五六七八九])?', s)
    if m:
        tens = (_CN_DIG.get(m.group(1), 1) if m.group(1) else 1) * 10
        ones = _CN_DIG.get(m.group(2), 0) if m.group(2) else 0
        return tens + ones
    return _CN_DIG.get(s)


# 「第一期：2026年8月28日14:30-16:30」类多场次行(≥2 场视为拆分信号)
_SESS_PAT = re.compile(
    r'第\s*([一二三四五六七八九十百\d]{1,3})\s*([期届场次轮节讲])\s*[:：]?\s*'
    r'(?:(\d{4})\s*年)?\s*(?:(\d{1,2})\s*月)?\s*(\d{1,2})\s*[日号]?'
    r'\s*(\d{1,2})[：:时点]\s*(\d{1,2})?分?'
    r'(?:\s*[-—–~至到]+\s*(\d{1,2})[：:时]\s*(\d{1,2})?分?)?')


def _extract_sessions(text):
    """提取「第X期/场/次: 日期 时间-时间」多场次列表。

    返回 [{'label','index','start','end'}]; 少于 2 场或无法解析日期返回 []。
    未写年份按当前年推算, 若已过则顺延一年; 缺结束时间默认 +1 小时。
    """
    now = cn_now()
    out = []
    for m in _SESS_PAT.finditer(text):
        num_s, unit, yy, mo, dd, h1, mi1, h2, mi2 = m.groups()
        idx = _cn_to_int(num_s)
        if not idx or not mo or not dd:
            continue
        try:
            year = int(yy) if yy else now.year
            start = datetime(year, int(mo), int(dd),
                             int(h1), int(mi1 or 0))
            if not yy and start < now:
                start = start.replace(year=year + 1)
            if h2 is not None:
                end = start.replace(hour=int(h2), minute=int(mi2 or 0))
                if end <= start:
                    end += timedelta(days=1)
            else:
                end = start + timedelta(hours=1)
        except ValueError:
            continue
        out.append({'label': f'第{num_s}{unit}', 'index': idx,
                    'start': start, 'end': end})
    out.sort(key=lambda x: x['index'])
    return out if len(out) >= 2 else []


def extract_assignees_from_text(text):
    result = {'assignees': [], 'is_all': False}

    if any(kw in text for kw in ['@所有人', '@all', '@All', '@ALL',
                                  '全员', '所有人', '全部人']):
        result['is_all'] = True
        return result

    at_mentions = re.findall(r'@([\w\u4e00-\u9fff]+)', text)
    if at_mentions:
        result['assignees'] = [n for n in at_mentions if n not in ['所有人', 'all', 'All', 'ALL']]
    assignee_match = re.search(
        r'(?:发给|分配给|给|指派给)[：:]?\s*'
        r'([\w\u4e00-\u9fff]+(?:[、,，\s]+[\w\u4e00-\u9fff]+)*)',
        text
    )
    if assignee_match:
        names = [n.strip() for n in re.split(r'[、,，\s]+', assignee_match.group(1)) if n.strip()]
        result['assignees'] = [n for n in names if n not in ['全员', '所有人', '全部人']]

    return result

TITLE_BLOCK_WORDS = ['反馈', '链接', '腾讯文档', 'https', 'http',
                      '通知', '请各位', '请各处室', '请提醒',
                      '请传达到位', '请确认', '请各部门', '请各单位']

TITLE_CLEAN_PREFIX = re.compile(r'^请[各全].{1,10}[，,。]')

# 会议通知中的「主题」行, 如「会议主题：xx学习」→ xx学习
THEME_LINE_PAT = re.compile(r'^(?:会议)?主题[：:][ \t]*(\S.*)$', re.M)


def extract_title_from_text(text):
    """标题兜底规则: 解析出的标题不足 6 字时, 回退取「主题:」后的文字."""
    title = _extract_title_base(text)
    if len(title) < 6:
        m = THEME_LINE_PAT.search(text)
        if m:
            theme = m.group(1).strip()
            if theme:
                return theme[:80]
    return title


def _extract_title_base(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        lines = [text]

    QUOTE_CHARS = '\u201c\u201d\u300c\u300d"'
    QUOTE_PAT = re.compile(r'[' + QUOTE_CHARS + r']([^' + QUOTE_CHARS + r']{4,60})[' + QUOTE_CHARS + r']')

    # 优先取第一个【】中的内容,如【分中心项目委会议时间】→ 分中心项目委会议时间
    # 若【】内容过短(如【通知】),取【】后正文作为标题
    first_bracket_line = None
    for line in lines:
        m = re.search(r'【([^】]+)】(.*)', line)
        if m:
            first_bracket_line = m
            break
    if first_bracket_line:
        name = first_bracket_line.group(1).strip()
        rest = re.sub(r'https?://\S+', '', first_bracket_line.group(2)).strip()
        rest = re.sub(r'@\S+', '', rest).strip()
        if len(name) >= 5 and name:
            return name[:80]
        if len(rest) >= 5 and not any(kw in rest for kw in TITLE_BLOCK_WORDS):
            return rest[:80]

    considered = []
    for line in lines:
        clean = re.sub(r'https?://\S+', '', line).strip()
        clean = re.sub(r'【[^】]*】', '', clean).strip()
        clean = re.sub(r'@所有人|@all|@All|@all', '', clean).strip()
        if clean:
            considered.append(clean)

    # 「动词:内容」结构优先取冒号后内容(如 提醒:明天交周报 → 明天交周报)
    for c in considered:
        m2c = re.search(r'^[^【】\n]{1,10}[：:]\s*(.+)$', c)
        if m2c:
            tail = m2c.group(1).strip()
            tail = re.sub(r'@\S+', '', tail).strip()
            if 4 <= len(tail) <= 60 and \
               not any(kw in tail for kw in TITLE_BLOCK_WORDS):
                return tail[:80]

    considered = [re.sub(r'[：:].*$', '', c).strip() or c for c in considered]

    for c in considered:
        quoted = QUOTE_PAT.findall(c)
        for q in quoted:
            if not any(kw in q for kw in TITLE_BLOCK_WORDS):
                return q[:80]

    for c in considered:
        for sep in ['。', '！', '，', ',', '；', ';', '——', '—', '\n']:
            if sep in c:
                parts = [p.strip() for p in c.split(sep) if p.strip()]
                for part in parts:
                    part_clean = re.sub(r'https?://\S+', '', part).strip()
                    part_clean = re.sub(r'【[^】]*】', '', part_clean).strip()
                    part_clean = re.sub(r'@\S+', '', part_clean).strip()
                    part_clean = re.sub(r'[「」""]', '', part_clean).strip()
                    part_clean = TITLE_CLEAN_PREFIX.sub('', part_clean).strip()
                    if 4 <= len(part_clean) <= 60 and \
                       not any(kw in part_clean for kw in TITLE_BLOCK_WORDS):
                        return part_clean[:80]

    for c in considered:
        cleaned = re.sub(r'(从|到|截止|提交|发给|给|指派给|分配[给到]|完成[于截至]).*', '', c).strip()
        cleaned = re.sub(r'[，,。！？\s]{2,}', '', cleaned).strip()
        cleaned = TITLE_CLEAN_PREFIX.sub('', cleaned).strip()
        if 4 <= len(cleaned) <= 60 and \
           not any(kw in cleaned for kw in TITLE_BLOCK_WORDS):
            return cleaned[:80]

    for c in considered:
        cleaned = TITLE_CLEAN_PREFIX.sub('', c).strip()
        if len(cleaned) >= 5 and not any(kw in cleaned for kw in TITLE_BLOCK_WORDS):
            return cleaned[:80]

    for c in considered:
        if len(c) >= 5 and not any(kw in c for kw in TITLE_BLOCK_WORDS):
            return c[:80]

    for c in considered:
        if c and len(c) >= 3 and not any(kw in c for kw in TITLE_BLOCK_WORDS):
            return c[:80]

    return '未命名待办'

def parse_task_from_text(text):
    now = cn_now()

    result = {
        'title': extract_title_from_text(text),
        'description': text,
        'category': '工作',
        'start_time': now,
        'end_time': None,
        'assignees': [],
        'is_all': False
    }

    # auto-detect category
    category_keywords = {
        '考试': ['考试', '测验', '笔试', '月考', '中考', '高考', '期中考', '期末考', '考级', '考核', '答辩'],
        '培训': ['培训', '训练', '课程', '集训', '学习班', '研修班', '岗前培训', '入职培训', '技能提升', '培训会'],
        '会议': ['会议', '开会', '例会', '晨会', '周会', '月会', '评审会', '研讨会', '复盘', '站会', '宣贯'],
        '工作': ['工作', '项目', '待办', '报告', '汇报', '方案', '开发', '测试', '上线', '需求', '周报', '月报'],
        '个人': ['个人', '学习', '读书', '运动', '健身', '购物', '家务', '休息', '娱乐', '游戏', '电影', '旅游'],
    }
    # 分类: 优先级 考试>培训>会议>工作>个人
    # 1. 标题以「会」结尾(宣贯会/动员会/评审会等) → 会议
    # 2. 正文含结构性会议标记(会议时间/会议地点/会议内容等) → 会议
    # 3. 标题含关键词 → 按字典序首个命中(即优先级顺序)
    # 4. 正文关键词计数投票, 平票取首匹配
    _title = result['title']
    _cat_hit = None
    if _title.endswith('会'):
        _cat_hit = '会议'
    elif re.search(r'会议[时地内]', text):
        _cat_hit = '会议'
    else:
        for cat, keywords in category_keywords.items():
            if any(kw in _title for kw in keywords):
                _cat_hit = cat
                break
    if _cat_hit:
        result['category'] = _cat_hit
    else:
        cat_scores = {}
        for cat, keywords in category_keywords.items():
            sc = sum(1 for kw in keywords if kw in text)
            if sc:
                cat_scores[cat] = sc
        if cat_scores:
            best = max(cat_scores.values())
            result['category'] = next(cat for cat, sc in cat_scores.items()
                                      if sc == best)

    assign_info = extract_assignees_from_text(text)
    result['assignees'] = assign_info['assignees']
    result['is_all'] = assign_info['is_all']
    # 人名校验: 仅保留系统中真实存在的姓名/用户名, 滤除「交给领导审批」类误抓
    try:
        _valid = set()
        for u in User.query.all():
            if u.name:
                _valid.add(u.name)
            if u.username:
                _valid.add(u.username)
    except Exception:
        _valid = set()
    if _valid and result['assignees']:
        result['assignees'] = [n for n in result['assignees'] if n in _valid]

    # 时间: 优先 JioNLP 语义解析(可给出未来开始时间); 失败回退旧候选链
    span = _parse_timespan_jionlp(text)
    parse_task_from_text._last_time_parser = 'jionlp' if span else 'legacy'
    best = None
    if span:
        if span.get('end'):
            best = span['end']
        # 显式区间(explicit)即使已开始/已结束也保留原始时刻
        if span.get('start') and (span['start'] > now or span.get('explicit')):
            result['start_time'] = span['start']

    # end_time: JioNLP 未命中时回退旧候选链
    if best is None:
        candidates = _find_all_datetime_candidates(text)
        if candidates:
            best = candidates[-1]
        else:
            # fallback to detect_deadline_from_text
            deadline_dt, dl_hour, dl_minute = detect_deadline_from_text(text)
            if deadline_dt:
                best = deadline_dt
            else:
                m = re.search(r'(\d+)([天周])', text)
                if m:
                    num = int(m.group(1))
                    unit = m.group(2)
                    if unit == '天':
                        best = now + timedelta(days=num)
                    elif unit == '周':
                        best = now + timedelta(weeks=num)
                else:
                    best = (now + timedelta(days=7)).replace(hour=18, minute=0, second=0)

    result['end_time'] = best

    # detect recurring pattern
    result['recurrence'] = None
    result['recurrence_text'] = ''
    result['recurrence_count'] = 0
    result['recurrence_interval_days'] = 0
    rec_text = text.replace('两', '2')
    # 每天/每日/天天
    if re.search(r'每[天日]|天天', text):
        result['recurrence'] = 'daily'
        result['recurrence_interval_days'] = 1
        result['recurrence_count'] = 10
        result['recurrence_text'] = '每天'
    else:
        # 每周X: 区间7天, 起点由时间解析落在对应星期
        wm = re.search(r'每(?:周|星期)([一二三四五六日天])', rec_text)
        if wm:
            result['recurrence'] = 'weekly'
            result['recurrence_interval_days'] = 7
            result['recurrence_count'] = 4
            result['recurrence_text'] = '每周' + wm.group(1)
        else:
            rec_m = re.search(r'每(\d*)(周|个?月|年)', rec_text)
            if rec_m:
                num_str = rec_m.group(1)
                unit = rec_m.group(2)
                num = int(num_str) if num_str else 1
                if unit == '周':
                    result['recurrence'] = 'weekly'
                    result['recurrence_interval_days'] = num * 7
                    result['recurrence_count'] = 4
                    result['recurrence_text'] = f'每{num}周' if num > 1 else '每周'
                elif '月' in unit:
                    result['recurrence'] = 'monthly'
                    result['recurrence_interval_days'] = num * 30
                    result['recurrence_count'] = 3
                    result['recurrence_text'] = f'每{num}个月' if num > 1 else '每月'
                elif '年' in unit:
                    result['recurrence'] = 'yearly'
                    result['recurrence_interval_days'] = num * 365
                    result['recurrence_count'] = 2
                    result['recurrence_text'] = f'每{num}年' if num > 1 else '每年'

    # 多场次(第X期: 日期时间): 拆分为多个待办, 抑制周期重复
    sessions = _extract_sessions(text)
    if sessions:
        result['sessions'] = sessions
        result['recurrence'] = None
        result['recurrence_text'] = ''
        result['recurrence_count'] = 0
        result['recurrence_interval_days'] = 0
        result['start_time'] = sessions[0]['start']
        result['end_time'] = sessions[0]['end']

    return result
