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
                 create_notification, db, generate_verify_code,
                 log_operation, logger, normalize_email, send_email,
                 send_verify_code)

from flask import (flash, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_user, logout_user
import secrets
from datetime import timedelta

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
    now = _time_mod.time()
    with _ip_lock:
        dq = _ip_attempts.setdefault(key, _deque())
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        if len(_ip_attempts) > 10000:  # 防字典无限增长, 清理空桶
            for k in [k for k, v in _ip_attempts.items() if not v]:
                _ip_attempts.pop(k, None)
        return False


def _client_key():
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or 'unknown')


def mask_email(email):
    """脱敏邮箱用于页面展示: abc@qq.com -> a**@qq.com"""
    if not email:
        return ''
    local, _, domain = email.partition('@')
    if len(local) <= 2:
        return f'{local[0]}***@{domain}'
    return f'{local[0]}***{local[-1]}@{domain}'


def send_unlock_code(user):
    """为锁定账号生成解锁验证码并发送邮件。返回 (ok, err, dev_code)。"""
    code = generate_verify_code()
    user.unlock_code = code
    user.unlock_code_expires_at = (cn_now() +
                                   timedelta(minutes=UNLOCK_CODE_TTL_MINUTES))
    user.locked_until = cn_now() + timedelta(minutes=LOGIN_LOCK_MINUTES)
    db.session.commit()
    text = (f'您的账号 @{user.username} 因多次密码输入错误已被临时锁定。\n'
            f'解锁验证码为: {code}\n'
            f'验证码 {UNLOCK_CODE_TTL_MINUTES} 分钟内有效,请勿泄露给他人。\n'
            f'如非本人操作,请忽略本邮件,并考虑修改密码。')
    html = (f'<div style="font-family:Microsoft YaHei,Arial,sans-serif;font-size:14px;color:#1e293b;">'
            f'<p>您的账号 <b>@{user.username}</b> 因多次密码输入错误已被临时锁定。</p>'
            f'<p>解锁验证码为:</p>'
            f'<p style="font-size:24px;font-weight:700;letter-spacing:4px;color:#4f46e7;">{code}</p>'
            f'<p>验证码 <b>{UNLOCK_CODE_TTL_MINUTES} 分钟</b>内有效,请勿泄露给他人。</p>'
            f'<p style="color:#94a3b8;font-size:12px;">如非本人操作,请忽略本邮件,并考虑修改密码。</p></div>')
    ok, err = send_email(user.email, '【知行合一】账号解锁验证码', html,
                         text, category='unlock')
    if not ok and not app.config['MAIL_SERVER']:
        logger.info('邮件服务未配置,解锁验证码(%s) 已写入日志,目标邮箱: %s',
                    code, user.email)
        return False, '邮件服务未配置,验证码已写入服务器日志', code
    return ok, err, ''


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    ctx = {'username': '', 'lock_email': False, 'masked_email': ''}
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
            if user.unlock_code:
                ctx['lock_email'] = True
                ctx['masked_email'] = mask_email(user.email)
                flash('密码错误次数过多，账号已锁定。请输入邮箱验证码解锁（也可验证后重置密码）', 'warning')
                return render_template('login.html', **ctx)
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
                flash('该账号已被禁用，请联系管理员', 'danger')
                return render_template('login.html', **ctx)
            user.failed_login_count = 0
            user.locked_until = None
            user.unlock_code = ''
            user.unlock_code_expires_at = None
            user.last_login = cn_now()
            user.last_seen = cn_now()
            login_user(user)
            session.permanent = True  # 会话 4 小时后自动过期退出登录
            log_operation('login', username,
                          f'用户 {user.name or user.username} 登录成功')
            db.session.commit()
            flash('登录成功！', 'success')
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/') and not next_page.startswith('//'):
                return redirect(next_page)
            return redirect(url_for('index'))
        if not user:
            log_operation('login_fail', username, '用户不存在')
            db.session.commit()
            flash('用户名或密码错误！', 'danger')
            return render_template('login.html', **ctx)
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_LOGIN_FAILS:
            if user.email_verified and user.email:
                send_unlock_code(user)
                ctx['lock_email'] = True
                ctx['masked_email'] = mask_email(user.email)
                flash(f'密码错误 {MAX_LOGIN_FAILS} 次，账号已锁定。已向绑定邮箱发送解锁验证码', 'warning')
            else:
                user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
                db.session.commit()
                log_operation('login_fail', username, f'连续密码错误，锁定 {LOGIN_LOCK_MINUTES} 分钟')
                db.session.commit()
                flash(f'密码错误 {MAX_LOGIN_FAILS} 次，账号已锁定 {LOGIN_LOCK_MINUTES} 分钟。请稍后再试', 'warning')
            return render_template('login.html', **ctx)
        remaining = MAX_LOGIN_FAILS - user.failed_login_count
        log_operation('login_fail', username, '用户名或密码错误')
        db.session.commit()
        flash(f'用户名或密码错误！剩余尝试次数 {remaining} 次', 'danger')
        return render_template('login.html', **ctx)
    return render_template('login.html', **ctx)


@app.route('/login/unlock/send', methods=['POST'])
def login_unlock_send():
    """锁定账号重发解锁验证码。"""
    username = request.form.get('username', '').strip()
    user = User.query.filter_by(username=username).first()
    now = cn_now()
    if (user and user.locked_until and user.locked_until > now
            and user.email_verified and user.email):
        send_unlock_code(user)
        flash('解锁验证码已重新发送，请查收邮件', 'success')
    else:
        flash('账号未处于可解锁状态', 'danger')
    return redirect(url_for('login'))


@app.route('/login/unlock', methods=['POST'])
def login_unlock():
    """邮箱验证码解锁:验证通过后解锁账号,可同时重置密码。"""
    username = request.form.get('username', '').strip()
    code = (request.form.get('code') or '').strip()
    new_password = request.form.get('new_password', '')
    user = User.query.filter_by(username=username).first()
    now = cn_now()
    if not user or not user.locked_until or user.locked_until <= now:
        flash('账号未处于锁定状态', 'danger')
        return redirect(url_for('login'))
    if not code:
        flash('请输入邮箱收到的验证码', 'danger')
        return redirect(url_for('login'))
    if not user.unlock_code or user.unlock_code_expires_at < now:
        flash('验证码已过期，请重新获取', 'danger')
        return redirect(url_for('login'))
    if user.unlock_code != code:
        log_operation('login_fail', username, '解锁验证码错误')
        db.session.commit()
        flash('验证码错误，请重新输入', 'danger')
        return redirect(url_for('login'))
    if new_password:
        if len(new_password) < 6:
            flash('新密码长度至少 6 位', 'danger')
            return redirect(url_for('login'))
        user.set_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    user.unlock_code = ''
    user.unlock_code_expires_at = None
    log_operation('login_unlock', username,
                  '通过邮箱验证码解锁账号' + ('并重置密码' if new_password else ''))
    db.session.commit()
    if new_password:
        flash('验证通过，密码已重置，请使用新密码登录', 'success')
    else:
        flash('验证通过，账号已解锁，请重新登录', 'success')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        if not username or not name:
            flash('用户名和姓名不能为空', 'danger')
            return render_template('register.html', username=username,
                                   name=name)
        if len(username) < 2 or len(username) > 80:
            flash('用户名长度需在 2-80 个字符之间', 'danger')
            return render_template('register.html', username=username,
                                   name=name)
        if len(name) > 80:
            flash('姓名不能超过 80 个字符', 'danger')
            return render_template('register.html', username=username,
                                   name=name)
        if len(password) < 6:
            flash('密码长度至少 6 位', 'danger')
            return render_template('register.html', username=username,
                                   name=name)
        if User.query.filter_by(username=username).first():
            flash('该账号已注册，请直接登录', 'danger')
            return render_template('register.html', username=username,
                                   name=name)
        reg_ip = client_ip()
        if User.query.filter(User.registration_ip == reg_ip).first():
            flash('当前访问 IP 地址已注册过账号，如需其他账号请联系管理员', 'danger')
            return render_template('register.html', username=username,
                                   name=name)
        user = User(username=username, name=name, role='user',
                    status='pending', registration_ip=reg_ip)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        for admin in User.query.filter_by(role='admin',
                                          is_disabled=False,
                                          status='approved').all():
            create_notification(
                admin.id, 'user_pending',
                f'新用户「{name or username}」(@{username}) 注册，等待审批')
        db.session.commit()
        log_operation('register', username,
                      f'新用户 {name or username} 注册，等待管理员审批')
        db.session.commit()
        flash('注册成功！账号正在等待管理员审批，审批通过后即可登录', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    log_operation('logout', current_user.username or '',
                  f'用户 {current_user.name or current_user.username} 退出登录')
    db.session.commit()
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))


@app.route('/guest/login')
def guest_login():
    """体验客户一键登录: 免密登录只读的 guest 账号(仅可查看,不可写)。"""
    user = User.query.filter_by(username='guest', role='guest').first()
    if not user or user.is_disabled or user.status != 'approved':
        flash('体验账号不可用，请稍后再试', 'warning')
        return redirect(url_for('login'))
    login_user(user)
    session.permanent = True
    log_operation('login', user.username,
                  f'体验客户 {user.name or user.username} 一键登录')
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/profile', methods=['GET'])
@login_required
def profile():
    """个人信息页:展示账号信息与邮箱绑定状态。"""
    return render_template('profile.html')


@app.route('/profile/send-verify-code', methods=['POST'])
@login_required
def profile_send_verify_code():
    """发送邮箱绑定校验码。"""
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get('email'))
    if not email:
        return jsonify({'ok': False, 'error': '邮箱格式不正确,请检查后重试'})
    dup = User.query.filter(
        db.or_(User.email == email, User.pending_email == email),
        User.id != current_user.id).first()
    if dup:
        return jsonify({'ok': False, 'error': '该邮箱已被其他账号绑定'})
    ok, err, dev_code = send_verify_code(current_user, email)
    return jsonify({'ok': ok, 'error': err or '', 'dev_code': dev_code})


@app.route('/profile/verify-email', methods=['POST'])
@login_required
def profile_verify_email():
    """校验邮箱校验码并完成绑定。"""
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get('email'))
    code = (data.get('code') or '').strip()
    if not email:
        return jsonify({'ok': False, 'error': '邮箱格式不正确,请检查后重试'})
    if not code:
        return jsonify({'ok': False, 'error': '请输入校验码'})
    user = current_user
    if user.pending_email != email:
        return jsonify({'ok': False, 'error': '邮箱与发送校验码时不一致,请重新发送'})
    if user.email_code != code:
        return jsonify({'ok': False, 'error': '校验码不正确,请重新输入'})
    if not user.email_code_expires_at or user.email_code_expires_at < cn_now():
        return jsonify({'ok': False, 'error': '校验码已过期,请重新发送'})
    user.email = email
    user.email_verified = True
    user.pending_email = ''
    user.email_code = ''
    user.email_code_expires_at = None
    db.session.commit()
    log_operation('email_bind', email, f'用户 {user.name or user.username} 绑定邮箱')
    return jsonify({'ok': True})


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
    if user.role == 'guest':
        log_operation('api_token_fail', username, '体验客户账号拒绝发放令牌')
        db.session.commit()
        return jsonify({'ok': False, 'error': '体验客户账号不可获取 API 令牌'}), 403
    user.failed_login_count = 0
    user.locked_until = None
    if not user.api_token:
        user.api_token = secrets.token_urlsafe(32)
        user.api_token_created_at = now
        db.session.commit()
    log_operation('api_token', username,
                  f'用户 {user.name or user.username} 获取 API 令牌')
    db.session.commit()
    return jsonify({
        'ok': True,
        'token': user.api_token,
        'user': {'id': user.id, 'username': user.username,
                 'name': user.name, 'role': user.role}
    })


@app.route('/profile/unbind-email', methods=['POST'])
@login_required
def profile_unbind_email():
    """解除邮箱绑定。"""
    user = current_user
    if not user.email:
        return jsonify({'ok': False, 'error': '当前未绑定邮箱'})
    email = user.email
    user.email = ''
    user.email_verified = False
    user.pending_email = ''
    user.email_code = ''
    user.email_code_expires_at = None
    db.session.commit()
    log_operation('email_unbind', email, f'用户 {user.name or user.username} 解除邮箱绑定')
    return jsonify({'ok': True})


@app.route('/profile/api-token/rotate', methods=['POST'])
@login_required
def profile_rotate_api_token():
    """重新生成 API 令牌(日历订阅链接共用), 旧令牌立即失效。"""
    user = current_user._get_current_object()
    user.api_token = secrets.token_urlsafe(32)
    user.api_token_created_at = cn_now()
    db.session.commit()
    log_operation('api_token_rotate', user.username,
                  f'用户 {user.name or user.username} 重新生成日历订阅/API 令牌')
    feed = url_for('user_todo_ics', token=user.api_token)
    return jsonify({'ok': True, 'token': user.api_token, 'feed_path': feed})
