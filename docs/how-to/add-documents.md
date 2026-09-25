# Add documents

`kennis corpus add` takes files, directories or URLs, and writes them into
exactly one collection. There is no "add to all three" - where a document
belongs is a decision, not a default.

```
kennis corpus add <sources>... --collection <literature|docs|notes>
```

The three shorthands `-l`, `-d` and `-n` mean the same as
`--collection literature|docs|notes`.

## A paper

```
kennis corpus add paper.pdf -l
```

PDF, DOCX, PPTX and XLSX are converted to markdown first. See
[Conversion](#conversion) below.

If you know the paper's identifier, supply it rather than letting kennis
infer one. It decides the document's own identifier, so getting it right
matters:

```
kennis corpus add paper.pdf -l --identifier arxiv:1101.1764
kennis corpus add paper.pdf -l --identifier 10.1088/0004-637X/728/1/27
```

To fetch by identifier without a local file:

```
kennis corpus add arxiv:1101.1764 -l
```

Override a derived citekey with `--citekey`, and a detected title with
`--title`.

## A note

```
kennis corpus add meeting.md -n
```

A note keeps the filename it arrived with. To write one directly instead of
adding a file, use [`kennis remember`](#write-a-note-directly).

## A documentation site

```
kennis corpus add https://stimela.readthedocs.io/en/latest/ -d --project stimela
```

kennis crawls from that page, converts each page to markdown, and files them
all under the project's group. Two limits apply, both adjustable:

```
--max-pages 300     # default
--max-depth 5       # default
```

`--project` is what the pages are grouped under, and is also what `--project`
on a search filters by.

## A directory

```
kennis corpus add ~/papers/ -l
```

Every readable file in it, converted as needed.

## Grouping

`--group` files documents into a subdirectory of the collection:

```
kennis corpus add paper.pdf -l --group radio-astronomy
```

Groups are ordinary directories and can nest. They are what `--group` filters
on at search time.

## Keeping the source

By default kennis keeps the markdown and discards the source bytes. To keep
both:

```
kennis corpus add paper.pdf -l --keep-original
```

Or set `corpus.keep_original = true` to make it the default.

## Conversion

Anything that is not already markdown or plain text goes through a converter.

**mineru** is the default. It runs locally, costs nothing, and is installed
with the `mineru` extra:

```
uv tool install "kennis[mineru] @ ."
```

**datalab** is hosted. It is chosen only by setting `conversion.backend` **and**
supplying an API key, because sending a document to a third party is never
something kennis does by default. See
[Keep credentials out of the config](credentials.md).

## Write a note directly

```
kennis remember "Cosine cuts only mean anything per-model."
kennis remember --from draft.md --title "Retrieval notes"
```

`remember` writes into `notes` and updates the notes index in the same
command - **once an index exists**. Before the first `kennis corpus index`
there is nothing to update, and it says `not indexed` and tells you so. Pass
`--no-index` to skip the update when adding several in a row.

## Then index

Adding a document does not make it searchable. Indexing does:

```
kennis corpus index                        # all three collections
kennis corpus index --collection docs      # just one
```

The first dense index downloads the embedding model - about 65 MB for the
default - and kennis prints a line saying so before it starts.

Reading does **not** require an index:

```
kennis read <handle>              # works on an unindexed document
kennis read <handle> --chunks 3   # needs the index, since chunks live there
```
