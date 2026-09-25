# Tutorial: your first corpus

Fifteen minutes, from nothing to a corpus you can search by meaning. Every
command and every output below was run; only the corpus paths are shown at
their default location rather than the throwaway one used to produce them.

You will need kennis [installed](install.md). Nothing else - this
tutorial uses no PDFs and no API keys.

## 1. Set kennis up

```
kennis config init
```

The wizard asks only what depends on you, and every question offers what is
already in effect, so pressing return throughout is a valid run. Accept the
defaults: `fastembed` for embedding, which runs locally and needs no key.

To skip it entirely and take every default:

```
kennis config init --defaults
```

## 2. Create the corpus

```
kennis corpus init
```

```
Created corpus at /home/you/.local/share/kennis/corpus
```

That directory is now a git repository. Everything from here commits.

## 3. Write three notes

`kennis remember` writes a note and files it in the `notes` collection.

```
kennis remember "Reciprocal rank fusion scores a chunk by 1/(60+rank) summed \
over the legs that ranked it, so agreement between two methods that fail \
differently is what wins." --title "Why fusion uses ranks"
```

```
Remembered Why fusion uses ranks, not indexed in 1ms
  + /home/you/.local/share/kennis/corpus/notes/Why fusion uses ranks.md
  hint: run `kennis corpus index` to make it searchable
```

Two things to notice.

The note is a real file with the name you gave it, in a directory you can
open in any editor. kennis stores markdown, not a database.

And it says **not indexed**. Writing a document and making it searchable are
separate steps, and kennis tells you which one has happened. Once an index
exists, `remember` updates it in the same command; the first note has no
index to update yet.

Add two more:

```
kennis remember "A cosine similarity has an absolute meaning only for the \
model that produced it. Cuts measured for one embedding model say nothing \
about another." --title "Relevance bands are per-model"

kennis remember "The corpus is ordinary markdown in ordinary directories. A \
directory holding content.md is a document with assets; any other directory \
is a group." --title "Corpus layout"
```

## 4. Index them

```
kennis corpus index
```

```
Using fastembed BAAI/bge-small-en-v1.5
Indexed 3 documents as 3 chunks in notes in 380ms
```

The first time you run this, kennis downloads the embedding model - about
65 MB - and prints a line saying so before it starts. It is cached in
`~/.cache/kennis/models`, so this happens once and survives a reboot.

## 5. Search

Here is the point of the whole exercise. Ask a question that shares **almost
no words** with any note:

```
kennis search "why do we combine rankings instead of scores"
```

```
warning: not searched, no index yet: literature, docs
  hint: run `kennis corpus index`
Found 4 passages, relevance by cosine similarity
  [1] [notes] Why fusion uses ranks
      relevance: medium  id=30ed1x2rt8 chunk=0
      Reciprocal rank fusion scores a chunk by 1/(60+rank) summed over the
      legs that ranked it, so agreement between two methods that fail
      differently is what wins.
  [2] [notes] Relevance bands are per-model
      relevance: low  id=gs0wo39jle chunk=0
      A cosine similarity has an absolute meaning only for the model that
      produced it. Cuts measured for one embedding model say nothing about
      another.
```

The query and the winning note share one word, "scores", and it is not even
used in the same sense. A keyword search would not have found it. The dense
leg matched on meaning.

Your identifiers will differ from these - they are minted per document.

Three things in that output are worth reading properly.

**The warning.** Two collections have no index because they have no
documents. kennis says which, rather than quietly searching less than you
asked it to.

**`relevance by cosine similarity`.** This names the scale the levels are on.
Here it is absolute: `medium` means the same thing for every query, because
the cuts were measured for this specific model. That is why the top hit is
`medium` and not `very high` - it is a decent match, and kennis says so
rather than flattering the best result it happened to find.

**`id=` and `chunk=`.** The coordinates for reading.

## 6. Read

```
kennis read 30ed1x2rt8
```

```
Read [notes] Why fusion uses ranks  (30ed1x2rt8)  .../notes/Why fusion uses ranks.md
Reciprocal rank fusion scores a chunk by 1/(60+rank) summed over the legs
that ranked it, so agreement between two methods that fail differently is
what wins.
```

The `Read ...` provenance line goes to **standard error**, the document goes
to **standard output**. So this gives you the markdown and nothing else:

```
kennis read 30ed1x2rt8 > note.md
```

For a long document, read just the passage a hit pointed at:

```
kennis read 30ed1x2rt8 --chunks 0:2
```

## 7. See the difference a model makes

Run the same kind of search with the dense leg switched off:

```
kennis search "rank" --mode bm25 --snippet none
```

```
Found 1 passage, relevance relative to the best lexical match
  [1] [notes] Why fusion uses ranks
      relevance: very high  id=30ed1x2rt8 chunk=0
  hint: run `kennis read 30ed1x2rt8 --chunks 0:2` to read one in context
```

The summary line has changed. With no dense leg there is no absolute scale,
so the level is a fraction of this query's own best hit - and the top hit of
a lexical search is `very high` by construction. kennis changes the wording
rather than presenting a relative number as though it were absolute.

## 8. Look at what you built

```
kennis corpus tree
```

```
Literature
Docs
Notes
  dxk40v39l3  Corpus layout.md
  gs0wo39jle  Relevance bands are per-model.md
  30ed1x2rt8  Why fusion uses ranks.md
```

```
kennis corpus history
```

Every step committed. Nothing you have done is unrecoverable.

## Where to go next

- [Add documents](../how-to/add-documents.md) - papers, PDFs, whole
  documentation sites
- [How retrieval works](../explanation/retrieval.md) - what the relevance
  levels actually mean
- [Commands](../reference/cli.md) - every option
