"""Clean article HTML and convert it without rewriting link targets."""

import json
import re

from bs4 import BeautifulSoup
from markdownify import markdownify


def html_to_markdown(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, nav, header, footer, iframe, noscript"):
        tag.decompose()
    for img in soup.find_all("img"):
        dimensions = [
            str(img.get(key, "")).strip().lower().removesuffix("px")
            for key in ("width", "height")
        ]
        style = img.get("style", "")
        if dimensions == ["1", "1"] or (
            re.search(r"(?:^|;)\s*width\s*:\s*1px\b", style)
            and re.search(r"(?:^|;)\s*height\s*:\s*1px\b", style)
        ):
            img.decompose()

    # Protect code from both the converter and prose whitespace normalization.
    blocks = {}
    for index, pre in enumerate(soup.find_all("pre")):
        token = f"OPTISIGNSCODEBLOCK{index}PLACEHOLDER"
        while token in html:
            token += "X"
        code = pre.get_text()
        runs = re.findall(r"`+", code)
        fence = "`" * max(3, max((len(run) + 1 for run in runs), default=3))
        classes = (pre.code or pre).get("class", [])
        language = next(
            (c.removeprefix("language-") for c in classes if c.startswith("language-")),
            "",
        )
        language = re.sub(r"[^\w+-]", "", language)
        blocks[token] = f"{fence}{language}\n{code}{'' if code.endswith(chr(10)) else chr(10)}{fence}"
        replacement = soup.new_tag("p")
        replacement.string = token
        pre.replace_with(replacement)

    for tag in reversed(soup.find_all()):
        if tag.name not in {"img", "br", "hr", "code"} and not tag.get_text(strip=True) and not tag.find(["img", "br", "hr", "code"]):
            tag.decompose()
    text = markdownify(str(soup), heading_style="ATX", bullets="-")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for token, block in blocks.items():
        text = text.replace(token, block)
    return text + "\n" if text else ""


def article_to_markdown(article):
    if not isinstance(article["body"], str):
        raise ValueError("Article body must be HTML text")
    metadata = "\n".join(
        f"{key}: {json.dumps(article[field], ensure_ascii=False)}"
        for key, field in (
            ("title", "title"), ("source", "html_url"),
            ("id", "id"), ("updated_at", "updated_at"),
        )
    )
    title = " ".join(article["title"].split())
    body = html_to_markdown(article["body"])
    return f"---\n{metadata}\n---\n\n# {title}\n\n{body}".rstrip("\n") + "\n"
