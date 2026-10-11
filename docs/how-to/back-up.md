# Back up the corpus

kennis writes the whole corpus, with its history, to one encrypted `.7z`
file in a folder you choose. It talks to no service and sets up no git
remote. If you want the backup to leave the machine, choose a folder that
a OneDrive, Google Drive or Dropbox client synchronises, or one on a
mounted drive. kennis neither knows nor asks which kind it is.

## What the backup holds

The backup holds the full text of every document, every note and the
history of both, encrypted with AES-256 under a password you type each
time. The file names inside it are encrypted too, so the folder shows one
file and nothing about what is in it. The working copy of the search
index is left out, because the history already holds it, and a restore
checks it out again.

Two consequences are worth stating plainly:

- **Sharing the backup, or the folder it is in, shares the full text.**
  The password is the only protection. To work with someone else, share
  a pack, which names its sources rather than carrying them, or share
  notes that are your own words.
- **Encryption does not settle whether the material may be there.**
  Material covered by an institution's data policy, such as notes holding
  research participants' personal data, may not be allowed in consumer
  cloud storage even encrypted. Check before choosing a synchronised
  folder.

## Choose the folder

```
kennis config set backup.folder ~/Dropbox/kennis
```

`--to` uses another folder for one run without changing the setting.

## Write a backup

```
kennis backup create
```

kennis asks for the password twice and never stores it. The archive is
written beside the previous one under a temporary name, opened again with
the same password and tested, and only then renamed over it. A backup that
fails at any point leaves the last good one exactly as it was.

The corpus is locked while the backup is written, so a note added from
another window waits rather than landing half in the archive.

## Check a backup

```
kennis backup check
kennis backup check --test
```

The first says whether the folder is there and can be written to, and
when the backup was last written and how large it is. With `--test`,
kennis asks for the password and decrypts every file in the archive
against its checksum. A wrong password and a damaged archive cannot be
told apart, so both are reported the same way.

## Restore

```
kennis backup restore ~/Dropbox/kennis/kennis-corpus.7z
kennis backup restore ~/Dropbox/kennis/kennis-corpus.7z --to ~/kennis-restored
```

The corpus is restored to the configured corpus folder, or to `--to`.
kennis refuses to restore over anything that is not empty, and refuses an
archive that names a path outside the corpus, before writing anything.

Without kennis, any 7-Zip-compatible program opens the file with the same
password, and the documents inside are ordinary Markdown.
