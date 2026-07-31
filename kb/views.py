import os
import uuid
from datetime import datetime

from flask import (Blueprint, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from . import llm, store
from .config import (ALLOWED_EXTENSIONS, KB_ASK_GRAPH_DEPTH, KB_ASK_TOP_K,
                     STATUS_QUEUED)
from .models import KbDocument, KbEntity, KbPage, KbTriple, db

kb_bp = Blueprint('kb', __name__, url_prefix='/kb')


def _kb_upload_dir():
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'kb')
    os.makedirs(path, exist_ok=True)
    return path


@kb_bp.route('/')
@login_required
def index():
    docs = (KbDocument.query.order_by(KbDocument.created_at.desc())
            .limit(200).all())
    total_pages = db.session.query(db.func.sum(KbPage.char_count)).scalar() or 0
    triple_count = KbTriple.query.count()
    entity_count = KbEntity.query.count()
    return render_template('kb/index.html', docs=docs,
                           total_pages=total_pages, triple_count=triple_count,
                           entity_count=entity_count,
                           status_queued=STATUS_QUEUED)


@kb_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        flash('未选择文件', 'danger')
        return redirect(url_for('kb.index'))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        flash(f'不支持的文件类型 {ext}(支持: PDF/图片)', 'danger')
        return redirect(url_for('kb.index'))
    store_name = uuid.uuid4().hex + ext
    target = os.path.join(_kb_upload_dir(), store_name)
    f.save(target)
    title = os.path.splitext(f.filename)[0] or '未命名文档'
    doc = KbDocument(title=title, filename=f.filename, file_path=target,
                     file_type=ext.lstrip('.'), file_size=os.path.getsize(target),
                     status=STATUS_QUEUED, uploaded_by=current_user.id)
    db.session.add(doc)
    db.session.commit()
    flash(f'已加入识别队列: {title}', 'success')
    return redirect(url_for('kb.doc_detail', doc_id=doc.id))


@kb_bp.route('/<int:doc_id>')
@login_required
def doc_detail(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        flash('文档不存在', 'danger')
        return redirect(url_for('kb.index'))
    pages = (KbPage.query.filter_by(doc_id=doc.id)
             .order_by(KbPage.page_no).all())
    triples = (KbTriple.query.filter_by(doc_id=doc.id)
               .order_by(KbTriple.id).all())
    entities = (KbEntity.query.filter_by(doc_id=doc.id)
                .order_by(KbEntity.id).all())
    return render_template('kb/doc_detail.html', doc=doc, pages=pages,
                           triples=triples, entities=entities)


@kb_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def doc_delete(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if doc:
        prior = [{'head': t.head, 'rel': t.rel, 'tail': t.tail,
                  'headType': t.head_type, 'tailType': t.tail_type}
                 for t in doc.triples]
        try:
            store.delete_doc_graph(doc.id, prior)
        except Exception:
            pass
        for p in doc.pages:
            store.delete_page(doc.id, p.page_no)
        if os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except OSError:
                pass
        db.session.delete(doc)
        db.session.commit()
        flash('文档已删除', 'success')
    return redirect(url_for('kb.index'))


@kb_bp.route('/<int:doc_id>/reprocess', methods=['POST'])
@login_required
def doc_reprocess(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if doc:
        doc.status = STATUS_QUEUED
        doc.error = None
        doc.updated_at = datetime.utcnow()
        db.session.commit()
        flash('已重新加入识别队列', 'info')
    return redirect(url_for('kb.doc_detail', doc_id=doc_id))


@kb_bp.route('/search')
@login_required
def search():
    q = (request.args.get('q') or '').strip()
    results = []
    triples = []
    if q:
        try:
            results = store.search_pages(q, k=20, alpha=0.5)
        except Exception as e:
            flash(f'搜索失败: {e}', 'danger')
        doc_ids = {r['doc_id'] for r in results[:8]}
        if doc_ids:
            triples, _ = store.graph_context(doc_ids, KB_ASK_GRAPH_DEPTH)
    return render_template('kb/search.html', q=q, results=results,
                           triples=triples)


@kb_bp.route('/ask', methods=['GET', 'POST'])
@login_required
def ask():
    question = ''
    answer = ''
    sources = []
    triples = []
    error = None
    if request.method == 'POST':
        question = (request.form.get('question') or '').strip()
        if not question:
            error = '请输入问题'
        else:
            try:
                hits = store.search_pages(question, k=KB_ASK_TOP_K, alpha=0.5)
                doc_ids = {r['doc_id'] for r in hits[:6]}
                triples, _ = store.graph_context(doc_ids, KB_ASK_GRAPH_DEPTH)
                sources = [{'title': h['title'], 'page': h['page_no'],
                            'text': h['text']} for h in hits]
                answer = llm.ask(question, sources)
            except Exception as e:
                error = f'问答失败: {e}'
    return render_template('kb/ask.html', question=question, answer=answer,
                           sources=sources, triples=triples, error=error)


@kb_bp.route('/status/<int:doc_id>')
@login_required
def status(doc_id):
    doc = db.session.get(KbDocument, doc_id)
    if not doc:
        return jsonify({'ok': False})
    return jsonify({'ok': True, 'status': doc.status, 'error': doc.error,
                    'page_count': doc.page_count})
