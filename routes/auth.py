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
"""auth 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import (app, login_required, User, client_ip, cn_now,
                 db, log_operation)

from flask import (flash, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_user, logout_user
from services import llm as llm_svc
import secrets
from datetime import timedelta
import re

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('user_dashboard'))
    return redirect(url_for('login'))


MAX_LOGIN_FAILS = 5
LOGIN_LOCK_MINUTES = 10
UNLOCK_CODE_TTL_MINUTES = 10

# --- 轻量 IP 限速(内存滑动窗口): 与按账号锁定互补, 防脚本高频撞库 ---
import threading
import time as _time_mod
from collections import deque as _deque

_ip_attempts = {}
_ip_lock = threading.Lock()


def _ip_rate_limited(key, limit=10, window=60):
    """滑动窗口限速: 同一 key(window 秒内)超过 limit 次返回 True。"""
    if app.config.get('TESTING'):
        return False
    now = _time_mod.time()
    with _ip_lock:
        dq = _ip_attempts.setdefault(key, _deque())
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        if len(_ip_attempts) > 10000:  # 防字典无限增长: 清理过期/空桶
            for k in [k for k, v in _ip_attempts.items() if not v]:
                _ip_attempts.pop(k, None)
            for k in [k for k, v in _ip_attempts.items()
                      if v and now - v[-1] > window * 2]:
                _ip_attempts.pop(k, None)
        return False


def _client_key():
    """限速键: 优先真实远端地址, 避免伪造 X-Forwarded-For 自刷。"""
    return request.remote_addr or request.headers.get(
        'X-Forwarded-For', '').split(',')[0].strip() or 'unknown'


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    ctx = {'username': ''}
    if request.method == 'POST':
        if _ip_rate_limited('login:' + _client_key(), limit=10, window=60):
            flash('尝试过于频繁，请 1 分钟后再试', 'warning')
            return render_template('login.html', **ctx)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        ctx['username'] = username
        user = User.query.filter_by(username=username).first()
        now = cn_now()
        if user and user.locked_until and user.locked_until > now:
            wait_min = int((user.locked_until - now).total_seconds() // 60) + 1
            log_operation('login_fail', username, '账号锁定中')
            db.session.commit()
            flash(f'密码错误次数过多，账号已锁定，请在 {wait_min} 分钟后再试', 'warning')
            return render_template('login.html', **ctx)
        if user and user.check_password(password):
            if user.status == 'pending':
                log_operation('login_fail', username, '账号待审批')
                db.session.commit()
                flash('该账号正在等待管理员审批，审批通过后方可登录', 'warning')
                return render_template('login.html', **ctx)
            if user.status == 'rejected':
                log_operation('login_fail', username, '注册申请被拒绝')
                db.session.commit()
                flash('该账号的注册申请已被拒绝，请联系管理员', 'danger')
                return render_template('login.html', **ctx)
            if user.is_disabled:
                log_operation('login_fail', username, '账号已禁用')
                db.session.commit()
                flash('该账号尚未启用或已被禁用，请联系管理员启用', 'danger')
                return render_template('login.html', **ctx)
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login = cn_now()
            user.last_seen = cn_now()
            login_user(user)
            session.permanent = True  # 会话会自动过期退出登录(见 PERMANENT_SESSION_LIFETIME)
            db.session.commit()
            flash('登录成功！', 'success')
            next_page = request.args.get('next')
            if next_page:
                from urllib.parse import urlsplit
                parts = urlsplit(next_page)
                if (next_page.startswith('/') and not next_page.startswith('//')
                        and not next_page.startswith('/\\') and not parts.netloc
                        and '\n' not in next_page and '\r' not in next_page):
                    return redirect(next_page)
            return redirect(url_for('index'))
        if not user:
            log_operation('login_fail', username, '用户不存在')
            db.session.commit()
            flash('用户名或密码错误！', 'danger')
            return render_template('login.html', **ctx)
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_LOGIN_FAILS:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            db.session.commit()
            log_operation('login_fail', username,
                          f'连续密码错误，锁定 {LOGIN_LOCK_MINUTES} 分钟')
            db.session.commit()
            flash(f'密码错误 {MAX_LOGIN_FAILS} 次，账号已锁定 {LOGIN_LOCK_MINUTES} 分钟。请稍后再试或联系管理员', 'warning')
            return render_template('login.html', **ctx)
        remaining = MAX_LOGIN_FAILS - user.failed_login_count
        log_operation('login_fail', username, '用户名或密码错误')
        db.session.commit()
        flash(f'用户名或密码错误！剩余尝试次数 {remaining} 次', 'danger')
        return render_template('login.html', **ctx)
    return render_template('login.html', **ctx)


# --- 自助注册: 直接注册, 账号默认禁用, 需管理员在后台启用后才能登录 ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    username = (request.form.get('username') or '').strip()
    name = (request.form.get('name') or '').strip()
    password = request.form.get('password', '')
    errs = []

    if request.method == 'POST':
        if _ip_rate_limited('register:' + _client_key(), limit=6, window=600):
            flash('注册过于频繁，请 10 分钟后再试', 'warning')
            return render_template('register.html', username=username, name=name)
        if not username or not name:
            errs.append('用户名和昵称不能为空')
        if len(username) < 2 or len(username) > 80:
            errs.append('用户名长度需在 2-80 个字符之间')
        if not re.match(r'^[A-Za-z0-9_.@-]+$', username):
            errs.append('用户名仅支持字母、数字、下划线、点、@ 与中横线')
        if len(name) > 80:
            errs.append('昵称不能超过 80 个字符')
        if len(password) < 6:
            errs.append('密码长度至少 6 位')
        if not errs and User.query.filter_by(username=username).first():
            errs.append('该账号已注册，请直接登录')
        if errs:
            flash('；'.join(errs), 'danger')
            return render_template('register.html', username=username, name=name)

        user = User(username=username, name=name, role='user',
                    status='approved', is_disabled=True,
                    registration_ip=client_ip())
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_operation('register', username,
                      f'新用户 {name or username} 注册成功(默认禁用, 待管理员启用)')
        flash('注册成功，账号已提交。请等待管理员启用后再登录。', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', username=username, name=name)


@app.route('/logout')
@login_required
def logout():
    session.pop('api_token_raw', None)
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))


@app.route('/profile', methods=['GET'])
@login_required
def profile():
    """个人信息页:展示账号信息、密码修改与日历订阅。"""
    return render_template('profile.html')


@app.route('/profile/llm-config', methods=['POST'])
@login_required
def profile_llm_save():
    """保存个人大模型配置; 留空项跟随管理员默认。"""
    existing = llm_svc.get_user_config(current_user)
    new_key = request.form.get('api_key', '').strip()
    if not new_key and request.form.get('clear_key') != '1' \
            and existing.get('api_key'):
        new_key = existing['api_key']
    llm_svc.save_user_config(current_user, {
        'api_key': new_key,
        'base_url': request.form.get('base_url', ''),
        'model': request.form.get('model', ''),
    })
    flash('大模型个人设置已保存', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/llm-config/clear', methods=['POST'])
@login_required
def profile_llm_clear():
    """清除个人大模型配置, 恢复跟随管理员默认。"""
    llm_svc.save_user_config(current_user, {
        'api_key': '', 'base_url': '', 'model': '',
    })
    flash('已恢复跟随管理员默认配置', 'success')
    return redirect(url_for('profile'))


@app.route('/api/token', methods=['POST'])
def api_token():
    """第三方 API 令牌获取: 使用用户名/密码换取 API Token。
    返回 {ok, token, user}; 之后通过 Authorization: Bearer <token> 访问接口。"""
    data = request.get_json(silent=True) or request.form
    if _ip_rate_limited('token:' + _client_key(), limit=10, window=60):
        return jsonify({'ok': False, 'error': '请求过于频繁,请稍后再试'}), 429
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'ok': False, 'error': '缺少用户名或密码'}), 400
    user = User.query.filter_by(username=username).first()
    now = cn_now()
    if user and user.locked_until and user.locked_until > now:
        log_operation('api_token_fail', username, '账号锁定中,拒绝发放令牌')
        db.session.commit()
        return jsonify({'ok': False, 'error': '账号已锁定,请稍后再试'}), 403
    if not (user and user.check_password(password)):
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= MAX_LOGIN_FAILS:
                user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            db.session.commit()
        log_operation('api_token_fail', username, '用户名或密码错误')
        db.session.commit()
        return jsonify({'ok': False, 'error': '用户名或密码错误'}), 401
    if user.status != 'approved':
        log_operation('api_token_fail', username, f'账号状态 {user.status},拒绝发放令牌')
        db.session.commit()
        return jsonify({'ok': False, 'error': '账号不可用,请联系管理员'}), 403
    if user.is_disabled:
        log_operation('api_token_fail', username, '账号已禁用,拒绝发放令牌')
        db.session.commit()
        return jsonify({'ok': False, 'error': '账号已被禁用'}), 403
    user.failed_login_count = 0
    user.locked_until = None
    cached = session.get('api_token_raw')
    if cached and user.api_token:
        # 会话内已签发过: 原样返回, 避免重复请求把令牌轮换掉
        db.session.commit()
        return jsonify({
            'ok': True,
            'token': cached,
            'user': {'id': user.id, 'username': user.username,
                     'name': user.name, 'role': user.role}
        })
    raw = secrets.token_urlsafe(32)
    from core.app_services import _token_hash
    user.api_token = _token_hash(raw)
    user.api_token_created_at = now
    session['api_token_raw'] = raw
    db.session.commit()
    log_operation('api_token', username,
                  f'用户 {user.name or user.username} 获取 API 令牌')
    db.session.commit()
    return jsonify({
        'ok': True,
        'token': raw,
        'user': {'id': user.id, 'username': user.username,
                 'name': user.name, 'role': user.role}
    })


@app.route('/profile/update-info', methods=['POST'])
@login_required
def profile_update_info():
    """修改用户名与昵称。"""
    if _ip_rate_limited('profile_edit:' + _client_key(), limit=10, window=60):
        return jsonify({'ok': False, 'error': '操作过于频繁，请稍后再试'})
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    name = (data.get('name') or '').strip()
    if not username:
        return jsonify({'ok': False, 'error': '用户名不能为空'})
    if len(username) < 2 or len(username) > 80:
        return jsonify({'ok': False, 'error': '用户名长度需在 2-80 个字符之间'})
    if not re.match(r'^[A-Za-z0-9_.@-]+$', username):
        return jsonify({'ok': False, 'error': '用户名仅支持字母、数字、下划线、点、@ 与中横线'})
    if len(name) > 80:
        return jsonify({'ok': False, 'error': '昵称不能超过 80 个字符'})
    user = current_user._get_current_object()
    if username != user.username:
        if User.query.filter_by(username=username).first():
            return jsonify({'ok': False, 'error': f'用户名 "{username}" 已被使用'})
    changed = []
    if user.username != username:
        old = user.username
        user.username = username
        changed.append(f'用户名 {old} → {username}')
    if user.name != name:
        old_name = user.name or '(空)'
        user.name = name
        changed.append(f'昵称 {old_name} → {name or "(空)"}')
    if not changed:
        return jsonify({'ok': False, 'error': '未做任何修改'})
    db.session.commit()
    log_operation('profile_update_info', username,
                  f'用户修改个人信息: {"; ".join(changed)}')
    return jsonify({'ok': True})


@app.route('/profile/change-password', methods=['POST'])
@login_required
def profile_change_password():
    """修改密码(需验证当前密码)。"""
    if _ip_rate_limited('profile_pwd:' + _client_key(), limit=5, window=300):
        return jsonify({'ok': False, 'error': '操作过于频繁，请 5 分钟后再试'})
    data = request.get_json(silent=True) or {}
    old_password = data.get('old_password') or ''
    new_password = data.get('new_password') or ''
    confirm_password = data.get('confirm_password') or ''
    if not old_password:
        return jsonify({'ok': False, 'error': '请输入当前密码'})
    if not new_password:
        return jsonify({'ok': False, 'error': '请输入新密码'})
    if len(new_password) < 6:
        return jsonify({'ok': False, 'error': '新密码长度至少 6 位'})
    if new_password != confirm_password:
        return jsonify({'ok': False, 'error': '两次输入的新密码不一致'})
    user = current_user._get_current_object()
    if not user.check_password(old_password):
        return jsonify({'ok': False, 'error': '当前密码不正确'})
    user.set_password(new_password)
    db.session.commit()
    log_operation('profile_change_pwd', user.username,
                  f'用户 {user.name or user.username} 修改了密码')
    return jsonify({'ok': True})


@app.route('/profile/api-token/rotate', methods=['POST'])
@login_required
def profile_rotate_api_token():
    """重新生成 API 令牌(日历订阅链接共用), 旧令牌立即失效。"""
    user = current_user._get_current_object()
    raw = secrets.token_urlsafe(32)
    from core.app_services import _token_hash
    user.api_token = _token_hash(raw)
    user.api_token_created_at = cn_now()
    session['api_token_raw'] = raw
    db.session.commit()
    log_operation('api_token_rotate', user.username,
                  f'用户 {user.name or user.username} 重新生成日历订阅/API 令牌')
    feed = url_for('user_todo_ics', token=raw)
    return jsonify({'ok': True, 'token': raw, 'feed_path': feed})
