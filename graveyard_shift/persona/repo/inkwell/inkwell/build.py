import sys
from pathlib import Path

from .text import excerpt, reading_time, slugify


def build(src, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for post in sorted(Path(src).glob("*.md")):
        title, _, body = post.read_text().partition("\n")
        title = title.lstrip("# ")
        page = out / f"{slugify(title)}.html"
        page.write_text(f"<h1>{title}</h1><p><em>{reading_time(body)} min read</em></p><p>{excerpt(body)}</p>")
    # TODO: generate an RSS feed


if __name__ == "__main__":
    build(*sys.argv[1:3])
