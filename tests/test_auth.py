# -*- coding: utf-8 -*-
"""自助注册流程测试: 直接注册、默认禁用、管理员启用后可登录。"""
import uuid

from app import app, db, User

CSRF = {'X-CSRF-Token': 'test-csrf'}


def _unique(prefix):
    return f'{prefix}{uuid.uuid4().hex[:8]}'


def _anon_client():
    c = app.test_client()
    with c.session_transaction() as s:
        s['_csrf_token'] = 'test-csrf'
    return c


def _fields(username, password='secret123'):
    return {'username': username, 'name': '测试用户', 'password': password,
            '_csrf_token': 'test-csrf'}


def _register(c, username, password='secret123'):
    return c.post('/register', data=_fields(username, password),
                  follow_redirects=True)


def _get_user(username):
    with app.app_context():
        return User.query.filter_by(username=username).first()


def _cleanup(username):
    with app.app_context():
        User.query.filter_by(username=username).delete()
        db.session.commit()


def test_register_creates_disabled_user():
    """注册即创建账号; 默认禁用, 等待管理员启用."""
    username = _unique('zreg_')
    c = _anon_client()
    try:
        r = _register(c, username)
        assert r.status_code == 200
        assert '注册成功' in r.get_data(as_text=True)
        user = _get_user(username)
        assert user is not None, '注册后账号应已创建'
        assert user.status == 'approved'
        assert user.is_disabled is True, '新注册用户默认禁用'
        assert user.role == 'user'
    finally:
        _cleanup(username)


def test_disabled_user_cannot_login():
    username = _unique('zdis_')
    c = _anon_client()
    try:
        _register(c, username)
        c2 = _anon_client()
        r = c2.post('/login', data={'username': username,
                                    'password': 'secret123',
                                    '_csrf_token': 'test-csrf'},
                    follow_redirects=True)
        body = r.get_data(as_text=True)
        assert '尚未启用' in body or '已被禁用' in body
        assert c2.get('/profile').status_code != 200
    finally:
        _cleanup(username)


def test_admin_enable_then_login(client):
    username = _unique('zen_')
    c = _anon_client()
    try:
        _register(c, username)
        user = _get_user(username)
        assert user.is_disabled is True

        # 管理员在后台点击「已禁用」切换为启用
        r = client.post(f'/admin/users/disable/{user.id}', headers=CSRF)
        assert r.status_code in (302, 200)
        with app.app_context():
            user = User.query.filter_by(username=username).first()
            assert user.is_disabled is False

        c2 = _anon_client()
        r = c2.post('/login', data={'username': username,
                                    'password': 'secret123',
                                    '_csrf_token': 'test-csrf'},
                    follow_redirects=True)
        assert '登录成功' in r.get_data(as_text=True)
        assert c2.get('/profile').status_code == 200
    finally:
        _cleanup(username)


def test_register_duplicate_username_rejected():
    username = _unique('zdup_')
    c = _anon_client()
    try:
        _register(c, username)
        r = _register(_anon_client(), username)
        assert '该账号已注册' in r.get_data(as_text=True)
        with app.app_context():
            assert User.query.filter_by(username=username).count() == 1
    finally:
        _cleanup(username)


def test_register_password_too_short_rejected():
    username = _unique('zpwd_')
    c = _anon_client()
    try:
        r = _register(c, username, password='123')
        assert '密码长度至少 6 位' in r.get_data(as_text=True)
        assert _get_user(username) is None
    finally:
        _cleanup(username)
