"""Citations as a CSL style writes them (#571).

A document's frontmatter becomes a CSL-JSON item and citeproc-py formats it
with the style `literature.citation_style` names, Harvard (Cite Them Right)
when it names none - a style citeproc-py ships, so nothing is vendored. A
style is a `.csl` file, such as one from the Zotero style repository, so a
person chooses one without kennis changing.

**One bibliography per call**, holding every document cited in it: a style
that tells two works by one author and year apart ("2011a", "2011b") can
only do so seeing both.

**A note is not CSL's.** It has no author and no date, and a style would
say "no date" of every one; a note is cited by its title in quotes.

What is formatted is plain text, typography and all: a style's curly quotes
are the style's.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from kennis.engine.corpus.schema import (
    DocsFrontmatter,
    DocumentFrontmatter,
    LiteratureFrontmatter,
)
from kennis.engine.errors import CitationStyleUnreadable
from kennis.engine.literature.names import is_braced, split_names, unbraced

if TYPE_CHECKING:
    from citeproc import CitationStylesStyle

    from kennis.engine.citing.locators import Locator
    from kennis.engine.pack.schema import LiteratureEntry

# A CSL-JSON item, as citeproc-py reads one.
type CslItem = dict[str, object]

_DEFAULT_STYLE: Final = "harvard-cite-them-right.csl"


@dataclass(frozen=True, slots=True)
class ToCite:
    """One passage to cite: its document's frontmatter and its locator."""

    frontmatter: DocumentFrontmatter
    locator: Locator | None


@dataclass(frozen=True, slots=True)
class Formatted:
    """A citation as the style writes it in the text, and its entry in a
    list of references."""

    citation: str
    reference: str


def style_path(setting: str) -> Path:
    """The `.csl` file `literature.citation_style` names, or the default."""
    if setting:
        return Path(setting).expanduser()
    import citeproc

    return Path(citeproc.__file__).parent / "data" / "styles" / _DEFAULT_STYLE


def formatted(passages: Sequence[ToCite], style: Path) -> list[Formatted]:
    """Each passage's citation and reference, in order, by `style`."""
    from citeproc import (
        Citation,
        CitationItem,
        CitationStylesBibliography,
        formatter,
    )
    from citeproc.source import Locator as CslLocator
    from citeproc.source.json import CiteProcJSON

    items = {
        passage.frontmatter.id: csl_item(passage.frontmatter)
        for passage in passages
        if not _is_a_note(passage.frontmatter)
    }
    if not items:
        return [_note(passage) for passage in passages]
    bibliography = CitationStylesBibliography(
        _loaded_style(style), CiteProcJSON(list(items.values())), formatter.plain
    )
    citations: list[Citation | None] = []
    for passage in passages:
        if _is_a_note(passage.frontmatter):
            citations.append(None)
            continue
        locator = passage.locator
        item = (
            CitationItem(
                passage.frontmatter.id,
                locator=CslLocator(locator.kind, locator.value),
            )
            if locator is not None
            else CitationItem(passage.frontmatter.id)
        )
        citation = Citation([item])
        bibliography.register(citation)
        citations.append(citation)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        references = {
            str(key): str(entry)
            for key, entry in zip(
                bibliography.keys, bibliography.bibliography(), strict=True
            )
        }
        results: list[Formatted] = []
        for passage, citation in zip(passages, citations, strict=True):
            if citation is None:
                results.append(_note(passage))
                continue
            results.append(
                Formatted(
                    citation=str(bibliography.cite(citation, _unknown)),
                    reference=references[passage.frontmatter.id.lower()],
                )
            )
    return results


def references(items: Sequence[CslItem], style: Path) -> dict[str, str]:
    """Each item's entry in a list of references by `style`, by its id.

    One bibliography for all of them, as `formatted` makes one, so a style
    that tells two works by one author and year apart can. citeproc-py keys
    its entries by the id lower-cased, so ids must differ by more than case.
    """
    from citeproc import (
        Citation,
        CitationItem,
        CitationStylesBibliography,
        formatter,
    )
    from citeproc.source.json import CiteProcJSON

    if not items:
        return {}
    bibliography = CitationStylesBibliography(
        _loaded_style(style), CiteProcJSON(list(items)), formatter.plain
    )
    for item in items:
        bibliography.register(Citation([CitationItem(str(item["id"]))]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        by_key = {
            str(key): str(entry)
            for key, entry in zip(
                bibliography.keys, bibliography.bibliography(), strict=True
            )
        }
    return {str(item["id"]): by_key[str(item["id"]).lower()] for item in items}


def _loaded_style(style: Path) -> CitationStylesStyle:
    from citeproc import CitationStylesStyle

    try:
        with warnings.catch_warnings():
            # citeproc-py warns of the style elements it does not implement;
            # what it does with the rest is what is returned.
            warnings.simplefilter("ignore")
            return CitationStylesStyle(str(style), validate=False)
    except Exception as error:
        # Any exception: a missing file, a file that is not XML, XML that is
        # not a style - each is the one fault the setting can have.
        raise CitationStyleUnreadable(
            f"the citation style {style} cannot be read (literature.citation_style)"
        ) from error


def pack_paper_item(entry: LiteratureEntry, item_id: str) -> CslItem:
    """A paper a pack declares, as CSL-JSON, from what its entry gives.

    The same shape `csl_item` makes of a held paper's frontmatter. An entry
    carries no journal, so a style writes it as an article.
    """
    item: CslItem = {"id": item_id, "type": "article"}
    if entry.title:
        item["title"] = entry.title
    if entry.authors:
        item["author"] = [_name(name) for name in entry.authors]
    if entry.year is not None:
        item["issued"] = {"date-parts": [[entry.year]]}
    paper = entry.paper
    if paper.kind == "doi":
        item["DOI"] = paper.value
    elif paper.kind == "arxiv":
        item["URL"] = f"https://arxiv.org/abs/{paper.value}"
    return item


def _unknown(item: object) -> None:
    """citeproc-py's report of a citation naming no item; every item cited
    here was registered, so there is nothing to report."""


def _is_a_note(frontmatter: DocumentFrontmatter) -> bool:
    return not isinstance(frontmatter, LiteratureFrontmatter | DocsFrontmatter)


def _note(passage: ToCite) -> Formatted:
    title = f'"{passage.frontmatter.title}"'
    locator = passage.locator
    citation = title if locator is None else f"{title}, {locator.kind} {locator.value}"
    return Formatted(citation=citation, reference=passage.frontmatter.title)


def located_note(title: str, locator: Locator | None, where: str) -> Formatted:
    """A context passage cited as a note is (#623): by its title and
    locator, with a reference that says where the file is, since a
    project's file and a pack's are not in the corpus."""
    quoted = f'"{title}"'
    citation = (
        quoted if locator is None else f"{quoted}, {locator.kind} {locator.value}"
    )
    return Formatted(citation=citation, reference=f"{quoted}, {where}")


def csl_item(frontmatter: DocumentFrontmatter) -> CslItem:
    """A paper or a docs page as CSL-JSON."""
    item: CslItem = {"id": frontmatter.id, "title": frontmatter.title}
    match frontmatter:
        case LiteratureFrontmatter(bib=bib):
            item["type"] = "article-journal" if bib.doi else "article"
            if bib.authors:
                item["author"] = [_name(name) for name in split_names(bib.authors)]
            if bib.year and bib.year.isdigit():
                item["issued"] = {"date-parts": [[int(bib.year)]]}
            if bib.doi:
                item["DOI"] = bib.doi
            elif bib.arxiv_id:
                item["URL"] = f"https://arxiv.org/abs/{bib.arxiv_id}"
        case DocsFrontmatter(docs=docs):
            # The project as the author: a style names the work by its author
            # first, and a page's own title would be said twice.
            item["type"] = "webpage"
            item["author"] = [{"literal": docs.project}]
            item["container-title"] = docs.project
            if docs.version:
                item["version"] = docs.version
            origin = frontmatter.source.origin
            if origin.startswith("url:"):
                item["URL"] = origin.removeprefix("url:")
    return item


def _name(name: str) -> dict[str, str]:
    """One author as CSL names one: a braced name whole, as an organisation;
    "Family, Given" at its comma; otherwise the last word as the family."""
    if is_braced(name):
        return {"literal": unbraced(name)}
    if name == "others":
        return {"literal": "others"}
    family, comma, given = name.partition(",")
    if comma:
        return {"family": family.strip(), "given": given.strip()}
    *givens, last = name.split()
    if not givens:
        return {"family": last}
    return {"family": last, "given": " ".join(givens)}


def passage_with_citation(passage: str, citation: str) -> str:
    """A passage in typographic quotation marks, then its citation: what a
    hit card copies (Brian, 2026-11-06). The marks are escapes because the
    source is ASCII; the clipboard is not a file."""
    return f"\u201c{passage}\u201d {citation}"


__all__ = [
    "Formatted",
    "ToCite",
    "csl_item",
    "formatted",
    "located_note",
    "passage_with_citation",
    "style_path",
]
