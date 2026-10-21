"""Homepage — redesigned for the client revisions of 13.10 (docs/brief.md → «Главная (новый порядок)»).

Order: full-screen hero · «О нашем питомнике» (numbers from site.stats) · breeds two per row · photo and video
carousel + lead band · advantages · video reviews · how to buy · FAQ (12 questions) · blog · SEO text · lead form.
Own data: src/data/home.json (stat details, carousel items, reviews, blog picks, FAQ).

City pages /<slug>/ (client 21.10): the same page for every city of cities.json — «Купить щенка в Новосибирске
напрямую от заводчика», the whole puppy catalog after the breeds, and not a word about where the kennel is
(hide_city: no «Москва» in the logo caption and footer, no reviews from Moscow and its region, no address tiles).
Copy: src/data/home-city.json.
"""

import re

from markupsafe import Markup

from _lib import crumbs, nb, nobr, sort_puppies

TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | домщенков.рф"


def routes(data):
    home = data["home"]
    breed_names = {b["slug"]: b["name"] for b in data["breeds"]}
    blog_meta = {b["slug"]: b for b in data["blog"]}
    posts = data["blog_posts"]["posts"]

    # blog teasers: one article per breed (character and care alternate); a cover may be swapped for another photo
    # of the same breed so the homepage does not repeat the lifestyle shots of the reviews
    teasers = []
    for pick in home["blog"]:
        meta, post = blog_meta[pick["slug"]], posts[pick["slug"]]
        topic = post["topic"]
        if meta.get("breed"):
            topic = f"{breed_names[meta['breed']]} · {topic.lower()}"
        teasers.append(dict(url=meta["url"], title=post["h1"], line=post["card_line"],
                            cover=pick.get("cover") or post["cover"], topic=topic))

    rating = data["site"]["ratings"][0]
    stats = []
    for s in data["site"]["stats"]:
        line = home["stat_lines"].get(s["icon"], "")
        if s["icon"] == "star":  # «4,9 — Яндекс Карты»: «128 отзывов владельцев», the count comes from site.ratings
            line = f"{rating['count']} {_plural(rating['count'], 'отзыв', 'отзыва', 'отзывов')} владельцев"
        stats.append(dict(s, line=line))

    shared = dict(
        stats=stats,
        media_items=home["media"],
        # «О нашем питомнике»: фото листаются сами, видео доигрывает до конца (правка 15.10)
        about_slides=home["about_slides"],
        teasers=teasers,
    )
    return [dict(
        url="/",
        template="pages/home.html.j2",
        context=dict(
            shared,
            title="Купить щенка в Москве — питомник собак домщенков.рф",
            description="Питомник собак в Москве: щенки мальтипу, французского бульдога, той-пуделя и бордер-колли. "
                        "Прививки, ветпаспорт, договор, гарантия, доставка по России.",
            # отзывы на главной — свои (правка 15.10): фото щенка, текст, имя, город, порода; /otzyvy/ — reviews.json
            reviews_home=home["reviews_home"],
            faq_items=home["faq"],
        ),
    )] + [city_page(data, c, shared) for c in data["cities"]]


def fill(text, **kw):
    """str.format for copy templates; unknown keys stay as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m.group(1), m.group(0))), text)


def one_box(text):
    """nobr() in one <span>: inside a flex box (eyebrow, chip, FAQ button) «в Санкт-Петербург» must not become
    a separate flex item with a gap before it."""
    return Markup("<span>") + nobr(text) + Markup("</span>")


def city_page(data, c, shared):
    """/<slug>/ — the homepage for one city (home-city.json); the kennel's own city is never named on it."""
    hc = data["home_city"]
    methods = data["delivery"]["methods"]
    ms = [methods[m]["phrase"] for m in c["methods"]]
    v = dict(name=c["name"], prep=c["prep"], acc=c["acc"], gen=c["gen"],
             methods=ms[0] if len(ms) == 1 else ", ".join(ms[:-1]) + " или " + ms[-1])
    ov = hc["overrides"].get(c["slug"], {})

    title = fill(hc["title"], **v) + BRAND
    if len(title) > TITLE_MAX:
        title = fill(hc["title_short"], **v) + BRAND
    description = fill(hc["description"], **v)
    if len(title) > TITLE_MAX or len(description) > DESC_MAX:
        raise ValueError(f"{c['url']}: title {len(title)} / description {len(description)} chars")

    # отзывы: ни одного из Москвы и области и ни одного, где упомянута Москва; отзыв из этого города — первым
    skip = set(hc["reviews_skip"])
    reviews = [r for r in data["home"]["reviews_home"] if r["city"] not in skip and "Москв" not in r["text"]]
    reviews.sort(key=lambda r: r["city"] != c["name"])

    # вопросы главной; «Доставляете щенков в другие города?» — про этот город
    fd = hc["faq_delivery"]
    answer = fill(fd["a"], **v)
    if c["methods"] == ["plane"]:
        answer += " " + fd["plane_only"]
    assert any(f["q"] == fd["replace"] for f in data["home"]["faq"]), "home-city.json faq_delivery.replace: no such question"
    faq = [dict(q=one_box(fill(fd["q"], **v)), a=nobr(answer)) if f["q"] == fd["replace"] else f
           for f in data["home"]["faq"]]

    seo = hc["seo"]
    return dict(
        url=c["url"],
        template="pages/home.html.j2",
        context=dict(
            shared,
            title=title,
            description=description,
            breadcrumbs=crumbs((c["name"], None)),
            city=dict(nb(v, "name", "prep", "acc", "gen"), slug=c["slug"]),
            hide_city=True,
            hero=dict(eyebrow=one_box(fill(hc["eyebrow"], **v)), h1=nobr(fill(hc["h1"], **v)),
                      sub=nobr(fill(hc["sub"], **v)), chip=one_box(fill(hc["chip_delivery"], **v)),
                      about_tail=nobr(fill(hc["about_tail"], **v)),
                      # «в Санкт-Петербурге» не переносится: на телефоне такой заголовок чуть мельче (main.css)
                      long="-" in c["prep"] and len(c["prep"]) > 15),
            pups=sort_puppies(data["puppies"]),
            pups_title=hc["pups_title"],
            pups_lead=nobr(fill(hc["pups_lead"], **v)),
            pups_help={k: fill(x, **v) for k, x in hc["pups_help"].items()},
            reviews_home=reviews,
            faq_items=faq,
            seo=dict(title=nobr(fill(seo["title"], **v)),
                     lead=nobr(fill(ov.get("seo_lead") or seo["lead"], **v)),
                     blocks=[dict(h=nobr(fill(b["h"], **v)), p=nobr(fill(b["p"], **v))) for b in seo["blocks"]]),
        ),
    )


def _plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
