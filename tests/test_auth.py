# -*- coding: utf-8 -*-
"""自助注册(邮箱验证, 自动开通账号)流程测试。"""
import re
import pytest

from app import app, db, User


def _csrf(c, path='/register'):
    r = c.get(path)
    m = re.search(r"window\.CSRF_TOKEN = '([^']+)'", r.get_data(as_text=True))
    return m.group(1) if m else 'test-csrf'


def _unique(prefix):
    import uuid
    return f'{prefix}{uuid.uuid4().hex[:8]}'


def _fields(username, email, code='', step='send_code'):
    data = {'username': username, 'name': '测试用户', 'email': email,
            'password': 'secret123', 'step': step}
    if code:
        data['code'] = code
    return data


def _send_code(c, username, email):
    return c.post('/register', data={**_fields(username, email),
                                     '_csrf_token': _csrf(c)}, follow_redirects=True)


def _extract_dev_code(resp):
    m = re.search(r'验证码\(仅开发模式可见\): (\d{6})', resp.get_data(as_text=True))
    assert m, '未找到开发模式验证码'
    return m.group(1)


def _user_count(username, email):
    with app.app_context():
        return User.query.filter(db.or_(User.username == username,
                                        User.email == email)).count()


def _cleanup(username, email):
    with app.app_context():
        u = User.query.filter(db.or_(User.username == username,
                                     User.email == email)).all()
        for x in u:
            db.session.delete(x)
        db.session.commit()


@pytest.fixture()
def no_mail(monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_SERVER', '')
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', '')


def test_self_register_email_verify_auto_approved(no_mail):
    username = _unique('zreg_')
    email = f'{username}@example.com'
    c = app.test_client()
    try:
        r = _send_code(c, username, email)
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert '验证码已发送' in body
        code = _extract_dev_code(r)
        # 第二步: 提交验证码完成注册
        r = c.post('/register', data={**_fields(username, email, code, step='verify'),
                                      '_csrf_token': _csrf(c)}, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            user = User.query.filter_by(username=username).first()
        assert user is not None, '注册后账号应已创建'
        assert user.status == 'approved', '自助注册应自动开通(approved), 无需管理员审批'
        assert user.role == 'user'
        assert user.email == email
        assert user.email_verified is True
    finally:
        _cleanup(username, email)


def test_self_register_login_works(no_mail):
    username = _unique('zlog_')
    email = f'{username}@example.com'
    c = app.test_client()
    try:
        code = _extract_dev_code(_send_code(c, username, email))
        c.post('/register', data={**_fields(username, email, code, step='verify'),
                                  '_csrf_token': _csrf(c)})
        # 用新账号重新登录
        c2 = app.test_client()
        data = {'username': username, 'password': 'secret123',
                '_csrf_token': _csrf(c2, '/login')}
        r = c2.post('/login', data=data, follow_redirects=True)
        assert r.status_code == 200
        assert '注册成功' not in r.get_data(as_text=True)
        assert c2.get('/profile').status_code == 200
    finally:
        _cleanup(username, email)


def test_self_register_wrong_code_does_not_create(no_mail):
    username = _unique('zbad_')
    email = f'{username}@example.com'
    c = app.test_client()
    try:
        _send_code(c, username, email)
        r = c.post('/register', data={**_fields(username, email, '000000', step='verify'),
                                      '_csrf_token': _csrf(c)}, follow_redirects=True)
        assert '验证码不正确' in r.get_data(as_text=True)
        assert _user_count(username, email) == 0
    finally:
        _cleanup(username, email)


def test_self_register_duplicate_username_rejected(no_mail):
    username = _unique('zdup_')
    email = f'{username}@example.com'
    c = app.test_client()
    try:
        code = _extract_dev_code(_send_code(c, username, email))
        c.post('/register', data={**_fields(username, email, code, step='verify'),
                                  '_csrf_token': _csrf(c)})
        # 同用户名, 不同邮箱: 应拒绝
        c2 = app.test_client()
        r = _send_code(c2, username, f'{username}2@example.com')
        assert '该账号已注册' in r.get_data(as_text=True)
    finally:
        _cleanup(username, email)


def test_self_register_duplicate_email_rejected(no_mail):
    username = _unique('zdup2_')
    email = f'{username}@example.com'
    c = app.test_client()
    try:
        code = _extract_dev_code(_send_code(c, username, email))
        c.post('/register', data={**_fields(username, email, code, step='verify'),
                                  '_csrf_token': _csrf(c)})
        # 同邮箱, 不同用户名: 应拒绝
        c2 = app.test_client()
        r = _send_code(c2, f'{username}x', email)
        assert '该邮箱已被注册' in r.get_data(as_text=True)
    finally:
        _cleanup(username, email)


def test_self_register_requires_email_format(no_mail):
    c = app.test_client()
    username = _unique('zfmt_')
    r = c.post('/register', data={**_fields(username, 'not-an-email'),
                                  '_csrf_token': _csrf(c)}, follow_redirects=True)
    assert '邮箱格式不正确' in r.get_data(as_text=True)
    assert _user_count(username, 'not-an-email') == 0