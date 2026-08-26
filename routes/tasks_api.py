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
"""tasks 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import (app, login_required, Group, Notification, Task,
                 TaskAssignment, User, _count_kb, _count_notes,
                 allowed_file, check_sensitive_words, cn_now,
                 create_notification, db, file_content_matches,
                 find_similar_tasks, get_same_group_users,
                 highlight_sensitive_words, logger, parse_task_from_text,
                 task_group)



from flask import flash, jsonify, redirect, render_template, request, url_for, Response
from services.task_service import purge_task, restore_task, soft_delete_task
from flask_login import current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
import json
import os
from datetime import date, datetime, time as dtime, timedelta, timezone

"""tasks REST API 路由(/api/*), 自 routes_tasks.py 拆分, endpoint 名称不变。"""

# 跨页面/API 共用的纯函数(拆分自 routes_tasks.py)
from routes.tasks_common import _build_task_stats, _similar_blocked_by_assignee

_HOLIDAY_CN = {
    "New Year's Day": '元旦',
    'Spring Festival': '春节',
    'Tomb-sweeping Day': '清明节',
    'Labour Day': '劳动节',
    'Dragon Boat Festival': '端午节',
    'Mid-autumn Festival': '中秋节',
    'National Day': '国庆节',
    'Anti-Fascist 70th Day': '抗战胜利纪念日',
}

# 在线节假日接口按年缓存(数据年内不变, 进程内仅请求一次)
_HOLIDAY_API_CACHE = {}


def _holiday_data_from_api(year):
    """免费节假日接口(timor.tech)按年获取, 作为本地库缺失/未更新的兜底与复核。

    返回 {'MM-DD': {'holiday': True休/False补班, 'name': 中文节日名}}; 失败返回 None。
    """
    if year in _HOLIDAY_API_CACHE:
        return _HOLIDAY_API_CACHE[year]
    try:
        import json as _json
        import urllib.request
        url = f'https://timor.tech/api/holiday/year/{year}'
        req = urllib.request.Request(
            url, headers={'User-Agent': 'TaskManager/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode('utf-8'))
        out = {}
        for k, v in (data.get('holiday') or {}).items():
            parts = str(k).split('-')
            m, dd = int(parts[0]), int(parts[1])
            out[f'{m:02d}-{dd:02d}'] = {
                'holiday': bool(v.get('holiday')),
                'name': str(v.get('name') or '')}
        _HOLIDAY_API_CACHE[year] = out
        return out
    except Exception:
        return None
@app.route('/api/group-members')
@login_required
def api_group_members():
    members = get_same_group_users(current_user)
    result = [{'id': u.id, 'name': u.name or u.username, 'username': u.username}
              for u in members]
    return jsonify(result)


@app.route('/api/search-tasks')
@login_required
def api_search_tasks():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    filters = [TaskAssignment.user_id == current_user.id]
    if q:
        pattern = f'%{q}%'
        filters.append(db.or_(
            Task.title.like(pattern),
            Task.description.like(pattern),
            TaskAssignment.note.like(pattern)
        ))
    if category:
        filters.append(Task.category == category)
    assignments = TaskAssignment.query.join(Task).filter(
        *filters
    ).order_by(Task.end_time.desc()).limit(20).all()
    results = []
    for a in assignments:
        results.append({
            'task_id': a.task.id,
            'title': a.task.title,
            'description': a.task.description or '',
            'category': a.task.category,
            'status': a.status,
            'progress': a.progress,
            'start_time': a.task.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': a.task.end_time.strftime('%Y-%m-%d %H:%M'),
            'detail_url': url_for('user_task_detail', task_id=a.task.id),
        })
    return jsonify(results)
@app.route('/api/quick-tasks', methods=['GET'])
@login_required
def api_quick_tasks_feed():
    """待办列表：返回当前用户创建的任务（最新在前）。
    默认只返回未完成待办，?completed=1 时包含已完成；?category=分类 时按分类筛选。"""
    show_completed = request.args.get('completed') == '1'
    category = (request.args.get('category') or '').strip()
    query = Task.query.filter_by(creator_id=current_user.id)
    if category:
        query = query.filter(Task.category == category)
    if not show_completed:
        query = query.filter(Task.assignments.any(
            TaskAssignment.status.in_(['pending', 'rejected'])))
    tasks = query.order_by(Task.created_at.desc()).limit(100).all()
    ids = [t.id for t in tasks]
    counts = {}
    if ids:
        rows = TaskAssignment.query.filter(
            TaskAssignment.task_id.in_(ids)).all()
        for a in rows:
            c = counts.setdefault(a.task_id, [0, 0])
            c[0] += 1
            if a.status in ('completed', 'approved'):
                c[1] += 1
    out = []
    for t in tasks:
        total, done = counts.get(t.id, [0, 0])
        out.append({
            'id': t.id,
            'title': t.title,
            'description': t.description or '',
            'category': t.category,
            'start_time': t.start_time.strftime('%Y-%m-%d %H:%M') if t.start_time else '',
            'end_time': t.end_time.strftime('%Y-%m-%d %H:%M') if t.end_time else '',
            'total': total,
            'done': done,
            'completed': total > 0 and done >= total,
        })
    # 分类计数（按是否含已完成过滤，不受选中分类影响）
    cat_query = Task.query.filter_by(creator_id=current_user.id)
    if not show_completed:
        cat_query = cat_query.filter(Task.assignments.any(
            TaskAssignment.status.in_(['pending', 'rejected'])))
    categories = {}
    for t in cat_query.all():
        categories[t.category] = categories.get(t.category, 0) + 1
    return jsonify({'ok': True, 'tasks': out, 'show_completed': show_completed,
                    'category': category, 'categories': categories})


def _task_display_and_section(t, status, now, ref=None):
    """计算任务的显示状态(display)与时间轴分段(section/section_label)。
    分段按 ref 时间归类(已完成=完成时间,未完成=截止时间),与日历口径一致。"""
    today_date = now.date()
    ref_date = (ref or t.end_time or now).date()
    start_date = t.start_time.date() if t.start_time else today_date
    # 显示状态
    if status == 'abandoned':
        display = 'abandoned'
    elif status in ('completed', 'approved'):
        display = 'completed'
    elif t.end_time < now:
        display = 'overdue'
    elif start_date <= today_date:
        display = 'today'
    else:
        display = 'future'
    # 分段
    diff_days = (ref_date - today_date).days
    if display == 'abandoned':
        section, section_label = 'abandoned', '已废弃'
    elif diff_days < -31:
        section, section_label = 'past', '更早'
    elif diff_days < -7:
        section, section_label = 'past_month', '过去一个月'
    elif diff_days < 0:
        section, section_label = 'past_week', '过去一周'
    elif diff_days == 0:
        section, section_label = 'today', '今天 · ' + today_date.strftime('%m月%d日')
    elif diff_days == 1:
        section, section_label = 'tomorrow', '明天'
    elif diff_days <= 7:
        section, section_label = 'future_week', '未来一周'
    elif diff_days <= 31:
        section, section_label = 'future_month', '未来一个月'
    else:
        section, section_label = 'later', '更远'
    return display, section, section_label


@app.route('/api/tasks/timeline', methods=['GET'])
@login_required
def api_tasks_timeline():
    """时间轴:返回当前用户相关任务的时间分布数据。
    ?start=YYYY-MM-DD&end=YYYY-MM-DD 可选,不传则返回全部待办;
    ?show_completed=1 包含已完成;?category=分类 按分类筛选。"""
    today = cn_now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        start = datetime.strptime(request.args.get('start', ''), '%Y-%m-%d') \
            if request.args.get('start') else None
    except Exception:
        start = None
    try:
        end = datetime.strptime(request.args.get('end', ''), '%Y-%m-%d') \
            if request.args.get('end') else None
    except Exception:
        end = None
    if end:
        end = end.replace(hour=23, minute=59, second=59)
    category = (request.args.get('category') or '').strip()
    show_completed = request.args.get('show_completed', '') == '1'
    # 查询当前用户的任务(创建的 + 被分配的)
    task_ids = set()
    # 创建的任务(排除已入回收站)
    created = Task.query.filter(
        Task.creator_id == current_user.id,
        Task.deleted_at.is_(None))
    if start:
        created = created.filter(Task.end_time >= start)
    if end:
        created = created.filter(Task.end_time <= end)
    for t in created.all():
        task_ids.add(t.id)
    # 被分配的任务(show_completed 时纳入已完成,与日历口径一致)
    a_statuses = ['pending', 'rejected']
    if show_completed:
        a_statuses += ['completed', 'approved']
    assigned_ids = [r[0] for r in db.session.query(
        TaskAssignment.task_id).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status.in_(a_statuses)).all()]
    # 已完成按完成时间归档: 完成时间在范围内(截止不在)的任务也要纳入
    done_in_range = []
    if start and end:
        done_in_range = [r[0] for r in db.session.query(
            TaskAssignment.task_id).filter(
            TaskAssignment.user_id == current_user.id,
            TaskAssignment.status.in_(('completed', 'approved')),
            TaskAssignment.completed_at.isnot(None),
            TaskAssignment.completed_at >= start,
            TaskAssignment.completed_at <= end).all()]
    extra_ids = set(assigned_ids) | set(done_in_range)
    if extra_ids:
        # 不在此处过滤 end_time: 已完成任务由完成时间归档,越界项由下方 ref 校验剔除
        extra = Task.query.filter(
            Task.id.in_(extra_ids),
            Task.deleted_at.is_(None))
        for t in extra.all():
            task_ids.add(t.id)
    if not task_ids:
        return jsonify({'ok': True, 'tasks': [], 'today': today.strftime('%Y-%m-%d')})
    # 消除序列化循环 N+1: groups 预取; assignments 为 lazy='dynamic'
    # 不支持预加载, 改为一次性批量载入后按任务分组
    from sqlalchemy.orm import selectinload
    tasks = Task.query.filter(Task.id.in_(task_ids), Task.deleted_at.is_(None)).options(
        selectinload(Task.groups)).order_by(Task.end_time).all()
    # 获取当前用户在这些任务上的分配状态
    assigns = {}
    for a in TaskAssignment.query.filter(
            TaskAssignment.task_id.in_(task_ids),
            TaskAssignment.user_id == current_user.id).all():
        assigns[a.task_id] = a
    # 全体被分配人(批量预取, 供序列化 assignee_ids 使用)
    assignee_map = {}
    for aa in TaskAssignment.query.filter(
            TaskAssignment.task_id.in_(task_ids)).all():
        assignee_map.setdefault(aa.task_id, []).append(aa.user_id)
    out = []
    all_categories = {}
    cat_key = lambda t: (t.category or '').strip() or '未分类'
    for t in tasks:
        a = assigns.get(t.id)
        status = a.status if a else 'pending'
        now = cn_now()
        # 归类基准: 已完成按完成时间,未完成按截止时间(与日历口径一致)
        done = status in ('completed', 'approved')
        ref = (a.completed_at or t.end_time) if (done and a) else t.end_time
        if start and end and ref and not (start <= ref <= end):
            continue
        display, section, section_label = _task_display_and_section(
            t, status, now, ref=ref)
        # 分类计数 — 与「全部」同口径的全集统计(不受category过滤影响, 归一化脏数据)
        s2 = status
        if s2 != 'abandoned' and not (s2 in ('completed', 'approved') and not show_completed):
            k = cat_key(t)
            all_categories[k] = all_categories.get(k, 0) + 1
        if category and cat_key(t) != category:
            continue
        # 默认不展示已完成
        if display == 'completed' and not show_completed:
            continue
        out.append({
            'id': t.id,
            'title': t.title,
            'description': (t.description or '')[:200],
            'full_description': t.description or '',
            'category': cat_key(t),
            'start_time': t.start_time.strftime('%Y-%m-%d %H:%M'),
            'end_time': t.end_time.strftime('%Y-%m-%d %H:%M'),
            'progress': a.progress if a else 0,
            'status': status,
            'display': display,
            'section': section,
            'section_label': section_label,
            'ref_date': ref.strftime('%Y-%m-%d') if ref else '',
            'note': (a.note or '') if a else '',
            'attachment': (a.attachment or '') if a else '',
            'assignment_id': a.id if a else None,
            'creator_id': t.creator_id,
            'is_owner': t.creator_id == current_user.id or current_user.role == 'admin',
            'assignee_ids': assignee_map.get(t.id, []),
            'group_ids': [g.id for g in t.groups],
        })
    # 安全上限: 防止极端数据量下响应过大(has_more 提示被截断)
    TL_MAX = 2000
    has_more = len(out) > TL_MAX
    if has_more:
        out = out[:TL_MAX]
    return jsonify({'ok': True, 'tasks': out, 'today': today.strftime('%Y-%m-%d'),
                    'categories': all_categories, 'has_more': has_more})


@app.route('/api/tasks/calendar')
@login_required
def api_tasks_calendar():
    """返回指定月份每天的任务密度 + 班/休标签"""
    try:
        from chinese_calendar import is_workday, get_holiday_detail
    except ImportError:
        is_workday = get_holiday_detail = None
    year = request.args.get('year', cn_now().year, type=int)
    month = request.args.get('month', cn_now().month, type=int)
    show_completed = request.args.get('show_completed', '') == '1'
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(seconds=1)
    # 仅当前用户相关任务:创建的 + 被分配的。
    # 口径与时间轴一致: 默认仅未完成(pending/rejected),
    # 勾选"显示已完成"(show_completed=1)时纳入已完成(completed/approved)。
    # 归档口径: 已完成按完成时间(completed_at),未完成按截止时间(end_time)
    a_statuses = ['pending', 'rejected']
    if show_completed:
        a_statuses += ['completed', 'approved']
    # SQL 层先按"归档时间落在当月"过滤分配行(未完成按任务 end_time,
    # 已完成按 completed_at), 只取命中行, 不再把该用户全部历史分配载入内存;
    # 状态表随后仅对最终命中的少量任务批量补查, 保证与时间轴同构口径
    from sqlalchemy import or_, and_
    assigned_rows = TaskAssignment.query.join(
        Task, Task.id == TaskAssignment.task_id).filter(
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status.in_(a_statuses),
        or_(and_(Task.end_time >= start, Task.end_time <= end),
            and_(TaskAssignment.completed_at.isnot(None),
                 TaskAssignment.completed_at >= start,
                 TaskAssignment.completed_at <= end))).all()
    visible_ids = {a.task_id for a in assigned_rows}
    done_in_range = [a.task_id for a in assigned_rows if a.completed_at]
    tasks = Task.query.filter(
        or_(Task.creator_id == current_user.id,
            Task.id.in_(visible_ids)),
        Task.deleted_at.is_(None),
        or_(and_(Task.end_time >= start, Task.end_time <= end),
            Task.id.in_(done_in_range))
    ).order_by(Task.end_time).all()
    status_by_task = {}
    done_at_by_task = {}
    if tasks:
        srows = TaskAssignment.query.filter(
            TaskAssignment.user_id == current_user.id,
            TaskAssignment.task_id.in_([t.id for t in tasks])).all()
        status_by_task = {a.task_id: a.status for a in srows}
        done_at_by_task = {a.task_id: a.completed_at for a in srows
                           if a.completed_at and start <= a.completed_at <= end}
    density = {}
    items = {}
    for t in tasks:
        st = status_by_task.get(t.id)
        done = st in ('completed', 'approved')
        if done and not show_completed:
            continue
        ref = done_at_by_task[t.id] if done and done_at_by_task.get(t.id) \
            else t.end_time
        if not (start <= ref <= end):
            continue
        ds = ref.strftime('%Y-%m-%d')
        density[ds] = density.get(ds, 0) + 1
        lst = items.setdefault(ds, [])
        if len(lst) < 5:
            lst.append({'title': t.title,
                        'time': ref.strftime('%H:%M'),
                        'category': t.category,
                        'done': done})
    tags = {}
    holidays = {}
    # 探测 chinese_calendar 是否覆盖该年份(旧版包对新年度抛 NotImplementedError)
    year_ok = True
    if get_holiday_detail is not None:
        try:
            get_holiday_detail(date(year, month, 1))
        except NotImplementedError:
            year_ok = False
        except Exception:
            pass
    lib_mode = is_workday is not None and year_ok
    holiday_mode = 'lib' if lib_mode else 'fallback'

    def _apply_api_day(ds, info):
        """应用在线接口的单日数据: holiday=True 休(带节日名), False 调休补班。"""
        if info.get('holiday'):
            tags[ds] = '休'
            if info.get('name'):
                holidays[ds] = info['name']
        else:
            tags[ds] = '班'

    import calendar as cal_mod
    num_days = (end - start).days + 1
    # 库缺失或版本过旧时, 先尝试在线接口兜底(避免 Python 库未更新导致无假日标记)
    api_year = None
    if not lib_mode:
        api_year = _holiday_data_from_api(year)
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        dow = d.weekday()
        ds = d.strftime('%Y-%m-%d')
        is_weekend = dow >= 5
        if api_year is not None:
            info = api_year.get(d.strftime('%m-%d'))
            if info is not None:
                _apply_api_day(ds, info)
                holiday_mode = 'api'
            elif is_weekend:
                tags[ds] = '休'
            continue
        if not lib_mode:
            # 库与接口均不可用: 周末视为休, 无补班与节日标记
            if is_weekend:
                tags[ds] = '休'
            continue
        try:
            is_hol, hname = get_holiday_detail(d)
        except Exception:
            continue
        if is_hol and hname:
            # 法定假日统一标休(含长假中的周六日,如国庆/中秋假期)
            tags[ds] = '休'
            holidays[ds] = _HOLIDAY_CN.get(hname, hname)
        elif is_weekend and is_workday(d):
            tags[ds] = '班'
    if lib_mode and not holidays:
        # 对比检验: 本地库本月未识别出任何法定假日时调接口复核, 防库数据过期
        api_year = _holiday_data_from_api(year)
        if api_year:
            applied = False
            for day in range(1, num_days + 1):
                d = date(year, month, day)
                info = api_year.get(d.strftime('%m-%d'))
                if info is not None:
                    _apply_api_day(d.strftime('%Y-%m-%d'), info)
                    applied = True
            if applied:
                holiday_mode = 'api'
    return jsonify({'ok': True, 'density': density, 'tags': tags,
                    'holidays': holidays, 'items': items,
                    'holiday_mode': holiday_mode,
                    'year': year, 'month': month})


_NOT_READY={'ok':False,'error':'智能时间解析正在初始化（首次需加载语言包），请稍候几秒再试','not_ready':True}

@app.route('/api/quick-task/preview', methods=['POST'])
@login_required
def api_quick_task_preview():
    """首页快速创建待办第一步：自然语言解析，返回待确认预览(与待办发布一致)。"""
    from kb.nlp_parser import jionlp_ready
    if not jionlp_ready():
        return jsonify(_NOT_READY)
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if len(text) < 2:
        return jsonify({'ok': False, 'error': '待办描述至少 2 个字'}), 400
    sensitive = check_sensitive_words(text) if text else []
    if sensitive:
        return jsonify({'ok': False, 'error': '输入内容包含敏感词，请修改后重试',
                        'sensitive_words': sensitive}), 400
    try:
        parsed = parse_task_from_text(text)
    except Exception as e:
        logger.error('Quick task preview failed: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': '解析待办失败，请检查输入格式'}), 400
    # 时间解析器可见性: jionlp=语义解析(准确) legacy=旧正则回退(容器缺jionlp)
    parsed['time_parser'] = 'legacy' if getattr(
        parse_task_from_text, '_last_time_parser', '') == 'legacy' else 'jionlp'
    title = (parsed.get('title') or '').strip()
    if not title or title == '未命名待办' or len(title) < 2:
        return jsonify({'ok': False, 'error': '无法提取待办标题（至少 2 个字）'}), 400

    # 解析出可编辑的初始值
    start = parsed.get('start_time') or cn_now()
    end = parsed.get('end_time') or (start + timedelta(days=1))
    if end <= start:
        end = start + timedelta(hours=1)

    assignee_ids = []
    assignee_names = []
    if current_user.role == 'admin' and parsed.get('is_all', False):
        is_all = True
    else:
        is_all = False
        for name in parsed.get('assignees') or []:
            u = User.query.filter(
                db.or_(User.name == name, User.username == name)).first()
            if u and not u.is_disabled and u.status == 'approved' and u.id != current_user.id:
                assignee_ids.append(u.id)
                assignee_names.append(u.name or u.username)
        assignee_ids.append(current_user.id)
        assignee_names.append(current_user.name or current_user.username)

    duplicate_tasks = []
    try:
        similar = find_similar_tasks(
            title, text, parsed.get('category') or '',
            start, end, unfinished_only=True)
        if similar and not _similar_blocked_by_assignee(
                similar, set(assignee_ids), [], is_all):
            similar = []
        for d in similar:
            creator = getattr(d.get('task'), 'creator', None)
            duplicate_tasks.append({
                'title': getattr(d.get('task'), 'title', ''),
                'similarity': d.get('similarity', 0),
                'creator': (creator.name or creator.username) if creator else '',
            })
    except Exception:
        pass

    user_groups = []
    try:
        if current_user.role == 'admin':
            _groups = Group.query.all()
        else:
            _groups = current_user.groups.all()
        user_groups = [{'id': g.id, 'name': g.name,
                        'member_count': len(g.members)} for g in _groups]
    except Exception:
        pass

    return jsonify({
        'ok': True,
        'title': title,
        'description': text,
        'category': parsed.get('category') or '工作',
        'start_time': start.strftime('%Y-%m-%dT%H:%M'),
        'end_time': end.strftime('%Y-%m-%dT%H:%M'),
        'is_all': is_all,
        'assignee_ids': assignee_ids,
        'assignee_names': assignee_names,
        'recurrence_text': parsed.get('recurrence_text', ''),
        'recurrence': parsed.get('recurrence') or '',
        'recurrence_interval_days': parsed.get('recurrence_interval_days') or 0,
        'recurrence_count': parsed.get('recurrence_count') or 0,
        'duplicate_tasks': duplicate_tasks,
        'user_groups': user_groups,
        'text': text,
    })


@app.route('/api/quick-task', methods=['POST'])
@login_required
def api_quick_task():
    """首页快速创建待办第二步：确认后创建(与待办发布一致)。"""
    from kb.nlp_parser import jionlp_ready
    if not jionlp_ready():
        return jsonify(_NOT_READY)
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title or len(title) < 2:
        return jsonify({'ok': False, 'error': '待办标题至少 2 个字'}), 400
    dt_fmt = '%Y-%m-%dT%H:%M'
    try:
        start = datetime.strptime(data.get('start_time', ''), dt_fmt)
    except Exception:
        start = cn_now()
    try:
        end = datetime.strptime(data.get('end_time', ''), dt_fmt)
    except Exception:
        end = start + timedelta(days=1)
    if end <= start:
        end = start + timedelta(hours=1)
    category = (data.get('category') or '').strip() or '工作'
    description = (data.get('description') or '').strip() or title

    is_all = current_user.role == 'admin' and bool(data.get('is_all'))
    assign_self = bool(data.get('assign_self', True))
    recurrence_interval_days = int(data.get('recurrence_interval_days') or 0)
    recurrence_count = int(data.get('recurrence_count') or 0)
    total = recurrence_count if recurrence_interval_days and recurrence_count > 0 else 1

    assignee_ids = set()
    if not is_all:
        for uid in data.get('assignee_ids') or []:
            try:
                assignee_ids.add(int(uid))
            except (TypeError, ValueError):
                continue
        if assign_self:
            assignee_ids.add(current_user.id)

    group_ids = []
    for gid in data.get('group_ids') or []:
        try:
            group_ids.append(int(gid))
        except (TypeError, ValueError):
            continue
    if not is_all and not assignee_ids and not group_ids:
        return jsonify({'ok': False, 'error': '请至少选择一位负责人(可勾选自己)'}), 400

    similar = find_similar_tasks(title, description, category,
                                 start, end, unfinished_only=True)
    if similar and _similar_blocked_by_assignee(
            similar, assignee_ids, group_ids, is_all):
        return jsonify({'ok': False, 'duplicate': True,
                        'error': '与现有未完成待办相似度过高（相似度 ≥ 70%），不允许发布，请修改待办标题或描述'}), 400

    created_titles = []
    try:
        db.session.rollback()  # 结束只读事务, 使 begin() 成为最外层事务
        with db.session.begin():
            for i in range(total):
                offset = timedelta(days=recurrence_interval_days * i)
                t_start = start + offset
                t_end = end + offset
                t_title = f'{title} (第{i+1}期/共{total}期)' if total > 1 else title
                task = Task(title=t_title, description=description,
                            category=category, start_time=t_start,
                            end_time=t_end, creator_id=current_user.id,
                            is_all=is_all)
                db.session.add(task)
                db.session.flush()
                if is_all:
                    target_users = User.query.all()
                    for u in target_users:
                        db.session.add(TaskAssignment(task_id=task.id, user_id=u.id))
                        create_notification(u.id, 'task_assigned',
                                            f'你收到一个新待办：「{t_title}」', task.id)
                else:
                    uid_set = set(assignee_ids)
                    if group_ids:
                        selected_groups = Group.query.filter(Group.id.in_(group_ids)).all()
                        for g in selected_groups:
                            for m in g.members:
                                if not m.is_disabled and m.status == 'approved':
                                    uid_set.add(m.id)
                            task.groups.append(g)
                    for uid in uid_set:
                        db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                        create_notification(uid, 'task_assigned',
                                            f'你收到一个新待办：「{t_title}」', task.id)
                created_titles.append(t_title)
    except Exception as e:
        db.session.rollback()
        logger.error('Quick task creation failed: %s', e, exc_info=True)
        return jsonify({'ok': False, 'error': '创建失败'}), 500
    return jsonify({'ok': True, 'task_id': task.id,
                    'url': url_for('user_task_detail', task_id=task.id),
                    'created': created_titles})


@app.route('/api/quick-note', methods=['POST'])
@login_required
def api_quick_note():
    """首页随手记(走笔记自动整理管道)。"""
    from routes.notes import (Note, parse_tags_json, apply_rules, simhash,
                              persist_md, find_duplicates, extract_title)
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': '内容不能为空'}), 400
    title = (data.get('title') or '').strip() or extract_title(content)
    tid = data.get('thread_id')
    from routes.notes import Thread
    thread = None
    if tid:
        thread = Thread.query.filter_by(id=int(tid)).first()
    note = Note(user_id=current_user.id,
                thread_id=thread.id if thread else None,
                title=title, content=content, version=1)
    raw_tags = data.get('tags') or []
    if isinstance(raw_tags, str):
        import re as _re
        raw_tags = [t for t in _re.split(r'[,，;；\s]+', raw_tags) if t.strip()]
    clean_tags = []
    for t in raw_tags:
        t = str(t).strip().lstrip('#')[:20]
        if t and t not in clean_tags:
            clean_tags.append(t)
    note.tags = json.dumps(clean_tags[:8], ensure_ascii=False)
    changes = apply_rules(note)
    note.simhash = str(simhash(content))
    db.session.add(note)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'ok': False, 'error': '保存失败'}), 500
    persist_md(note)
    dup = find_duplicates(note)
    return jsonify({'ok': True, 'note_id': note.id, 'warnings': dup})
@app.route('/api/task/<int:task_id>')
@login_required
def api_task_detail(task_id):
    """待办内联详情(JSON):供待办页右侧面板展示。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if current_user.role != 'admin' and \
            not TaskAssignment.query.filter_by(
                task_id=task.id, user_id=current_user.id).first():
        return jsonify({'ok': False, 'error': '无权查看'}), 403
    assignment = TaskAssignment.query.filter_by(
        user_id=current_user.id, task_id=task.id).first()
    assigns = TaskAssignment.query.filter(
        TaskAssignment.task_id == task.id).all()
    stats = _build_task_stats([task.id], current_user.id)[0].get(task.id, {})
    return jsonify({
        'ok': True,
        'task': {
            'id': task.id,
            'title': task.title,
            'description': task.description or '',
            'category': task.category,
            'status': assignment.status if assignment else '',
            'progress': assignment.progress if assignment else 0,
            'note': assignment.note if assignment else '',
            'start_time': (task.start_time.strftime('%Y-%m-%d %H:%M')
                           if task.start_time else ''),
            'end_time': (task.end_time.strftime('%Y-%m-%d %H:%M')
                         if task.end_time else ''),
            'start_dt': (task.start_time.strftime('%Y-%m-%dT%H:%M')
                         if task.start_time else ''),
            'end_dt': (task.end_time.strftime('%Y-%m-%dT%H:%M')
                       if task.end_time else ''),
            'is_all': task.is_all,
            'creator': task.creator.name or task.creator.username,
            'creator_id': task.creator_id,
            'created_at': task.created_at.strftime('%Y-%m-%d %H:%M')
                          if task.created_at else '',
            'group_ids': [g.id for g in task.groups],
            'can_edit': (current_user.role == 'admin'
                         or task.creator_id == current_user.id
                         or assignment is not None),
            'can_delete': (current_user.role == 'admin'
                           or task.creator_id == current_user.id),
            'assignment_id': assignment.id if assignment else None,
            'assignments': [{
                'assignment_id': a.id,
                'user_id': a.user_id,
                'user': a.user.name or a.user.username,
                'status': a.status,
                'progress': a.progress,
                'note': a.note or '',
                'attachment': a.attachment or '',
                'completed_at': a.completed_at.strftime('%Y-%m-%d %H:%M')
                               if a.completed_at else '',
                'rejection_reason': a.rejection_reason or '',
                'self': a.user_id == current_user.id,
            } for a in assigns],
            'stats': stats,
        }
    })


@app.route('/api/task/<int:task_id>/edit', methods=['POST'])
@login_required
def api_task_edit(task_id):
    """右侧面板内联修改待办(JSON)。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    is_assignee = TaskAssignment.query.filter_by(
        task_id=task.id, user_id=current_user.id).first() is not None
    if task.creator_id != current_user.id and current_user.role != 'admin' \
            and not is_assignee:
        return jsonify({'ok': False, 'error': '无权编辑该待办'}), 403
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title or len(title) < 2:
        return jsonify({'ok': False, 'error': '待办标题至少 2 个字'}), 400
    try:
        start = datetime.strptime(data.get('start_time', ''), '%Y-%m-%dT%H:%M') \
            if data.get('start_time') else task.start_time
        end = datetime.strptime(data.get('end_time', ''), '%Y-%m-%dT%H:%M') \
            if data.get('end_time') else task.end_time
        if start is not None and end is not None and end <= start:
            end = start + timedelta(hours=1)
    except Exception:
        return jsonify({'ok': False, 'error': '时间格式错误'}), 400
    task.title = title
    task.category = (data.get('category') or '').strip() or '工作'
    task.start_time = start
    task.end_time = end
    if 'description' in data:
        task.description = (data.get('description') or '').strip()
    # 修改任务状态(通过编辑面板)
    new_status = (data.get('status') or '').strip()
    if new_status in ('pending', 'completed', 'abandoned'):
        assignment = TaskAssignment.query.filter_by(
            task_id=task.id, user_id=current_user.id).first()
        if assignment and assignment.status != new_status:
            assignment.status = new_status
            if new_status == 'completed':
                assignment.progress = 100
                assignment.completed_at = cn_now()
            elif new_status == 'pending':
                assignment.progress = 0
                assignment.completed_at = None
            elif new_status == 'abandoned':
                assignment.abandoned_at = cn_now()
    db.session.commit()
    return jsonify({'ok': True, 'task_id': task.id})


def _get_task_any(task_id):
    """按 id 取任务(含已入回收站), 供恢复/彻底删除/重复删除等场景."""
    from sqlalchemy import select
    return db.session.execute(
        select(Task).where(Task.id == task_id)
        .execution_options(include_deleted=True)).scalar_one_or_none()


@app.route('/api/task/<int:task_id>/delete', methods=['POST'])
@login_required
def api_task_delete(task_id):
    """删除待办(仅创建者或管理员)。"""
    task = _get_task_any(task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '只能删除自己创建的待办'}), 403
    soft_delete_task(task)
    return jsonify({'ok': True, 'task_id': task.id, 'undoable': True})


@app.route('/api/tasks/batch_delete', methods=['POST'])
@login_required
def api_tasks_batch_delete():
    """批量删除待办(仅创建者或管理员)。支持 ?cascade=1 级联删除同周期后续待办。"""
    data = request.get_json(silent=True) or {}
    task_ids = data.get('task_ids') or []
    cascade = data.get('cascade', False)
    if not task_ids:
        return jsonify({'ok': False, 'error': '未选择待办'}), 400
    tasks = Task.query.filter(Task.id.in_(task_ids)).all()
    if not tasks:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    mine = [t for t in tasks if t.creator_id == current_user.id or current_user.role == 'admin']
    if not mine:
        return jsonify({'ok': False, 'error': '只能删除自己创建的待办'}), 403
    import re
    pat = re.compile(r'^(.*?)\s*\(第(\d+)期/共(\d+)期\)$')
    extra_ids = set()
    if cascade:
        for t in mine:
            m = pat.match(t.title)
            if m:
                base_title = m.group(1)
                cur_num = int(m.group(2))
                all_of_series = Task.query.filter(
                    Task.creator_id == t.creator_id,
                    Task.deleted_at.is_(None),
                    Task.title.like(base_title + ' (第%期/共' + m.group(3) + '期)')
                ).all()
                for s in all_of_series:
                    sm = pat.match(s.title)
                    if sm and int(sm.group(2)) > cur_num:
                        extra_ids.add(s.id)
    if extra_ids:
        extra_tasks = Task.query.filter(Task.id.in_(extra_ids)).all()
        mine.extend([t for t in extra_tasks if t not in mine])
    now = cn_now()
    deleted = []
    for t in mine:
        t.deleted_at = now
        deleted.append(t.id)
    db.session.commit()
    return jsonify({'ok': True, 'deleted': deleted, 'count': len(deleted)})


@app.route('/api/task/<int:task_id>/times', methods=['POST'])
@login_required
def api_task_update_times(task_id):
    """局部更新待办起止时间(抽屉内联编辑): 创建者/管理员/负责人。"""
    task = _get_task_any(task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    is_assignee = TaskAssignment.query.filter_by(
        task_id=task.id, user_id=current_user.id).first() is not None
    if task.creator_id != current_user.id \
            and current_user.role != 'admin' and not is_assignee:
        return jsonify({'ok': False, 'error': '无权修改该待办时间'}), 403
    data = request.get_json(silent=True) or {}

    def _parse(val):
        val = (val or '').strip().replace('T', ' ')
        if not val:
            return None, None
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(val, fmt), None
            except ValueError:
                continue
        return None, '时间格式无效'

    start_time, err = _parse(data.get('start_time'))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    end_time, err = _parse(data.get('end_time'))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    if start_time:
        task.start_time = start_time
    if end_time:
        task.end_time = end_time
    db.session.commit()
    return jsonify({
        'ok': True,
        'start_display': task.start_time.strftime('%m-%d %H:%M')
        if task.start_time else '',
        'end_display': task.end_time.strftime('%m-%d %H:%M')
        if task.end_time else '',
        'start_raw': task.start_time.strftime('%Y-%m-%d %H:%M')
        if task.start_time else '',
        'end_raw': task.end_time.strftime('%Y-%m-%d %H:%M')
        if task.end_time else '',
    })


@app.route('/api/tasks/trash', methods=['GET'])
@login_required
def api_tasks_trash():
    """回收站列表(含软删过滤豁免): 仅创建者本人或管理员可见。"""
    from sqlalchemy import select
    stmt = select(Task).where(
        Task.deleted_at.isnot(None)).execution_options(include_deleted=True)
    if current_user.role != 'admin':
        stmt = stmt.where(Task.creator_id == current_user.id)
    rows = db.session.execute(
        stmt.order_by(Task.deleted_at.desc())).scalars().all()
    return jsonify({'ok': True, 'items': [{
        'id': t.id, 'title': t.title, 'category': t.category,
        'start_time': t.start_time.strftime('%Y-%m-%d %H:%M') if t.start_time else '',
        'end_time': t.end_time.strftime('%Y-%m-%d %H:%M') if t.end_time else '',
        'deleted_at': t.deleted_at.strftime('%m-%d %H:%M'),
        'assignee_count': t.assignments.count()} for t in rows]})


@app.route('/api/task/<int:task_id>/restore', methods=['POST'])
@login_required
def api_task_restore(task_id):
    """从回收站恢复(创建者或管理员)。"""
    task = _get_task_any(task_id)
    if not task or not task.deleted_at:
        return jsonify({'ok': False, 'error': '待办不存在或不在回收站'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '无权恢复该待办'}), 403
    restore_task(task)
    return jsonify({'ok': True})


@app.route('/api/tasks/batch_restore', methods=['POST'])
@login_required
def api_tasks_batch_restore():
    """批量恢复回收站待办(创建者或管理员)。"""
    tasks = Task.query.filter(
        Task.deleted_at.isnot(None),
        Task.creator_id == current_user.id,
    ).all()
    if current_user.role == 'admin':
        tasks = Task.query.filter(Task.deleted_at.isnot(None)).all()
    if not tasks:
        return jsonify({'ok': False, 'error': '回收站为空'}), 404
    for t in tasks:
        restore_task(t)
    return jsonify({'ok': True, 'count': len(tasks)})


@app.route('/api/task/<int:task_id>/purge', methods=['POST'])
@login_required
def api_task_purge(task_id):
    """彻底删除(不可逆, 创建者或管理员); 需前端 uiConfirm 二次确认。"""
    task = _get_task_any(task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '无权彻底删除该待办'}), 403
    purge_task(task)
    return jsonify({'ok': True})


@app.route('/api/task/<int:task_id>/reopen', methods=['POST'])
@login_required
def api_task_reopen(task_id):
    """重新打开待办:将已完成的分配恢复为进行中(创建者或管理员)。"""
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '无权操作'}), 403
    assignments = TaskAssignment.query.filter(
        TaskAssignment.task_id == task.id,
        TaskAssignment.status.in_(['completed', 'approved'])).all()
    for a in assignments:
        a.status = 'pending'
        a.completed_at = None
        a.rejection_reason = None
        a.progress = 0
    db.session.commit()
    return jsonify({'ok': True, 'reset': len(assignments)})


@app.route('/api/task/<int:task_id>/assign', methods=['POST'])
@login_required
def api_task_assign(task_id):
    """修改分配人(创建者或管理员)。

    默认仅新增分配;带 sync=true 时为全量同步:不在列表中的已分配
    用户将被标记为废弃(abandoned),废弃后再次勾选则恢复为进行中。
    """
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'ok': False, 'error': '待办不存在'}), 404
    if task.creator_id != current_user.id and current_user.role != 'admin':
        return jsonify({'ok': False, 'error': '无权操作'}), 403
    data = request.get_json(silent=True) or {}
    user_ids = data.get('user_ids') or []
    group_ids = data.get('group_ids') or []
    rows = TaskAssignment.query.filter_by(task_id=task.id).all()
    existing_map = {a.user_id: a for a in rows}
    added = []

    # 同步任务关联的群组
    if 'group_ids' in data:
        new_groups = [db.session.get(Group, int(gid)) for gid in group_ids
                      if str(gid).lstrip('-').isdigit()]
        new_groups = [g for g in new_groups if g is not None]
        task.groups = new_groups

    # 由群组展开得到的成员 id 集合
    group_member_ids = set()
    if group_ids:
        for gid in group_ids:
            try:
                gid = int(gid)
            except (TypeError, ValueError):
                continue
            g = db.session.get(Group, gid)
            if g:
                for m in g.members:
                    if not m.is_disabled and m.status == 'approved':
                        group_member_ids.add(m.id)

    if data.get('sync'):
        keep = set()
        for raw in user_ids:
            try:
                uid = int(raw)
            except (TypeError, ValueError):
                continue
            if uid in keep:
                continue
            keep.add(uid)
            a = existing_map.get(uid)
            if a is None:
                u = db.session.get(User, uid)
                if not u or u.is_disabled or u.status != 'approved':
                    continue
                db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                create_notification(uid, 'task_assigned',
                                    f'你收到一个新待办：「{task.title}」', task.id)
                added.append(u.name or u.username)
            elif a.status == 'abandoned':
                a.status = 'pending'
                a.abandoned_at = None
                a.progress = 0
                added.append(a.user.name or a.user.username)
        # 群组成员确保在分配名单中
        for uid in group_member_ids:
            if uid in keep:
                continue
            keep.add(uid)
            a = existing_map.get(uid)
            if a is None:
                u = db.session.get(User, uid)
                if u and not u.is_disabled and u.status == 'approved':
                    db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                    added.append(u.name or u.username)
            elif a.status == 'abandoned':
                a.status = 'pending'
                a.abandoned_at = None
                a.progress = 0
        removed = []
        now = cn_now()
        for a in rows:
            if a.user_id not in keep and a.status != 'abandoned':
                a.status = 'abandoned'
                a.abandoned_at = now
                removed.append(a.user.name or a.user.username)
        db.session.commit()
        return jsonify({'ok': True, 'added': added, 'removed': removed})

    existing = set(existing_map.keys())
    for uid in user_ids:
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            continue
        u = db.session.get(User, uid)
        if not u or u.is_disabled or u.status != 'approved' or uid in existing:
            continue
        existing.add(uid)
        db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
        create_notification(uid, 'task_assigned',
                            f'你收到一个新待办：「{task.title}」', task.id)
        added.append(u.name or u.username)
    if added:
        db.session.commit()
    return jsonify({'ok': True, 'added': added})


def _sync_task_assignees_from_form(task):
    """Sync task assignees from form POST data (assignee_ids + group_ids + is_all)."""
    user_ids = request.form.getlist('assignee_ids')
    group_ids = request.form.getlist('group_ids')
    is_all = request.form.get('is_all') == '1'
    
    if group_ids:
        new_groups = [db.session.get(Group, int(gid)) for gid in group_ids
                      if str(gid).lstrip('-').isdigit()]
        new_groups = [g for g in new_groups if g is not None]
        task.groups = new_groups
    else:
        task.groups = []
    
    keep = set()
    existing = TaskAssignment.query.filter_by(task_id=task.id).all()
    existing_map = {a.user_id: a for a in existing}
    
    if is_all:
        all_users = User.query.filter_by(status='approved').all()
        for u in all_users:
            if not u.is_disabled:
                keep.add(u.id)
    else:
        if group_ids:
            for gid in group_ids:
                try:
                    gid = int(gid)
                except (TypeError, ValueError):
                    continue
                group = db.session.get(Group, gid)
                if group:
                    for member in group.members:
                        keep.add(member.id)
        for uid in user_ids:
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                continue
            keep.add(uid)
    
    if task.is_all:
        keep.add(task.creator_id)
    
    kept_ids = set(keep)
    for uid in kept_ids:
        a = existing_map.get(uid)
        if a is None:
            u = db.session.get(User, uid)
            if u and not u.is_disabled and u.status == 'approved':
                db.session.add(TaskAssignment(task_id=task.id, user_id=uid))
                create_notification(uid, 'task_assigned',
                                  f'你收到一个新待办：「{task.title}」', task.id)
        elif a.status == 'abandoned':
            a.status = 'pending'
            a.abandoned_at = None
            a.progress = 0
    
    now = cn_now()
    for a in existing:
        if a.user_id not in kept_ids and a.status != 'abandoned':
            a.status = 'abandoned'
            a.abandoned_at = now




# ---- 日历订阅(iCal/.ics): 手机日历一次性订阅, 自动同步待办 ----
_ICS_ESCAPES = str.maketrans({'\\': '\\\\', ';': '\\;', ',': '\\,',
                              '\n': '\\n', '\r': ''})


def _ics_escape(text):
    """RFC5545 文本转义: 反斜杠/分号/逗号/换行。"""
    return str(text or '').translate(_ICS_ESCAPES)


def _ics_fold(line):
    """RFC5545 行折叠: 每行不超过 75 字节(UTF-8), 续行以空格开头。"""
    lines, cur, cur_len = [], '', 0
    for ch in line:
        l = len(ch.encode('utf-8'))
        limit = 75 if not lines else 74
        if cur_len + l > limit:
            lines.append(cur)
            cur, cur_len = ' ' + ch, 1 + l
        else:
            cur += ch
            cur_len += l
    if cur:
        lines.append(cur)
    return lines or ['']


_CN_TZ = timezone(timedelta(hours=8))


def _ics_utc(dt):
    """库内 naive 北京时间 → UTC iCal 格式(YYYYMMDDTHHMMSSZ)。"""
    return dt.replace(tzinfo=_CN_TZ).astimezone(timezone.utc)\
        .strftime('%Y%m%dT%H%M%SZ')


def _build_todo_ics(user, tasks, feed_label='今日待办'):
    """生成 iCal 文本。提醒规则(VIEWER 手机本地通知):
    开始时间在今天的待办 → 开始前 30 分钟;
    开始时间不在今天的待办 → 截止前 60 分钟(RELATED=END);
    全天事件不附提醒。"""
    stamp = _ics_utc(cn_now())
    today = cn_now().date()
    cal_name = _ics_escape(
        f'知行合一·{(user.name or user.username)}·{feed_label}')
    lines = ['BEGIN:VCALENDAR',
             'VERSION:2.0',
             'METHOD:PUBLISH',
             'PRODID:-//TaskManager//Todo Feed//CN',
             'CALSCALE:GREGORIAN',
             f'X-WR-CALNAME:{cal_name}',
             'X-WR-TIMEZONE:Asia/Shanghai',
             'REFRESH-INTERVAL;VALUE=DURATION:PT2H',
             'X-PUBLISHED-TTL:PT2H']
    for t in tasks:
        s, e = t.start_time, t.end_time
        # 解析器「全天」语义(00:00-23:59)输出为 VALUE=DATE 全天事件
        allday = (s.time() == dtime.min and e.hour == 23 and e.minute == 59)
        lines += ['BEGIN:VEVENT',
                  f'UID:todo-{t.id}@taskmanager',
                  f'DTSTAMP:{stamp}']
        if allday:
            lines += [f"DTSTART;VALUE=DATE:{s.strftime('%Y%m%d')}",
                      f"DTEND;VALUE=DATE:{(e + timedelta(days=1)).strftime('%Y%m%d')}"]
        else:
            if not e or e <= s:
                e = s + timedelta(minutes=30)
            lines += [f'DTSTART:{_ics_utc(s)}', f'DTEND:{_ics_utc(e)}']
        cat = (t.category or '').strip()
        desc = (t.description or '')[:500]
        # 空值属性行直接省略: 小米日历(ical4j)对个别空属性解析严格,
        # 任何一行不合规范都会导致整个订阅静默失败
        lines.append('SUMMARY:' + _ics_escape(f'[{cat}] {t.title}' if cat else t.title))
        if desc:
            lines.append('DESCRIPTION:' + _ics_escape(desc))
        if cat:
            lines.append('CATEGORIES:' + _ics_escape(cat))
        lines += ['STATUS:CONFIRMED',
                  'SEQUENCE:0',
                  'TRANSP:OPAQUE']
        if not allday:
            if s.date() == today:
                # 开始在今天: 开始前30分钟(Relative)
                alarm_desc, trigger = '待办即将开始', 'TRIGGER:-PT30M'
            else:
                # 开始不在今天: 截止前60分钟
                # 使用绝对时间而非 RELATED=END: 小米日历(ical4j)不支持
                # RELATED=END 会把闹钟时间算成异常值(如-10268分钟)且无法关闭
                alarm_desc = '待办即将截止，请尽快完成'
                abs_alarm = _ics_utc(e - timedelta(minutes=60))
                trigger = f'TRIGGER;VALUE=DATE-TIME:{abs_alarm}'
            lines += ['BEGIN:VALARM',
                      'ACTION:DISPLAY',
                      'DESCRIPTION:' + _ics_escape(alarm_desc),
                      trigger,
                      'END:VALARM']
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    body = '\r\n'.join(f for line in lines for f in _ics_fold(line))
    return body + '\r\n'


def _feed_q_int(name, default, lo, hi):
    """订阅 URL 整数参数解析: 非法/越界回退默认值。"""
    raw = (request.args.get(name) or '').strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return max(lo, min(v, hi))


@app.route('/user/todo.ics')
def user_todo_ics():
    """待办 iCal 订阅源: 手机日历添加一次 URL 即自动同步。

    鉴权: ?token=<API令牌>(与 /api/token 同一令牌) 免 Cookie;
    已登录会话亦可直接访问。仅输出**未完成**(创建的+被指派的,
    全部负责人已完成的不输出)且截止时间落在时间窗内的待办;
    软删除由全局查询过滤剔除。
    参数: ?days=N  时间窗=今天起 N 天(默认 3, 即未来 3 天)
    提醒: 开始在今天的待办开始前 30 分钟, 其余截止前 60 分钟。"""
    token = (request.args.get('token') or '').strip()
    user = None
    if token:
        u = User.query.filter_by(api_token=token).first()
        if u is not None and not u.is_disabled and u.status == 'approved':
            user = u
    elif current_user.is_authenticated:
        user = current_user._get_current_object()
    if user is None:
        return Response('Unauthorized\n', status=401, mimetype='text/plain')
    days = _feed_q_int('days', 3, 1, 366)
    day0 = cn_now().replace(hour=0, minute=0, second=0, microsecond=0)
    ids = {r[0] for r in db.session.query(TaskAssignment.task_id).filter(
        TaskAssignment.user_id == user.id,
        TaskAssignment.status.in_(('pending', 'rejected'))).all()}
    ids |= {r[0] for r in db.session.query(Task.id).filter(
        Task.creator_id == user.id).all()}
    tasks = []
    if ids:
        tasks = Task.query.filter(Task.id.in_(ids),
                                  Task.end_time >= day0,
                                  Task.end_time < day0 + timedelta(days=days))\
            .order_by(Task.start_time).limit(1000).all()
        # 已完成的不再同步/提醒: 存在非放弃的负责人且全部已完成/已验收;
        # 无任何有效负责人的(纯自建待办)视为未完成, 保留
        rows = db.session.query(
            TaskAssignment.task_id, TaskAssignment.status).filter(
            TaskAssignment.task_id.in_([t.id for t in tasks])).all()
        by_task = {}
        for tid, st in rows:
            by_task.setdefault(tid, set()).add(st)

        def _still_open(tid):
            active = by_task.get(tid, set()) - {'abandoned'}
            return not active or not active <= {'completed', 'approved'}

        tasks = [t for t in tasks if _still_open(t.id)]
    label = '今日待办' if days == 1 else f'未来{days}日待办'
    resp = Response(_build_todo_ics(user, tasks, feed_label=label),
                    mimetype='text/calendar')
    resp.headers['Content-Disposition'] = 'inline; filename="todo.ics"'
    resp.headers['Cache-Control'] = 'no-store'
    return resp
