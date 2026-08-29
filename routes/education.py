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
"""教育模块: 纯前端学习乐园(导航栏「教育」入口)。

定位: 本地运行、无需联网、儿童友好。提供两个纯前端应用:
- 幼小衔接工作台(/edu#workbench): 5-6 岁每日打卡
  语文(古诗/识字/笔顺) · 数学(20 以内加减法/错题本) · 英语(单词/对话)
  随机出题、优先出历史错题、自动打分、答题记录自动保存(localStorage)。
- 宝贝启蒙乐园(/edu#paradise): 3-6 岁图文早教互动小游戏
  认数字/认字母/动物认知/颜色认知/形状认知/看图识字等。

页面完全由前端 JS 驱动(数据内嵌), 本模块仅负责渲染页面骨架,
无需任何数据库模型或网络请求。
"""
import logging

from flask import Blueprint, render_template

logger = logging.getLogger(__name__)

education_bp = Blueprint('education', __name__, url_prefix='/edu')


@education_bp.route('/')
def index():
    """教育学习乐园(纯前端, 本地运行, 无需联网)。"""
    return render_template('education.html')
