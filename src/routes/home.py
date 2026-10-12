"""Homepage — approved by the client; its look must not change."""

HOME_FAQ = ["price", "docs", "age", "delivery", "booking"]
HOME_REVIEWS = ["anna-bonya", "igor-tajson", "marina-chapa"]
# the eight cards of the approved strip, in its order (two per breed); the catalog shows every puppy
HOME_PUPPIES = [
    "maltipu-f1-krem-2026-08", "maltipu-f1b-mini-shokolad-2026-07",
    "francuzskij-buldog-palevyj-2026-07", "francuzskij-buldog-krem-2026-07",
    "toj-pudel-abrikos-2026-07", "toj-pudel-ryzhij-2026-08",
    "border-kolli-goluboj-mramor-2026-07", "border-kolli-cherno-belyj-2026-07",
]


def routes(data):
    faq = {f["id"]: f for f in data["faq"]}
    reviews = {r["id"]: r for r in data["reviews"]}
    puppies = {p["slug"]: p for p in data["puppies"]}
    return [dict(
        url="/",
        template="pages/home.html.j2",
        context=dict(
            title="Купить щенка в Москве — питомник собак Puppy House",
            description="Щенки мальтипу, французского бульдога, той-пуделя и бордер-колли из питомника в Москве. "
                        "Документы, прививки, договор, доставка по России. Узнайте цену.",
            faq_items=[faq[i] for i in HOME_FAQ],
            reviews_home=[reviews[i] for i in HOME_REVIEWS],
            home_puppies=[puppies[s] for s in HOME_PUPPIES],
        ),
    )]
