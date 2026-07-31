import logging

from .config import KB_EMBED_MODEL

logger = logging.getLogger(__name__)

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        logger.info('loading embedding model %s ...', KB_EMBED_MODEL)
        _embedder = TextEmbedding(model_name=KB_EMBED_MODEL)
    return _embedder


def embed_texts(texts):
    return [v.tolist() for v in get_embedder().embed(list(texts))]


def embed_text(text):
    return embed_texts([text])[0]
