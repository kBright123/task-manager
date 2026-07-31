import logging
import os

from . import embed
from .config import (KB_NAMESPACE, KB_PAGES_COLLECTION, KB_SOCHDB_PATH)

logger = logging.getLogger(__name__)

_db = None


def get_db():
    global _db
    if _db is None:
        from sochdb.database import Database
        os.makedirs(os.path.dirname(KB_SOCHDB_PATH) or '.', exist_ok=True)
        _db = Database.open_concurrent(KB_SOCHDB_PATH)
    return _db


def ensure_schema():
    db = get_db()
    try:
        db.create_namespace(KB_NAMESPACE)
    except Exception:
        pass
    ns = db.namespace(KB_NAMESPACE)
    if KB_PAGES_COLLECTION not in ns.list_collections():
        from sochdb.namespace import CollectionConfig
        col = CollectionConfig(name=KB_PAGES_COLLECTION, dimension=512,
                               enable_hybrid_search=True,
                               content_field='text')
        ns.create_collection(col)
        logger.info('created collection %s', KB_PAGES_COLLECTION)
    return ns


def page_doc_id(doc_id, page_no):
    return f'd{doc_id}p{page_no}'


def doc_node_id(doc_id):
    return f'doc:{doc_id}'


def entity_node_id(name):
    return name.strip()


def upsert_page(doc_id, page_no, title, filename, text):
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    vec = embed.embed_text(text or ' ')
    col.insert(id=page_doc_id(doc_id, page_no), vector=vec, content=text,
               metadata={
                   'text': text,
                   'doc_id': str(doc_id),
                   'page_no': str(page_no),
                   'title': title,
                   'filename': filename,
               })


def delete_page(doc_id, page_no):
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    try:
        col.delete(page_doc_id(doc_id, page_no))
    except Exception as e:
        logger.warning('delete_page %s failed: %s', page_doc_id(doc_id, page_no), e)


def search_pages(query, k=10, alpha=0.5):
    ns = ensure_schema()
    col = ns.collection(KB_PAGES_COLLECTION)
    vec = embed.embed_text(query)
    results = col.hybrid_search(vec, text_query=query, k=k, alpha=alpha)
    out = []
    for r in results.results:
        meta = r.metadata or {}
        out.append({
            'id': r.id,
            'score': r.score,
            'doc_id': int(meta.get('doc_id', 0) or 0),
            'page_no': int(meta.get('page_no', 0) or 0),
            'title': meta.get('title', ''),
            'filename': meta.get('filename', ''),
            'text': meta.get('text', ''),
        })
    return out


def add_doc_node(doc_id, title):
    get_db().add_node(KB_NAMESPACE, doc_node_id(doc_id), 'doc',
                      {'title': title, 'doc_id': str(doc_id)})


def add_entity_node(name, node_type, doc_id):
    get_db().add_node(KB_NAMESPACE, entity_node_id(name), node_type or 'entity',
                      {'doc_id': str(doc_id)})


def add_triple_edge(doc_id, page_no, triple):
    db = get_db()
    head = entity_node_id(triple['head'])
    tail = entity_node_id(triple['tail'])
    db.add_node(KB_NAMESPACE, head, triple.get('headType') or 'entity',
                {'doc_id': str(doc_id)})
    db.add_node(KB_NAMESPACE, tail, triple.get('tailType') or 'entity',
                {'doc_id': str(doc_id)})
    db.add_edge(KB_NAMESPACE, head, triple['rel'], tail,
                {'doc_id': str(doc_id), 'page_no': str(page_no)})
    db.add_edge(KB_NAMESPACE, head, 'appears_in', doc_node_id(doc_id),
                {'doc_id': str(doc_id)})
    db.add_edge(KB_NAMESPACE, tail, 'appears_in', doc_node_id(doc_id),
                {'doc_id': str(doc_id)})


def delete_doc_graph(doc_id, triples):
    db = get_db()
    for t in triples:
        try:
            db.delete_edge(entity_node_id(t['head']), t['rel'],
                           entity_node_id(t['tail']), KB_NAMESPACE)
        except Exception as e:
            logger.warning('delete_edge failed: %s', e)
        try:
            db.delete_edge(entity_node_id(t['head']), 'appears_in',
                           doc_node_id(doc_id), KB_NAMESPACE)
        except Exception:
            pass
        try:
            db.delete_edge(entity_node_id(t['tail']), 'appears_in',
                           doc_node_id(doc_id), KB_NAMESPACE)
        except Exception:
            pass
    try:
        db.delete_node(doc_node_id(doc_id), KB_NAMESPACE)
    except Exception:
        pass


def graph_context(doc_ids, max_depth=2):
    """围绕给定文档节点双向遍历图,返回三元组与实体名。"""
    db = get_db()
    start = [doc_node_id(d) for d in doc_ids]
    seen_nodes = set(start)
    frontier = start
    edge_list = []
    for _ in range(max_depth):
        nxt = []
        for node in frontier:
            try:
                nb = db.get_neighbors(node, direction='both',
                                      namespace=KB_NAMESPACE)
            except Exception:
                continue
            for item in nb.get('neighbors', []):
                edge = item.get('edge') or {}
                f, r, t = (edge.get('from_id'), edge.get('edge_type'),
                           edge.get('to_id'))
                if f and r and t:
                    edge_list.append((f, r, t))
                nid = item.get('node_id')
                if nid and nid not in seen_nodes:
                    seen_nodes.add(nid)
                    nxt.append(nid)
        frontier = nxt
        if not frontier:
            break
    triples = []
    entities = set()
    seen_edges = set()
    for f, r, t in edge_list:
        if r == 'appears_in':
            continue
        entities.add(f)
        entities.add(t)
        key = (f, r, t)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        triples.append({'head': f, 'rel': r, 'tail': t})
    return triples, sorted(e for e in entities if e)
