# -*- coding: utf-8 -*-
"""看板 API 回归(/api/board): 增删改查、完成态、数据校验、跨用户隔离.

测试直连开发库(sqlite:///tasks.db), 用例内创建的数据在 finally 中以
用户维度整体清理(user_id 归属本用例), 不留脏数据.
"""
import secrets

CSRF = {'X-CSRF-Token': 'test-csrf'}  # 与 conftest.make_client 会话内 token 一致


def _mk(prefix='看板回归'):
    return prefix + secrets.token_hex(5)


def _cleanup(tag):
    """按唯一内容前缀清理本用例为用户1创建的看板条目."""
    from app import app, db
    from core.models import BoardItem
    with app.app_context():
        BoardItem.query.filter(
            BoardItem.user_id == 1,
            BoardItem.content.like(tag + '%')).delete()
        db.session.commit()


def test_board_crud_lifecycle(client):
    """创建→列表→标记完成→编辑→删除, 空内容/空白内容被拒."""
    tag = _mk()
    try:
        r = client.post('/api/board', json={'content': ''}, headers=CSRF).get_json()
        assert r and not r['ok'] and '不能为空' in r['error']
        r = client.post('/api/board', json={'content': '   '}, headers=CSRF).get_json()
        assert r and not r['ok']

        r = client.post('/api/board', json={'content': tag + '写好测试报告'},
                        headers=CSRF).get_json()
        assert r and r['ok'], r
        bid = r['item']['id']
        assert r['item']['done'] is False
        assert r['item']['date']  # 'MM-DD HH:MM'

        r = client.get('/api/board').get_json()
        assert r['ok']
        mine = [i for i in r['items'] if i['id'] == bid]
        assert len(mine) == 1 and mine[0]['content'] == tag + '写好测试报告'

        # 标记完成
        r = client.put('/api/board/%d' % bid, json={'done': True},
                       headers=CSRF).get_json()
        assert r['ok'] and r['item']['done'] is True
        # 编辑内容(完成态保留)
        r = client.put('/api/board/%d' % bid, json={'content': tag + '改名'},
                       headers=CSRF).get_json()
        assert r['ok'] and r['item']['content'] == tag + '改名'
        assert r['item']['done'] is True

        # 删除后不可再改
        r = client.delete('/api/board/%d' % bid, headers=CSRF).get_json()
        assert r['ok']
        r = client.put('/api/board/%d' % bid, json={'done': False},
                       headers=CSRF)
        assert r.status_code == 404
    finally:
        _cleanup(tag)


def test_board_finished_first_then_newest(client):
    """未完成在前(新的在前), 已完成统一排后."""
    tag = _mk()
    try:
        a = client.post('/api/board', json={'content': tag + 'a'}, headers=CSRF).get_json()['item']
        b = client.post('/api/board', json={'content': tag + 'b'}, headers=CSRF).get_json()['item']
        client.put('/api/board/%d' % a['id'], json={'done': True}, headers=CSRF).get_json()
        items = [i['content'] for i in client.get('/api/board').get_json()['items']]
        # 只看本条用例创建的, 保持相对顺序即可
        mine = [c for c in items if c.startswith(tag)]
        assert mine == [tag + 'b', tag + 'a'], mine
    finally:
        _cleanup(tag)


def test_board_discard_hides_from_list(client):
    """废弃(discarded)后从列表隐藏, 完成态/内容保留; 可取消废弃恢复显示."""
    tag = _mk()
    try:
        r = client.post('/api/board', json={'content': tag + '废弃我'},
                        headers=CSRF).get_json()
        assert r['ok']
        bid = r['item']['id']
        client.put('/api/board/%d' % bid, json={'done': True}, headers=CSRF).get_json()

        # 废弃后不在默认列表
        r = client.put('/api/board/%d' % bid, json={'discarded': True},
                       headers=CSRF).get_json()
        assert r['ok'] and r['item']['discarded'] is True
        ids = [i['id'] for i in client.get('/api/board').get_json()['items']]
        assert bid not in ids

        # 直接 PUT 仍可更新已废弃条目的内容/完成态
        r = client.put('/api/board/%d' % bid,
                       json={'content': tag + '改过', 'done': False},
                       headers=CSRF).get_json()
        assert r['ok'] and r['item']['content'] == tag + '改过'
        assert r['item']['done'] is False and r['item']['discarded'] is True

        # 取消废弃恢复显示
        r = client.put('/api/board/%d' % bid, json={'discarded': False},
                       headers=CSRF).get_json()
        assert r['ok'] and r['item']['discarded'] is False
        mine = [i for i in client.get('/api/board').get_json()['items']
                if i['id'] == bid]
        assert len(mine) == 1
    finally:
        _cleanup(tag)


def test_board_cross_user_isolated(client):
    """用户1无法读写用户2的看板条目(返回 404)."""
    from app import app, db
    from core.models import BoardItem
    bid = None
    try:
        with app.app_context():
            it = BoardItem(user_id=2, content='用户2的私密条目')
            db.session.add(it)
            db.session.commit()
            bid = it.id
        r = client.put('/api/board/%d' % bid, json={'done': True}, headers=CSRF)
        assert r.status_code == 404
        r = client.delete('/api/board/%d' % bid, headers=CSRF)
        assert r.status_code == 404
        ids = [i['id'] for i in client.get('/api/board').get_json()['items']]
        assert bid not in ids
    finally:
        if bid is not None:
            with app.app_context():
                BoardItem.query.filter_by(id=bid).delete()
                db.session.commit()