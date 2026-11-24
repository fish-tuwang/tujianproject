"""Remove verbatim echo openings before reply segmentation reaches QQ."""
import re
import unicodedata


def normalized(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC',text) if c.isalnum())


def clean(text, query):
    target=normalized(query)
    if not target:return text
    # Remove only a complete matching opening clause; retain substantive answers.
    rest=text.lstrip()
    while rest:
        match=re.match(r'^([^\n。！？!?]+)[。！？!?]*(?:[^\w\u3400-\u9fff\n]*)(?:\n|$)?',rest)
        if not match:break
        clause=normalized(match.group(1))
        if clause != target:break
        rest=rest[match.end():].lstrip()
    return rest
