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
"""notify 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import app, login_required

@app.route('/notifications')
@login_required
def notifications():
    notes = Notification.query.filter_by(
        user_id=current_user.id).order_by(
        Notification.created_at.desc()).limit(200).all()
    return render_template('notifications.html', notifications=notes)


@app.route('/notifications/<int:note_id>/read', methods=['GET', 'POST'])
@login_required
def read_notification(note_id):
    note = db.session.get(Notification, note_id)
    if note and note.user_id == current_user.id:
        note.is_read = True
        db.session.commit()
        _clear_cached_notifications(current_user.id)
        if note.task_id:
            return redirect(url_for('user_task_detail', task_id=note.task_id))
    return redirect(url_for('notifications'))


@app.route('/notifications/read-all', methods=['POST'])
@login_required
def read_all_notifications():
    Notification.query.filter_by(
        user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    _clear_cached_notifications(current_user.id)
    flash('所有通知已标记为已读', 'info')
    return redirect(request.referrer or url_for('notifications'))


@app.route('/api/notifications/unread')
@login_required
def api_unread_notifications():
    """供前端轮询:返回未读数 + 最近通知(用于浏览器通知与未读小红点)。"""
    unread = Notification.query.filter_by(
        user_id=current_user.id, is_read=False).count()
    rows = Notification.query.filter_by(
        user_id=current_user.id).order_by(
        Notification.created_at.desc()).limit(20).all()
    return jsonify({'ok': True, 'unread': unread, 'items': [
        {'id': n.id, 'message': n.message, 'is_read': n.is_read,
         'created_at': n.created_at.strftime('%Y-%m-%d %H:%M:%S')
         if n.created_at else ''} for n in rows]})


@app.route('/uploads/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
