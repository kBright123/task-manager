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

"""星运模块(单文件版): 免费开放的星座命理工作台。

定位: 数据全透明 · 功能无限制 · 依托开源生态。
- 排盘: 本地纯 Python 引擎(services/astro_engine.py, 零依赖零调用费用);
- 每日运势: 本地确定性生成为主数据, 可选叠加免费开放接口 aztro 原文;
- 紫微斗数: 免费自托管 FateStar 端点可配置接入(env ASTRO_ZIWEI_URL),
  未配置时如实提示而非伪造数据;
- 知识库: 内置术语库, 全站术语点击弹窗解释;
- 用户中心: 登录用户无限云端存档排盘记录, 支持导出 JSON 与打印/PDF;
  订阅每日站内运势提醒(经 create_notification 投递, 打开页面即送达)。

页面 /astro 对所有访客开放(反付费墙原则), 仅"云端存档/订阅"需要登录,
游客可用本地暂存并在登录后一键入库。
"""
import datetime
import io
import json
import logging
import os
import threading
import time

from flask import Blueprint, Response, jsonify, render_template, request
from flask_login import current_user, login_required

from core.app_services import create_notification
from services import astro_engine as ae

logger = logging.getLogger(__name__)

# 公历→农历换算(jionlp 开源库): 进程内仅导入一次, 并屏蔽其启动横幅输出,
# 避免 Windows GBK 控制台因打印中文横幅触发 UnicodeEncodeError。
_S2L = None
try:
    import contextlib as _ctxlib
    import io as _io
    with _ctxlib.redirect_stdout(_io.StringIO()):
        import jionlp as _jionlp
    _S2L = _jionlp.solar2lunar
except Exception as _je:  # pragma: no cover - 部署环境缺包时降级
    logger.warning('jionlp 不可用, 农历自动换算已禁用: %r', _je)

cn_now = lambda: datetime.datetime.now(
    datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)


db = None
AstroChart = None
AstroSub = None


def init_models(database):
    """由 app.py 注入 db 并定义模型(避免循环导入, 与 notes/pet 同模式)。"""
    global db, AstroChart, AstroSub
    db = database

    class AstroChart_(database.Model):
        __tablename__ = 'astro_chart'
        __table_args__ = (
            database.Index('ix_astro_chart_user', 'user_id'),
        )
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, nullable=False)
        kind = database.Column(database.String(20), default='natal')
        title = database.Column(database.String(200), default='')
        input_json = database.Column(database.Text, default='{}')
        result_json = database.Column(database.Text, default='{}')
        created_at = database.Column(database.DateTime, default=cn_now)

    class AstroSub_(database.Model):
        __tablename__ = 'astro_sub'
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, nullable=False, unique=True)
        sign = database.Column(database.String(20), default='')
        hour = database.Column(database.Integer, default=8)
        last_sent_date = database.Column(database.String(10), default='')
        updated_at = database.Column(database.DateTime, default=cn_now)

    AstroChart, AstroSub = AstroChart_, AstroSub_


astro_bp = Blueprint('astro', __name__, url_prefix='/astro')

# aztro 开放接口的进程内缓存 {(sign, day): (ts, payload)}, 12h 失效
_AZTRO_CACHE = {}
_AZTRO_TTL = 12 * 3600
_AZTRO_LOCK = threading.Lock()

MAX_RECORDS = 100000          # 云端存档上限: 十万条起步, 实质不限量
MAX_BODY_KB = 256


def _payload():
    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception:
        return None
    return data


def _clamp(v, lo, hi, dft):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return dft
    return max(lo, min(hi, v))


def _parse_birth(data):
    try:
        bd = datetime.datetime.strptime(
            '%s %s' % (data.get('birth_date', '').strip(),
                       data.get('birth_time', '').strip() or '12:00'),
            '%Y-%m-%d %H:%M')
    except ValueError:
        return None
    if not datetime.datetime(1900, 1, 1) <= bd <= cn_now() + datetime.timedelta(days=1):
        return None
    return bd


def _save_record(user_id, kind, title, inp, result):
    rec = AstroChart(user_id=user_id, kind=kind, title=title[:200],
                     input_json=json.dumps(inp, ensure_ascii=False),
                     result_json=json.dumps(result, ensure_ascii=False))
    db.session.add(rec)
    db.session.commit()
    return rec


# ---------------------------------------------------------------- 页面


@astro_bp.route('/')
def index():
    """星运工作台(公开访问, 反付费墙: 游客与登录用户体验一致)。"""
    return render_template('astro.html',
                           ziwei_ready=bool(os.environ.get('ASTRO_ZIWEI_URL')))


# ---------------------------------------------------------------- 排盘 API


@astro_bp.route('/api/chart', methods=['POST'])
def api_chart():
    data = _payload()
    if not data:
        return jsonify({'ok': False, 'error': '参数格式错误'}), 400
    bd = _parse_birth(data)
    if not bd:
        return jsonify({'ok': False, 'error': '请提供有效的出生日期(1900至今)'}), 400
    lat = _clamp(data.get('lat'), -85, 85, 31.23)
    lon = _clamp(data.get('lon'), -180, 180, 121.47)
    name = (data.get('name') or '').strip()[:40] or '未命名命盘'
    try:
        western = ae.natal_chart(bd, lat=lat, lon_east=lon, name=name)
        bazi = ae.bazi_pillars(bd)
        result = {
            'western': western, 'bazi': bazi,
            'engine': 'TaskAstro 纯Python引擎 · Schlyter低精度星历(±0.1°级)',
            'generated_at': cn_now().strftime('%Y-%m-%d %H:%M'),
        }
        if _S2L is not None:
            try:
                ly, lm, ld_, leap = _S2L(
                    datetime.datetime(bd.year, bd.month, bd.day))
            except Exception as le:
                logger.info('lunar derive failed', exc_info=True)
                result['ziwei_error'] = ('农历换算失败(%s)，可在紫微盘卡片中'
                                         '手动指定农历后重排' % str(le)[:60])
            else:
                hour_idx = ((bd.hour + 1) // 2) % 12
                gender = data.get('gender') if data.get('gender') in (
                    '男', '女') else '男'
                zt = ae.ziwei_chart(ly, lm, ld_, hour_idx=hour_idx,
                                    gender=gender, leap=bool(leap))
                zt['derived'] = True
                result['ziwei'] = zt
                result['lunar_input'] = {'year': ly, 'month': lm, 'day': ld_,
                                         'leap': bool(leap),
                                         'hour_idx': hour_idx,
                                         'gender': gender}
        else:
            result['ziwei_error'] = ('服务器缺少 jionlp 库，无法自动换算农历；'
                                     '部署端 pip install jionlp 后重启即可恢复，'
                                     '或先在紫微盘中手动指定农历')
    except Exception as e:
        logger.warning('astro chart failed: %s', e)
        return jsonify({'ok': False, 'error': '排盘计算失败, 请检查参数'}), 500
    saved = False
    if getattr(current_user, 'is_authenticated', False) and data.get('save'):
        try:
            rec = _save_record(current_user.id, 'natal',
                               '%s · %s' % (name, western['birth_iso']),
                               {'birth_date': data.get('birth_date'),
                                'birth_time': data.get('birth_time') or '12:00',
                                'lat': lat, 'lon': lon},
                               result)
            saved = bool(rec.id)
        except Exception as e:
            db.session.rollback()
            logger.warning('astro record save failed: %s', e)
    return jsonify({'ok': True, 'result': result, 'saved': saved})


@astro_bp.route('/api/ziwei', methods=['POST'])
def api_ziwei():
    """紫微斗数本地排盘(纯代码安星, 无需任何外部服务)。

    输入农历生辰: year/month/day/hour_idx(子0..亥11)/gender/leap。
    另保留免费自托管 FateStar 端点转发能力(env ASTRO_ZIWEI_URL),
    便于需要六层运限/亮度层等深度数据的部署者自行扩展。
    """
    data = _payload() or {}
    try:
        result = {'ziwei': ae.ziwei_chart(
            lunar_year=int(data.get('year') or 0),
            lunar_month=int(data.get('month') or 0),
            lunar_day=int(data.get('day') or 0),
            hour_idx=int(data.get('hour_idx', 0)),
            gender=data.get('gender') or '男',
            leap=bool(data.get('leap')))}
        result['engine'] = 'TaskAstro 本地安星引擎 · 《紫微斗数全书》通行安星表'
        result['generated_at'] = cn_now().strftime('%Y-%m-%d %H:%M')
    except (ValueError, AssertionError, KeyError) as e:
        logger.info('ziwei bad input: %s', e)
        return jsonify({'ok': False,
                        'error': '请填写有效的农历生辰(月1-12/日1-30)'}), 400
    except Exception as e:
        logger.warning('ziwei failed: %s', e)
        return jsonify({'ok': False, 'error': '排盘计算失败'}), 500
    saved = False
    if getattr(current_user, 'is_authenticated', False) and data.get('save'):
        try:
            zt = result['ziwei']
            rec = _save_record(
                current_user.id, 'ziwei',
                '紫微盘 · %s' % zt['lunar_text'],
                {'year': data.get('year'), 'month': data.get('month'),
                 'day': data.get('day'), 'leap': bool(data.get('leap')),
                 'hour_idx': data.get('hour_idx'), 'gender': data.get('gender')},
                result)
            saved = bool(rec.id)
        except Exception as e:
            db.session.rollback()
            logger.warning('ziwei record save failed: %s', e)
    return jsonify({'ok': True, 'result': result, 'saved': saved})


@astro_bp.route('/api/ziwei-remote', methods=['POST'])
def api_ziwei_remote():
    """可选: 转发到自托管 FateStar 免费端点(六层运限等深度数据)。

    FateStar Ziwei 为免费匿名 REST/MCP 服务, 无 Key 无次数限制;
    本站不内置第三方云端地址, 由部署者通过 ASTRO_ZIWEI_URL 自行指定,
    保证数据流向透明可控。未配置时如实说明而非伪造数据。
    """
    base = os.environ.get('ASTRO_ZIWEI_URL', '').rstrip('/')
    data = _payload() or {}
    if not base:
        return jsonify({'ok': False, 'reason': 'not_configured'})
    try:
        import requests
        resp = requests.post(base + '/chart', json=data, timeout=8)
        return jsonify({'ok': True, 'data': resp.json()})
    except Exception as e:
        logger.info('ziwei upstream unavailable: %s', e)
        return jsonify({'ok': False, 'reason': 'upstream_unavailable'})


# ---------------------------------------------------------------- 每日运势


def _aztro(sign_key, day):
    """调用免费开放的 aztro 接口(无认证无限制); 失败返回 None 不影响主流程。"""
    cache_key = (sign_key, day)
    now = time.time()
    with _AZTRO_LOCK:
        hit = _AZTRO_CACHE.get(cache_key)
        if hit and now - hit[0] < _AZTRO_TTL:
            return hit[1]
    try:
        import requests
        r = requests.post('https://aztro.sameerkumar.website/',
                          params={'sign': sign_key, 'day': day}, timeout=6)
        data = r.json() if r.status_code == 200 else None
    except Exception:
        data = None
    if data:
        with _AZTRO_LOCK:
            _AZTRO_CACHE[cache_key] = (now, data)
    return data


@astro_bp.route('/api/fortune')
def api_fortune():
    sign = request.args.get('sign', 'aries').strip()
    if sign not in ae.SIGN_KEY_ORDER:
        return jsonify({'ok': False, 'error': '未知星座'}), 400
    date_str = request.args.get('date', '').strip()
    try:
        date_obj = (datetime.date.fromisoformat(date_str) if date_str
                    else cn_now().date())
    except ValueError:
        return jsonify({'ok': False, 'error': '日期格式应为 YYYY-MM-DD'}), 400
    if date_obj > cn_now().date() + datetime.timedelta(days=730):
        return jsonify({'ok': False, 'error': '仅支持未来两年内的日期'}), 400
    local = ae.daily_fortune(sign, date_obj)
    cal = ae.daily_calendar_info(date_obj)
    aztro_data = _aztro(sign, 'today' if date_obj == cn_now().date()
                        else ('yesterday'
                              if date_obj == cn_now().date() - datetime.timedelta(days=1)
                              else 'tomorrow'))
    return jsonify({'ok': True, 'local': local, 'calendar': cal,
                    'aztro': aztro_data,
                    'aztro_note': ('国际数据源 aztro 原文(免费开放接口)' if aztro_data
                                   else 'aztro 接口暂不可达, 已完整使用本地确定性引擎')})


@astro_bp.route('/api/tarot', methods=['POST'])
def api_tarot():
    data = request.get_json(force=True, silent=True) or {}
    seed = data.get('seed')
    seed_text = '%s|%s' % (seed, cn_now().strftime('%Y%m%d')) if seed else None
    cards = ae.tarot_draw(n=3, seed_text=seed_text)
    spreads = ['过去 / 根源', '现在 / 局势', '未来 / 走向']
    return jsonify({'ok': True, 'cards': [
        dict(c, position=spreads[i]) for i, c in enumerate(cards)]})


# ---------------------------------------------------------------- 知识库


@astro_bp.route('/api/terms')
def api_terms():
    q = (request.args.get('q') or '').strip().lower()
    items = ae.list_terms()
    if q:
        items = [t for t in items
                 if q in t['key'].lower() or q in t['title'].lower()
                 or q in t['summary'].lower()]
    return jsonify({'ok': True, 'items': items, 'count': len(items)})


@astro_bp.route('/api/terms/<path:key>')
def api_term(key):
    t = ae.get_term(key)
    if not t:
        return jsonify({'ok': False, 'error': '词条不存在'}), 404
    return jsonify({'ok': True, 'term': dict(t, key=key)})


# ---------------------------------------------------------------- 我的存档


def _record_dto(rec, full=False):
    dto = {'id': rec.id, 'kind': rec.kind, 'title': rec.title,
           'created_at': rec.created_at.strftime('%Y-%m-%d %H:%M')
           if rec.created_at else ''}
    if full:
        dto['input'] = json.loads(rec.input_json or '{}')
        try:
            dto['result'] = json.loads(rec.result_json or '{}')
        except ValueError:
            dto['result'] = {}
    return dto


@astro_bp.route('/api/records')
@login_required
def api_records():
    rows = (AstroChart.query.filter_by(user_id=current_user.id)
            .order_by(AstroChart.id.desc()).limit(MAX_RECORDS).all())
    return jsonify({'ok': True, 'items': [_record_dto(r) for r in rows],
                    'count': len(rows), 'quota': '不限量'})


@astro_bp.route('/api/records', methods=['POST'])
@login_required
def api_records_save():
    data = _payload()
    if not data or 'result' not in data:
        return jsonify({'ok': False, 'error': '缺少存档内容'}), 400
    blob = json.dumps(data['result'], ensure_ascii=False)
    if len(blob) > MAX_BODY_KB * 1024 * 4:
        return jsonify({'ok': False, 'error': '单条记录过大'}), 400
    rec = _save_record(current_user.id, data.get('kind', 'daily'),
                       (data.get('title') or '未命名记录')[:200],
                       data.get('input') or {}, data['result'])
    return jsonify({'ok': True, 'id': rec.id})


@astro_bp.route('/api/records/<int:rec_id>', methods=['DELETE'])
@login_required
def api_records_delete(rec_id):
    rec = AstroChart.query.filter_by(id=rec_id, user_id=current_user.id).first()
    if not rec:
        return jsonify({'ok': False, 'error': '记录不存在'}), 404
    db.session.delete(rec)
    db.session.commit()
    return jsonify({'ok': True})


@astro_bp.route('/api/records/<int:rec_id>')
@login_required
def api_records_get(rec_id):
    rec = AstroChart.query.filter_by(id=rec_id, user_id=current_user.id).first()
    if not rec:
        return jsonify({'ok': False, 'error': '记录不存在'}), 404
    return jsonify({'ok': True, 'item': _record_dto(rec, full=True)})


@astro_bp.route('/api/records/export')
@login_required
def api_records_export():
    """全量导出为 JSON(存档即权力: 数据随时带走, 无任何限制)。"""
    rows = (AstroChart.query.filter_by(user_id=current_user.id)
            .order_by(AstroChart.id.asc()).all())
    payload = {
        'site': '知行合一 · 星运', 'exported_at': cn_now().strftime('%Y-%m-%d %H:%M'),
        'note': '全部历史档案, 无数量限制, 可重新导入任何兼容系统',
        'count': len(rows),
        'records': [_record_dto(r, full=True) for r in rows],
    }
    buf = io.BytesIO(json.dumps(payload, ensure_ascii=False,
                                indent=2).encode('utf-8'))
    filename = 'astro_archive_%s.json' % cn_now().strftime('%Y%m%d_%H%M')
    return Response(buf.getvalue(), mimetype='application/json',
                    headers={'Content-Disposition':
                             'attachment; filename="%s"' % filename})


# ---------------------------------------------------------------- 订阅提醒


@astro_bp.route('/api/subscribe', methods=['GET'])
@login_required
def api_subscribe_get():
    sub = AstroSub.query.filter_by(user_id=current_user.id).first()
    if not sub:
        return jsonify({'ok': True, 'sub': None})
    return jsonify({'ok': True, 'sub': {
        'sign': sub.sign, 'hour': sub.hour,
        'last_sent_date': sub.last_sent_date}})


@astro_bp.route('/api/subscribe', methods=['POST'])
@login_required
def api_subscribe_set():
    data = _payload() or {}
    sub = AstroSub.query.filter_by(user_id=current_user.id).first()
    if data.get('off'):
        if sub:
            db.session.delete(sub)
            db.session.commit()
        return jsonify({'ok': True, 'sub': None})
    sign = data.get('sign', '')
    if sign not in ae.SIGN_KEY_ORDER:
        return jsonify({'ok': False, 'error': '请先选择星座'}), 400
    hour = int(_clamp(data.get('hour'), 0, 23, 8))
    if not sub:
        sub = AstroSub(user_id=current_user.id)
        db.session.add(sub)
    sub.sign, sub.hour = sign, hour
    sub.updated_at = cn_now()
    db.session.commit()
    deliver_due_digests(current_user.id)
    return jsonify({'ok': True, 'sub': {
        'sign': sub.sign, 'hour': sub.hour,
        'last_sent_date': sub.last_sent_date}})


def deliver_due_digests(user_id=None):
    """投递到期未读的每日星运提醒(站内通知)。

    触发时机: 用户打开星运页或修改订阅设置。按(小时已到, 当日未发)判定,
    幂等安全, 不依赖外部定时器; 后续接入 job_worker 定时任务时可无缝复用。
    """
    if db is None or AstroSub is None:
        return
    now = cn_now()
    today = now.strftime('%Y-%m-%d')
    try:
        q = AstroSub.query.filter(AstroSub.last_sent_date != today,
                                  AstroSub.hour <= now.hour)
        subs = q.all() if user_id is None else q.filter_by(user_id=user_id).all()
        sent = 0
        for sub in subs:
            f = ae.daily_fortune(sub.sign, now.date())
            top = max(f['dims'], key=lambda dd: dd['score'])
            low = min(f['dims'], key=lambda dd: dd['score'])
            msg = ('[%s今日星运] %s 综合运势 %d/100 · 最旺%s(%d分), '
                   '留意%s(%d分); 幸运色%s, 幸运数%s。点此查看完整解读与宜忌。' % (
                       f['sign'], today, f['overall'],
                       top['label'], top['score'], low['label'], low['score'],
                       f['lucky_color'],
                       '/'.join(str(n) for n in f['lucky_numbers'])))
            create_notification(sub.user_id, 'astro_daily', msg)
            sub.last_sent_date = today
            sent += 1
        if sent:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning('astro digest failed: %s', e)
