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
"""search 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import app, login_required

def _kb_path(name):
    """集合名(可能形如 '一级·二级')转展示路径: '/一级/二级'。"""
    if not name:
        return ''
    parts = [p for p in str(name).split('·') if p]
    return '/' + '/'.join(parts)


def _unified_search_data(q):
    """统一检索:待办 + 笔记 + 知识库,分类型返回 dict(API 与检索结果页复用)。

    每个条目携带精简的展示字段,前端仅渲染「标题 + 一行元信息」:
    - 知识库: path(集合路径)/score
    - 待办:   priority(高/中/低)/end_date(截止 MM-DD)
    - 随手记: date(创建 MM-DD)/thread
    """
    q = (q or '').strip()
    if not q:
        return {'q': '', 'tasks': [], 'notes': [], 'kb': [], 'total': 0}
    pat = f'%{q}%'

    now = cn_now()

    # 待办(我参与的)
    filters = [TaskAssignment.user_id == current_user.id]
    filters.append(db.or_(
        Task.title.like(pat), Task.description.like(pat),
        TaskAssignment.note.like(pat)))
    assigns = TaskAssignment.query.join(Task).filter(
        *filters).order_by(Task.end_time.desc()).limit(20).all()
    tasks = []
    for a in assigns:
        end = a.task.end_time
        if end < now:
            pri = '高'
        elif end - now < timedelta(hours=48):
            pri = '中'
        else:
            pri = '低'
        tasks.append({
            'task_id': a.task.id,
            'title': a.task.title,
            'description': a.task.description or '',
            'category': a.task.category,
            'status': a.status,
            'end_time': end.strftime('%Y-%m-%d %H:%M'),
            'priority': pri,
            'end_date': end.strftime('%m-%d'),
            'detail_url': url_for('user_task_detail', task_id=a.task.id),
        })

    # 笔记(个人)
    from notes import Note, parse_tags_json
    notes = Note.query.filter(Note.user_id == current_user.id).filter(
        db.or_(Note.title.like(pat), Note.content.like(pat))
    ).order_by(Note.created_at.desc()).limit(20).all()
    note_rows = [{
        'id': n.id,
        'title': n.title,
        'content': (n.content or '')[:200],
        'tags': parse_tags_json(n.tags),
        'thread': n.thread.name if n.thread else '',
        'created_at': n.created_at.strftime('%Y-%m-%d %H:%M') if
        n.created_at else '',
        'date': n.created_at.strftime('%m-%d') if n.created_at else '',
        'detail_url': url_for('notes.index', note_id=n.id),
    } for n in notes]

    # 知识库(优先知识点,再补文档页;按当前用户可见范围过滤)
    kb = []
    try:
        import knowledge as _kb
        visible = _kb._visible_doc_ids()  # None=全部(管理员)
        visible_points = _kb._visible_point_ids()
        vp_set = set(visible_points) if visible_points is not None else None
        coll_names = {}

        def _load_coll_names(ids):
            try:
                from knowledge import KbCollection as _KbCollection
                from knowledge import KbDocument as _KbDoc
                return dict(
                    db.session.query(_KbDoc.id, _KbCollection.name)
                    .join(_KbCollection,
                          _KbDoc.collection_id == _KbCollection.id)
                    .filter(_KbDoc.id.in_(ids)).all())
            except Exception as _e:
                app.logger.warning('unified kb path failed: %s', _e)
                return {}

        # 1) 知识点优先
        point_hit_docs = set()
        try:
            _pt_rows = [pt for pt in _kb.keyword_search_points(q, k=12)
                        if vp_set is None or pt['point_id'] in vp_set]
            _pt_previews = _previews_map([pt['doc_id'] for pt in _pt_rows])
            for pt in _pt_rows:
                point_hit_docs.add(pt['doc_id'])
                kb.append({
                    'type': 'point',
                    'point_id': pt['point_id'],
                    'doc_id': pt['doc_id'],
                    'title': pt['title'],
                    'filename': pt['filename'],
                    'score': round(min(pt['score'] * 20, 99)),
                    'pages': [{'page_no': pt['page_start'],
                               'snippet': str(_kb.make_snippet(
                                   pt['content'], q))}],
                    'preview_url': url_for('kb.preview', doc_id=pt['doc_id'])
                    if _pt_previews.get(pt['doc_id']) else '',
                    'detail_url': url_for('kb.point_detail',
                                          pid=pt['point_id']),
                    'path': _kb_path(pt['collection_name']),
                })
        except Exception as _e:
            app.logger.warning('unified kb point search failed: %s', _e)

        # 2) 文档级兜底(已有知识点命中的文档不重复)
        try:
            res = _kb.keyword_search_pages(q, k=10)
            grouped = _kb.group_results(res, q, max_pages_per_doc=2)
            doc_ids = [g['doc_id'] for g in grouped
                       if g['doc_id'] not in point_hit_docs]
            if doc_ids:
                coll_names = _load_coll_names(doc_ids)
                _doc_previews = _previews_map(doc_ids)
            else:
                _doc_previews = {}
            for g in grouped:
                if g['doc_id'] in point_hit_docs:
                    continue
                if visible is not None and g['doc_id'] not in visible:
                    continue
                kb.append({
                    'type': 'doc',
                    'doc_id': g['doc_id'],
                    'title': g['title'],
                    'filename': g['filename'],
                    'score': round(g['best_score'] * 100),
                    'pages': [{'page_no': p['page_no'],
                               'snippet': str(p['snippet'])}
                              for p in g['pages']],
                    'preview_url': url_for('kb.preview', doc_id=g['doc_id'])
                    if _doc_previews.get(g['doc_id']) else '',
                    'detail_url': url_for('kb.doc_detail', doc_id=g['doc_id']),
                    'path': _kb_path(coll_names.get(g['doc_id'], '')),
                })
        except Exception as _e:
            app.logger.warning('unified kb doc search failed: %s', _e)
    except Exception as _e:
        app.logger.warning('unified kb search failed: %s', _e)

    total = len(tasks) + len(notes) + len(kb)
    if total > 0:
        try:
            from knowledge import record_history
            record_history('unified', q)
        except Exception as _e:
            app.logger.warning('record unified history failed: %s', _e)
    return {'q': q, 'tasks': tasks, 'notes': note_rows, 'kb': kb,
            'total': total}


@app.route('/api/unified-search')
@login_required
def api_unified_search():
    """统一检索:待办 + 笔记 + 知识库,分类型返回(下拉/全屏检索共用)。"""
    data = _unified_search_data(request.args.get('q', ''))
    return jsonify({'ok': True, **data})


@app.route('/search')
@login_required
def unified_search_page():
    """统一检索独立结果页(检索结果各组「查看全部 ›」的落地页)。"""
    q = (request.args.get('q') or '').strip()
    data = _unified_search_data(q)
    return render_template('search.html', q=q, data=data)


@app.route('/api/unified-search/history')
@login_required
def api_unified_search_history():
    """首页统一检索的历史(当前用户最近 top5) + 热门标签。"""
    try:
        from knowledge import get_recent_unified
        items = get_recent_unified(current_user.id, 5)
    except Exception as _e:
        app.logger.warning('load unified history failed: %s', _e)
        items = []
    return jsonify({'ok': True, 'items': items, 'hot': _hot_tags()})


def _hot_tags(limit=6):
    """当前用户笔记中使用最多的标签(热门标签,供检索输入前推荐)。"""
    from collections import Counter
    from notes import Note, parse_tags_json
    cnt = Counter()
    try:
        notes = Note.query.filter_by(user_id=current_user.id).order_by(
            Note.created_at.desc()).limit(500).all()
        for n in notes:
            for t in parse_tags_json(n.tags):
                t = (t or '').strip()
                if t:
                    cnt[t] += 1
    except Exception as _e:
        app.logger.warning('load hot tags failed: %s', _e)
        return []
    return [t for t, _c in cnt.most_common(limit)]


def _previews_map(doc_ids):
    """批量判断哪些文档有本地预览文件,返回 {doc_id: bool}。

    替代逐条 _has_preview(每条一次 db.session.get + os.path.exists),
    一次 IN 查询 + 批量路径检查,消除检索结果渲染时的 N+1。"""
    from knowledge import KbDocument, _resolve_stored_path
    ids = sorted({int(i) for i in (doc_ids or []) if i})
    if not ids:
        return {}
    try:
        rows = db.session.query(
            KbDocument.id, KbDocument.file_path).filter(
            KbDocument.id.in_(ids)).all()
    except Exception as _e:
        app.logger.warning('batch preview check failed: %s', _e)
        return {}
    return {doc_id: bool(fp and os.path.exists(_resolve_stored_path(fp)))
            for doc_id, fp in rows}


