# -*- coding: utf-8 -*-
"""页面渲染与关键交互标记回归(收编自 verify_fixes.py)."""
import re


def _get(client, url):
    r = client.get(url)
    assert r.status_code == 200, f'{url} -> {r.status_code}'
    return r.get_data(as_text=True)


def test_dashboard_basic(client):
    d = _get(client, '/user/dashboard')
    assert 'id="calGrid"' in d
    assert 'dashTimeline' in d
    # 一屏纯CSS布局(扣除固定导航高度, 否则容器底部被视口裁切)
    assert 'calc(100dvh - var(--nav-height))' in d
    # 日历悬浮框已移除
    assert 'calTooltipTitle' not in d
    assert 'onmouseenter="calShowTooltip' not in d
    # 废弃 dashFit 已清除
    assert 'dashFit' not in d


def test_tasks_timeline_title_only(client):
    d = _get(client, '/user/tasks')
    assert 'tl-card-desc' not in d
    assert 'tlToggleDesc' not in d


def test_dark_mode_wiring(client):
    css = client.get('/static/css/app.css').get_data(as_text=True)
    assert '[data-theme="dark"] {' in css
    assert css.count('{') == css.count('}'), 'CSS 花括号不配平'
    for url in ('/user/dashboard', '/user/tasks'):
        d = _get(client, url)
        assert 'themeToggle' in d and "localStorage.getItem('kb_theme')" in d


def test_preview_legacy_banner_template():
    src = open('templates/tasks.html').read()
    assert "preview.time_parser == 'legacy'" in src


def test_notifications_page(client):
    d = _get(client, '/notifications')
    assert 'list-group-item' in d or '暂无通知' in d


CSRF = {'X-CSRF-Token': 'test-csrf'}


def _mk(client, prefix='接口回归'):
    import secrets
    title = f'{prefix}{secrets.token_hex(5)}'
    r = client.post('/api/quick-task', json={
        'title': title, 'start_time': '2026-08-24 09:00',
        'end_time': '2026-08-24 10:00', 'category': '工作',
        'description': '', 'assignee_ids': [1], 'group_ids': [],
        'is_all': False}, headers=CSRF).get_json()
    assert r and r.get('ok'), r
    tid = r.get('task_id') or r.get('id')
    assert tid
    return tid


def test_task_times_api(client):
    tid = _mk(client)
    r = client.post(f'/api/task/{tid}/times',
                    json={'start_time': '2026-08-25T10:30', 'end_time': ''},
                    headers=CSRF).get_json()
    assert r['ok'] and r['start_display'] == '08-25 10:30'
    r2 = client.post(f'/api/task/{tid}/times', json={'start_time': 'bad'},
                     headers=CSRF)
    assert r2.status_code == 400
    assert client.delete(f'/api/task/{tid}', headers=CSRF).status_code in (404, 405)
    assert client.post(f'/api/task/{tid}/delete', headers=CSRF).get_json()['ok']
