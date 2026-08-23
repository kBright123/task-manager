# -*- coding: utf-8 -*-
"""Flask 扩展单例(db/login_manager), 供 app 与 models 共享, 消除循环导入."""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
