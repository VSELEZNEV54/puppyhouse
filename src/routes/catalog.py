"""Catalog of puppies: /shchenki/ — reference inner page for the other groups.
Owns: src/templates/catalog/, assets/js/catalog.js (filters). Puppy pages /shchenki/<slug>/ belong to another group."""

from _lib import by_id, crumbs, sort_puppies

FAQ = ["price", "booking", "age", "visit"]


def routes(data):
    faq = by_id(data["faq"])
    pups = sort_puppies(data["puppies"])
    return [dict(
        url="/shchenki/",
        template="catalog/catalog.html.j2",
        context=dict(
            title="Щенки в наличии — купить щенка в Москве | Puppy House",
            description="Щенки мальтипу, французского бульдога, той-пуделя и бордер-колли в наличии. "
                        "Покажем по видео. Договор, ветпаспорт, доставка по России. Узнайте цену.",
            breadcrumbs=crumbs(("Щенки", "/shchenki/")),
            items=pups,
            faq_items=[faq[i] for i in FAQ],
            related=[
                {"url": "/dokumenty-i-garantii/", "title": "Документы и гарантии", "line": "Договор, ветпаспорт, метрика РКФ", "icon": "doc", "color": "sky"},
                {"url": "/dostavka/", "title": "Доставка", "line": "По Москве и в другие города", "icon": "car", "color": "mint"},
                {"url": "/rassrochka/", "title": "Бронь и рассрочка", "line": "Бронь по договору, остаток частями", "icon": "wallet", "color": "sun"},
                {"url": "/podbor-porody/", "title": "Подобрать породу", "line": "Тест на 2 минуты", "icon": "sparkle", "color": "lilac"},
            ],
        ),
    )]
