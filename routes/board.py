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

"""个人看板模块(仪表盘日历区「看板」视图的 REST API)。

组成:
- 模型: BoardItem(core.models,由 app.py 的 db.create_all() 统一建表)
- API : GET/POST /api/board, PUT/DELETE /api/board/<id>
- 语义: 每用户独立的进行中/已完成条目; 完成项在前端置灰划线, 排序不迁移
"""
from flask import jsonify, request

from app import app, login_required, logger
from flask_login import current_user
from core.models import BoardItem, db

_MAX_CONTENT = 2000


def _board_item_dict(it):
    """序列化单个看板条目(created_at 转北京时间字符串, 前端直接展示)."""
    return {
        'id': it.id,
        'content': it.content or '',
        'done': bool(it.done),
        'date': it.created_at.strftime('%m-%d %H:%M') if it.created_at else '',
        'created_at': it.created_at.strftime('%Y-%m-%d %H:%M') if it.created_at else '',
    }


@app.route('/api/board', methods=['GET'])
@login_required
def api_board_list():
    items = BoardItem.query.filter_by(user_id=current_user.id).order_by(
        BoardItem.done, BoardItem.created_at.desc(), BoardItem.id.desc()).all()
    return jsonify({'ok': True, 'items': [_board_item_dict(i) for i in items]})


@app.route('/api/board', methods=['POST'])
@login_required
def api_board_create():
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'ok': False, 'error': '内容不能为空'}), 400
    if len(content) > _MAX_CONTENT:
        return jsonify({'ok': False, 'error': '内容过长(最多 %d 字)' % _MAX_CONTENT}), 400
    item = BoardItem(user_id=current_user.id, content=content)
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True, 'item': _board_item_dict(item)})


@app.route('/api/board/<int:item_id>', methods=['PUT'])
@login_required
def api_board_update(item_id):
    item = db.session.get(BoardItem, item_id)
    if item is None or item.user_id != current_user.id:
        return jsonify({'ok': False, 'error': '条目不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'done' in data:
        item.done = bool(data.get('done'))
    if 'content' in data:
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({'ok': False, 'error': '内容不能为空'}), 400
        item.content = content[:_MAX_CONTENT]
    db.session.commit()
    return jsonify({'ok': True, 'item': _board_item_dict(item)})


@app.route('/api/board/<int:item_id>', methods=['DELETE'])
@login_required
def api_board_delete(item_id):
    item = db.session.get(BoardItem, item_id)
    if item is None or item.user_id != current_user.id:
        return jsonify({'ok': False, 'error': '条目不存在'}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({'ok': True})


logger.info('[board] 看板 API 已加载')