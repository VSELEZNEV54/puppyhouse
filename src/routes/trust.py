"""Trust pages: /roditeli/, /vypuskniki/, /otzyvy/, /dokumenty-i-garantii/.
Owns: src/templates/trust/, src/data/trust.json (copy), assets/css/trust.css, assets/js/trust.js
(review filter + «Оставить отзыв» modal on /otzyvy/)."""

from _lib import by_id, crumbs


def _faq(items, faq):
    """trust.json FAQ entries: {"ref": "<faq.json id>"} or a page-specific {"q", "a"}."""
    return [faq[i["ref"]] if "ref" in i else i for i in items]


def routes(data):
    t = data["trust"]
    faq = by_id(data["faq"])
    breeds = by_id(data["breeds"], "slug")
    stats = by_id(data["site"]["stats"], "icon")

    rod = t["roditeli"]
    parents = [dict(p, b=breeds[p["breed"]]) for p in rod["parents"]["items"]]

    vyp = t["vypuskniki"]
    stories = [dict(s, b=breeds[s["breed"]]) for s in vyp["stories"]["items"]]

    otz = t["otzyvy"]
    reviews = data["reviews"]
    # filter chips: only breeds that have reviews, in breeds.json order
    review_breeds = [b for b in data["breeds"] if any(r["breed"] == b["slug"] for r in reviews)]

    dok = t["dokumenty"]
    groups = {
        "all": data["breeds"],
        "rkf": [b for b in data["breeds"] if b["rkf"]],
        "hybrid": [b for b in data["breeds"] if not b["rkf"]],
    }
    docs = [dict(d, fit_breeds=groups[d["breeds"]]) for d in dok["docs"]["items"]]

    return [
        dict(
            url="/roditeli/",
            template="trust/roditeli.html.j2",
            context=dict(
                title=rod["title"],
                description=rod["description"],
                breadcrumbs=crumbs(("Родители", None)),
                pg=rod,
                parents=parents,
                faq_items=_faq(rod["faq"], faq),
            ),
        ),
        dict(
            url="/vypuskniki/",
            template="trust/vypuskniki.html.j2",
            context=dict(
                title=vyp["title"],
                description=vyp["description"],
                breadcrumbs=crumbs(("Выпускники", None)),
                pg=vyp,
                stats=[stats[i] for i in vyp["stats"]],
                stories=stories,
            ),
        ),
        dict(
            url="/otzyvy/",
            template="trust/otzyvy.html.j2",
            context=dict(
                title=otz["title"],
                description=otz["description"],
                breadcrumbs=crumbs(("Отзывы", None)),
                pg=otz,
                reviews=reviews,
                review_breeds=review_breeds,
            ),
        ),
        dict(
            url="/dokumenty-i-garantii/",
            template="trust/dokumenty.html.j2",
            context=dict(
                title=dok["title"],
                description=dok["description"],
                breadcrumbs=crumbs(("Документы и гарантии", None)),
                pg=dok,
                docs=docs,
                faq_items=_faq(dok["faq"], faq),
            ),
        ),
    ]
