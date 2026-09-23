# Milestone 5, item 4: `kennis remember`

Milestone / step: plan milestone 5 item 4, the last item - "`kennis
remember`, writing to notes by default". Design section 12.
Date: 2026-09-23

Previous sketch: `2026-09-23-m5m-the-lock-under-real-contention.md`.

## What I am about to do

One verb that takes prose rather than identifiers, writes it into the notes
collection as an ordinary document, and indexes its own write so the thing
just remembered is findable in the same session.

    kennis remember "QuartiCal needs --input-ms-time-chunk tuned for long tracks"
    kennis remember --from notes.md
    echo "..." | kennis remember

Design section 12 also gives `--context`, writing into a workspace's
`.context/`. **That is not built here.** The context bundle is 0.3 and there
is nowhere for it to write. The design's own rule about `auto_sync` applies -
a setting nothing reads is hidden rather than offered - so the flag is absent
rather than present and failing.

## How I expect it to work

### The write: `engine/corpus/remember.py`

Prose is not a source file, so it does not go through `resolve_inputs` or a
converter. It becomes a `Converted` directly and reuses the note writer that
`add_notes` already has:

    Converted(
        markdown=text,
        via="remember",          # new value in ConversionVia
        format="markdown",
        origin="remember:inline" | f"path:{path}",
        sha256=sha256_of(text.encode()),
        suggested_title=title_from_markdown(text, <derived>),
    )

`via="remember"` is what section 12 asks for and is the whole point: it
distinguishes a thing the user told kennis from a document kennis ingested,
and no other value in the vocabulary says that. `owner="user"` comes free -
`_write` already sets it - which is the second half of section 12's promise,
that no pack and no sync will ever overwrite it.

`sha256` is set deliberately, so `_duplicate_of` catches the same note
remembered twice and reports `UNCHANGED` rather than writing a second copy.
An agent repeating itself is the expected case once the MCP server exists.

`add.py:_write` becomes public as `write_note`, and `_Uniqueness` becomes
`Uniqueness`. Both are exactly what is needed and duplicating either would
mean two pieces of code minting identifiers against different views of the
collection.

**The title**, in order: `--title`; a leading `# Heading`; otherwise the
first line, trimmed at a word boundary to 60 characters. A note is addressed
by its identifier, but its filename comes from its title, so the fallback has
to be something a person can recognise in `corpus tree`.

### The index: `engine/indexing.py`

`corpus index` currently assembles the build itself in `cli/commands/
corpus.py` - binding, index root, repository, batch size. `remember` needs
the same assembly, so it moves into the engine as

    reindex_collection(corpus_root, name, settings, *, repository, events)
        -> BuildReport | None

returning `None` for an empty collection, which is what `index_command`
already special-cases. Both callers then use it.

**It indexes only a collection that already has an index.** This is the
degradation, and it is not the one section 16 describes. Section 16's case is
lock contention; this is cost. A notes collection of 500 documents that has
never been indexed would make `remember` pay a full cold build - 50s for a
1942-chunk corpus by section 15's measurement - for a one-line note. With a
manifest already present the vector cache holds every existing chunk, so the
rebuild embeds only the new ones and the cost is a BM25 rebuild plus roughly
40ms. So: manifest present, index; absent, write the note and report that
`kennis corpus index` is what makes it findable.

`IndexOutcome` is therefore `indexed | unindexed | skipped`, a value the
engine names and `render/` phrases. Not a sentence: the invariant (#81) is
that a value carrying the facts as fields must not also carry a sentence
built from them.

### The command: `cli/commands/remember.py`

    kennis remember [TEXT] [--from PATH] [--title TEXT] [--group TEXT] [--no-index]

- `TEXT`, `--from` and standard input are three routes to one string, and
  giving two of them is an error rather than a precedence rule.
- No text anywhere, with standard input a terminal: an error naming
  `kennis remember --help`.
- The corpus lock is taken for the whole command, as every other mutating
  command does, and one commit follows: `remember(notes): 1 document`.

`_existing_corpus` is copied in `commands/corpus.py` and `commands/
search.py` already. A third copy would be silly, so it moves to
`cli/context.py` and all three use it.

## What I expect to be uncertain or difficult

1. **Whether `remember` may take the corpus lock at all.** Section 16 says it
   "must not block a tool call waiting for a lock" and that on contention it
   writes the note anyway and defers the index. But that section assumes a
   per-collection *index* lock, and what was built is one corpus-wide lock
   around every mutating command. Writing the note without it would race
   `corpus restore` and git. I expect to take the lock and fail fast like
   everything else, and to log the divergence - the case section 16 is about
   is an MCP server that does not exist until 0.2.
2. **The first-line title.** Truncation at a word boundary, an empty first
   line, a note that is one long unbroken token, a title that is entirely
   punctuation and cleans to nothing. `title_filename` already falls back to
   `untitled.md`, so the failure mode is a filename rather than a crash.
3. **The crossing test.** The plan's own named risk: a document written by a
   new path that the loader cannot see, silently. Remember, then search,
   then assert the text comes back - written before the implementation.
4. **The model download inside a `remember`.** A machine that has never
   embedded pays 33s. `corpus index` announces it; `remember` must too, or it
   looks hung. Restricting to collections that already have a manifest
   removes most of this case but not all of it: a lexical index has no model
   and switching the backend afterwards would hit it.
5. **Whether the body should be normalised at all.** I think not: section 12
   says this takes prose, and the one correct thing to do with prose the user
   typed is store it unchanged. No ligature repair, no markdown
   normalisation - both exist to undo a converter's damage and there is no
   converter here.

## What actually happened that I did not expect

### The extraction I planned was not worth making

The sketch said `corpus index`'s assembly would move into an
`engine/indexing.py` that `remember` would share. Writing it showed the
shared part is one `build_index` call with its arguments; everything else
`index_command` does - the backend announcement, the loop over three
collections, the empty-collection skip, the commit - belongs to that command
and not to `remember`. A module to hold six lines with two callers would have
been an abstraction extracted from one example. `remember` calls `build_index`
directly and `index_command` is untouched.

### Uncertainty 4 was a real defect, and the test that found it downloaded a
### model while failing

I expected the manifest restriction to remove most of the model-download
case. It does not. `read_manifest` answers "is there an index", and a user
who indexed lexically and then set `embedding.backend` has one - a lexical
one. `remember` would then build the *dense* index: download the model and
re-embed every existing chunk, 33s plus 50s by section 15, inside a command
that had just cost 7ms.

The test asserting this fails printed `Fetching 5 files` while failing, which
is the defect happening in front of me rather than being argued about. The
fix compares `manifest.index_id` against `index_id_for(binding)`, so
`remember` only ever extends an index of the kind it would have built.

Both causes - no index, and an index of another kind - report `unindexed`,
because the thing the reader needs to know is the same in both: the note is
not in the published index and `kennis corpus index` is what puts it there.

### Running the command found the trailing full stop

1422 tests passed and the first real note landed on disk as

    Ionospheric screens need direction-dependent solutions..md

Remembered prose is a sentence, `title_filename` appends `.md`, and every
fixture I had written was a fragment or a heading. This is the sixth time in
this project that running the command found what the suite did not, and the
pattern is the same every time: the fixtures shared a property with each
other that real input does not have.

`remember(notes): 1 documents` in the commit subject is *not* a defect, which
was worth checking rather than assuming. `commit_summary` is a storage format
that `_SUBJECT` parses back, and it is deliberately unpluralised so that the
writer and the reader are two halves of one format.

### Uncertainty 1 resolved against the design, and is logged

`remember` takes the corpus lock and fails fast like every other mutating
command. Design section 16 would have it write the note and defer only the
index, but that rests on a per-collection index lock that was never built -
what exists is one corpus-wide lock. Writing a note outside it would race
`corpus restore` and git's own index. Concern #167 records the divergence and
what would have to change to honour section 16, which is an 0.2 question
because the agent it protects does not exist until the MCP server does.

### The title rules, and what they cost

Three tests pin the derivation and all three were caught by injection:
a heading wins, a first line is trimmed between words at 60 characters, and
a derived title loses its trailing sentence punctuation while a given one
keeps it. The last distinction is the one I would not have thought to make
before seeing `solutions..md`.

### Two duplications removed, one left alone

`_existing_corpus` existed twice and would have been three times, so it is
now `cli/context.py:existing_corpus`. `add.py`'s `_write`, `_Uniqueness` and
`_duplicate_of` became `write_note`, `Uniqueness` and `duplicate_of` rather
than being copied, because two writers minting identifiers against different
views of a collection is exactly the bug the record exists to prevent.

### What it does on a real corpus

    Remembered QuartiCal needs --input-ms-time-chunk tuned for long, not indexed in 1ms
      hint: run `kennis corpus index` to make it searchable
    Remembered Ionospheric screens need direction-dependent solutions, indexed, 2 chunks in 7ms
    Found 1 passage
      = [notes] Ionospheric screens need direction-dependent solutions.  (326dql1vze)

The second note was searchable in the same shell, 7ms after being written,
which is what section 12 promises.
