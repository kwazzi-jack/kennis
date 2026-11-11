"""Which of a conversion's image files are kept, and under what name.

A converter writes far more image files than its markdown links: MinerU
wrote 129 for one paper and linked 5, the rest being crops of equations and
tables (#134, measured 2026-11-11). What is kept is what the markdown links,
named by its own content, beside the document.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from kennis.engine.corpus.images import IMAGE_SUFFIXES, kept_images

# The opening of a real JPEG. **Not valid UTF-8**, which is the point: a
# fixture of `b"png"` decodes as text and hides every place that reads an
# image as one.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb"
OTHER_JPEG = JPEG + b"\x00\x43\x00\x08\x06\x06"

MINERU_NAME = "38a2f261a5eb2daa06e47cb49e72b197349af48cfa480a96e9b2356bffda6610.jpg"


def name_of(content: bytes, suffix: str = ".jpg") -> str:
    return hashlib.sha256(content).hexdigest()[:16] + suffix


def test_a_linked_image_is_kept_under_a_name_made_from_its_content(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / MINERU_NAME).write_bytes(JPEG)
    markdown = f"Before.\n\n![](images/{MINERU_NAME})  \nFigure 1. A caption.\n"

    rewritten, images = kept_images(markdown, directory)

    assert images == {name_of(JPEG): JPEG}
    assert rewritten == f"Before.\n\n![]({name_of(JPEG)})  \nFigure 1. A caption.\n"


def test_the_name_is_not_the_converters(tmp_path: Path) -> None:
    """MinerU's 64 characters are not a hash of the file, and another
    converter names an image by its page; the stored name is the content's
    own, so it does not depend on which converter wrote it."""
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "_page_0_Figure_1.jpeg").write_bytes(JPEG)

    _, images = kept_images("![](images/_page_0_Figure_1.jpeg)\n", directory)

    assert list(images) == [name_of(JPEG, ".jpeg")]


def test_an_image_nothing_links_is_not_kept(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "linked.jpg").write_bytes(JPEG)
    (directory / "images" / "an-equation-crop.jpg").write_bytes(OTHER_JPEG)

    _, images = kept_images("![](images/linked.jpg)\n", directory)

    assert list(images.values()) == [JPEG]


def test_markdown_that_links_nothing_keeps_nothing_and_is_unchanged(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "crop.jpg").write_bytes(JPEG)
    markdown = "# A paper\n\nNo figure here, only $x^2$.\n"

    assert kept_images(markdown, directory) == (markdown, {})


def test_one_image_linked_twice_is_one_file(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "a.jpg").write_bytes(JPEG)
    (directory / "images" / "the-same-again.jpg").write_bytes(JPEG)

    rewritten, images = kept_images(
        "![](images/a.jpg)\n\n![](images/the-same-again.jpg)\n\n![](images/a.jpg)\n",
        directory,
    )

    assert images == {name_of(JPEG): JPEG}
    assert rewritten.count(f"![]({name_of(JPEG)})") == 3


def test_two_images_keep_two_names(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "a.jpg").write_bytes(JPEG)
    (directory / "images" / "b.jpg").write_bytes(OTHER_JPEG)

    _, images = kept_images("![](images/a.jpg)\n\n![](images/b.jpg)\n", directory)

    assert images == {name_of(JPEG): JPEG, name_of(OTHER_JPEG): OTHER_JPEG}


def test_the_alternative_text_is_kept(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "a.png").write_bytes(JPEG)

    rewritten, _ = kept_images("![Refer to caption](images/a.png)\n", directory)

    assert rewritten == f"![Refer to caption]({name_of(JPEG, '.png')})\n"


# ---------------------------------------------------------------------------
# What is left exactly as written
# ---------------------------------------------------------------------------


def test_a_link_to_a_file_that_is_not_there_is_left_as_written(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    directory.mkdir()
    markdown = "![](images/gone.jpg)\n"

    assert kept_images(markdown, directory) == (markdown, {})


@pytest.mark.parametrize(
    "target",
    [
        "https://arxiv.org/html/1501.00187v2/fig1.png",
        "http://example.org/a.jpg",
        "//example.org/a.jpg",
        "data:image/png;base64,AAAA",
    ],
)
def test_a_remote_image_is_left_as_written(tmp_path: Path, target: str) -> None:
    directory = tmp_path / "auto"
    directory.mkdir()
    markdown = f"![Refer to caption]({target})\n"

    assert kept_images(markdown, directory) == (markdown, {})


def test_a_link_that_leaves_the_directory_keeps_nothing(tmp_path: Path) -> None:
    """The file exists, which is what makes this the test: a converter's
    markdown must not be able to name a file of the person's and have kennis
    copy it into the corpus."""
    directory = tmp_path / "auto"
    directory.mkdir()
    (tmp_path / "private.jpg").write_bytes(JPEG)
    absolute = (tmp_path / "private.jpg").as_posix()
    markdown = f"![](../private.jpg)\n\n![]({absolute})\n"
    assert (directory / ".." / "private.jpg").is_file(), "the fixture lost its file"

    assert kept_images(markdown, directory) == (markdown, {})


def test_a_link_through_a_symlink_out_of_the_directory_keeps_nothing(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (tmp_path / "private.jpg").write_bytes(JPEG)
    try:
        (directory / "images" / "a.jpg").symlink_to(tmp_path / "private.jpg")
    except OSError:
        pytest.skip("this platform would not make the symbolic link")
    markdown = "![](images/a.jpg)\n"

    assert kept_images(markdown, directory) == (markdown, {})


@pytest.mark.parametrize("name", ["drawing.svg", "content.md", "paper.pdf", "noext"])
def test_a_file_that_is_not_a_raster_image_is_not_kept(
    tmp_path: Path, name: str
) -> None:
    """An SVG is a document that can carry script, and anything else is not
    an image at all: neither is copied into the corpus as one."""
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / name).write_bytes(JPEG)
    markdown = f"![](images/{name})\n"

    assert kept_images(markdown, directory) == (markdown, {})


def test_a_directory_named_like_an_image_is_not_kept(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    (directory / "images" / "a.jpg").mkdir(parents=True)
    markdown = "![](images/a.jpg)\n"

    assert kept_images(markdown, directory) == (markdown, {})


# ---------------------------------------------------------------------------
# The name
# ---------------------------------------------------------------------------


def test_the_suffix_is_lowercased(tmp_path: Path) -> None:
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "A.JPG").write_bytes(JPEG)

    _, images = kept_images("![](images/A.JPG)\n", directory)

    assert list(images) == [name_of(JPEG)]


def test_a_kept_name_is_one_short_component_with_an_image_suffix(
    tmp_path: Path,
) -> None:
    """Sixteen hexadecimal characters and a suffix, with no separator: a
    name that is one file directly in the document's directory, that cannot
    be `content.md` or a kept original (a `.pdf`), and that leaves a mirror's
    copy of a long-titled paper under Windows' 260 characters."""
    directory = tmp_path / "auto"
    (directory / "images").mkdir(parents=True)
    for index, suffix in enumerate(sorted(IMAGE_SUFFIXES)):
        (directory / "images" / f"f{index}{suffix}").write_bytes(JPEG + bytes([index]))
    markdown = "".join(
        f"![](images/f{index}{suffix})\n"
        for index, suffix in enumerate(sorted(IMAGE_SUFFIXES))
    )

    _, images = kept_images(markdown, directory)

    assert len(images) == len(IMAGE_SUFFIXES)
    for name in images:
        assert re.fullmatch(r"[0-9a-f]{16}\.(jpg|jpeg|png|gif|webp)", name), name


def test_a_mirrored_paper_with_a_long_title_stays_under_the_windows_limit() -> None:
    """Arithmetic, because the converter tests do not run on Windows: the
    longest path an add writes is a mirror's copy of an image."""
    corpus = r"C:\Users\a-long-account-name\AppData\Local\kennis\kennis"
    mirror = corpus + "\\.git\\kennis-staging\\" + "0" * 32
    title = "T" * 100
    image = name_of(JPEG, ".jpeg")

    longest = f"{mirror}\\literature\\radio-astronomy\\{title}\\{image}"

    assert len(longest) < 260
