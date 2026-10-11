# 13a. Backup: the archive, the operation and the command line

Milestone / step: milestone 13, first half (`design/plan.md`), #413, #420
Date: 2026-10-11

## What I am about to do

Write, check and restore an encrypted `.7z` of the corpus, from the
engine, through `operations.py`, and from the command line. The window's
Backup section is 13b. One setting, `backup.folder`; the password is
asked for each time and never stored.

## How I expect it to work

**`engine/backup.py`**, with `py7zr` (decided 2026-10-09):

- `members_of(corpus_root)` walks the corpus and returns
  `(path, "corpus/<relative>")` pairs for every directory and regular
  file, except `index/` at the top (it is rebuilt from the documents)
  and the lock file (it is a fact about this process, not the corpus).
  Symbolic links are not followed or stored. A link inside the corpus
  is something kennis never writes, and following one could put a file
  from outside the corpus into the backup.
- `write_backup(corpus_root, folder, password, events)` refuses an empty
  password and a folder that does not exist or is not writable. It
  writes `.kennis-corpus.7z.partial-<token>` in the folder with
  `header_encryption=True`, so the names are encrypted too, and emits a
  `Progress` per member. It then opens the archive again with the same
  password, requires `testzip()` to report nothing, and requires the
  names to equal what was written. Only after that does `os.replace`
  rename the file over `kennis-corpus.7z`. Any failure removes the
  partial file, so the last good backup is never destroyed. The
  returned report carries the path, the size, the member count and the
  elapsed time.
- `check_backup(folder, password=None)` reports whether the folder
  exists and is writable, and the archive's modification time and
  size. Given a password, it also opens the archive and tests every
  member. These are facts, with no sentence: a front end words them.
- `restore_backup(archive, target, password)` refuses a target that
  exists and is not empty. It checks every name before extracting
  anything: each must lie under `corpus/`, with no `..` part and no
  anchor, because an archive is data from outside. It extracts into a
  sibling `.<name>.restoring-<token>` directory and renames
  `corpus/` into place. The index is not in the archive, so the report
  says `kennis corpus index` comes next.

**A wrong password is not one exception.** With the header encrypted, a
wrong key decrypts it into arbitrary bytes. Over 300 wrong passwords,
`py7zr` raised `TypeError` 298 times and `Bad7zFile` twice. The single
call that opens and tests the archive therefore maps any exception to
`BackupUnreadable` ("the password is wrong or the archive is damaged").
The original is chained so the log keeps it. The catch covers only
that call, so a defect in kennis's own code is not hidden by it.

**`operations.back_up_corpus`** takes the corpus lock for the whole
write, as any operation that reads the repository does. A commit made
during the backup would otherwise land half in and half out of `.git`.
Restoring takes no lock, because its target does not exist yet.

**Command line: `kennis backup create | check | restore FILE`.** The
plan named `kennis corpus restore <file>`, but `corpus restore
DOCUMENT_ID COMMIT` already exists and restores one document from
history. A `backup` group keeps the three verbs together. The password
is prompted for with hidden input, and `create` asks for it twice.
`--to` overrides the folder for one run.

**The setting**: `backup.folder`, empty by default. `create` with no
folder configured and no `--to` refuses and names `kennis config set
backup.folder <folder>`.

## What I expect to be uncertain or difficult

- Empty directories in `.git`: whether `py7zr` stores and restores a
  directory entry, and whether `git status` works on a restored corpus.
  The test runs git on the restored copy rather than trusting the file
  list.
- Whether `testzip()` tests everything with a solid archive, or only
  the first block. A test can corrupt a byte and see.
- Time: AES with LZMA2 over a corpus of a few hundred MB. Measure on
  Brian's corpus size before claiming anything.
- Restoring into a cloud-synchronised folder half-way through a sync is
  not something kennis can detect; the temp-and-rename covers what it
  can.

## What actually happened that I did not expect

- **The index is tracked, so the plan's reason for leaving it out was
  wrong** (#443). The first restore test listed every index file as
  deleted in `git status`. The archive still leaves `index/` out, now
  because `.git` holds it already, and the restore checks it out of
  HEAD. A restored corpus is searchable at once, with no rebuild.
- **The index lock file is committed** (#444), which surfaced in the same
  `git status`.
- **`kennis corpus restore` was taken.** It restores one document from
  history, so the backup is its own group: `kennis backup create | check
  | restore`.
- **The tests could read Brian's API key and wrote to his log** (#442).
  The configuration and log directories were redirected per file, never
  for every test, and the real log held 311 lines from test runs. That
  fix was committed on its own first.
- **The probe wrote into the checkout.** A script run from the
  repository's working directory created `src/a/` and `t.7z` there.
  Both were removed, and later probes ran from the scratchpad.
- **An empty directory survives**: py7zr stores directory members, and
  `git status` on a restored copy is clean. `git log` is identical.
- **`testzip` catches a damaged byte anywhere.** A byte flipped in the
  middle of the file, and one flipped at offset 64, were both reported.
  The second is inside the data, so the names still read, and the
  failure surfaces during extraction instead. Both paths are tested.
- **Measured on Brian's corpus**, read without changing it: 739 entries,
  2.7 MB, 0.9 s. The stock `7z t` reports "Everything is Ok", and
  listing the archive without the password stops at a password prompt.
- **Two checks were enforced twice, and one test was untidy.** The anchor
  check on a restored name was inert under injection, because a name
  with an anchor cannot begin with `corpus`, so it was removed. The test
  for hidden names left the archive open when the injected defect made
  it readable, which pytest reported as an error rather than a failure.
- 24 injections: 23 caught, and the inert one led to the removal.
