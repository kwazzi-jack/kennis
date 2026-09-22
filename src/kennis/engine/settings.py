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
gets forgotten when a new printing path is added. Keys live in
`credentials.toml` at mode 0600, which nothing here reads.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Final, Literal, get_args, get_origin

from platformdirs import user_config_dir
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
_CONFIG_FILE: Final = "config.toml"
_CREDENTIALS_FILE: Final = "credentials.toml"


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
        default="BAAI/bge-small-en-v1.5",
        description="Model name, interpreted by the backend.",
        examples=[
            '"BAAI/bge-small-en-v1.5"    (fastembed)',
            '"nomic-embed-text"          (ollama)',
            '"text-embedding-3-small"    (openai)',
        ],
    )
    dimensions: int = Field(
        default=384, ge=1, le=8192, description="Width of a vector."
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

    default_top_k: int = Field(
        default=5, ge=1, le=100, description="How many hits a search returns."
    )
    rrf_k: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Reciprocal rank fusion constant: score = sum 1 / (k + rank).",
    )
    corpus_method: Literal["hybrid", "bm25", "dense"] = Field(
        default="hybrid", description="Retrieval method for corpus collections."
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

    backend: Literal["mineru"] = Field(
        default="mineru", description="Converter for PDF, DOCX, PPTX and XLSX."
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


def config_path() -> Path:
    return config_dir() / _CONFIG_FILE


def credentials_path() -> Path:
    """Where API keys live. Nothing in this module reads it."""
    return config_dir() / _CREDENTIALS_FILE


def load_settings() -> Settings:
    """Every setting, resolved."""
    try:
        return Settings()
    except ValidationError as error:
        raise SettingsError(
            _first_problem(error), resolution="kennis config show"
        ) from error


def config_template() -> str:
    """The configuration file as `config init` writes it.

    Every key, at its default, **commented out**. Writing defaults as active
    values would freeze them at install time, so a later kennis that improves
    a default would never reach anyone who ran this.

    The `Options`, `Range` and `Examples` lines are derived from the model, so
    they cannot drift from what it actually accepts - which is precisely what
    a hand-written comment does.
    """
    lines = [
        "# kennis configuration. Every key is shown at its default, commented",
        "# out, so improving a default still reaches you. Uncomment to change.",
        "#",
        "# API keys do not belong here: `kennis config init` writes them to",
        "# credentials.toml, readable only by you.",
    ]
    for section_name, section_field in Settings.model_fields.items():
        annotation = section_field.annotation
        if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
            continue
        lines.append("")
        lines.append(f"[{section_name}]")
        entries = [
            _described(key, field) for key, field in annotation.model_fields.items()
        ]
        lines.append("\n#\n".join(entries))
    return "\n".join(lines) + "\n"


def _described(key: str, field: FieldInfo) -> str:
    """One key: what it is for, what it accepts, and its default."""
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

    lines.append(f"# {key} = {_as_toml(field.default)}")
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


def _as_toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _first_problem(error: ValidationError) -> str:
    """The offending setting and why, in one line."""
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}"
