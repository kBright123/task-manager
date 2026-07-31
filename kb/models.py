import logging
from datetime import datetime

from sqlalchemy import event

from app import db
from .config import STATUS_QUEUED

logger = logging.getLogger(__name__)


class KbDocument(db.Model):
    __tablename__ = 'kb_document'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    filename = db.Column(db.String(500), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), default='')
    file_size = db.Column(db.Integer, default=0)
    page_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default=STATUS_QUEUED, index=True)
    error = db.Column(db.Text)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    pages = db.relationship('KbPage', backref='document',
                            lazy='dynamic', cascade='all, delete-orphan')
    triples = db.relationship('KbTriple', backref='document',
                              lazy='dynamic', cascade='all, delete-orphan')


class KbPage(db.Model):
    __tablename__ = 'kb_page'
    id = db.Column(db.Integer, primary_key=True)
    doc_id = db.Column(db.Integer, db.ForeignKey('kb_document.id'),
                       nullable=False, index=True)
    page_no = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, default='')
    char_count = db.Column(db.Integer, default=0)


class KbEntity(db.Model):
    __tablename__ = 'kb_entity'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    node_type = db.Column(db.String(50), default='entity')
    doc_id = db.Column(db.Integer, db.ForeignKey('kb_document.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class KbTriple(db.Model):
    __tablename__ = 'kb_triple'
    id = db.Column(db.Integer, primary_key=True)
    doc_id = db.Column(db.Integer, db.ForeignKey('kb_document.id'),
                       nullable=False, index=True)
    page_no = db.Column(db.Integer, default=0)
    head = db.Column(db.String(200), nullable=False)
    rel = db.Column(db.String(200), nullable=False)
    tail = db.Column(db.String(200), nullable=False)
    head_type = db.Column(db.String(50), default='')
    tail_type = db.Column(db.String(50), default='')


def enable_sqlite_wal():
    @event.listens_for(db.engine, 'connect')
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA busy_timeout=10000')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.close()
