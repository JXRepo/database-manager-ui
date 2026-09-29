"""
Rank platform help with a pinned local sentence embedding model

Only explicit setup downloads public model files. Question matching is offline.
"""

import hashlib
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from django.conf import settings


MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
MODEL_FILES = (
    ("model.onnx", "onnx/model_quint8_avx2.onnx", 118453870,
     "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f"),
    ("sentencepiece.bpe.model", "sentencepiece.bpe.model", 5069051,
     "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865"),
)
_inference_lock = threading.Lock()


class ModelUnavailable(RuntimeError):
    """
    Signal that prepared help choices should replace semantic matching
    """


def model_directory():
    """
    Return the local model asset directory
    """
    default = settings.BASE_DIR / ".assistant-models" / MODEL_REVISION
    return Path(getattr(settings, "ASSISTANT_MODEL_DIR", default))


def _verified(path, size, digest):
    """
    Check one asset against its pinned size and SHA-256 digest

    Parameters
    ----------
    path : Path
        Local asset path.
    size : int
        Expected bytes.
    digest : str
        Expected SHA-256 hex digest.

    Returns
    -------
    bool
        Whether the complete trusted asset is present.
    """
    try:
        if path.stat().st_size != size:
            return False
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest() == digest
    except OSError:
        return False


def assets_ready(directory):
    """
    Verify that all model assets are present without contacting a server

    Parameters
    ----------
    directory : Path
        Directory containing model files.

    Returns
    -------
    bool
        Whether both assets match the pinned snapshot.
    """
    return all(_verified(directory / name, size, digest) for name, _, size, digest in MODEL_FILES)


def prepare_model():
    """
    Download and verify missing model assets during explicit setup

    Returns
    -------
    Path
        Directory containing verified model files.
    """
    import requests

    directory = model_directory()
    directory.mkdir(parents=True, exist_ok=True)
    for name, source, size, digest in MODEL_FILES:
        target = directory / name
        if _verified(target, size, digest):
            continue
        url = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{source}"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
                temporary = Path(handle.name)
                received = 0
                with requests.get(url, stream=True, timeout=(10, 60)) as response:
                    response.raise_for_status()
                    for chunk in response.iter_content(1024 * 1024):
                        received += len(chunk)
                        if received > size:
                            raise ValueError(f"Unexpected size for assistant model asset {name}")
                        handle.write(chunk)
            if not _verified(temporary, size, digest):
                raise ValueError(f"Integrity check failed for assistant model asset {name}")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return directory


class _Encoder:
    """
    Keep one CPU encoder and public help vectors per web process
    """

    def __init__(self, directory):
        """
        Load verified assets without importing a training framework

        Parameters
        ----------
        directory : Path
            Verified local asset directory.
        """
        import numpy as np
        import onnxruntime as ort
        import sentencepiece as spm

        self.np = np
        self.tokenizer = spm.SentencePieceProcessor(model_file=str(directory / "sentencepiece.bpe.model"))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        self.session = ort.InferenceSession(str(directory / "model.onnx"), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.examples = ()
        self.vectors = None

    def encode(self, texts):
        """
        Encode short texts with XLM-R IDs and attention-mask mean pooling

        Parameters
        ----------
        texts : sequence of str
            Texts to encode, capped at 128 model tokens each.

        Returns
        -------
        numpy.ndarray
            Unit vectors with 384 dimensions.
        """
        np = self.np
        vectors = []
        # Quantize each sentence independently so unrelated index entries do not
        # change its activation scale or its similarity to a standalone query
        for text in texts:
            pieces = self.tokenizer.encode(text, out_type=int)[:126]
            # XLM-R reserves 0/1/2/3 for start, padding, end and unknown
            ids = np.asarray([[0] + [piece + 1 if piece else 3 for piece in pieces] + [2]], dtype=np.int64)
            output = self.session.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids),
                                             "token_type_ids": np.zeros_like(ids)})[0]
            mean = output.mean(axis=1)
            vectors.append(mean / np.maximum(np.linalg.norm(mean, axis=1, keepdims=True), 1e-9))
        return np.concatenate(vectors)


@lru_cache(maxsize=1)
def _encoder(directory):
    """
    Load one trusted model while the caller holds the inference lock

    Parameters
    ----------
    directory : Path
        Local model directory.

    Returns
    -------
    _Encoder
        Reusable local encoder.
    """
    if not assets_ready(directory):
        raise ModelUnavailable("Run manage.py prepare_assistant_model during setup")
    try:
        return _Encoder(directory)
    except Exception as error:
        raise ModelUnavailable("The local assistant model could not be loaded") from error


def rank_topics(question, examples):
    """
    Rank topic examples by meaning without retaining user questions

    Parameters
    ----------
    question : str
        User question.
    examples : tuple of (str, str)
        Topic identifiers and maintained example questions.

    Returns
    -------
    list of (str, float)
        Topic scores in descending order.
    """
    if not _inference_lock.acquire(timeout=2):
        raise ModelUnavailable("Assistant matching is busy")
    try:
        encoder = _encoder(model_directory())
        if encoder.examples != examples:
            encoder.vectors = encoder.encode([text for _, text in examples])
            encoder.examples = examples
        query = encoder.encode([question])[0]
        scores = {}
        for (topic, _), score in zip(examples, encoder.vectors @ query):
            scores[topic] = max(scores.get(topic, -1.0), float(score))
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)
    except ModelUnavailable:
        raise
    except Exception as error:
        raise ModelUnavailable("The local assistant could not match this question") from error
    finally:
        _inference_lock.release()
