# -*- coding: utf-8 -*-
"""通用化近义匹配: 精确子串未命中时按字形覆盖率(单字+二元组)与同义词兜底召回。

场景A(差一两个字): 问「青年理论学习小组」, 库内「青年理论小组」——整句 LIKE
或 AND 分词匹配不上, 靠近似召回。
场景B(部分关键词): 问「青年学习」, 库内「青年理论学习小组」——中间缺字,
单字全覆盖 + 二元组半覆盖仍能召回。
场景C(同义词): 问「开会」, 库内「例会记录」——字符完全不重叠, 命中同义词组召回。"""
import secrets

from kb.knowledge import (
    _FUZZY_MIN_COVERAGE, KbDocument, KbPage, fuzzy_coverage,
    fuzzy_coverage_syn, keyword_search_pages)
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


def test_fuzzy_partial_keyword():
    # 部分关键词(中间缺字): 问「青年学习」仍能命中「青年理论学习小组」
    assert fuzzy_coverage('青年学习', '青年理论学习小组') >= _FUZZY_MIN_COVERAGE
    assert fuzzy_coverage('青年学习', '外出拜访客户') < _FUZZY_MIN_COVERAGE


def test_fuzzy_synonym_hit():
    # 同义词: 字符完全不重叠, 靠同义词组命中
    assert fuzzy_coverage_syn('开会', '会议记录安排') >= _FUZZY_MIN_COVERAGE
    assert fuzzy_coverage_syn('例会时间', '周会通知') >= _FUZZY_MIN_COVERAGE
    # 无关文本即使含「会」也不误伤
    assert fuzzy_coverage_syn('开会', '周一采购清单') < _FUZZY_MIN_COVERAGE


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


def test_unified_search_recalls_synonym_task(client):
    title = f'周例会材料准备{secrets.token_hex(3)}'
    r = client.post('/api/quick-task', json={
        'title': title, 'start_time': '2026-09-20 09:00',
        'end_time': '2026-09-20 10:00', 'category': '工作',
        'description': '', 'assignee_ids': [1], 'group_ids': [],
        'is_all': False}, headers=CSRF).get_json()
    assert r and r.get('ok'), r
    tid = r.get('task_id')
    try:
        # 同义问法: 「会议材料」vs 待办「周例会材料准备」字符几乎不重叠
        data = client.get('/api/unified-search?q=会议材料').get_json()
        titles = [t['title'] for t in data['tasks']]
        assert title in titles, f'同义待办未召回: {titles}'
    finally:
        client.post(f'/api/task/{tid}/delete', headers=CSRF)


def test_unified_search_recalls_synonym_note(client):
    with app.app_context():
        note = Note(user_id=1, title=f'周例会材料准备{secrets.token_hex(3)}',
                    content='周例会材料准备完毕', version=1, tags='[]', simhash='')
        db.session.add(note)
        db.session.commit()
        nid, ntitle = note.id, note.title
    try:
        data = client.get('/api/unified-search?q=会议材料').get_json()
        titles = [n['title'] for n in data['notes']]
        assert ntitle in titles, f'同义笔记未召回: {titles}'
    finally:
        with app.app_context():
            Note.query.filter_by(id=nid).delete()
            db.session.commit()


def test_unified_search_recalls_partial_keyword_note(client):
    with app.app_context():
        note = Note(user_id=1, title='青年理论学习小组活动安排',
                    content='青年理论学习小组本周活动', version=1,
                    tags='[]', simhash='')
        db.session.add(note)
        db.session.commit()
        nid = note.id
    try:
        data = client.get('/api/unified-search?q=青年学习').get_json()
        titles = [n['title'] for n in data['notes']]
        assert '青年理论学习小组活动安排' in titles, \
            f'部分关键词笔记未召回: {titles}'
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