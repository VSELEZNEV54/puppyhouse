"""Homepage — redesigned for the client revisions of 13.10 (docs/brief.md → «Главная (новый порядок)»).

Order: full-screen hero · «О нашем питомнике» (numbers from site.stats) · breeds two per row · photo and video
carousel + lead band · advantages · video reviews · how to buy · FAQ (12 questions) · blog · SEO text · lead form.
Own data: src/data/home.json (stat details, carousel items, reviews, blog picks, FAQ).
"""


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

    return [dict(
        url="/",
        template="pages/home.html.j2",
        context=dict(
            title="Купить щенка в Москве — питомник собак домщенков.рф",
            description="Питомник собак в Москве: щенки мальтипу, французского бульдога, той-пуделя и бордер-колли. "
                        "Прививки, ветпаспорт, договор, гарантия, доставка по России.",
            stats=stats,
            media_items=home["media"],
            # «О нашем питомнике»: фото листаются сами, видео доигрывает до конца (правка 15.10)
            about_slides=home["about_slides"],
            # отзывы на главной — свои (правка 15.10): фото щенка, текст, имя, город, порода; /otzyvy/ — reviews.json
            reviews_home=home["reviews_home"],
            faq_items=home["faq"],
            teasers=teasers,
        ),
    )]


def _plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
