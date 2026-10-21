"""Homepage — redesigned for the client revisions of 13.10 (docs/brief.md → «Главная (новый порядок)»).

Order: full-screen hero · «О нашем питомнике» (numbers from site.stats) · breeds two per row · catalog (the first
HOME_PUPS puppies of /shchenki/, client 21.10) · photo and video carousel + lead band · advantages · video reviews · how to buy · FAQ (12 questions) · blog · SEO text · lead form.
Own data: src/data/home.json (stat details, carousel items, reviews, blog picks, FAQ).

City pages /shchenki-v-<city>/ (client 21.10): the homepage for every city of cities.json, different only in the
heading («Щенки в Новосибирске напрямую от заводчика»). Not a word about where the kennel is (hide_city: no «Москва»
in the logo caption, footer and texts, no reviews from Moscow and its region, no address tile, the Moscow paragraph of
the SEO text is the city's own). Copy: src/data/home-city.json.
"""

import re

from _lib import crumbs, nobr, sort_puppies

TITLE_MAX, DESC_MAX = 60, 160
BRAND = " | домщенков.рф"
HOME_PUPS = 12  # 4 / 3 / 2 per row — every row full; phones show the first 8 (main.css .hm-pups)


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
        catalog=sort_puppies(data["puppies"])[:HOME_PUPS],
        media_items=home["media"],
        # «О нашем питомнике»: фото листаются сами, видео доигрывает до конца (правка 15.10)
        about_slides=home["about_slides"],
        faq_items=home["faq"],
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
        ),
    )] + [city_page(data, c, shared) for c in data["cities"]]


def fill(text, **kw):
    """str.format for copy templates; unknown keys stay as they are."""
    return re.sub(r"\{(\w+)\}", lambda m: str(kw.get(m.group(1), m.group(0))), text)


def city_page(data, c, shared):
    """/shchenki-v-<city>/ — the homepage with the city in the heading (home-city.json); the kennel's own city is
    never named on it."""
    hc = data["home_city"]
    v = dict(name=c["name"], prep=c["prep"])
    ov = hc["overrides"].get(c["slug"], {})

    title = fill(hc["title"], **v) + BRAND
    if len(title) > TITLE_MAX:
        title = fill(hc["title_short"], **v) + BRAND
    description = fill(hc["description"], **v)
    if len(title) > TITLE_MAX or len(description) > DESC_MAX:
        raise ValueError(f"{c['url']}: title {len(title)} / description {len(description)} chars")

    # отзывы главной без Москвы и области (и без тех, где упомянута Москва); отзыв из этого города — первым
    skip = set(hc["reviews_skip"])
    reviews = [r for r in data["home"]["reviews_home"] if r["city"] not in skip and "Москв" not in r["text"]]
    reviews.sort(key=lambda r: r["city"] != c["name"])

    seo = hc["seo"]
    return dict(
        url=c["url"],
        template="pages/home.html.j2",
        context=dict(
            shared,
            title=title,
            description=description,
            breadcrumbs=crumbs((fill(hc["crumb"], **v), None)),
            city=dict(name=c["name"], slug=c["slug"]),
            hide_city=True,
            hero=dict(h1=nobr(fill(hc["h1"], **v)),
                      # «в Санкт-Петербурге» не переносится: на телефоне такой заголовок чуть мельче (main.css)
                      long="-" in c["prep"] and len(c["prep"]) > 15),
            reviews_home=reviews,
            seo=dict(title=nobr(fill(seo["title"], **v)), lead=nobr(fill(ov.get("seo_lead") or seo["lead"], **v)),
                     local_h=nobr(fill(seo["local_h"], **v)), local_p=nobr(fill(seo["local_p"], **v))),
        ),
    )


def _plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
