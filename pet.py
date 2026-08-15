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
"""电子宠物模块(双击导航栏 logo 触发)。

- 模型: Pet / PetRecord (由 app.py 调用 init_models(db) 注入)
- 属性: 饱腹度(hunger) / 快乐度(happiness) / 精力值(energy), 均 0-100
- 行为记录: 红心/黑心 + 备注, 时间倒序, 可删除
- 交互: 喂食/玩耍/清洁/睡觉(前三项消耗红心, 睡觉免费)
- 自动衰减: 每次读取状态时按经过的秒数折算, 无需后台进程
"""
import datetime
import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

logger = logging.getLogger(__name__)

db = None
Pet = None
PetRecord = None
PetItem = None

# 每 20 秒衰减值
DECAY_PER_TICK = {
    'hunger': 0.8,
    'happiness': 0.5,
    'energy': 0.6,
}
TICK_SECONDS = 20

# 长时间不照顾的提示阈值(小时): 超过后显示"饿了/困了/脏了"动画与提示
HUNGRY_AFTER_HOURS = 8      # 不喂食
SLEEPY_AFTER_HOURS = 12     # 不睡觉
DIRTY_AFTER_HOURS = 8       # 不洗澡

# 装饰商城: 用红心购买房子/猫盆/衣服
# 每类第一个 key 为默认(免费且永久拥有)
SHOP = {
    'house': [
        {'key': 'none',    'name': '无房子',   'emoji': '⬜', 'price': 0},
        {'key': 'cottage', 'name': '小木屋',   'emoji': '🛖', 'price': 15},
        {'key': 'pink',    'name': '粉红小屋', 'emoji': '🏠', 'price': 30},
        {'key': 'castle',  'name': '梦幻城堡', 'emoji': '🏰', 'price': 60},
        {'key': 'cloud',   'name': '云端小屋', 'emoji': '☁️', 'price': 100},
    ],
    'bowl': [
        {'key': 'none',  'name': '无猫盆',   'emoji': '⬜', 'price': 0},
        {'key': 'basic', 'name': '普通猫盆', 'emoji': '🥣', 'price': 8},
        {'key': 'cer',   'name': '陶瓷猫盆', 'emoji': '🍽️', 'price': 20},
        {'key': 'gold',  'name': '金边猫盆', 'emoji': '🏆', 'price': 45},
    ],
    'clothes': [
        {'key': 'none',  'name': '无搭配',   'emoji': '⬜', 'price': 0},
        {'key': 'bow',   'name': '蝴蝶结',   'emoji': '🎀', 'price': 12},
        {'key': 'scarf', 'name': '小围巾',   'emoji': '🧣', 'price': 20},
        {'key': 'vest',  'name': '小背心',   'emoji': '🧥', 'price': 40},
        {'key': 'robe',  'name': '王者披风', 'emoji': '🦸', 'price': 70},
    ],
}
DEFAULT_ITEMS = {cat: items[0]['key'] for cat, items in SHOP.items()}

# 互动获得的红心(装饰货币)奖励
INTERACT_HEARTS = {
    'feed': 2, 'play': 3, 'clean': 1, 'sleep': 0, 'pat': 1,
}
RECORD_HEART_AMOUNT = 5
RECORD_BLACK_AMOUNT = 0

# 进化等级体系: 形态名 / 所需累计经验 / 图标 / 徽章 / 进化形态(用于形象变化)
# 每个形态会带来宠物形象升级: 体型、配色、装饰、特效
EVOLUTIONS = [
    {'name': '奶猫',  'icon': '🐱', 'need': 0,     'badge': '新手上路',
     'form': 'kitten'},
    {'name': '小猫',  'icon': '🐱', 'need': 30,    'badge': '活泼好动',
     'form': 'kitty'},
    {'name': '成猫',  'icon': '🐈', 'need': 90,    'badge': '稳健可靠',
     'form': 'cat'},
    {'name': '大猫',  'icon': '🦁', 'need': 200,   'badge': '优雅从容',
     'form': 'bigcat'},
    {'name': '猫咪王', 'icon': '🐯', 'need': 400,  'badge': '王者风范',
     'form': 'catking'},
    {'name': '神兽',  'icon': '🐉', 'need': 700,   'badge': '传说神兽',
     'form': 'divine'},
]

# 互动配置: 消耗红心 / 属性变化 / 获得的经验
INTERACTIONS = {
    'feed':  {'hearts': 1, 'name': '喂食', 'emoji': '🍕', 'exp': 8,
              'effects': {'hunger': 25}, 'msg': '喂食成功！饱腹 +25'},
    'play':  {'hearts': 1, 'name': '玩耍', 'emoji': '🎾', 'exp': 12,
              'effects': {'happiness': 25, 'energy': -15},
              'msg': '玩耍成功！快乐 +25'},
    'clean': {'hearts': 1, 'name': '清洁', 'emoji': '🛁', 'exp': 6,
              'effects': {'happiness': 20}, 'msg': '清洁成功！快乐 +20'},
    'sleep': {'hearts': 0, 'name': '睡觉', 'emoji': '💤', 'exp': 0,
              'effects': {'energy': 40, 'hunger': -8, 'happiness': 5},
              'msg': '睡觉成功！精力 +40'},
    'pat':   {'hearts': 0, 'name': '摸一摸', 'emoji': '👋', 'exp': 0,
              'effects': {'happiness': 5}, 'msg': '喵呜～好舒服'},
}


def init_models(database):
    global db, Pet, PetRecord, PetItem
    db = database

    class Pet_(database.Model):
        __tablename__ = 'pet'
        __table_args__ = (
            database.Index('ix_pet_user', 'user_id'),
        )
        id = database.Column(database.Integer, primary_key=True)
        user_id = database.Column(database.Integer, nullable=False)
        hunger = database.Column(database.Float, default=80)
        happiness = database.Column(database.Float, default=80)
        energy = database.Column(database.Float, default=80)
        hearts = database.Column(database.Integer, default=3)
        black_hearts = database.Column(database.Integer, default=0)
        level = database.Column(database.Integer, default=1)
        exp = database.Column(database.Integer, default=0)
        stars = database.Column(database.Integer, default=0)
        equipped_house = database.Column(
            database.String(40), default='none')
        equipped_bowl = database.Column(
            database.String(40), default='none')
        equipped_clothes = database.Column(
            database.String(40), default='none')
        last_feed_at = database.Column(database.DateTime)
        last_sleep_at = database.Column(database.DateTime)
        last_clean_at = database.Column(database.DateTime)
        updated_at = database.Column(
            database.DateTime, default=datetime.datetime.utcnow)
        created_at = database.Column(
            database.DateTime, default=datetime.datetime.utcnow)

    class PetRecord_(database.Model):
        __tablename__ = 'pet_record'
        __table_args__ = (
            database.Index('ix_pet_record_pet', 'pet_id', 'created_at'),
        )
        id = database.Column(database.Integer, primary_key=True)
        pet_id = database.Column(database.Integer, nullable=False, index=True)
        kind = database.Column(database.String(10), default='heart')
        note = database.Column(database.String(500), default='')
        stars = database.Column(database.Integer, default=0)
        created_at = database.Column(
            database.DateTime, default=datetime.datetime.utcnow)

    class PetItem_(database.Model):
        __tablename__ = 'pet_item'
        __table_args__ = (
            database.Index('ix_pet_item_pet', 'pet_id'),
        )
        id = database.Column(database.Integer, primary_key=True)
        pet_id = database.Column(database.Integer, nullable=False, index=True)
        category = database.Column(database.String(20), nullable=False)
        item_key = database.Column(database.String(40), nullable=False)
        created_at = database.Column(
            database.DateTime, default=datetime.datetime.utcnow)

    Pet, PetRecord, PetItem = Pet_, PetRecord_, PetItem_
    return {'Pet': Pet, 'PetRecord': PetRecord, 'PetItem': PetItem}


pet_bp = Blueprint('pet', __name__, url_prefix='/api/pet')


def _get_or_create_pet():
    """获取当前用户的宠物,不存在则创建。"""
    pet = Pet.query.filter_by(user_id=current_user.id).first()
    if pet is None:
        pet = Pet(user_id=current_user.id, hunger=80, happiness=80,
                  energy=80, hearts=3, black_hearts=0)
        db.session.add(pet)
        db.session.commit()
    return pet


def _owned_item_keys(pet, category):
    """返回某类别已拥有的物品 key 集合(默认物品永远拥有)。"""
    keys = {SHOP[category][0]['key']}
    for item in PetItem.query.filter_by(pet_id=pet.id, category=category).all():
        keys.add(item.item_key)
    return keys


def _shop_payload(pet):
    """商城数据: 每类商品列表 + 已拥有集合 + 当前穿戴。"""
    payload = {}
    for category, items in SHOP.items():
        owned = _owned_item_keys(pet, category)
        equipped = getattr(pet, 'equipped_' + category) or \
            DEFAULT_ITEMS[category]
        payload[category] = {
            'items': items,
            'owned': sorted(owned),
            'equipped': equipped,
        }
    return payload


def _apply_decay(pet):
    """按自上次更新以来的秒数折算属性衰减, 返回 (是否发生衰减, 表情线索)。"""
    now = datetime.datetime.utcnow()
    last = pet.updated_at or pet.created_at or now
    elapsed = max(0, (now - last).total_seconds())
    if elapsed < TICK_SECONDS:
        return False
    ticks = int(elapsed // TICK_SECONDS)
    changed = False
    for attr, rate in DECAY_PER_TICK.items():
        val = getattr(pet, attr) - rate * ticks
        val = max(0, min(100, val))
        if abs(val - getattr(pet, attr)) > 0.001:
            changed = True
        setattr(pet, attr, round(val, 1))
    pet.updated_at = last + datetime.timedelta(
        seconds=ticks * TICK_SECONDS)
    if changed:
        db.session.add(pet)
        db.session.commit()
    return changed


def _pet_payload(pet):
    level_info = _level_info(pet)
    level = _level_from_exp(pet.exp or 0)
    return {
        'id': pet.id,
        'hunger': pet.hunger,
        'happiness': pet.happiness,
        'energy': pet.energy,
        'hearts': pet.hearts,
        'black_hearts': pet.black_hearts,
        'mood': _mood(pet),
        'level': level,
        'level_name': level_info['name'],
        'level_icon': level_info['icon'],
        'level_badge': level_info['badge'],
        'level_progress': level_info['progress'],
        'level_need': level_info['need'],
        'exp': pet.exp,
        'form': level_info['form'],
        'equipped_house': pet.equipped_house or 'none',
        'equipped_bowl': pet.equipped_bowl or 'none',
        'equipped_clothes': pet.equipped_clothes or 'none',
        'needs': _pet_needs(pet),
    }


def _pet_needs(pet):
    """根据上次喂食/睡觉/清洁的时间判断宠物需求。
    返回 {'hungry': bool, 'sleepy': bool, 'dirty': bool}。"""
    now = datetime.datetime.utcnow()
    needs = {'hungry': False, 'sleepy': False, 'dirty': False}
    h = HUNGRY_AFTER_HOURS * 3600
    s = SLEEPY_AFTER_HOURS * 3600
    d = DIRTY_AFTER_HOURS * 3600
    if pet.last_feed_at is None or (now - pet.last_feed_at).total_seconds() > h:
        needs['hungry'] = True
    if pet.last_sleep_at is None or (now - pet.last_sleep_at).total_seconds() > s:
        needs['sleepy'] = True
    if pet.last_clean_at is None or (now - pet.last_clean_at).total_seconds() > d:
        needs['dirty'] = True
    return needs


def _level_from_exp(exp):
    """根据累计经验推导当前等级序号(1 起)。"""
    level = 1
    for i, lv in enumerate(EVOLUTIONS):
        if exp >= lv['need']:
            level = i + 1
        else:
            break
    return level


def _level_info(pet):
    """根据累计经验计算进化等级信息, 返回 {name, icon, badge, need, progress, form}。
    progress 为当前等级内经验占比 0-100。等级由经验值直接推导, 保证一致性。"""
    exp = pet.exp or 0
    idx = 0
    for i, lv in enumerate(EVOLUTIONS):
        if exp >= lv['need']:
            idx = i
        else:
            break
    cur = EVOLUTIONS[idx]
    nxt = _level_by_index(idx + 1)
    if nxt is None:
        return {
            'name': cur['name'], 'icon': cur['icon'],
            'badge': cur['badge'], 'need': cur['need'],
            'form': cur['form'], 'progress': 100,
        }
    span = max(1, nxt['need'] - cur['need'])
    pct = max(0, min(100, int((exp - cur['need']) * 100 / span)))
    return {
        'name': cur['name'], 'icon': cur['icon'],
        'badge': cur['badge'], 'need': nxt['need'],
        'form': cur['form'], 'progress': pct,
    }


def _level_by_index(idx):
    if 0 <= idx < len(EVOLUTIONS):
        return EVOLUTIONS[idx]
    return None


def _apply_exp(pet, amount):
    """增加经验并处理进化, 返回 (升到的新等级, 是否进化)。"""
    pet.exp = (pet.exp or 0) + amount
    old_level = pet.level or 1
    new_level = old_level
    for i in range(len(EVOLUTIONS)):
        if pet.exp >= EVOLUTIONS[i]['need']:
            new_level = max(new_level, i + 1)
    pet.level = new_level
    return new_level, new_level > old_level


def _mood(pet):
    if pet.hunger < 20 or pet.happiness < 20:
        return 'sad'          # 😿
    if pet.energy < 15:
        return 'tired'        # 😾
    if pet.hunger > 70 and pet.happiness > 70 and pet.energy > 70:
        return 'happy'        # 😸
    return 'normal'           # 🐱


@pet_bp.route('/state')
@login_required
def pet_state():
    pet = _get_or_create_pet()
    _apply_decay(pet)
    return jsonify({'ok': True, 'pet': _pet_payload(pet)})


@pet_bp.route('/interact', methods=['POST'])
@login_required
def pet_interact():
    pet = _get_or_create_pet()
    _apply_decay(pet)
    action = (request.json or {}).get('action', '')
    cfg = INTERACTIONS.get(action)
    if not cfg:
        return jsonify({'ok': False, 'error': '未知操作'}), 400
    if pet.hearts < cfg['hearts']:
        return jsonify({'ok': False, 'error': '红心不足，无法进行该互动'}), 400
    if cfg['hearts']:
        pet.hearts -= cfg['hearts']
    for attr, delta in cfg['effects'].items():
        val = getattr(pet, attr) + delta
        setattr(pet, attr, round(max(0, min(100, val)), 1))
    new_level, leveled_up = _apply_exp(pet, cfg.get('exp', 0))
    heart_gain = INTERACT_HEARTS.get(action, 0)
    if heart_gain:
        pet.hearts = (pet.hearts or 0) + heart_gain
    now = datetime.datetime.utcnow()
    if action == 'feed':
        pet.last_feed_at = now
    elif action == 'sleep':
        pet.last_sleep_at = now
    elif action == 'clean':
        pet.last_clean_at = now
    pet.updated_at = now
    db.session.add(pet)
    db.session.commit()
    payload = _pet_payload(pet)
    if leveled_up:
        payload['leveled_up'] = new_level
    return jsonify({'ok': True, 'pet': payload, 'msg': cfg['msg']})


@pet_bp.route('/records')
@login_required
def pet_records():
    pet = _get_or_create_pet()
    rows = PetRecord.query.filter_by(pet_id=pet.id).order_by(
        PetRecord.created_at.desc()).limit(200).all()
    return jsonify({'ok': True, 'records': [
        {'id': r.id, 'kind': r.kind, 'note': r.note, 'stars': r.stars or 0,
         'time': r.created_at.strftime('%m-%d %H:%M')}
        for r in rows]})


@pet_bp.route('/records', methods=['POST'])
@login_required
def pet_record_add():
    pet = _get_or_create_pet()
    data = request.json or {}
    kind = data.get('kind', 'heart')
    if kind not in ('heart', 'black'):
        return jsonify({'ok': False, 'error': '记录类型错误'}), 400
    note = (data.get('note') or '').strip()[:500]
    hearts = data.get('stars')
    if hearts is None:
        hearts = RECORD_HEART_AMOUNT if kind == 'heart' else RECORD_BLACK_AMOUNT
    try:
        hearts = int(hearts)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': '红心数量格式错误'}), 400
    hearts = max(0, min(100, hearts))
    rec = PetRecord(pet_id=pet.id, kind=kind, note=note, stars=hearts)
    db.session.add(rec)
    if kind == 'heart':
        pet.hearts += 1
        pet.hearts += hearts
    else:
        pet.black_hearts += 1
        pet.hearts += hearts
    db.session.add(pet)
    db.session.commit()
    return jsonify({'ok': True, 'record': {
        'id': rec.id, 'kind': rec.kind, 'note': rec.note,
        'stars': rec.stars,
        'time': rec.created_at.strftime('%m-%d %H:%M')},
        'pet': _pet_payload(pet)})


@pet_bp.route('/records/<int:record_id>', methods=['DELETE'])
@login_required
def pet_record_delete(record_id):
    pet = _get_or_create_pet()
    rec = db.session.get(PetRecord, record_id)
    if not rec or rec.pet_id != pet.id:
        return jsonify({'ok': False, 'error': '记录不存在'}), 404
    if rec.kind == 'heart':
        pet.hearts = max(0, pet.hearts - 1)
    else:
        pet.black_hearts = max(0, pet.black_hearts - 1)
    pet.hearts = max(0, (pet.hearts or 0) - (rec.stars or 0))
    db.session.delete(rec)
    db.session.add(pet)
    db.session.commit()
    return jsonify({'ok': True, 'pet': _pet_payload(pet)})


@pet_bp.route('/shop')
@login_required
def pet_shop():
    pet = _get_or_create_pet()
    return jsonify({
        'ok': True,
        'hearts': pet.hearts or 0,
        'shop': _shop_payload(pet),
        'pet': _pet_payload(pet),
    })


@pet_bp.route('/shop/buy', methods=['POST'])
@login_required
def pet_shop_buy():
    pet = _get_or_create_pet()
    data = request.json or {}
    category = data.get('category', '')
    item_key = data.get('item_key', '')
    if category not in SHOP:
        return jsonify({'ok': False, 'error': '商品类别错误'}), 400
    item = next((i for i in SHOP[category] if i['key'] == item_key), None)
    if not item:
        return jsonify({'ok': False, 'error': '商品不存在'}), 400
    if item_key in _owned_item_keys(pet, category):
        return jsonify({'ok': False, 'error': '已经拥有该物品'}), 400
    if (pet.hearts or 0) < item['price']:
        return jsonify({'ok': False, 'error': '红心不足，无法购买'}), 400
    pet.hearts = (pet.hearts or 0) - item['price']
    db.session.add(PetItem(pet_id=pet.id, category=category,
                           item_key=item_key))
    db.session.add(pet)
    db.session.commit()
    return jsonify({'ok': True, 'hearts': pet.hearts,
                    'shop': _shop_payload(pet),
                    'pet': _pet_payload(pet)})


@pet_bp.route('/shop/equip', methods=['POST'])
@login_required
def pet_shop_equip():
    pet = _get_or_create_pet()
    data = request.json or {}
    category = data.get('category', '')
    item_key = data.get('item_key', '')
    if category not in SHOP:
        return jsonify({'ok': False, 'error': '类别错误'}), 400
    if item_key not in _owned_item_keys(pet, category):
        return jsonify({'ok': False, 'error': '未拥有该物品'}), 400
    setattr(pet, 'equipped_' + category, item_key)
    db.session.add(pet)
    db.session.commit()
    return jsonify({'ok': True, 'shop': _shop_payload(pet),
                    'pet': _pet_payload(pet)})