import logging
import os
import sqlite3
import sys
import time

from . import llm, ocr, store
from .config import (KB_EXTRACT_PAGE_MAX_CHARS, KB_POLL_INTERVAL,
                     STATUS_DONE, STATUS_EMBED, STATUS_FAILED, STATUS_GRAPH,
                     STATUS_OCR)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('kb.worker')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'instance', 'tasks.db')


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def claim_next(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute(
            "SELECT id, file_path, title, filename FROM kb_document "
            "WHERE status IN ('queued','failed') "
            "ORDER BY created_at ASC LIMIT 1").fetchone()
        if row:
            conn.execute(
                "UPDATE kb_document SET status=?, updated_at=datetime('now') "
                "WHERE id=?", (STATUS_OCR, row[0]))
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise


def update_status(conn, doc_id, status, error=None, page_count=None):
    sql = "UPDATE kb_document SET status=?, updated_at=datetime('now')"
    params = [status]
    if error is not None:
        sql += ", error=?"
        params.append(error)
    if page_count is not None:
        sql += ", page_count=?"
        params.append(page_count)
    sql += " WHERE id=?"
    params.append(doc_id)
    conn.execute(sql, params)
    conn.commit()


def process_document(conn, row):
    doc_id, file_path, title, filename = row
    try:
        update_status(conn, doc_id, STATUS_OCR)
        logger.info('[doc %s] OCR: %s', doc_id, filename)
        pages = ocr.ocr_file(file_path)
        page_count = len(pages)

        update_status(conn, doc_id, STATUS_EMBED, page_count=page_count)
        conn.execute("DELETE FROM kb_page WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM kb_triple WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM kb_entity WHERE doc_id=?", (doc_id,))
        conn.commit()

        for page_no, text in pages:
            if text.strip():
                store.upsert_page(doc_id, page_no, title, filename, text)
                conn.execute(
                    "INSERT INTO kb_page (doc_id, page_no, text, char_count) "
                    "VALUES (?,?,?,?)",
                    (doc_id, page_no, text, len(text)))
        conn.commit()

        update_status(conn, doc_id, STATUS_GRAPH)
        all_triples = []
        for page_no, text in pages:
            snippet = text[:KB_EXTRACT_PAGE_MAX_CHARS].strip()
            if len(snippet) < 8:
                continue
            try:
                triples = llm.extract_triples(snippet)
            except Exception as e:
                logger.warning('[doc %s] extract failed page %s: %s',
                               doc_id, page_no, e)
                triples = []
            for t in triples:
                conn.execute(
                    "INSERT INTO kb_triple (doc_id, page_no, head, rel, tail,"
                    " head_type, tail_type) VALUES (?,?,?,?,?,?,?)",
                    (doc_id, page_no, t['head'], t['rel'], t['tail'],
                     t['headType'], t['tailType']))
                conn.execute(
                    "INSERT OR IGNORE INTO kb_entity "
                    "(name, node_type, doc_id) VALUES (?,?,?)",
                    (t['head'], t['headType'], doc_id))
                conn.execute(
                    "INSERT OR IGNORE INTO kb_entity "
                    "(name, node_type, doc_id) VALUES (?,?,?)",
                    (t['tail'], t['tailType'], doc_id))
                all_triples.append(t)
        conn.commit()

        if all_triples:
            store.add_doc_node(doc_id, title)
            for t in all_triples:
                store.add_triple_edge(doc_id, 0, t)
            logger.info('[doc %s] graph: %d triples', doc_id,
                        len(all_triples))

        update_status(conn, doc_id, STATUS_DONE)
        logger.info('[doc %s] done: %d pages, %d triples', doc_id,
                    page_count, len(all_triples))
    except Exception as e:
        logger.exception('[doc %s] failed', doc_id)
        update_status(conn, doc_id, STATUS_FAILED, error=str(e))


def main():
    store.ensure_schema()
    conn = connect()
    logger.info('kb.worker started, polling every %.1fs', KB_POLL_INTERVAL)
    while True:
        try:
            row = claim_next(conn)
            if row:
                process_document(conn, row)
            else:
                time.sleep(KB_POLL_INTERVAL)
        except Exception as e:
            logger.error('worker loop error: %s', e)
            time.sleep(KB_POLL_INTERVAL)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
