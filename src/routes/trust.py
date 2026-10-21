"""Trust pages: /o-pitomnike/, /otzyvy/, /dokumenty-i-garantii/.
Owns: src/templates/trust/, src/data/trust.json (copy), assets/css/trust.css, assets/js/trust.js
(«Показать ещё отзывы» + «Оставить отзыв» modal on /otzyvy/).
Client 21.10: /vypuskniki/ is gone — the graduates (owners' photo reviews, as on the homepage) are a block of
«О питомнике» (/o-pitomnike/), the page about the kennel itself. /otzyvy/ shows the same photo reviews, no breed filter."""

from _lib import by_id, crumbs, mixed_puppies, sort_puppies
from blog import rich

ABOUT_PUPS = 8  # «Каталог щенков» on /o-pitomnike/: 4 / 2 per row — full rows (3 per row: the first 6, trust.css)
OTZ_PUPS = 8  # «Щенки в наличии» on /otzyvy/: the first puppies of /shchenki/, as on the homepage


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
                # «Каталог щенков» as on the homepage: the first 8 cards in the catalog's order + «Перейти в каталог»
                catalog=sort_puppies(data["puppies"])[:ABOUT_PUPS],
                # «Наши выпускники»: the owners' photo reviews of the homepage (home.json → reviews_home)
                graduates=data["home"]["reviews_home"],
                faq_items=_faq(about["faq"], faq),
                pups_strip=False,      # the template has its own catalog block (8 cards), like the homepage
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
                # the owners' photo reviews of the homepage (home.json → reviews_home), all of them
                reviews=data["home"]["reviews_home"],
                catalog=sort_puppies(data["puppies"])[:OTZ_PUPS],
                pups_strip=False,      # the template places «Щенки в наличии» itself, right after the advantages
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
                # «Щенки в наличии» (client 21.10): the standard block — two puppies of every breed + «Весь каталог»
                catalog=mixed_puppies(data["breeds"]),
                pups_strip=False,
            ),
        ),
    ]
