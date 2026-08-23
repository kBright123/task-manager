# -*- coding: utf-8 -*-
"""pytest 共享夹具: 构建已登录测试客户端(无外部依赖时也可被 run_tests.py 直接导入)."""
import os
import sys

os.environ.setdefault('KB_VECTOR_DISABLED', '1')
os.environ.setdefault('KB_LLM_DISABLED', '1')
os.environ.setdefault('KB_CLASSIFIER_ENABLED', '0')
os.environ.setdefault('KB_AUTOPIP', '0')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest  # noqa: E402
except ImportError:  # 零依赖运行(run_tests.py)时无 pytest
    pytest = None

if pytest is not None:
    @pytest.fixture()
    def client():
        from app import app
        app.config['TESTING'] = True
        c = app.test_client()
        with c.session_transaction() as s:
            s['_user_id'] = '1'
            s['_fresh'] = True
        return c


def make_client():
    from app import app
    app.config['TESTING'] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s['_user_id'] = '1'
        s['_fresh'] = True
        s['_csrf_token'] = 'test-csrf'
    return c
