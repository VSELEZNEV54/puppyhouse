"""Small helpers for route modules. READ-ONLY for page-group agents (copy what you need into your module
if you want something different). Files starting with "_" are not route modules.

    from _lib import crumbs, by_id, sort_puppies, mixed_puppies, adj_gen
    from _lib import nobr, nb      # copy text → Markup that never breaks inside «Санкт-Петербург» or «10–16 лет»
"""

import re

from markupsafe import Markup, escape

HOME = ("Главная", "/")
NBSP = "\u00a0"


def crumbs(*items):
    """crumbs(("Щенки", "/shchenki/"), ("Пломбир", None)) -> [["Главная", "/"], ["Щенки", "/shchenki/"], ["Пломбир", None]].
    The last item is the current page (rendered as text, not a link)."""
    out = [list(HOME)] + [list(i) for i in items]
    out[-1][1] = None
    return out


def by_id(items, key="id"):
    """{item[key]: item} for a list of dicts (faq.json by "id", breeds by "slug", ...)."""
    return {i[key]: i for i in items}


def sort_puppies(puppies):
    """Available first, then «скоро», then reserved; source order inside each group."""
    return sorted(puppies, key=lambda p: p["status_order"])


def mixed_puppies(breeds, per_breed=2):
    """«Щенки в наличии» of a page about all breeds (client 21.10): per_breed puppies of every breed, breed after breed,
    so each row of four cards shows all four breeds (8 cards with the default)."""
    per = [sort_puppies(b["puppies"]) for b in breeds]
    return [pups[i] for i in range(per_breed) for pups in per if len(pups) > i]


# Visible copy never breaks inside «Санкт-Петербург», «о бордер-колли» or a range like «10–16 лет»: such words go into
# <span class="nw"> (the macros' |typo keeps Markup tags). Copy with a hand-written link (<a href="/…/">) is trusted
# Markup from our own data; everything else is escaped first. Meta title/description and attributes stay plain text.
_HYPHENATED = re.compile(r"(?<![\w-])((?:\w{1,2} )?\w+(?:-\w+)+)")
_RANGE = re.compile(r"(?<![\w,])(\d+(?:,\d+)?–\d+(?:,\d+)?)(?: (?=[а-яё])(?!(?:и|или|а|но|до|в|во|на|с|со|по|за|из|от|к|у|о)\b))?")
_TAG = re.compile(r"(<[^>]+>)")


def _nobr_text(s):
    s = _HYPHENATED.sub(r'<span class="nw">\1</span>', s)
    return _RANGE.sub(lambda m: f'<span class="nw">{m.group(1)}</span>' + (NBSP if m.group(0).endswith(" ") else ""), s)


def nobr(text):
    """Text → Markup with hyphenated words and number ranges kept on one line (links in our own copy stay links)."""
    if not isinstance(text, str):
        return text
    raw = text if "<a " in text else str(escape(text))
    return Markup("".join(p if p.startswith("<") else _nobr_text(p) for p in _TAG.split(raw)))


def adj_gen(phrase):
    """Colour adjectives in the genitive, the accusative of an animal in a title («Купить рыжего щенка»):
    «Голубой мраморный» → «голубого мраморного», «чёрно-белый» → «чёрно-белого», «рыжий» → «рыжего», «пегий» → «пегого»."""
    def one(w):
        if w.endswith(("ый", "ой")):
            return w[:-2] + "ого"
        if w.endswith("ий"):
            return w[:-2] + ("ого" if w[-3:-2] in ("г", "к", "х") else "его")
        return w
    return " ".join(one(w) for w in phrase.lower().split())


def nb(d, *keys):
    """Copy of dict d with the given text keys passed through nobr()."""
    return {k: (nobr(v) if k in keys else v) for k, v in d.items()}
