"""This module has been deprecated, all TTS logic is part of OPM now
The 2 methods below remain for backwards compatibility only
TODO: move these to ovos_utils
"""
import hashlib
from pathlib import Path


def hash_sentence(sentence: str):
    """Convert the sentence into a hash value used for the file name

    Args:
        sentence: The sentence to be cached
    """
    encoded_sentence = sentence.encode("utf-8", "ignore")
    sentence_hash = hashlib.md5(encoded_sentence).hexdigest()

    return sentence_hash


def hash_from_path(path: Path) -> str:
    """Returns hash from a given path.

    Simply removes extension and folder structure leaving the hash.

    Args:
        path: path to get hash from

    Returns:
        Hash reference for file.
    """
    return path.with_suffix('').name
