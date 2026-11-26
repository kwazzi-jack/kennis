# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6", "platformdirs>=4"]
# ///
"""Bring a corpus written by kennis before v0.15.0 to v0.15.0's shape.

    uv run upgrade_corpus.py            # say what would change; change nothing
    uv run upgrade_corpus.py --apply    # back up, then change it

It decides by reading the corpus and changes it only through the `kennis`
on PATH, so every change is a kennis operation with its own commit, and
`kennis corpus history` and `kennis corpus restore` cover it. Three things:

1. **Figures.** A paper converted before v0.15.0 links images MinerU wrote
   and the corpus never kept. Each one whose PDF is still where its record
   says, unchanged, is removed and converted again with MinerU 4 - text
   and figures - under the same identifier, which kennis derives from the
   DOI or arXiv number. A pack's paper is written again by `kennis corpus
   sync` from the pack's own file; yours by `kennis corpus add`. A paper
   whose PDF moved or changed is named and left as it is.
2. **Tags.** `tags.yml` is read no longer; each tag in it becomes an
   annotation (`kennis tag`), checked first against the passage's words,
   and the file is removed.
3. **`.gitignore` and `.gitattributes`.** A line `kennis corpus init` writes
   today and this corpus lacks is added.

Then the index is rebuilt (`kennis corpus index`), and the corpus is read
again: anything still to do is listed and the exit status is 1.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from platformdirs import user_data_dir

# `kennis corpus init`'s lines in v0.15.0, comments and blank lines left
# out. A test in kennis asserts these equal what `corpus init` writes.
EXPECTED_LINES: Mapping[str, tuple[str, ...]] = {
    ".gitignore": (
        ".kennis.lock",
        "index/**",
        "!index/*/",
        "!index/*/latest.json",
        "!index/*/*/",
        "!index/*/*/binding.json",
        "index/*/.*/",
        "index/*/vectors/",
        "packs/",
    ),
    ".gitattributes": (
        "* text=auto eol=lf",
        "*.npy binary",
        "*.jsonl -diff",
        "index/** -diff -text",
    ),
}

ADDED_HEADER = "# Added by upgrade_corpus.py for kennis v0.15.0."
TAGS_FILE = "tags.yml"

# A markdown image: `![caption](target)`, the target possibly in <>.
_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")

type Ran = tuple[int, str]
type Runner = Callable[[Sequence[str], bool], Ran]


@dataclass(frozen=True, slots=True)
class Paper:
    """A paper to convert again, with what its record says it came from."""

    document_id: str
    title: str
    markdown: Path
    owner: str
    pdf: Path
    sha256: str
    identifier: str
    citekey: str
    group: str


@dataclass(frozen=True, slots=True)
class Left:
    """A paper that links images it does not hold and is not converted
    again, and why."""

    paper: Paper
    reason: str


@dataclass(frozen=True, slots=True)
class TagGroup:
    """The tags `tags.yml` put on one passage, or on a whole document when
    `chunk` is None, with the words the passage opened with."""

    document_id: str
    chunk: int | None
    quote: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    from_packs: tuple[Paper, ...] = ()
    own: tuple[Paper, ...] = ()
    left: tuple[Left, ...] = ()
    tags: tuple[TagGroup, ...] = ()
    colours: Mapping[str, str] = field(default_factory=dict)
    tags_file: bool = False
    lines: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Tags that could not be placed, kept for the report after an apply.
    unplaced: tuple[TagGroup, ...] = ()
    # Removed, not written again, and restored as they were (#694).
    put_back: tuple[Paper, ...] = ()
    # Removed, not written again, and the restore failed too.
    lost: tuple[Paper, ...] = ()

    def has_work(self) -> bool:
        """Whether an apply would change anything: a paper left is only
        reported."""
        return bool(self.from_packs or self.own or self.tags_file or self.lines)

    def is_empty(self) -> bool:
        return not (
            self.from_packs
            or self.own
            or self.left
            or self.tags_file
            or self.lines
            or self.unplaced
            or self.put_back
            or self.lost
        )


# ---------------------------------------------------------------------------
# Reading the corpus
# ---------------------------------------------------------------------------


def frontmatter_of(markdown: Path) -> dict[str, object] | None:
    text = markdown.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    loaded = yaml.safe_load(text[4:end])
    return loaded if isinstance(loaded, dict) else None


def body_of(markdown: Path) -> str:
    text = markdown.read_text(encoding="utf-8", errors="replace")
    end = text.find("\n---\n", 4) if text.startswith("---\n") else -1
    return text[end + 5 :] if end >= 0 else text


def unheld_images(markdown: Path) -> list[str]:
    """Local images the markdown links that are not beside it."""
    missing: list[str] = []
    for target in _IMAGE.findall(body_of(markdown)):
        if "://" in target or target.startswith(("/", "data:", "#")):
            continue
        if not (markdown.parent / target).is_file():
            missing.append(target)
    return missing


def digest_of(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            hashed.update(block)
    return hashed.hexdigest()


def group_of(markdown: Path, literature: Path) -> str:
    """The folder the paper is filed in, relative to the collection: a
    paper in a directory of its own is filed where the directory is."""
    folder = (
        markdown.parent.parent if markdown.name == "content.md" else markdown.parent
    )
    relative = folder.relative_to(literature)
    return "" if relative == Path(".") else relative.as_posix()


def text_field(mapping: object, key: str) -> str:
    if isinstance(mapping, dict):
        value = mapping.get(key)
        if isinstance(value, str):
            return value
    return ""


def papers_to_convert(
    corpus: Path, only: frozenset[str] = frozenset()
) -> tuple[list[Paper], list[Paper], list[Left]]:
    literature = corpus / "literature"
    from_packs: list[Paper] = []
    own: list[Paper] = []
    left: list[Left] = []
    if not literature.is_dir():
        return from_packs, own, left
    for markdown in sorted(literature.rglob("*.md")):
        relative = markdown.relative_to(literature)
        if any(part.startswith(".") for part in relative.parts):
            continue
        front = frontmatter_of(markdown)
        if front is None:
            continue
        source = front.get("source")
        origin = text_field(source, "from")
        if text_field(source, "via") != "mineru" or not origin.startswith("path:"):
            continue
        if only and text_field(front, "id") not in only:
            continue
        if not unheld_images(markdown):
            continue
        paper = Paper(
            document_id=text_field(front, "id"),
            title=text_field(front, "title"),
            markdown=markdown,
            owner=text_field(front, "owner"),
            pdf=Path(origin[len("path:") :]),
            sha256=text_field(source, "sha256"),
            identifier=text_field(front, "id_from"),
            citekey=text_field(front.get("bib"), "citekey"),
            group=group_of(markdown, literature),
        )
        reason = why_not_convertible(paper, corpus)
        if reason is not None:
            left.append(Left(paper, reason))
        elif paper.owner.startswith("pack:"):
            from_packs.append(paper)
        else:
            own.append(paper)
    return from_packs, own, left


def held_identifiers(corpus: Path) -> frozenset[str]:
    """Every literature document's identifier, as the corpus has it now."""
    literature = corpus / "literature"
    if not literature.is_dir():
        return frozenset()
    held: set[str] = set()
    for markdown in literature.rglob("*.md"):
        relative = markdown.relative_to(literature)
        if any(part.startswith(".") for part in relative.parts):
            continue
        front = frontmatter_of(markdown)
        if front is not None and text_field(front, "id"):
            held.add(text_field(front, "id"))
    return frozenset(held)


def in_the_store(paper: Paper, corpus: Path) -> Path | None:
    """The pack's own file for `paper` in this corpus's store, found by its
    place under `packs/<id>/` rather than by the absolute path recorded,
    which names wherever the corpus was when it was converted."""
    pack_id = paper.owner[len("pack:") :]
    parts = paper.pdf.parts
    for index in range(len(parts) - 1):
        if parts[index] == "packs" and parts[index + 1] == pack_id:
            candidate = corpus.joinpath("packs", pack_id, *parts[index + 2 :])
            return candidate if candidate.is_file() else None
    return None


def why_not_convertible(paper: Paper, corpus: Path) -> str | None:
    if not paper.document_id or not paper.identifier:
        return "its record names no identifier to convert it again under"
    if paper.owner.startswith("pack:"):
        stored = in_the_store(paper, corpus)
        if stored is not None:
            if paper.sha256 and digest_of(stored) == paper.sha256:
                return None
            return f"the pack's file {stored} is not the one it was converted from"
        if paper.pdf.is_file() and digest_of(paper.pdf) == paper.sha256:
            return (
                "you supplied its PDF for a pack, so a sync would ask for it "
                f"again: run `kennis corpus remove {paper.document_id}`, then "
                f"`kennis corpus sync` on a terminal and give it {paper.pdf}"
            )
        return f"its PDF is no longer at {paper.pdf}"
    if paper.owner != "user":
        return f"its owner {paper.owner!r} is not one kennis knows"
    if not paper.pdf.is_file():
        return f"its PDF is no longer at {paper.pdf}"
    if not paper.sha256 or digest_of(paper.pdf) != paper.sha256:
        return f"{paper.pdf} is not the file it was converted from"
    return None


def tags_in(corpus: Path) -> tuple[list[TagGroup], dict[str, str]]:
    """`tags.yml` as v0.14.0 wrote it: each tag's targets, or a mapping of
    its `colour` and `targets`; a target is a document with, for a
    passage, its chunk and the words it opened with."""
    path = corpus / TAGS_FILE
    if not path.is_file():
        return [], {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return [], {}
    grouped: dict[tuple[str, int | None], tuple[str | None, list[str]]] = {}
    colours: dict[str, str] = {}
    for name, value in loaded.items():
        targets = value
        if isinstance(value, dict):
            colour = value.get("colour")
            if isinstance(colour, str):
                colours[str(name)] = colour
            targets = value.get("targets", [])
        for target in targets if isinstance(targets, list) else []:
            if not isinstance(target, dict) or not isinstance(
                target.get("document"), str
            ):
                continue
            chunk = target.get("chunk")
            key = (target["document"], chunk if isinstance(chunk, int) else None)
            quote = target.get("quote")
            existing = grouped.setdefault(
                key, (quote if isinstance(quote, str) else None, [])
            )
            existing[1].append(str(name))
    groups = [
        TagGroup(document, chunk, quote, tuple(sorted(set(names))))
        for (document, chunk), (quote, names) in grouped.items()
    ]
    return groups, colours


def missing_lines(corpus: Path) -> dict[str, tuple[str, ...]]:
    missing: dict[str, tuple[str, ...]] = {}
    for name, expected in EXPECTED_LINES.items():
        path = corpus / name
        held = (
            {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
            if path.is_file()
            else set()
        )
        lacking = tuple(line for line in expected if line not in held)
        if lacking:
            missing[name] = lacking
    return missing


def plan_upgrade(corpus: Path, only: frozenset[str] = frozenset()) -> Plan:
    """What an upgrade would do; with `only`, to those papers alone."""
    from_packs, own, left = papers_to_convert(corpus, only)
    tags, colours = tags_in(corpus)
    return Plan(
        from_packs=tuple(from_packs),
        own=tuple(own),
        left=tuple(left),
        tags=tuple(tags),
        colours=colours,
        tags_file=(corpus / TAGS_FILE).is_file(),
        lines=missing_lines(corpus),
    )


# ---------------------------------------------------------------------------
# Changing it, through kennis
# ---------------------------------------------------------------------------


class StepFailed(Exception):
    """A kennis command the upgrade ran did not succeed."""

    put_back: tuple[Paper, ...] = ()
    lost: tuple[Paper, ...] = ()


def required(run: Runner, arguments: Sequence[str], *, capture: bool = False) -> str:
    code, output = run(arguments, capture)
    if code != 0:
        raise StepFailed(f"`kennis {' '.join(arguments)}` exited with {code}")
    return output


def words_of(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def holds_quote(passage: str, quote: str) -> bool:
    """Whether the passage's words contain the quote's, in order and
    together; markdown and spacing are not the passage's words."""
    wanted = words_of(quote)
    held = words_of(passage)
    return bool(wanted) and any(
        held[start : start + len(wanted)] == wanted
        for start in range(len(held) - len(wanted) + 1)
    )


def converted_tags(plan: Plan, run: Runner, corpus: Path) -> list[TagGroup]:
    unplaced: list[TagGroup] = []
    for group in plan.tags:
        if group.chunk is None:
            passage = [group.document_id]
        else:
            shown = run(["read", group.document_id, "--chunks", str(group.chunk)], True)
            if group.quote and (
                shown[0] != 0 or not holds_quote(shown[1], group.quote)
            ):
                unplaced.append(group)
                continue
            passage = [f"id={group.document_id}", f"chunk={group.chunk}"]
        code, _ = run(["tag", ",".join(group.tags), *passage], False)
        if code != 0:
            unplaced.append(group)
    for name, colour in sorted(plan.colours.items()):
        required(run, ["tag", name, "--colour", colour])
    if not unplaced:
        (corpus / TAGS_FILE).unlink()
    return unplaced


def added_lines(plan: Plan, corpus: Path) -> None:
    for name, lacking in plan.lines.items():
        path = corpus / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n{ADDED_HEADER}\n" + "".join(f"{line}\n" for line in lacking)
        path.write_text(text, encoding="utf-8", newline="\n")


def converted_papers(
    plan: Plan, run: Runner, corpus: Path
) -> tuple[tuple[Paper, ...], tuple[Paper, ...]]:
    """Each paper removed and written again; returns those put back as they
    were, and those that could not be.

    A sync reports a paper it could not convert and exits 0 (#694), and
    an add exits 1 for one paper it refused (Brian's trial, 2026-11-26),
    so whether a paper came back is looked at, never inferred from an
    exit status; and it is looked at when a step fails outright as well,
    because by then every paper has been removed.
    """
    removed: list[Paper] = []
    try:
        _removed_and_written_again(plan, run, removed)
    except StepFailed as failure:
        failure.put_back, failure.lost = put_back(removed, run, corpus)
        raise
    return put_back(removed, run, corpus)


def put_back(
    removed: Sequence[Paper], run: Runner, corpus: Path
) -> tuple[tuple[Paper, ...], tuple[Paper, ...]]:
    held = held_identifiers(corpus)
    restored: list[Paper] = []
    lost: list[Paper] = []
    for paper in removed:
        if paper.document_id in held:
            continue
        # Recorded rather than raised: a failure here must not hide the
        # step that failed first.
        code, _ = run(["corpus", "restore", paper.document_id], False)
        if code == 0 and paper.document_id in held_identifiers(corpus):
            restored.append(paper)
        else:
            lost.append(paper)
    return tuple(restored), tuple(lost)


def _removed_and_written_again(plan: Plan, run: Runner, removed: list[Paper]) -> None:
    for paper in (*plan.from_packs, *plan.own):
        required(
            run,
            [
                "corpus",
                "remove",
                paper.document_id,
                "--collection",
                "literature",
                "--yes",
            ],
        )
        removed.append(paper)
    if plan.from_packs:
        required(run, ["corpus", "sync"])
    for paper in plan.own:
        arguments = [
            "corpus",
            "add",
            "-l",
            str(paper.pdf),
            "--identifier",
            paper.identifier,
        ]
        if paper.citekey:
            arguments += ["--citekey", paper.citekey]
        if paper.title:
            arguments += ["--title", paper.title]
        if paper.group:
            arguments += ["--group", paper.group]
        # Not `required`: an add exits 1 for the one paper it refused, and
        # the papers after it are still to be written again.
        run(arguments, False)


def upgrade_corpus(
    corpus: Path,
    *,
    run: Runner,
    apply: bool,
    backup: bool,
    only: frozenset[str] = frozenset(),
) -> Plan:
    """The plan, carried out when `apply`; returns what is left to do."""
    plan = plan_upgrade(corpus, only)
    if not apply or not plan.has_work():
        return plan
    if backup:
        required(run, ["backup", "create"])
    # Tags first. `kennis read --chunks` reads the index, which holds the
    # text tags.yml was written against until `corpus index` at the end;
    # a tag on a paper converted again keeps the words it was put on, and
    # is no longer found if MinerU 4 writes them differently.
    unplaced = converted_tags(plan, run, corpus) if plan.tags_file else []
    if plan.lines:
        added_lines(plan, corpus)
    restored: tuple[Paper, ...] = ()
    lost: tuple[Paper, ...] = ()
    if plan.from_packs or plan.own:
        restored, lost = converted_papers(plan, run, corpus)
    required(run, ["corpus", "index"])
    after = plan_upgrade(corpus, only)
    return Plan(
        from_packs=after.from_packs,
        own=after.own,
        left=after.left,
        tags=after.tags,
        colours=after.colours,
        tags_file=after.tags_file,
        lines=after.lines,
        unplaced=tuple(unplaced),
        put_back=restored,
        lost=lost,
    )


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def corpus_root(given: str | None) -> Path:
    if given:
        return Path(given).expanduser()
    if os.environ.get("KENNIS_CORPUS_ROOT"):
        return Path(os.environ["KENNIS_CORPUS_ROOT"]).expanduser()
    answered = subprocess.run(
        ["kennis", "config", "get", "corpus.root"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    configured = answered.stdout.strip()
    if answered.returncode == 0 and configured:
        return Path(configured).expanduser()
    return Path(user_data_dir("kennis"))


def kennis_runner(corpus: Path) -> Runner:
    """`kennis` on PATH, pointed at `corpus` whatever the settings say, so
    it acts on the corpus this script read. An uncaptured command keeps the
    terminal, which is how `backup create` asks for its password."""
    environment = {**os.environ, "KENNIS_CORPUS_ROOT": str(corpus)}

    def run(arguments: Sequence[str], capture: bool) -> Ran:
        print(f"\n$ kennis {' '.join(arguments)}", flush=True)
        if capture:
            done = subprocess.run(
                ["kennis", *arguments],
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                stdin=subprocess.DEVNULL,
                timeout=600,
            )
            return done.returncode, done.stdout
        # No timeout: a sync converts every paper and takes as long as
        # MinerU does; the person watching can stop it with Ctrl-C.
        return subprocess.run(["kennis", *arguments], env=environment).returncode, ""

    return run


def described(plan: Plan) -> list[str]:
    lines: list[str] = []
    if plan.from_packs:
        lines.append(
            "Convert again from the pack's file, then `kennis corpus sync`: "
            f"{len(plan.from_packs)}"
        )
        lines += [f"  {paper.document_id}  {paper.title}" for paper in plan.from_packs]
    if plan.own:
        lines.append(
            f"Convert again from your PDF, with `kennis corpus add`: {len(plan.own)}"
        )
        lines += [
            f"  {paper.document_id}  {paper.title}  ({paper.pdf})" for paper in plan.own
        ]
    if plan.left:
        lines.append(
            f"Linking figures it does not hold, and left as it is: {len(plan.left)}"
        )
        lines += [
            f"  {left.paper.document_id}  {left.paper.title}: {left.reason}"
            for left in plan.left
        ]
    converting = {paper.document_id for paper in (*plan.from_packs, *plan.own)}
    if plan.tags_file:
        lines.append(
            f"Tags in {TAGS_FILE} to make annotations: {len(plan.tags)} passages"
        )
        for group in plan.tags:
            where = (
                "the whole document" if group.chunk is None else f"chunk {group.chunk}"
            )
            lines.append(f"  {', '.join(group.tags)} on {group.document_id}, {where}")
            if group.document_id in converting:
                lines.append(
                    "    on a paper converted again: no longer found if MinerU 4 "
                    "writes these words differently"
                )
    if plan.unplaced:
        lines.append(
            "Tags not placed, because the passage no longer holds their "
            f"words; {TAGS_FILE} kept:"
        )
        for group in plan.unplaced:
            lines.append(
                f"  {', '.join(group.tags)} on {group.document_id}, "
                f"chunk {group.chunk}: {group.quote!r}"
            )
    for name, lacking in plan.lines.items():
        lines.append(f"Lines to add to {name}: " + ", ".join(lacking))
    if plan.put_back:
        lines.append(
            "Could not be converted again, so put back as it was; run this "
            f"script again to try again: {len(plan.put_back)}"
        )
        lines += [f"  {paper.document_id}  {paper.title}" for paper in plan.put_back]
    if plan.lost:
        lines.append(
            "Removed, not converted again and not put back; put each back with "
            f"the command beside it: {len(plan.lost)}"
        )
        lines += [
            f"  {paper.document_id}  {paper.title}: "
            f"kennis corpus restore {paper.document_id}"
            for paper in plan.lost
        ]
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bring a corpus written before kennis v0.15.0 to v0.15.0's shape."
    )
    parser.add_argument("--corpus", help="The corpus folder; kennis's own by default.")
    parser.add_argument("--apply", action="store_true", help="Make the changes.")
    parser.add_argument(
        "--paper",
        action="append",
        default=[],
        metavar="ID",
        help=(
            "Convert only this paper again, by its identifier; repeat for "
            "more. Tags and lines are upgraded all the same."
        ),
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="With --apply: do not run `kennis backup create` first.",
    )
    options = parser.parse_args(argv)
    corpus = corpus_root(options.corpus)
    if not (corpus / ".git").is_dir():
        print(f"There is no kennis corpus at {corpus}.", file=sys.stderr)
        return 2
    print(f"Corpus: {corpus}")
    only = frozenset(options.paper)
    plan = plan_upgrade(corpus, only)
    if plan.is_empty():
        print("Nothing to upgrade.")
        return 0
    print("\n".join(described(plan)))
    if not options.apply:
        print("\nNothing was changed. Run again with --apply to make these changes.")
        return 0
    try:
        remaining = upgrade_corpus(
            corpus,
            run=kennis_runner(corpus),
            apply=True,
            backup=not options.no_backup,
            only=only,
        )
    except StepFailed as failure:
        undone = described(Plan(put_back=failure.put_back, lost=failure.lost))
        if undone:
            print("\n" + "\n".join(undone), file=sys.stderr)
        print(
            f"\nStopped: {failure}. Run this script again to carry on.", file=sys.stderr
        )
        return 1
    if remaining.is_empty():
        print("\nThe corpus is upgraded.")
        return 0
    print("\nStill to do:\n" + "\n".join(described(remaining)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
