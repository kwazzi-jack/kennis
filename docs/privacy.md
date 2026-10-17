# Your data: where it is kept and where it goes

kennis keeps everything it holds on your own machine, in folders you can
open, and it has no account, no server of its own and no telemetry. Its
author receives nothing from your use of it. Material leaves the machine in
exactly the ways listed on this page, and most of them happen only after
you ask for them.

This page is a notice about how the software behaves. It is not legal
advice, and it does not decide what you are permitted to store or send.

## Where kennis keeps things

| what | Linux default | what it holds |
|---|---|---|
| the corpus | `~/.local/share/kennis` | the full text of every document and note, its search index, and the git history of both |
| configuration | `~/.config/kennis/config.toml` | your settings, including the Unpaywall email address if you set one |
| credentials | `~/.config/kennis/credentials.toml` | API keys, readable only by your account where the platform has file modes |
| state | `~/.local/state/kennis` | the window's recent searches: each query, its scope, its count and when it ran, never the results |
| the log | `~/.local/state/kennis/log` | what each command did, for diagnosis |
| models | `~/.cache/kennis/models` | the downloaded embedding model |
| a context bundle | `.context/` inside a project | the project's notes and their search index |

On macOS and Windows these are the platform's equivalent folders;
`kennis config path` prints the real ones. `KENNIS_CONFIG_DIR`,
`KENNIS_STATE_DIR`, `KENNIS_LOG_DIR` and the `corpus.root` setting move
them.

The corpus is a git repository with **no remote**. kennis commits to it
and never pushes it anywhere. Recent searches can be cleared from the
window's search page.

## When material leaves the machine

### Things you ask for, which fetch from a named host

| when | host | what that host receives |
|---|---|---|
| adding an arXiv paper | `export.arxiv.org`, `arxiv.org`, `ar5iv.labs.arxiv.org` | the arXiv identifier, and your IP address |
| adding a paper by DOI, with an email set | `api.unpaywall.org` | the DOI and your email address |
| adding a documentation site or a file by address | the site you name | the pages requested, with a User-Agent naming kennis |
| `corpus sync` with a pack installed | the sources the pack names | the same as adding each one by hand |
| the first index with the default backend | `huggingface.co` | the model's name, as for any model download |
| the first PDF conversion | `huggingface.co` or `modelscope.cn`, as MinerU's `MINERU_MODEL_SOURCE` chooses | the names of MinerU's models |

Each of these sends an identifier or an address, not your documents.

### Settings that send your text to a third party

These are never defaults. Each needs a setting **and** a key, so neither
alone turns one on.

| setting | host | what is sent |
|---|---|---|
| `conversion.backend = datalab` | `www.datalab.to` | every document you convert, in full |
| `embedding.backend = openai` | `api.openai.com`, or the `base_url` you set | the text of every chunk you index and every query you search |
| `embedding.backend = ollama` | `localhost` by default, or the `base_url` you set | the same, to whatever machine that address is |

With the defaults - MinerU for conversion and fastembed for embedding -
both run on your machine.

### Links you follow

The window links a paper to its pages on `arxiv.org`, `doi.org` and
`ui.adsabs.harvard.edu`, and the backup's caution to this documentation
on `kwazzi-jack.github.io`. Nothing is requested until you click one, and
the page opens without a referrer, so the site is not told that kennis
sent you. A pack file's first line names its schema on
`raw.githubusercontent.com`; kennis does not fetch it, but an editor with
a YAML language server may.

kennis never fetches an image inside a document on your behalf, because
that request would tell the image's host which document is being read. A
remote image is shown as its host's name instead.

### Agents

`kennis serve` answers an AI agent's searches and reads with the text of
your documents. **Whatever the agent's model runs on receives that text**:
if the agent uses a hosted model, the provider receives every passage the
agent reads. That is a property of the agent you connect, not of kennis,
and it applies to any document kennis holds. The agent's `remember` tool
writes notes into the corpus or the bundle.

### Things you share yourself

- **A context bundle is committed with its project.** `.context/` holds
  the notes and their search index, including the indexed text, so
  pushing the project shares them with everyone who can read the
  repository.
- **A backup holds the full text of everything**, encrypted with a
  password you type each time. If the folder you choose is synchronised
  by a cloud client, the encrypted file goes to that provider. See
  [Back up the corpus](how-to/back-up.md).
- **A pack names its sources rather than carrying them**, so sharing a
  pack shares where to fetch each document, not the documents.

## What you are responsible for

kennis copies documents you add into the corpus and converts them, and it
does not check whether you may. Whether you may keep a copy of a paper, a
site or a dataset, and whether material covered by an institution's data
policy - research participants' personal data, for example - may be
stored on this machine, in a backup folder, or sent to a backend above,
is for you and the material's terms to settle.

kennis is free software under the GNU General Public License, version 3 or
later, and like all software under that licence it comes with **no
warranty**, to the extent permitted by law. The licence's full text is in
the repository's `LICENSE` file.
