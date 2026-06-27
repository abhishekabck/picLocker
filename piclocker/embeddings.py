import logging

import numpy as np
from sentence_transformers import SentenceTransformer
from PIL import Image
from piclocker import config

log = logging.getLogger("piclocker.embeddings")

__model = None


def __create_model():
    log.info("loading CLIP model %s (first use may download ~600MB)...", config.CLIP_MODEL)
    model = SentenceTransformer(config.CLIP_MODEL)
    log.info("CLIP model loaded")
    return model

def get_model():
    global __model
    if __model is None:
        __model = __create_model()
    return __model

def get_embedding(image) -> np.ndarray:
    return get_model().encode(image)

def encode_text(text) -> np.ndarray:
    return get_model().encode(text)
