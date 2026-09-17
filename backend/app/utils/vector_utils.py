# app/utils/vector_utils.py
"""Conversion between Python float lists and pgvector's text literal.

Vectors travel to Postgres as text and are cast in SQL (``$1::text::vector``).
That keeps the driver free of any vector codec, so a connection established
before the extension is registered still works.
"""

from typing import List, Optional, Sequence


def to_pgvector(vector: Optional[Sequence[float]]) -> Optional[str]:
    """``[0.1, 0.2]`` -> ``'[0.1,0.2]'``"""
    if vector is None:
        return None
    return "[" + ",".join(f"{float(v):.6f}" for v in vector) + "]"


def from_pgvector(literal: Optional[str]) -> Optional[List[float]]:
    """``'[0.1,0.2]'`` -> ``[0.1, 0.2]``"""
    if not literal:
        return None
    stripped = literal.strip().strip("[]")
    if not stripped:
        return []
    return [float(part) for part in stripped.split(",")]
