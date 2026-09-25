# Choose an embedding backend

The embedding backend turns chunks and queries into vectors, which is what
the dense leg of a search ranks by. Four choices.

| backend | runs | needs | notes |
|---|---|---|---|
| `fastembed` | locally | nothing | the default; downloads a 65 MB model on first index |
| `ollama` | locally, via a daemon | ollama installed | pulls the model if the daemon lacks it |
| `openai` | hosted | an API key | sends your text to OpenAI |
| `none` | - | nothing | lexical search only |

```
kennis config set embedding.backend ollama
kennis config set embedding.model nomic-embed-text
```

Changing the backend or the model means the stored vectors no longer match
what a query would produce, so **reindex**:

```
kennis corpus index
```

## fastembed

The default, and the one to keep unless you have a reason. It runs in-process
with no daemon and no key.

On first index it downloads `BAAI/bge-small-en-v1.5`, about 65 MB, into
`~/.cache/kennis/models`. kennis prints a line saying it is doing so. The
download is cached, so a reinstall or a reboot does not repeat it.

This is also the only model whose relevance bands kennis has **measured**, so
it is the only one where `relevance: high` is an absolute claim rather than a
comparative one. A different model still works; it just gets no relevance
level. See [How retrieval works](../explanation/retrieval.md).

## ollama

```
kennis config set embedding.backend ollama
kennis config set embedding.model nomic-embed-text
kennis config set embedding.base_url http://localhost:11434
```

If the daemon does not hold the model, kennis pulls it. That is the thing you
asked for by naming it, not a surprise - but note that a name is a name, and
a large one pulls a large model. `mxbai-embed-large` is 669 MB. A name ollama
does not recognise is a 404, so a typo is an error rather than a download.

## openai

```
kennis config set embedding.backend openai
kennis config set embedding.model text-embedding-3-small
```

This sends your document text to OpenAI. It needs a key, which does not go in
`config.toml` - see [Keep credentials out of the
config](credentials.md).

## none

```
kennis config set embedding.backend none
```

Lexical search only. BM25 still works, `--mode dense` has nothing to run, and
`--mode hybrid` falls back to `bm25` rather than failing. Relevance levels
become relative to each query's best hit, and the summary line says so.

Reasonable when the corpus is small, when your queries use the corpus's own
vocabulary, or when you do not want a model download at all.

## Dimensions

`embedding.dimensions` should match what the model actually produces - 384
for `BAAI/bge-small-en-v1.5`, 768 for `nomic-embed-text`.

!!! warning "Not currently validated"
    As of 0.1.1 kennis does not check this against the model. The model
    decides the real width regardless, so a wrong value does not corrupt
    your vectors or your search results - but it is recorded in the index's
    `binding.json` as though it were true, and because it forms part of the
    index identity, changing it forces a full reindex that achieves nothing.

    Set it correctly, or leave it at the default.
