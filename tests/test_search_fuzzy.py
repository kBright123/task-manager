# -*- coding: utf-8 -*-
"""通用化近义匹配: 精确子串未命中时按字符二元组覆盖率兜底召回。

场景: 用户问「青年理论学习小组」, 而待办/笔记/知识库里存的是「青年理论小组」——
整句 LIKE 或 AND 分词都匹配不上, 需要近似匹配兜底。"""
import secrets

from kb.knowledge import (
    _FUZZY_MIN_COVERAGE, KbDocument, KbPage, fuzzy_coverage,
    keyword_search_pages)
from routes.notes import Note
from app import app, db

CSRF = {'X-CSRF-Token': 'test-csrf'}


def test_fuzzy_coverage_metric():
    # 差一词的近义文本: 覆盖率应过阈值
    assert fuzzy_coverage('青年理论学习小组', '青年理论小组') >= _FUZZY_MIN_COVERAGE
    # 完全相同 = 1.0
    assert fuzzy_coverage('青年理论学习小组', '青年理论学习小组') == 1.0
    # 无关文本不误伤
    assert fuzzy_coverage('青年理论学习小组', '下午三点开部门会议') < _FUZZY_MIN_COVERAGE
    assert fuzzy_coverage('', '任意文本') == 0.0


def _mk_task(client):
    title = f'青年理论小组{secrets.token_hex(3)}'
    r = client.post('/api/quick-task', json={
        'title': title, 'start_time': '2026-09-20 09:00',
        'end_time': '2026-09-20 10:00', 'category': '工作',
        'description': '', 'assignee_ids': [1], 'group_ids': [],
        'is_all': False}, headers=CSRF).get_json()
    assert r and r.get('ok'), r
    return title, r.get('task_id')


def test_unified_search_recalls_near_miss_task(client):
    title, tid = _mk_task(client)
    try:
        data = client.get('/api/unified-search?q=青年理论学习小组').get_json()
        titles = [t['title'] for t in data['tasks']]
        assert title in titles, f'近义待办未召回: {titles}'
    finally:
        client.post(f'/api/task/{tid}/delete', headers=CSRF)


def test_unified_search_recalls_near_miss_note(client):
    with app.app_context():
        note = Note(user_id=1, title=f'青年理论小组{secrets.token_hex(3)}',
                    content='青年理论小组会议纪要', version=1, tags='[]', simhash='')
        db.session.add(note)
        db.session.commit()
        nid = note.id
    try:
        data = client.get('/api/unified-search?q=青年理论学习小组').get_json()
        titles = [n['title'] for n in data['notes']]
        assert note.title in titles, f'近义笔记未召回: {titles}'
    finally:
        with app.app_context():
            Note.query.filter_by(id=nid).delete()
            db.session.commit()


def test_keyword_pages_recalls_near_miss_kb(client):
    with app.app_context():
        suffix = secrets.token_hex(3)
        doc = KbDocument(title=f'青年理论小组{suffix}', filename=f'f{suffix}.txt',
                         file_path=f'/tmp/f{suffix}.txt', status='done')
        db.session.add(doc)
        db.session.flush()
        db.session.add(KbPage(doc_id=doc.id, page_no=1,
                              text='青年理论小组本季度组织安排'))
        db.session.commit()
        doc_id = doc.id
        doc_title = doc.title
    try:
        res = keyword_search_pages('青年理论学习小组', k=10)
        ids = [r['doc_id'] for r in res]
        assert doc_id in ids, f'近义知识页未召回: {ids}'
    finally:
        with app.app_context():
            KbPage.query.filter_by(doc_id=doc_id).delete()
            KbDocument.query.filter_by(id=doc_id).delete()
            db.session.commit()