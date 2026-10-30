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

## How much text a model reads

Every embedding model reads at most a fixed number of *tokens* - pieces of
words - per chunk. A chunk longer than that is refused or cut short,
depending on the backend:

| model | backend | tokens it reads | past that |
|---|---|---|---|
| `text-embedding-3-small`, `text-embedding-3-large` | openai | 8192 | the request is refused |
| `BAAI/bge-small-en-v1.5` | fastembed | 512 | the rest of the chunk is ignored, with no message |
| `nomic-embed-text` | ollama | 8192 | depends on the context Ollama runs it with |

The limits are the models' published ones. kennis knows these four and
treats any other model's limit as unknown, never as large enough.

**When an index is built**, kennis checks each passage it embeds:

- for **openai**, a passage longer in bytes than the limit is shortened, at a
  character, before it is sent. OpenAI's tokenizer never makes more tokens
  than a text has bytes, so a request can no longer be refused for length;
- for **fastembed**, the model's own tokenizer counts exactly which passages
  it will cut short;
- for **ollama**, nothing: it exposes no tokenizer, and cuts a long text by
  itself.

If any passage was not read whole, the build ends with one warning saying how
many. A meaning search does not see the end of such a passage; the keyword
search always reads all of it.

**When you change `chunking.size`, `embedding.backend` or `embedding.model`**,
with `kennis config set` or on the settings page, kennis says whether a chunk
of that size fits the model, using the ratios below - as a warning when it
may not. On the settings page the line is under the chunk size, and changes
as the size is changed.

How many tokens a chunk is depends on what it holds. Measured on one
corpus of papers, documentation and notes, with OpenAI's tokenizer:

| content | characters per token |
|---|---|
| prose | about 4.2 |
| code | about 3.1 |
| display maths | about 2.6 |
| tables | about 1.8 |
| the densest chunk | 1.3 |

A chunk is at most the ceiling, twice `chunking.size` (see [How retrieval
works](../explanation/retrieval.md#how-a-document-is-cut)), so at the default
size of 1500 a chunk is at most 3000 characters: at worst about 2300 tokens,
within OpenAI's 8192. With `bge-small`, a prose chunk of 1500 characters is
about 360 tokens and fits, but a dense table of the same length does not, and
its end is not seen by the dense leg. BM25 always reads the whole chunk.

## Changing backend

`kennis config init` and the settings page offer each backend's own model when
the backend is changed, so accepting what they offer keeps the two in step.
`kennis config set` changes one value and offers nothing, which is why the
commands above set the model as well as the backend.

There is no setting for the width of a vector. The model fixes it, and kennis
takes it from the vectors the model returns.
