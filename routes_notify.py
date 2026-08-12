# -*- coding: utf-8 -*-
"""notify 路由, 自 app.py 单文件拆分, 保持原 endpoint 名称不变。"""
from app import app, login_required

@app.route('/notifications')
@login_required
def notifications():
    notes = Notification.query.filter_by(
        user_id=current_user.id).order_by(
        Notification.created_at.desc()).all()
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


@app.route('/uploads/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
