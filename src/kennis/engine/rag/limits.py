"""How much an embedding model reads, and whether a chunk fits it (#577).

A model reads at most a fixed number of tokens per text. Past it OpenAI
refuses the request and fastembed's models drop the rest without a word,
so what the dense leg sees of a long chunk depends on the model. The chunk
ceiling bounds a chunk's characters (#578); this module turns that bound
into tokens for a model, and says when it is not enough.

**The ratios are measured, not assumed.** Characters per token over 10,076
chunks of one corpus of papers, documentation and notes (Brian's,
2026-10-30, with OpenAI's `cl100k_base`): about 4.2 for prose and 1.3 for
the densest chunk, a table. An estimate built on them is an estimate, and
every front end says so.

**The limits are the models' published ones.** A model not in the table is
unknown, never assumed to fit. fastembed's loaded tokenizer states its own
limit, and the index build reads it there rather than here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from kennis.engine.rag.chunking import ChunkParameters

PROSE_CHARACTERS_PER_TOKEN: Final = 4.2
DENSEST_CHARACTERS_PER_TOKEN: Final = 1.3

INPUT_TOKENS: Final[dict[tuple[str, str], int]] = {
    ("openai", "text-embedding-3-small"): 8192,
    ("openai", "text-embedding-3-large"): 8192,
    ("openai", "text-embedding-ada-002"): 8191,
    # Read from its tokenizer: `truncation.max_length` is 512.
    ("fastembed", "BAAI/bge-small-en-v1.5"): 512,
}

type FitVerdict = Literal["fits", "dense-may-not-fit", "may-not-fit", "unknown"]


def input_tokens(backend: str, model: str) -> int | None:
    """The most tokens `model` reads per text, where kennis knows it."""
    return INPUT_TOKENS.get((backend, model))


@dataclass(frozen=True, slots=True)
class ChunkFit:
    """How a chunk of this size compares with what the model reads.

    `prose_tokens` estimates a chunk of prose at the size; `densest_tokens`
    the worst chunk at the ceiling. `model_tokens` is None when the limit is
    unknown, and the verdict is then `unknown`.
    """

    ceiling: int
    prose_tokens: int
    densest_tokens: int
    model_tokens: int | None
    verdict: FitVerdict


def chunk_fit(size: int, backend: str, model: str) -> ChunkFit | None:
    """Whether chunks of `size` fit `model`, or None with no model at all."""
    if backend == "none":
        return None
    ceiling = ChunkParameters(size=size).ceiling
    prose = round(size / PROSE_CHARACTERS_PER_TOKEN)
    densest = round(ceiling / DENSEST_CHARACTERS_PER_TOKEN)
    limit = input_tokens(backend, model)
    verdict: FitVerdict
    if limit is None:
        verdict = "unknown"
    elif densest <= limit:
        verdict = "fits"
    elif prose <= limit:
        verdict = "dense-may-not-fit"
    else:
        verdict = "may-not-fit"
    return ChunkFit(
        ceiling=ceiling,
        prose_tokens=prose,
        densest_tokens=densest,
        model_tokens=limit,
        verdict=verdict,
    )


def shortened_to_bytes(texts: Sequence[str], limit: int) -> tuple[list[str], int]:
    """`texts` with each one cut to at most `limit` UTF-8 bytes, and how many
    were cut.

    For a byte-level tokenizer, OpenAI's: every token covers at least one
    byte, so a text of at most `limit` bytes is at most `limit` tokens and
    cannot be refused for length. None of 10,076 measured chunks had more
    tokens than bytes. Cut at a character, never inside one. Decided by the
    text and the limit alone, so a cached vector made from a cut passage is
    the one the same passage gets again.
    """
    sent: list[str] = []
    shortened = 0
    for text in texts:
        encoded = text.encode("utf-8")
        if len(encoded) <= limit:
            sent.append(text)
            continue
        # The bytes are a prefix of valid UTF-8, so the only undecodable
        # part is a character the cut went through, at the very end.
        sent.append(encoded[:limit].decode("utf-8", errors="ignore"))
        shortened += 1
    return sent, shortened


__all__ = [
    "DENSEST_CHARACTERS_PER_TOKEN",
    "INPUT_TOKENS",
    "PROSE_CHARACTERS_PER_TOKEN",
    "ChunkFit",
    "FitVerdict",
    "chunk_fit",
    "input_tokens",
    "shortened_to_bytes",
]
