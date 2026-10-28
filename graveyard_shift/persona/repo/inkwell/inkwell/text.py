import re


def slugify(title):
    """Turn a post title into a URL slug: 'Hello, World!' -> 'hello-world'."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")


def reading_time(text, words_per_minute=200):
    """Whole minutes to read the text, at least 1."""
    return max(1, round(len(text.split()) / words_per_minute))


def excerpt(text, limit=140):
    """The first `limit` characters, cut at a word boundary."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"
