"""Trust pages: /o-pitomnike/, /otzyvy/, /dokumenty-i-garantii/.
Owns: src/templates/trust/, src/data/trust.json (copy), assets/css/trust.css, assets/js/trust.js
(review filter + «Оставить отзыв» modal on /otzyvy/).
Client 21.10: /vypuskniki/ is gone — the graduates (owners' photo reviews, as on the homepage) are a block of
«О питомнике» (/o-pitomnike/), the page about the kennel itself."""

from _lib import by_id, crumbs
from blog import rich


def _faq(items, faq):
    """trust.json FAQ entries: {"ref": "<faq.json id>"} or a page-specific {"q", "a"}."""
    return [faq[i["ref"]] if "ref" in i else i for i in items]


def routes(data):
    t = data["trust"]
    faq = by_id(data["faq"])

    about = t["o_pitomnike"]
    # SEO text of the page: paragraphs with the blog mini-markup ([label](/url/) → link)
    about_seo = dict(about["seo"], blocks=[dict(b, p=rich(b["p"])) for b in about["seo"]["blocks"]])

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
            url="/o-pitomnike/",
            template="trust/o-pitomnike.html.j2",
            context=dict(
                title=about["title"],
                description=about["description"],
                breadcrumbs=crumbs(("О питомнике", None)),
                pg=about,
                seo=about_seo,
                stats=data["site"]["stats"],
                # «Наши выпускники»: the owners' photo reviews of the homepage (home.json → reviews_home)
                graduates=data["home"]["reviews_home"],
                faq_items=_faq(about["faq"], faq),
                pups_strip=False,      # the template places the «Щенки в наличии» strip itself, before the FAQ
                blog_strip=False,
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
