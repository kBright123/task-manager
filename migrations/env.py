# -*- coding: utf-8 -*-
"""Alembic 迁移环境: 复用 app 的 db 元数据与实例库.
用法: venv/bin/alembic revision --autogenerate -m "..." / venv/bin/alembic upgrade head
(需先 pip install -r requirements-dev.txt)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('KB_VECTOR_DISABLED', '1')
os.environ.setdefault('KB_LLM_DISABLED', '1')

from alembic import context  # noqa: E402
from sqlalchemy import engine_from_config, pool  # noqa: E402

from app import app as flask_app, db  # noqa: E402

config = context.config
if not config.get_main_option('sqlalchemy.url'):
    with flask_app.app_context():
        config.set_main_option('sqlalchemy.url', db.engine.url.render_as_string(hide_password=False))

target_metadata = db.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option('sqlalchemy.url'),
                      target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.', poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,
                          target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
