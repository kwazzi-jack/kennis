"""An OpenAI-compatible embedding service, as the server sees kennis.

`embedding.backend = openai` with `embedding.base_url` reaches any server
that implements OpenAI's embeddings endpoint. What such a server receives is
asserted here against a stand-in on loopback, which the network guard lets
through: the path under the base URL, the model, the texts, the key, and the
format of the vectors asked for. OpenAI's own client asks for base64 unless
told otherwise, and a server that implements only the API's default, float,
would refuse the first request of an index build (Brian, 2026-10-31).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from kennis.engine.rag import embedding
from kennis.engine.rag.embedding import ModelBinding, embedder_for

MODEL = "a-compatible-model"
KEY = "a-key-for-the-stand-in"


class Recorded:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.bodies: list[dict[str, object]] = []
        self.authorisations: list[str] = []


@pytest.fixture
def stand_in() -> Iterator[tuple[str, Recorded]]:
    """A server answering `/v1/embeddings` as OpenAI's API documents it,
    in floats, the format a server must support."""
    recorded = Recorded()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length))
            recorded.paths.append(self.path)
            recorded.bodies.append(body)
            recorded.authorisations.append(self.headers.get("authorization", ""))
            if body.get("encoding_format", "float") != "float":
                self.send_response(400)
                self.end_headers()
                return
            texts = body["input"]
            answer = {
                "object": "list",
                "model": body["model"],
                "data": [
                    {
                        "object": "embedding",
                        "index": index,
                        "embedding": [1.0, 2.0, 2.0],
                    }
                    for index, _ in enumerate(texts)
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
            encoded = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *arguments: object) -> None:
            """Quiet: the test reads what was recorded."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1", recorded
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KENNIS_EMBEDDING_API_KEY_ENV", "A_COMPATIBLE_KEY")
    monkeypatch.setenv("A_COMPATIBLE_KEY", KEY)


def test_a_compatible_server_receives_the_request_in_openai_s_form(
    stand_in: tuple[str, Recorded], keyed: None
):
    address, recorded = stand_in
    embedder = embedder_for(ModelBinding(kind="openai", model=MODEL, host=address))

    vectors = embedder.embed(["first passage", "second passage"])

    assert recorded.paths == ["/v1/embeddings"]
    body = recorded.bodies[0]
    assert body["model"] == MODEL
    assert body["input"] == ["first passage", "second passage"]
    assert recorded.authorisations == [f"Bearer {KEY}"]
    assert np.allclose(vectors, [[1.0, 2.0, 2.0], [1.0, 2.0, 2.0]])


def test_a_compatible_server_is_asked_for_floats(
    stand_in: tuple[str, Recorded], keyed: None
):
    """The API's own default, which every compatible server supports;
    base64 is OpenAI's client's choice, and an option a server may lack."""
    address, recorded = stand_in

    embedder_for(ModelBinding(kind="openai", model=MODEL, host=address)).embed(["x"])

    assert recorded.bodies[0]["encoding_format"] == "float"


def test_openai_s_own_service_keeps_the_client_s_compact_answer(
    monkeypatch: pytest.MonkeyPatch, keyed: None
):
    """No base URL is OpenAI itself, where base64 is about half the bytes of
    an index build's answers; the format is left to the client there."""
    asked: list[dict[str, object]] = []

    class Answer:
        def __init__(self) -> None:
            self.data: list[object] = []

    class Embeddings:
        def create(self, **options: object) -> Answer:
            asked.append(options)
            return Answer()

    class Client:
        def __init__(self, **options: object) -> None:
            self.embeddings = Embeddings()

    import openai

    monkeypatch.setattr(openai, "OpenAI", Client)

    embedding._OpenAiEmbedder(ModelBinding(kind="openai", model=MODEL)).embed(["x"])

    assert "encoding_format" not in asked[0]
