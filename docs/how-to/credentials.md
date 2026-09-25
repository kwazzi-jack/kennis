# Keep credentials out of the config

An API key never goes in `config.toml`.

## Why

`kennis config show` writes the settings model to standard output by design -
it is how you inspect a configuration, and it is what someone pastes into a
bug report. A key in that model would make every printing path need
redaction, and redaction is the step that gets forgotten when a new printing
path is added.

So keys are not part of the settings model at all. There is exactly one
function that reads them, and nothing prints them.

## Where a key goes

kennis looks in four places, in order, and takes the first that has it:

1. **The environment variable** named by `embedding.api_key_env`, which
   defaults to `OPENAI_API_KEY`.
2. **`.env.keys`** in the configuration directory.
3. **`.env`** in the configuration directory.
4. **`credentials.toml`** in the configuration directory.

`.env.keys` is preferred over `.env` because a file whose only job is secrets
can be given a mode and a backup policy of its own.

Find the directory with:

```
kennis config path
```

## The easy way

```
kennis config init
```

The guided setup asks for a key only when the backend you chose needs one,
and writes it to `credentials.toml` with mode `0600` - readable only by you.
It is never echoed back to the terminal.

## By hand

```
export OPENAI_API_KEY=sk-...
```

or, in `~/.config/kennis/.env.keys`:

```
OPENAI_API_KEY=sk-...
```

```
chmod 600 ~/.config/kennis/.env.keys
```

## Pointing at a different variable

If your key lives under another name:

```
kennis config set embedding.api_key_env MY_PROJECT_OPENAI_KEY
```

That records the variable's **name** in the config, which is not a secret.
The value stays wherever you put it.

## Nothing is sent by default

Both of kennis's third-party paths are opt-in and need two things, not one:

- **datalab** conversion requires setting `conversion.backend` **and**
  supplying a key;
- **openai** embedding requires setting `embedding.backend` **and** supplying
  a key.

Setting one without the other is an error that says what is missing, not a
silent upload. Sending a document to a third party is never a default.
