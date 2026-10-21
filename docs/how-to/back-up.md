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
checks it out again. So is what kennis keeps only while it works: the copy
a task prepares its changes in, and the conversions it keeps for a day so
that a failed add need not convert again.

Two consequences are worth stating plainly:

- **Sharing the backup, or the folder it is in, shares the full text.**
  The password is the only protection. To work with someone else, share
  a pack, which names its sources rather than carrying them, or share
  notes that are your own words.
- **Encryption does not settle whether the material may be there.**
  Material covered by an institution's data policy, such as notes holding
  research participants' personal data, may not be allowed in consumer
  cloud storage even encrypted. The next section says what to check.

## Before you choose a cloud folder

kennis gives no legal advice, and it cannot tell what the corpus holds or
what applies to it. This section says which questions to ask and who can
answer them. It matters most when the corpus holds **personal data** -
anything about an identifiable person, such as interview notes, survey
answers or a participant list - and the folder is one a cloud client
synchronises.

**Encrypted personal data is still personal data.** You hold the password,
so to you the backup is the data itself. Encryption is a safeguard the law
recognises, not a permission:

- The EU's General Data Protection Regulation (GDPR), which the UK keeps
  in its own law, names "the pseudonymisation and encryption of personal
  data" among the security measures a controller may take (Article 32),
  and spares notifying people of a breach when the data was made
  "unintelligible to any person who is not authorised to access it, such
  as encryption" (Article 34). Storing the data with a provider whose
  servers are outside the EU is a transfer, which Chapter V governs
  separately. [Regulation (EU) 2016/679 on EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj).
- South Africa's Protection of Personal Information Act (POPIA) requires
  security measures for personal information (section 19) and limits
  sending it outside the Republic (section 72).
  [The Act on gov.za](https://www.gov.za/documents/protection-personal-information-act)
  and [the Information Regulator](https://inforegulator.org.za/).
- Other countries have laws of their own; these two are examples, not a
  list.

**An institution can be stricter than the law.** Three documents often
decide where research data may be kept:

- the **ethics approval** for a study, which may name where its data is
  stored and who may hold a copy;
- a **data management plan**, which a funder or the institution may
  require and which names the storage;
- the institution's **data or information security policy**, which may
  allow only storage the institution provides.

**A licence can limit copies.** A paper, dataset or site may come under
terms that say how many copies you may keep and where. A backup is a copy.

**Who can answer.** The institution's data protection officer or
information officer, its research data management office, and the ethics
committee that approved the study. Ask before the first backup to a
synchronised folder, not after.

If the answer is no, choose a folder on a drive you control, or one the
institution provides, or keep the personal data out of the corpus.

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

A write cannot be placed while the backup is written, so a note added from
another window lands before or after the archive, never half in it.

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
