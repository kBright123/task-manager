# -*- coding: utf-8 -*-
"""同群组一对一聊天(微信风格)。

能力:
- 联系人列表(所有可见用户, 按「未读→最近消息→常问频率」排序, 常问优先)
- 会话消息读写、引用回复(quote); 对端离线时自动用 LLM 基于其资料代答
- 显式 @提问 / AI代答 / 重新回答
- 人话(kind=user)与大模型回答(kind=bot)分离展示; 可对 ask 重新回答

说明:
- 待办取「被@人参与且非'个人'分类」的任务; 笔记取被@人的随手记;
  知识库取对方可见范围(kb._doc_ids_for_user)。
- 全链路走 CSRF(AJAX 全局注入 X-CSRF-Token)。
"""
from datetime import timedelta
import json

from flask import jsonify, request, url_for
from flask_login import current_user, login_required

from app import app, db
from core.app_services import create_notification
from core.models import ChatMessage, Task, TaskAssignment, User
from core.timeutil import cn_now
from kb.chat_intent import ACTION_INTENTS, QUERY_INTENTS, classify_question, parse_question_time

_CHAT_DISABLED_HINT = '大模型服务未启用，未能自动起草回答；可人工回复。'
_CHAT_NO_SOURCE_HINT = ('TA 当前没有可用的非个人待办/笔记/公开知识库资料，'
                        '暂时无法基于TA的内容回答。')
_ASK_SYSTEM_NL = ('你是「小知」助手，基于资料回答用户问题。检索结果已在界面展示，'
                  '请精炼作答，不要逐条复述；引用具体事实时用 [资料 N] 标注。'
                  '回答控制在几句话或少量要点。\n\n')


def _chat_system(target, asker):
    return (
        f'你是{target}的资料助手，基于TA的待办、笔记和公开知识库资料来回答'
        f'{asker}的问题。资料以 [资料 N] 标注，引用具体事实时用 [资料 N] 简单标注。'
        '回答简洁，使用中文；如果资料不足以回答，明确说"资料中未找到"，不要编造。'
        '不要逐条复述每条资料。\n\n')


def _conv_key(a, b):
    return f'{min(a, b)}-{max(a, b)}'


def _target_user(uid):
    """校验可聊天对象: 存在/可见(非禁用/已批准) + 非本人, 不限群组。"""
    if uid == current_user.id:
        return None
    user = db.session.get(User, uid)
    if user is None or user.is_disabled or user.status != 'approved':
        return None
    return user


def _visible_users(me):
    return User.query.filter(
        User.id != me,
        User.is_disabled == False,  # noqa: E712
        User.status == 'approved').all()


def _display(u):
    return (u.name or u.username) if u else ''


def _msg_payload(m):
    reply_content = ''
    if m.reply_to_id:
        pre = db.session.get(ChatMessage, m.reply_to_id)
        if pre is not None:
            reply_content = (pre.content or '')[:160]
    links = []
    try:
        if m.extra:
            raw = json.loads(m.extra) or {}
            links = raw.get('links') or []
    except Exception:
        links = []
    return {
        'id': m.id,
        'kind': m.kind,
        'source': m.source,
        'from_id': m.from_user_id,
        'to_id': m.to_user_id,
        'content': m.content or '',
        'reply_to_id': m.reply_to_id,
        'reply_content': reply_content,
        'links': links,
        'created_at': m.created_at.strftime('%Y-%m-%d %H:%M') if
        m.created_at else '',
        'time_hm': m.created_at.strftime('%H:%M') if m.created_at else '',
        'is_mine': m.from_user_id == current_user.id,
        'unread': not m.is_read and m.to_user_id == current_user.id,
    }


@app.route('/api/chat/contacts')
@login_required
def api_chat_contacts():
    """联系人 = 所有可见用户(不限群组), 按 未读数→最近消息→常问频率 排序。"""
    me = current_user.id
    members = _visible_users(me)
    rows = []
    since = cn_now() - timedelta(days=30)
    for u in members:
        key = _conv_key(me, u.id)
        unread = ChatMessage.query.filter(
            ChatMessage.conversation_id == key,
            ChatMessage.from_user_id == u.id,
            ChatMessage.to_user_id == me,
            ChatMessage.kind == 'user',
            ChatMessage.is_read == False).count()  # noqa: E712
        last = ChatMessage.query.filter(
            ChatMessage.conversation_id == key
        ).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()
                   ).first()
        freq = ChatMessage.query.filter(
            ChatMessage.conversation_id == key,
            ChatMessage.created_at >= since).count()
        rows.append({
            'id': u.id,
            'name': u.name or u.username,
            'username': u.username,
            'online': u.is_online,
            'unread': unread,
            'last_ts': last.created_at.strftime('%Y-%m-%d %H:%M') if
            last else '',
            'last_epoch': (last.created_at.timestamp() if last else 0),
            'last_preview': (last.content or '')[:40] if last else '',
            'last_kind': last.kind if last else '',
            'freq': freq,
            'hot': unread > 0 or freq >= 5,
        })
    rows.sort(key=lambda r: (-r['unread'], -bool(r['last_epoch']),
                             -r['last_epoch'], -r['freq'], r['name']))
    return jsonify({'ok': True, 'contacts': rows})


@app.route('/api/chat/search')
@login_required
def api_chat_search():
    """按姓名/用户名搜索本系统用户(会话列表上方搜索框)。
    搜索范围含禁用/待审账号(标注状态), 能否聊天由 chatable 给出。"""
    q = (request.args.get('q') or '').strip().lower()
    if not q:
        return jsonify({'ok': True, 'users': []})
    me = current_user.id
    users = [u for u in User.query.filter(User.id != me).all()
             if q in (u.name or '').lower() or q in u.username.lower()]
    users.sort(key=lambda u: (0 if ((u.name or '').lower().startswith(q)
                                    or u.username.lower().startswith(q))
                              else 1, u.name or u.username))
    out = []
    for u in users[:30]:
        chatable = not u.is_disabled and u.status == 'approved'
        hint = ''
        if u.is_disabled:
            hint = '已禁用'
        elif u.status != 'approved':
            hint = '待审核' if u.status == 'pending' else u.status
        out.append({'id': u.id, 'name': u.name or u.username,
                    'username': u.username, 'online': u.is_online,
                    'chatable': chatable, 'hint': hint})
    return jsonify({'ok': True, 'users': out})


@app.route('/api/chat/with/<int:uid>')
@login_required
def api_chat_with(uid):
    """拉取与 uid 的会话消息(asc), 并自动把对方消息标记已读。"""
    peer = _target_user(uid)
    if peer is None:
        return jsonify({'ok': False, 'error': '对方不可聊'}), 403
    me = current_user.id
    key = _conv_key(me, uid)
    before = request.args.get('before', type=int)
    limit = min(int(request.args.get('limit', 50)), 100)
    q = ChatMessage.query.filter(ChatMessage.conversation_id == key)
    if before:
        q = q.filter(ChatMessage.id < before)
    msgs = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    msgs.reverse()
    unread_ids = [m.id for m in msgs
                  if m.to_user_id == me and not m.is_read]
    if unread_ids:
        ChatMessage.query.filter(ChatMessage.id.in_(unread_ids)).update(
            {ChatMessage.is_read: True})
        db.session.commit()
    return jsonify({'ok': True,
                    'peer': {'id': peer.id, 'name': _display(peer),
                             'username': peer.username,
                             'online': getattr(peer, 'is_online', False)},
                    'messages': [_msg_payload(m) for m in msgs]})


def _make_message(peer, content, kind='user', source='chat', reply_to_id=None,
                  is_read=False):
    if peer is None and kind == 'bot':
        # bot 代答方向: from=被@人 -> to=提问者
        raise ValueError('peer required for bot message')
    m = ChatMessage(
        conversation_id=_conv_key(current_user.id, peer.id),
        from_user_id=current_user.id if kind == 'user' else peer.id,
        to_user_id=peer.id if kind == 'user' else current_user.id,
        kind=kind, source=source, content=content,
        reply_to_id=reply_to_id, is_read=is_read)
    db.session.add(m)
    return m


def _notify_new(peer, text, task_id=None):
    try:
        create_notification(peer.id, 'chat', text, task_id)
    except Exception as _e:
        app.logger.warning('chat notify failed: %s', _e)


@app.route('/api/chat/send', methods=['POST'])
@login_required
def api_chat_send():
    """发送普通聊天/引用回复消息(人工); 对方离线时自动用 LLM 代答。"""
    data = request.get_json(silent=True) or {}
    peer = _target_user(int(data.get('to_user_id') or 0))
    if peer is None:
        return jsonify({'ok': False, 'error': '对方不可聊'}), 403
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': '消息不能为空'}), 400
    if len(content) > 2000:
        return jsonify({'ok': False, 'error': '消息过长'}), 400
    reply_to_id = data.get('reply_to_id') or None
    if reply_to_id:
        cid = _conv_key(current_user.id, peer.id)
        prev = db.session.get(ChatMessage, int(reply_to_id))
        if prev is None or prev.conversation_id != cid:
            reply_to_id = None
    m = _make_message(peer, content, 'user',
                      'reply' if reply_to_id else 'chat', reply_to_id)
    db.session.flush()
    bot, links = None, []
    cls = classify_question(content)
    if cls['intent'] in QUERY_INTENTS:
        # 自然语言提问(日程/检索/知识问答/问候等): 即使对方在线也由小知作答
        res = _answer_natural(content, peer)
        bot = _make_message(peer, res.get('content') or '', 'bot',
                            'intent', m.id)
        bot.extra = json.dumps({'links': res.get('links') or []},
                               ensure_ascii=False)
        db.session.add(bot)
        links = res.get('links') or []
    elif not peer.is_online:
        # 对端离线: LLM 基于 TA 的非个人资料自动回复
        bot, links = _draft_bot_answer(peer, content, m.id, 'chat')
    db.session.commit()
    _notify_new(peer, f'{_display(current_user)} 私聊你：「{(content or "")[:60]}」')
    payload = {'ok': True, 'message': _msg_payload(m)}
    if bot is not None:
        payload['bot'] = _msg_payload(bot)
        payload['links'] = links
    return jsonify(payload)


def _build_target_sources(question, target):
    """基于被@人的内容构建 llm_ask 的 sources 与前端 links。"""
    from datetime import datetime
    pat = f'%{question}%'
    sources, links = [], []

    def _add(title, text, href, tag):
        text = (text or '').strip()
        if not text:
            text = (title or '').strip()
        sources.append({'title': title or '', 'page': '',
                        'text': text[:500]})
        links.append({'title': title or '', 'href': href or '#', 'tag': tag})

    from core.models import Task, TaskAssignment
    now = cn_now()
    assigns = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == target.id,
        Task.category != '个人',
        db.or_(Task.title.like(pat), Task.description.like(pat),
               TaskAssignment.note.like(pat)),
    ).order_by(Task.end_time.desc()).limit(3).all()
    for a in assigns:
        end = a.task.end_time
        if end < now:
            pri = '高'
        elif end - now < timedelta(hours=48):
            pri = '中'
        else:
            pri = '低'
        note = '；'.join(x for x in [
            ('状态 ' + str(a.status or '')),
            ('截止 ' + str(a.task.end_time.strftime('%Y-%m-%d %H:%M') if
             a.task.end_time else '')),
            ('优先级 ' + pri)] if x)
        _add(f"[待办] {a.task.title or ''}",
             (a.task.description or '') + (f'（{note}）' if note else ''),
             url_for('user_tasks') + '?highlight=' + str(a.task.id),
             '待办')

    from routes.notes import Note
    notes = Note.query.filter(Note.user_id == target.id).filter(
        db.or_(Note.title.like(pat), Note.content.like(pat))
    ).order_by(Note.created_at.desc()).limit(3).all()
    for n in notes:
        _add(f"[随记] {n.title or ''}", n.content or '',
             url_for('notes.index', note_id=n.id), '随记')

    try:
        import kb.knowledge as _kb
        doc_ids = _kb._doc_ids_for_user(target.id)
        hits = _kb.search_pages(question, k=6, alpha=0.5, doc_ids=doc_ids)
        for h in hits[:3]:
            _add(f"[知识库] {h['title'] or ''}",
                 h.get('text') or '', h.get('page') or '-',
                 url_for('kb.doc_detail', doc_id=h['doc_id']), '知识库')
    except Exception as _e:
        app.logger.warning('chat kb search failed: %s', _e)
    return sources[:6], links


def _draft_bot_answer(peer, question, ask_msg_id, source='ask'):
    """生成并保存大模型代答消息(基于被@人资料), 失败写入提示文本。"""
    from kb.knowledge import KB_LLM_DISABLED, llm_ask
    sources, links = [], []
    try:
        sources, links = _build_target_sources(question, peer)
    except Exception as _e:
        app.logger.warning('chat target sources failed: %s', _e)

    def _finalize(m):
        m.extra = json.dumps({'links': links}, ensure_ascii=False)
        db.session.add(m)
        return m, links

    if not sources:
        text = _CHAT_NO_SOURCE_HINT
        return _finalize(_make_message(peer, text, 'bot', source, ask_msg_id))
    if KB_LLM_DISABLED:
        m = _make_message(peer, _CHAT_DISABLED_HINT, 'bot', source, ask_msg_id)
        m.extra = json.dumps({'links': links}, ensure_ascii=False)
        db.session.add(m)
        return m, links
    try:
        answer = (llm_ask(
            question, sources,
            system=_chat_system(_display(peer), _display(current_user)),
            force=True) or '').strip()
        if not answer or 'LLM 服务已禁用' in answer:
            answer = _CHAT_DISABLED_HINT
        return _finalize(_make_message(peer, answer, 'bot', source, ask_msg_id))
    except Exception as e:
        app.logger.warning('chat bot answer failed: %s', e)
        m = _make_message(peer, f'大模型代答失败：{e}', 'bot', source, ask_msg_id)
        db.session.add(m)
        return m, links


def _rows_from_links(links):
    """把 source links 转成前端可渲染的答案行列表。"""
    return [{'type': l.get('tag') or '', 'tag': l.get('tag') or '',
             'title': l.get('title') or '', 'desc': '',
             'href': l.get('href') or '#'} for l in (links or [])]


def _first_pending_task(uid, keyword):
    """按标题/描述模糊匹配第一条未完成任务(用于「完成X」提问)。"""
    pat = f'%{(keyword or "").strip()}%'
    if not keyword or not pat.strip('%'):
        return None
    return TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == uid,
        TaskAssignment.status.notin_(['done', 'abandoned']),
        db.or_(Task.title.like(pat), Task.description.like(pat)),
    ).order_by(Task.end_time.asc()).first()


def _answer_natural(question, target=None):
    """规则意图分类 + 时间解析 → 结构化回答(不写库)。

    target=None 表示小知助手(查询本人数据); target 为私聊对象时,
    检索/问答基于对方资料。返回 dict: intent/content/rows/links/meta。
    """
    from kb.knowledge import KB_LLM_DISABLED, llm_ask
    from routes.search import _unified_search_data

    cls = classify_question(question)
    intent = cls['intent']
    content = cls['content']
    ts = cls['time']
    rows, links, meta = [], [], {'time': ts}
    me_name = _display(current_user)
    peer_name = _display(target) if target else ''
    scope_name = peer_name or me_name
    scope_id = target.id if target else current_user.id

    def _row(tag, title, desc, href):
        rows.append({'type': tag or '', 'tag': tag or '', 'title': title or '',
                     'desc': (desc or '')[:160], 'href': href or '#'})
        return rows[-1]

    if intent == 'greeting':
        return {'intent': intent,
                'content': '你好！我是小知。可以问我「今天有什么任务」「搜一下报销流程」'
                           '「XX 是什么意思」，也可以直接说「添加待办 / 随手记 / 上传」创建内容。',
                'rows': [], 'links': [], 'meta': meta}
    if intent == 'help':
        return {'intent': intent,
                'content': '你可以在任意对话里直接提问，我会自动理解意图：\n'
                           '· 日程查询：今天 / 明天 / 本周有什么任务？几点开会？\n'
                           '· 全站检索：搜一下「报销流程」\n'
                           '· 知识问答：XX 是什么意思？怎么做？\n'
                           '· 快速创建：添加待办「明天 9:00 交周报」/ 随手记「…」\n'
                           '· 教育娱乐 / 上传知识',
                'rows': [], 'links': [], 'meta': meta}
    if intent in ACTION_INTENTS:
        hint = {
            'task_create': f'好的 {me_name}，正在为你打开「快速创建待办」，说出内容即可自动解析时间与分配。',
            'note_create': '已在为你打开「随手记」，内容会自动带过去。',
            'education': '已为你切换到教育娱乐。',
            'upload': '已为你打开「上传知识」。',
        }[intent]
        return {'intent': intent, 'content': hint,
                'rows': [], 'links': [], 'meta': {'action': intent}}

    if intent == 'task_done':
        import re as _re
        dm = _re.match(r'^(?:完成|搞定|做完了|标记完成)[\s:：]?(?:「|《|")?'
                       r'(?P<what>[^，。！？!?、\n]{1,30})', content)
        what = dm.group('what') if dm else content
        a = _first_pending_task(scope_id, what)
        if a is None:
            return {'intent': intent,
                    'content': f'没有找到标题或描述含「{what}」的未完成任务。',
                    'rows': [], 'links': [], 'meta': meta}
        t = a.task
        when = t.end_time.strftime('%Y-%m-%d %H:%M') if t.end_time else '未定'
        _row('待办', t.title,
             f'截止 {when} · {t.category} · 状态 {a.status or "pending"}',
             url_for('user_tasks') + '?highlight=' + str(t.id))
        return {'intent': intent,
                'content': f'找到待办「{t.title or ""}」（截止 {when}）。'
                           f'需要我帮你在待办页完成它吗？',
                'rows': rows, 'links': [], 'meta': meta}

    if intent == 'schedule':
        span = ts or parse_question_time('今天')
        label = (span.get('label') or span.get('range_label')) or '今天'
        assigns = TaskAssignment.query.join(Task).filter(
            TaskAssignment.user_id == scope_id,
            TaskAssignment.status.notin_(['done', 'abandoned']),
            Task.end_time >= span['start'],
            Task.end_time < span['end'],
        ).order_by(Task.end_time.asc()).limit(8).all()
        if not assigns:
            return {'intent': intent,
                    'content': f'{scope_name} 在{label}暂时没有待办 / 日程安排。',
                    'rows': [], 'links': [], 'meta': {'time': span}}
        lines = []
        for a in assigns[:8]:
            t = a.task
            when = t.end_time.strftime('%m-%d %H:%M') if t.end_time else '未定'
            status = '' if a.status == 'pending' else f'（{a.status}）'
            lines.append(f'· {t.title or "未命名任务"} — 截止 {when}{status}')
            _row('待办', t.title, f'截止 {when} · {t.category}',
                 url_for('user_tasks') + '?highlight=' + str(t.id))
        return {'intent': intent,
                'content': f'📅 {scope_name} 在{label}的日程安排：\n' + '\n'.join(lines),
                'rows': rows, 'links': [], 'meta': {'time': span}}

    # 其余意图(search / knowledge / chat): 资料检索 + 大模型整理
    if target is not None:
        sources, links = _build_target_sources(question, target)
        if not sources:
            return {'intent': intent,
                    'content': f'{peer_name} 目前没有可用的非个人待办 / 笔记 / 公开知识资料来回答这个问题。',
                    'rows': [], 'links': [], 'meta': meta}
        if KB_LLM_DISABLED:
            bullet = '\n'.join(f'· [{s.get("title") or ""}]' for s in sources[:8])
            return {'intent': intent,
                    'content': f'已找到 {len(sources)} 条相关线索：\n{bullet}\n'
                               '（大模型服务未启用，以上为资料列表，可点开下方链接查看）',
                    'rows': _rows_from_links(links), 'links': links, 'meta': meta}
        answer = ''
        try:
            answer = (llm_ask(question, sources,
                              system=_chat_system(peer_name, me_name),
                              force=True) or '').strip()
        except Exception as e:
            app.logger.warning('chat nl peer llm failed: %s', e)
        if not answer or 'LLM 服务已禁用' in answer:
            answer = '检索到一些资料，但大模型整理失败，请查看下方链接。'
        return {'intent': intent, 'content': answer,
                'rows': _rows_from_links(links), 'links': links, 'meta': meta}

    # 小知: 本人统一检索(待办+随手记+知识库) → 大模型精炼
    hits = _unified_search_data(question)
    kb, tasks, notes = (hits.get('kb') or []), (hits.get('tasks') or []), (hits.get('notes') or [])
    sources, links = [], []

    def _add_src(title, text, href, tag):
        text = (text or '').strip() or (title or '').strip()
        if not text:
            return
        sources.append({'title': title or '', 'page': '', 'text': text[:500]})
        links.append({'title': title or '', 'href': href or '#', 'tag': tag})
        _row(tag, title, text[:140], href)

    for it in kb[:3]:
        p = (it.get('pages') or [{}])[0]
        _add_src(f"[知识库] {it.get('title') or it.get('filename') or ''}",
                 p.get('snippet') or '',
                 it.get('detail_url') or it.get('preview_url') or '#', '知识库')
    for t in tasks[:3]:
        note = '；'.join(x for x in [
            ('状态 ' + str(t.get('status') or '')),
            ('截止 ' + str(t.get('end_time') or ''))] if x)
        _add_src(f"[待办] {t.get('title') or ''}",
                 (t.get('description') or '') + (('（' + note + '）') if note else ''),
                 t.get('detail_url') or '#', '待办')
    for n in notes[:3]:
        _add_src(f"[随记] {n.get('title') or ''}", n.get('content') or '',
                 n.get('detail_url') or '#', '随记')
    if not sources:
        return {'intent': intent,
                'content': '没有在知识库 · 待办 · 随手记中检索到相关内容，换个问法试试？',
                'rows': [], 'links': [], 'meta': meta}
    if KB_LLM_DISABLED:
        bullet = '\n'.join(f'· {s.get("title") or ""}' for s in sources[:8])
        return {'intent': intent,
                'content': f'共找到 {len(sources)} 条相关内容：\n{bullet}',
                'rows': rows, 'links': links, 'meta': meta}
    answer = ''
    try:
        answer = (llm_ask(question, sources, system=_ASK_SYSTEM_NL,
                          force=True) or '').strip()
    except Exception as e:
        app.logger.warning('chat nl llm failed: %s', e)
    if not answer or 'LLM 服务已禁用' in answer:
        bullet = '\n'.join(f'· {s.get("title") or ""}' for s in sources[:8])
        answer = f'已找到 {len(sources)} 条相关内容：\n{bullet}'
    return {'intent': intent, 'content': answer,
            'rows': rows, 'links': links, 'meta': meta}


@app.route('/api/chat/nl', methods=['POST'])
@login_required
def api_chat_nl():
    """自然语言提问(所有会话通用): 规则意图分类 + 时间解析 → 结构化回答。

    to_user_id 存在时, 同时把提问与回答落库为该会话的 ask/intent 消息。"""
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'ok': False, 'error': '问题不能为空'}), 400
    if len(question) > 2000:
        return jsonify({'ok': False, 'error': '问题过长'}), 400
    tid = int(data.get('to_user_id') or 0)
    peer = _target_user(tid) if tid else None
    res = _answer_natural(question, peer)
    ask_payload = bot_payload = None
    if peer is not None:
        reply_to_id = data.get('reply_to_id') or None
        if reply_to_id:
            cid = _conv_key(current_user.id, peer.id)
            prev = db.session.get(ChatMessage, int(reply_to_id))
            if prev is None or prev.conversation_id != cid:
                reply_to_id = None
        ask = _make_message(peer, question, 'user', 'ask', reply_to_id)
        db.session.flush()
        bot = _make_message(peer, res.get('content') or '', 'bot',
                            'intent', ask.id)
        bot.extra = json.dumps({'links': res.get('links') or []},
                               ensure_ascii=False)
        db.session.commit()
        _notify_new(peer, f'{_display(current_user)} 向你提问：「{(question or "")[:60]}」')
        ask_payload = _msg_payload(ask)
        bot_payload = _msg_payload(bot)
    return jsonify({'ok': True, 'intent': res.get('intent'),
                    'content': res.get('content') or '',
                    'rows': res.get('rows') or [], 'links': res.get('links') or [],
                    'meta': res.get('meta') or {}, 'time': res.get('meta', {}).get('time'),
                    'ask': ask_payload, 'bot': bot_payload})


@app.route('/api/chat/tidy', methods=['POST'])
@login_required
def api_chat_tidy():
    """用大模型把一段回答整理得更有条理(悬浮「✨ LLM 整理」标签触发)。"""
    data = request.get_json(silent=True) or {}
    txt = (data.get('text') or '').strip()
    if not txt:
        return jsonify({'ok': False, 'error': '内容为空'}), 400
    if len(txt) > 6000:
        txt = txt[:6000]
    from kb.knowledge import KB_LLM_DISABLED, llm_ask
    if KB_LLM_DISABLED:
        return jsonify({'ok': False, 'error': 'LLM 服务未启用'})
    import re as _re
    cleaned = _re.sub(r'\s*\[资料\s*\d+\]\s*', ' ', txt).strip()
    try:
        answer = (llm_ask(
            '把以下回答整理得更清晰、更有条理，保留要点与数据，去掉 [资料 N] 标注，'
            '直接输出整理后的正文：\n\n' + cleaned,
            [], system='你是内容整理助手，只输出整理后的正文，不要解释、不要客套、不要开头语。',
            force=True) or '').strip()
    except Exception as e:
        app.logger.warning('chat tidy failed: %s', e)
        return jsonify({'ok': False, 'error': str(e)})
    if not answer or 'LLM 服务已禁用' in answer:
        return jsonify({'ok': False, 'error': 'LLM 整理失败'})
    return jsonify({'ok': True, 'answer': answer})


@app.route('/api/chat/ask', methods=['POST'])
@login_required
def api_chat_ask():
    """@提问: 存提问(kind=user/source=ask) + 自动让大模型基于TA资料代答。"""
    data = request.get_json(silent=True) or {}
    peer = _target_user(int(data.get('to_user_id') or 0))
    if peer is None:
        return jsonify({'ok': False, 'error': '对方不可聊'}), 403
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'ok': False, 'error': '问题不能为空'}), 400
    if len(question) > 2000:
        return jsonify({'ok': False, 'error': '问题过长'}), 400
    reply_to_id = data.get('reply_to_id') or None
    ask = _make_message(peer, question, 'user', 'ask', reply_to_id)
    db.session.flush()
    bot, links = _draft_bot_answer(peer, question, ask.id)
    db.session.commit()
    _notify_new(peer, f'{_display(current_user)} @了你并提问：「{(question or "")[:60]}」')
    return jsonify({'ok': True, 'ask': _msg_payload(ask),
                    'bot': _msg_payload(bot),
                    'links': links})


@app.route('/api/chat/reanswer', methods=['POST'])
@login_required
def api_chat_reanswer():
    """对某条消息重新让大模型代答(删除旧 bot 回答后重新生成)。"""
    data = request.get_json(silent=True) or {}
    msg_id = int(data.get('message_id') or 0)
    tgt = db.session.get(ChatMessage, msg_id)
    if tgt is None:
        return jsonify({'ok': False, 'error': '无效的消息'}), 400
    ask = None
    if tgt.kind == 'bot':
        if tgt.reply_to_id:
            ask = db.session.get(ChatMessage, tgt.reply_to_id)
    else:
        ask = tgt
    if ask is None or ask.kind != 'user':
        return jsonify({'ok': False, 'error': '无效的消息'}), 400
    if ask.from_user_id != current_user.id:
        return jsonify({'ok': False, 'error': '只能重新回答自己的提问'}), 403
    key = ask.conversation_id
    peer = db.session.get(User, ask.to_user_id)
    if peer is None:
        return jsonify({'ok': False, 'error': '对方不存在'}), 404
    old = ChatMessage.query.filter(
        ChatMessage.conversation_id == key,
        ChatMessage.kind == 'bot',
        ChatMessage.reply_to_id == ask.id).all()
    for o in old:
        db.session.delete(o)
    db.session.flush()
    bot, links = _draft_bot_answer(peer, ask.content, ask.id)
    db.session.commit()
    return jsonify({'ok': True, 'bot': _msg_payload(bot),
                    'links': links})


@app.route('/api/chat/read', methods=['POST'])
@login_required
def api_chat_read():
    """标记与某用户的会话已读。"""
    data = request.get_json(silent=True) or {}
    uid = int(data.get('uid') or 0)
    key = _conv_key(current_user.id, uid)
    ChatMessage.query.filter(
        ChatMessage.conversation_id == key,
        ChatMessage.to_user_id == current_user.id,
        ChatMessage.is_read == False).update({ChatMessage.is_read: True})  # noqa: E712
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/chat/conversation/delete', methods=['POST'])
@login_required
def api_chat_delete_conversation():
    """删除与某用户的会话(清空双方该对话的聊天记录)。"""
    data = request.get_json(silent=True) or {}
    peer = _target_user(data.get('peer_id') or data.get('uid'))
    if peer is None:
        return jsonify({'ok': False, 'error': '对方不可聊'}), 403
    key = _conv_key(current_user.id, peer.id)
    ChatMessage.query.filter(ChatMessage.conversation_id == key).delete()
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/chat/unread')
@login_required
def api_chat_unread():
    """未读人工消息数(用于悬浮球角标)。"""
    n = ChatMessage.query.filter(
        ChatMessage.to_user_id == current_user.id,
        ChatMessage.kind == 'user',
        ChatMessage.is_read == False).count()  # noqa: E712
    return jsonify({'ok': True, 'count': n})