# -*- coding: utf-8 -*-
"""全项目统一时间源."""
from datetime import datetime, timezone, timedelta


def cn_now():
    """当前北京时间(naive), 全项目统一时间源(与服务器时区无关)。"""
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
