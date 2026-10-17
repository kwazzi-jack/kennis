"""What can be tuned, and where an answer comes from.

Precedence is the environment, then `config.toml`, then the field's default.

**The environment is read by exact name**, not by splitting on a delimiter.
pydantic-settings offers `env_nested_delimiter="_"`, and design section 13
specifies against it for a reason that is easy to verify and easy to miss:

    KENNIS_EMBEDDING_BACKEND     -> embedding.backend      works
    KENNIS_EMBEDDING_API_KEY_ENV -> embedding.api.key.env  matches nothing

The second is dropped **in silence**. No error, no warning; the field keeps
its default, and a user who set the variable and watched it do nothing has no
way to find out why. So the source below walks the model's own sections and
fields and looks up `KENNIS_<SECTION>_<FIELD>` by exact name.

**Only settings something reads are offered.** A setting nothing honours is
worse than a missing one: it is a promise. `ingestion.use_mcp_sampling`,
which the design marks deferred, is deliberately absent.

**Credentials are not settings.** `config show` writes this model to standard
output by design, so a user debugging will paste it into an issue. A key here
would make every printing path need redaction, and redaction is the step that
gets forgotten when a new printing path is added. Keys live outside this
model, and `credential` below is the one function that reads them.
"""

from __future__ import annotations

import logging
import os
import shlex
import sys
import tomllib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Literal, get_args, get_origin

from dotenv import dotenv_values
from platformdirs import user_config_dir, user_log_dir, user_state_dir
from pydantic import BaseModel, Field, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from kennis.engine.errors import SettingsError

_ENVIRONMENT_PREFIX: Final = "KENNIS"
_CONFIG_DIR_VARIABLE: Final = "KENNIS_CONFIG_DIR"
_STATE_DIR_VARIABLE: Final = "KENNIS_STATE_DIR"
_LOG_DIR_VARIABLE: Final = "KENNIS_LOG_DIR"
_CONFIG_FILE: Final = "config.toml"
_CREDENTIALS_FILE: Final = "credentials.toml"

# Consulted in this order, both inside the configuration directory. `.env` is
# the conventional name; `.env.keys` is preferred over it because a file whose
# only job is secrets can be given a mode and a backup policy of its own.
_ENV_FILES: Final[tuple[str, ...]] = (".env.keys", ".env")


# Each backend's own model. A model name means something only to its
# backend, so the setup offers this one when the backend is changed rather
# than keeping the previous backend's, which failed only at the next index
# (#441). There is no width beside it: the model fixes the width of its
# vectors, and as a setting it could only be wrong in silence.
EMBEDDING_DEFAULTS: Final[dict[str, str]] = {
    "fastembed": "BAAI/bge-small-en-v1.5",
    "ollama": "nomic-embed-text",
    "openai": "text-embedding-3-small",
}


class EmbeddingSettings(BaseModel):
    """How chunks and queries become vectors."""

    backend: Literal["fastembed", "ollama", "openai", "none"] = Field(
        default="fastembed",
        # The download is named here because this is where it is chosen.
        # Announcing it during `corpus index` is a warning, not consent, and
        # the command whose purpose is to spend minutes is the worst place to
        # interrupt someone. Concern #96. 65 MB is measured, not quoted: the
        # default model's cache on this machine, twice.
        description=(
            "Backend used to embed chunks. fastembed downloads a 65 MB model "
            "the first time you index; none means lexical search only."
        ),
    )
    model: str = Field(
        default=EMBEDDING_DEFAULTS["fastembed"],
        description="Model name, interpreted by the backend.",
        examples=[
            '"BAAI/bge-small-en-v1.5"    (fastembed)',
            '"nomic-embed-text"          (ollama)',
            '"text-embedding-3-small"    (openai)',
        ],
    )
    normalise: bool = Field(
        default=True,
        description="Scale vectors to unit length, so cosine is a dot product.",
    )
    batch_size: int = Field(
        default=64, ge=1, le=1024, description="Texts per backend request."
    )
    base_url: str = Field(
        default="",
        description="Server address. Unused for fastembed.",
        examples=['"http://localhost:11434"    (ollama)'],
    )
    api_key_env: str = Field(
        default="OPENAI_API_KEY",
        description="Environment variable holding the key, for hosted backends.",
        examples=['"OPENAI_API_KEY"'],
    )


class ChunkingSettings(BaseModel):
    """How a document is cut up before it is indexed."""

    size: int = Field(
        default=1500, ge=100, le=20000, description="Target characters per chunk."
    )
    overlap: int = Field(
        default=200,
        ge=0,
        le=5000,
        description="Characters shared between neighbouring chunks.",
    )


class RetrievalSettings(BaseModel):
    """How a search is run."""

    # Per scope, not across them: search prints one group per collection and
    # each contributes up to this many, so a corpus with three indexed
    # collections and a project bundle can print four times it. It was 5
    # while one merged list was truncated globally; 3 keeps the worst case
    # near what that used to show. Concern #232.
    default_top_k: int = Field(
        default=3,
        ge=1,
        le=100,
        description=(
            "How many hits a search returns from each scope it searched, so a "
            "sweep can return this many times the number of scopes."
        ),
    )
    corpus_method: Literal["hybrid", "bm25", "dense"] = Field(
        default="hybrid", description="Retrieval method for corpus collections."
    )
    # `bm25` rather than `hybrid`, and it is the design's decision rather
    # than a cautious default. A dense bundle index would turn `context
    # init` from an offline scaffold into a 65 MB model download, and it
    # makes the binding match across machines much less likely - which is
    # what committing the index with the project is for. design.md,
    # "The context bundle carries its own index".
    context_method: Literal["hybrid", "bm25", "dense"] = Field(
        default="bm25",
        description=(
            "Retrieval method for a project's context bundle. bm25 keeps "
            "`kennis context init` offline and its index portable between "
            "machines; anything else needs an embedding backend."
        ),
    )


class CorpusSettings(BaseModel):
    """Where the corpus lives and how documents are added to it."""

    root: str = Field(
        default="",
        description="Corpus directory. Empty means the platform data directory.",
        examples=['"~/knowledge"'],
    )
    keep_original: bool = Field(
        default=False, description="Keep the source file beside the document."
    )
    default_group: str = Field(
        default="",
        description="Group new documents are filed under when none is given.",
        examples=['"inbox"'],
    )


class ConversionSettings(BaseModel):
    """How binary documents become markdown."""

    backend: Literal["mineru", "datalab"] = Field(
        default="mineru",
        description=(
            # No install command here. A description is schema metadata: it
            # is written into config.toml as a comment, where it would tell
            # a reader to run something that does nothing for the way they
            # installed kennis. The command that installs mineru depends on
            # that, and is `MineruConverter.install_hint()`. Concerns #185,
            # #195.
            "Converter for PDF, DOCX, PPTX and XLSX. mineru runs locally and "
            "is installed with kennis; datalab is hosted, needs an API key, "
            "and sends the document to a third party."
        ),
    )
    mode: Literal["fast", "balanced", "accurate"] = Field(
        default="balanced",
        description=(
            "How hard the datalab backend works, and what it charges. "
            "Measured per page: fast 0.4c, balanced 0.4c, accurate 1.0c. "
            "The server only reuses a conversion when the mode matches, so "
            "changing this and re-adding a document pays for it again. "
            "mineru ignores this - it runs locally and costs nothing."
        ),
    )
    repair_ligatures: bool = Field(
        default=True,
        description=(
            "Repair ligature damage against the PDF's own text layer, read "
            "with pypdfium2. mineru drops a letter from ff, fi and fl on "
            "some documents, which no reindex can undo. Costs 0.7ms a page "
            "and applies to mineru only - datalab showed no such damage."
        ),
    )
    batch_size: int = Field(
        default=8,
        ge=0,
        le=512,
        description="Documents per converter run. 0 is one run.",
    )


class LiteratureSettings(BaseModel):
    """How papers are identified and fetched."""

    request_delay: float = Field(
        default=3.0,
        ge=0.0,
        le=60.0,
        description="Seconds between arXiv requests. arXiv states three.",
    )
    unpaywall_email: str = Field(
        default="",
        pattern=r"^$|^[^@\s]+@[^@\s]+$",
        description=(
            "Your email address, which Unpaywall requires, to look up a free "
            "and legal copy of a paper known only by its DOI. Empty: Unpaywall "
            "is not asked, and such a paper needs your own copy."
        ),
    )


class LoggingSettings(BaseModel):
    """What is written to the log file."""

    level: Literal["debug", "info", "warning", "error"] = Field(
        default="info", description="Detail written to the log file."
    )
    max_bytes: int = Field(
        default=1_048_576, ge=1024, description="Size at which the log rotates."
    )
    backup_count: int = Field(
        default=3, ge=0, le=100, description="Rotated log files kept."
    )


class BackupSettings(BaseModel):
    """Where the encrypted backup of the corpus is written."""

    folder: str = Field(
        default="",
        description=(
            "Folder the encrypted backup is written to, often one a cloud "
            "client synchronises. The backup holds the full text of every "
            "document."
        ),
    )


class Settings(BaseSettings):
    """Every setting kennis honours."""

    model_config = SettingsConfigDict(env_prefix=f"{_ENVIRONMENT_PREFIX}_")

    embedding: EmbeddingSettings = EmbeddingSettings()
    chunking: ChunkingSettings = ChunkingSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    corpus: CorpusSettings = CorpusSettings()
    conversion: ConversionSettings = ConversionSettings()
    literature: LiteratureSettings = LiteratureSettings()
    logging: LoggingSettings = LoggingSettings()
    backup: BackupSettings = BackupSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Environment, then the file, then defaults.

        pydantic's own `env_settings` is replaced rather than supplemented:
        leaving it in place would reintroduce delimiter splitting beside the
        exact-name lookup, and two sources disagreeing about one variable is
        worse than either.
        """
        return (
            init_settings,
            ExactNameEnvSource(settings_cls),
            TomlFileSource(settings_cls),
        )


class ExactNameEnvSource(PydanticBaseSettingsSource):
    """`KENNIS_<SECTION>_<FIELD>`, matched whole.

    Written here because pydantic-settings has no such source. Design section
    13 names one; no class of that name exists in 2.15.0, and the requirement
    it stands for is real - see this module's docstring.
    """

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        # Required by the base class and unused: the whole model is built in
        # `__call__`, because a section's variables cannot be found without
        # knowing the section's own field names.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for section_name, section_field in self.settings_cls.model_fields.items():
            annotation = section_field.annotation
            if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
                continue
            section = {
                key: os.environ[variable]
                for key in annotation.model_fields
                if (variable := f"{_ENVIRONMENT_PREFIX}_{section_name}_{key}".upper())
                in os.environ
            }
            if section:
                values[section_name] = section
        return values


class TomlFileSource(PydanticBaseSettingsSource):
    """`config.toml`, if there is one.

    A missing file is not an error: kennis runs on its defaults until someone
    chooses otherwise, and requiring `config init` before the first command
    would be a step with nothing behind it.
    """

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        path = config_path()
        if not path.is_file():
            return {}
        try:
            return dict(tomllib.loads(path.read_text(encoding="utf-8")))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise SettingsError(
                f"{path} could not be read: {error}",
                resolution="kennis config path",
            ) from error


# What protects the credentials file, said no more strongly than it holds.
# On Windows `chmod(0o600)` sets nothing but the read-only flag: the file is
# kept from other users by the profile directory's own permissions, which an
# administrator can read through.
def credentials_kept(platform: str) -> str:
    return (
        "kept in your own user profile"
        if platform == "win32"
        else "readable only by you"
    )


CREDENTIALS_KEPT: Final = credentials_kept(sys.platform)


def config_dir() -> Path:
    """Where kennis keeps its configuration.

    `KENNIS_CONFIG_DIR` overrides the platform default, and is what makes a
    test - or a second profile - isolatable through the same mechanism a user
    has rather than a back door only tests know about.
    """
    override = os.environ.get(_CONFIG_DIR_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_config_dir("kennis"))


def state_dir() -> Path:
    """Where kennis keeps state that is neither log nor configuration.

    `KENNIS_STATE_DIR` overrides the platform default, by the mechanism
    `config_dir` uses. On Linux the default is `~/.local/state/kennis`, the
    parent of the log directory, so the two sit together.
    """
    override = os.environ.get(_STATE_DIR_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_state_dir("kennis"))


def log_dir() -> Path:
    """Where kennis keeps its log, overridden by `KENNIS_LOG_DIR`."""
    override = os.environ.get(_LOG_DIR_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_log_dir("kennis"))


def own_directories(corpus_root: Path) -> tuple[Path, ...]:
    """Every directory kennis writes its own files into.

    Nothing in them is ever a source to add: the corpus would be copied into
    itself, the configuration holds API keys in `credentials.toml`, and the
    state holds the reader's search history - each a supported format, and
    each, once added, a document an agent can read.
    """
    return (corpus_root, config_dir(), state_dir(), log_dir())


def overriding_variable(key: str) -> str | None:
    """The environment variable setting `key` ("section.field") now, if any.

    The environment wins over `config.toml`, so a value written to the
    file while one of these is set changes nothing anyone can see. Named
    as the source above names it, by exact name.
    """
    section, _, field = key.partition(".")
    variable = f"{_ENVIRONMENT_PREFIX}_{section}_{field}".upper()
    return variable if variable in os.environ else None


def config_path() -> Path:
    return config_dir() / _CONFIG_FILE


def credentials_path() -> Path:
    """Where `config init` writes API keys. `credential` reads it last."""
    return config_dir() / _CREDENTIALS_FILE


@contextmanager
def _without_dotenv_complaints() -> Iterator[None]:
    """Keep python-dotenv's parser quiet for the duration of one read.

    A malformed line is reported through `logging`, and with no handler
    configured that reaches standard error through the last-resort handler.
    Every command calls `credential`, and the engine never prints, so one
    stray quote in a secrets file would otherwise make every command emit a
    line kennis did not compose. Raising the level on the parent suppresses
    the child `dotenv.main` too, because a logger with no level of its own
    inherits its ancestor's.
    """
    logger = logging.getLogger("dotenv")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(previous)


def _from_env_file(path: Path, variable: str) -> str:
    """One variable out of a `.env` file, or `""` if it is not usable there.

    `dotenv_values` is used rather than `load_dotenv` because it returns the
    contents instead of merging them into `os.environ`. Were the file to leak
    into the environment, the environment-wins rule in `credential` would
    stop being a rule and become an accident of which call ran first.

    A bare `NAME` with no `=` parses to `None` and `NAME=` to the empty
    string. Neither is a key, and both fall through to the next source.
    """
    if not path.is_file():
        return ""
    with _without_dotenv_complaints():
        try:
            values = dotenv_values(path, encoding="utf-8")
        except OSError:
            return ""
    found = values.get(variable)
    return found if isinstance(found, str) else ""


def _from_credentials_file(variable: str) -> str:
    """One variable out of `credentials.toml`, or `""`.

    The variable name is the identity; the section it sits under is an
    implementation detail of whatever wrote it, so every section is searched.
    """
    path = credentials_path()
    if not path.is_file():
        return ""
    try:
        stored = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return ""
    for values in stored.values():
        if isinstance(values, dict) and isinstance(values.get(variable), str):
            return str(values[variable])
    return ""


def credential(variable: str) -> str:
    """One API key, from the first of four places that holds it.

    The environment, then `.env.keys`, then `.env`, then `credentials.toml` -
    the last three inside the configuration directory.

    **The environment wins.** A shell export, a CI secret and a one-off
    override all arrive that way, and none of them should be shadowed by a
    file written months earlier. `credentials.toml` comes last because it is
    the file kennis writes itself, and so the one a user is least likely to
    have edited most recently.

    **No `.env` is read from the working directory.** kennis is run from
    wherever the user happens to be, frequently somebody else's checkout. A
    `.env` there belongs to that project, and honouring it would let an
    arbitrary repository supply the key kennis uses to send a document to a
    third party (rules.md 4.5).

    Every failure yields nothing rather than raising - a missing file, an
    unreadable one, one that does not parse. Only the command that needs a
    key should fail for the want of one, not every command that happens to
    load settings.
    """
    from_environment = os.environ.get(variable)
    if from_environment:
        return from_environment

    directory = config_dir()
    for name in _ENV_FILES:
        from_file = _from_env_file(directory / name, variable)
        if from_file:
            return from_file

    return _from_credentials_file(variable)


def load_settings() -> Settings:
    """Every setting, resolved.

    A value that is refused is named with where it came from, and the
    remedy is the one that removes it: pointing at `config show` for an
    exported variable sent the reader to a file with nothing wrong in it.
    """
    try:
        return Settings()
    except ValidationError as error:
        raise refused_setting(error, config_path()) from error


def refused_setting(error: ValidationError, path: Path) -> SettingsError:
    """The first refused value, named by its source: the variable that
    overrides it, or the file at `path`."""
    first = error.errors()[0]
    location = [str(part) for part in first["loc"]]
    key = ".".join(location[:2])
    variable = overriding_variable(key) if len(location) > 1 else None
    if variable is not None:
        return SettingsError(
            f"{key}: {first['msg']} (set by {variable})",
            resolution=f"unset {variable}",
        )
    return SettingsError(
        f"{'.'.join(location)} in {path}: {first['msg']}",
        resolution=repair_of(key, path),
    )


def repair_of(key: str, path: Path) -> str:
    """The command that puts `key` back to its default, or the edit that
    does when its default is not one to type on a command line."""
    section, _, name = key.partition(".")
    model = section_models().get(section)
    field = model.model_fields.get(name) if model is not None else None
    default = field.default if field is not None else None
    if isinstance(default, bool):
        return f"kennis config set {key} {'true' if default else 'false'}"
    if isinstance(default, int | float | str) and default != "":
        return f"kennis config set {key} {shlex.quote(str(default))}"
    return f"remove {key} from {path}"


def config_document(values: Mapping[str, Mapping[str, object]] | None = None) -> str:
    """The configuration file, with every key of every section active.

    `values` overrides the defaults by section and key; anything it does not
    name is written at its default. Every key is written, including one at
    its default, because the value a person accepted is the value saved and
    a complete file is one that can be synced (Brian, 2026-10-12). This
    reverses a template that commented the defaults out so that a later
    kennis could change them: compatibility starts at v1.0.0.

    The `Options`, `Range` and `Examples` lines are derived from the model, so
    they cannot drift from what it actually accepts - which is precisely what
    a hand-written comment does.
    """
    given = values or {}
    lines = [
        "# kennis configuration. Every setting is written, including those at",
        "# their default, and `kennis config init` replaces the whole file.",
        "#",
        "# API keys do not belong here. kennis takes one from the environment",
        "# first, then .env.keys, then .env, then credentials.toml - the last",
        "# three in this directory. `kennis config init` writes the last of",
        f"# them, {CREDENTIALS_KEPT}.",
    ]
    for section_name, model in section_models().items():
        defaults = model().model_dump()
        section_values = {**defaults, **given.get(section_name, {})}
        lines.append("")
        lines.append(f"[{section_name}]")
        entries = [
            _described(key, field, section_values[key])
            for key, field in model.model_fields.items()
        ]
        lines.append("\n#\n".join(entries))
    return "\n".join(lines) + "\n"


def section_models() -> dict[str, type[BaseModel]]:
    """Each section's own model, by section name.

    Plain models, which read no environment: `Settings` does, even through
    `model_validate`, so a value exported for one shell would otherwise be
    taken for a value to keep.
    """
    models: dict[str, type[BaseModel]] = {}
    for section_name, section_field in Settings.model_fields.items():
        annotation = section_field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            models[section_name] = annotation
    return models


def unknown_settings() -> tuple[str, ...]:
    """Every name in the file that no section declares, sorted (#480).

    A section's name when the section is unknown, `section.key` when only
    the key is. The models ignore such a name, so a misspelt key leaves
    the default in force; this is how a front end can say so. A file that
    is missing names nothing, and so does one that will not read: the
    loader refuses that with its own message.
    """
    path = config_path()
    try:
        stored = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    models = section_models()
    unknown: list[str] = []
    for section_name, section in stored.items():
        model = models.get(section_name)
        if model is None or not isinstance(section, dict):
            unknown.append(section_name)
            continue
        unknown.extend(
            f"{section_name}.{key}" for key in section if key not in model.model_fields
        )
    return tuple(sorted(unknown))


def _described(key: str, field: FieldInfo, value: object) -> str:
    """One key: what it is for, what it accepts, and its value."""
    lines = [f"# {field.description}" if field.description else f"# {key}"]

    options = _options_of(field.annotation)
    if options:
        lines.append(f"# Options: {' | '.join(options)}")
    bounds = _range_of(field)
    if bounds:
        lines.append(f"# Range: {bounds}")
    for index, example in enumerate(field.examples or []):
        lines.append(
            f"# Examples: {example}" if index == 0 else f"#           {example}"
        )

    lines.append(f"{key} = {toml_value(value)}")
    return "\n".join(lines)


def _options_of(annotation: object) -> tuple[str, ...]:
    """The values a `Literal` field accepts, if it is one.

    Unwrapped rather than matched on the annotation directly, because a field
    may arrive wrapped and the options are still the point.
    """
    if get_origin(annotation) is Literal:
        return tuple(str(value) for value in get_args(annotation))
    return ()


def _range_of(field: FieldInfo) -> str | None:
    lower = upper = None
    for item in field.metadata:
        lower = getattr(item, "ge", None) if lower is None else lower
        upper = getattr(item, "le", None) if upper is None else upper
    if lower is None or upper is None:
        return None
    return f"{lower}-{upper}"


def toml_value(value: object) -> str:
    """One value as TOML. A string is escaped, because a Windows path holds
    backslashes and a folder name may hold a quote."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
