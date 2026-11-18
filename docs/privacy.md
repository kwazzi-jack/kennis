# Your data: where it is kept and where it goes

kennis keeps everything it holds on your own machine, in folders you can
open, and it has no account, no server of its own and no telemetry of its
own, and it turns off the telemetry of the libraries it runs (see
[Libraries that report to their makers](#libraries-that-report-to-their-makers)).
Its author receives nothing from your use of it. Material leaves the machine in
exactly the ways listed on this page, and most of them happen only after
you ask for them.

This page is a notice about how the software behaves. It is not legal
advice, and it does not decide what you are permitted to store or send.

## Where kennis keeps things

| what | Linux default | what it holds |
|---|---|---|
| the corpus | `~/.local/share/kennis` | the full text of every document and note, the images a converted document links, its search index, and the git history of all of it |
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
| adding an arXiv paper | `arxiv.org`, `ar5iv.labs.arxiv.org`, and `export.arxiv.org` for its `robots.txt` alone | the arXiv identifier, and your IP address |
| adding a paper by DOI, with an email set | `api.unpaywall.org` | the DOI and your email address |
| adding a paper by DOI with its text in hand, or `pack update` for a DOI entry with no citekey | `doi.org`, which redirects to the registry that issued the DOI - `api.crossref.org` or `data.crosscite.org` | the DOI, and your IP address |
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

### Libraries that report to their makers

kennis runs two libraries that collect telemetry unless told not to, and
from v0.15.0 it tells them not to, whatever your environment says.

- **ONNX Runtime**, Microsoft's engine for running models, which kennis
  uses through `fastembed` (the default embedding backend) and which
  MinerU uses in every conversion. From its version 1.29 it writes a
  device identifier and a queue of events under your cache folder
  (`~/.cache/Microsoft/DeveloperTools/.onnxruntime/` on Linux) as soon as
  it is loaded, and posts them to `mobile.events.data.microsoft.com`:
  your operating system and processor, your network type, the names of
  the models it runs, and the full path of the Python that ran it, which
  usually contains your account name. kennis sets
  `ORT_DISABLE_TELEMETRY=1` in its own process and in every converter it
  starts, which stops all of it on Linux and macOS, and calls ONNX
  Runtime's own off switch on Windows, where the variable is ignored.
- **MinerU** keeps a telemetry of its own from its version 4; kennis
  sets `MINERU_TELEMETRY_DISABLED=1` for it.

**kennis v0.14.0 and earlier did not do this**, and every one of those
releases installed an ONNX Runtime that reports, so using `fastembed` or
converting a PDF sent those events. If you used one, the folder above may
still hold a queue that any program using ONNX Runtime without the switch
will send; deleting the folder removes the queue and the identifier.

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
