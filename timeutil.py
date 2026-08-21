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
"""统一时间源。

全应用业务时间统一使用北京时间(UTC+8), 与服务器/容器时区无关,
避免 utcnow 与本地时间混用导致展示时间偏差(如操作日志慢8小时)。
"""
from datetime import datetime, timedelta, timezone

_CN_TZ = timezone(timedelta(hours=8))


def cn_now():
    """当前北京时间(naive datetime), 与既有业务存储格式一致。"""
    return datetime.now(_CN_TZ).replace(tzinfo=None)
