"""Small helpers for route modules. READ-ONLY for page-group agents (copy what you need into your module
if you want something different). Files starting with "_" are not route modules.

    from _lib import crumbs, by_id, sort_puppies
"""

HOME = ("Главная", "/")


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
