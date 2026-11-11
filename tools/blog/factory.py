#!/usr/bin/env python3
"""Контент-завод блога домщенков.рф — всё, что можно сделать без модели (0 токенов).

    python3 tools/blog/factory.py status              светофор: вышло, в буфере, черновики, кого писать; на сколько дней хватит
    python3 tools/blog/factory.py plan                план с ориентировочными датами → content/blog/план.md
    python3 tools/blog/factory.py next [N] [--json]   следующие N тем, которые надо написать (по порядку плана)
    python3 tools/blog/factory.py brief <slug>        задание писателю: карточка, правила по месяцу, ссылки, фото
    python3 tools/blog/factory.py photos [--rebuild] [<slug>]   каталог фото сайта / кандидаты для статьи
    python3 tools/blog/factory.py img <slug> <n> <файл> --alt "…"   иллюстрация → assets/img/blog/<slug>-<n>.jpg
    python3 tools/blog/factory.py lint [<slug>…]      проверка черновиков (без аргументов — все)
    python3 tools/blog/factory.py approve <slug> [--note …] | hold <slug> | draft <slug>
    python3 tools/blog/factory.py publish [--date ГГГГ-ММ-ДД] [--dry-run] [--force]
    python3 tools/blog/factory.py unpublish <slug>

Файлы: content/blog/plan.json (план), content/blog/posts/<slug>.json (статьи завода),
content/blog/published.json (что вышло — пишет только publish), content/blog/photos.json (каталог фото).
Правила текста: content/blog/ПРАВИЛА.md. Как устроен завод: content/blog/README.md.
Коды выхода: 0 — ок; 1 — ошибки проверки; 2 — неверный вызов; 3 — публиковать нечего (буфер пуст)."""

import argparse
import datetime
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BLOG = ROOT / "content" / "blog"
POSTS = BLOG / "posts"
PLAN = BLOG / "plan.json"
PUBLISHED = BLOG / "published.json"
PHOTOS = BLOG / "photos.json"
LEGACY = ROOT / "src" / "data" / "blog-posts.json"
PUBLISH_JSON = ROOT / "src" / "data" / "publish.json"
IMG = ROOT / "assets" / "img"
TZ_MSK = datetime.timezone(datetime.timedelta(hours=3))  # Москва без перехода на летнее время

WORDS_MIN, WORDS_OK, WORDS_MAX = 600, 700, 1400   # слов в тексте статьи (вступление, разделы, вопросы)
PHOTOS_MIN = 3                                    # фото в теле статьи; обложка и шапка — сверх этого
BANNED = [  # (шаблон, почему) — в тексте статьи
    (r"\bлучш(?:ий|ая|ее|ие) (?:питомник|заводчик)", "без «лучший питомник» (бриф)"),
    (r"№\s?1", "без «№1» (бриф)"),
    (r"в современном мире|ни для кого не секрет|в наше время", "вода во вступлении"),
    (r"puppy house", "бренд — домщенков.рф"),
    (r"\d[\d\s]*(?:₽|руб)", "цены щенков на сайте не публикуем (кнопка «Узнать цену»)"),
    (r"\[[^\]]*\](?!\()", "заглушка в квадратных скобках"),
    (r"гарантир\w+,? что (?:аллерги|не заболе)", "медицинских гарантий не даём"),
]
DOSE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:мг|мл/кг|мг/кг|таблет\w*)\b", re.I)
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\((/[^)\s]*)\)")
WORD_RE = re.compile(r"[\wё]+(?:-[\wё]+)*", re.I)
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")
BREED_WORDS = {"maltipu": "мальтипу", "pudel": "той-пудель", "kolli": "бордер-колли", "buldog": "французский бульдог"}
BREED_SLUG = {"maltipu": "maltipu", "pudel": "toj-pudel", "kolli": "border-kolli", "buldog": "francuzskij-buldog"}
COLOUR_WORDS = {"belyj": "белый", "white": "белый", "chernyj": "чёрный", "black": "чёрный", "kremovyj": "кремовый",
                "cream": "кремовый", "abrikosovyj": "абрикосовый", "apricot": "абрикосовый", "ryzhij": "рыжий",
                "red": "рыжий", "shokoladnyj": "шоколадный", "chocolate": "шоколадный", "korichnevyj": "коричневый",
                "seryj": "серый", "silver": "серебристый", "serebristyj": "серебристый", "goluboj": "голубой",
                "blue": "голубой", "palevyj": "палевый", "pegij": "пегий", "pied": "пегий", "tigrovyj": "тигровый",
                "mramornyj": "мраморный", "trehcvetnyj": "трёхцветный", "lilovyj": "лиловый", "fantom": "фантом",
                "partikolor": "партиколор", "sobolinyj": "соболиный"}


# ---------------------------------------------------------------- data
def load(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def plan():
    return load(PLAN)


def cards():
    return plan()["cards"]


def card_of(slug):
    for c in cards():
        if c["slug"] == slug:
            return c
    raise SystemExit(f"нет темы «{slug}» в content/blog/plan.json")


def links_max(c, p=None):
    lm = (p or plan())["links_max"]
    return int(lm.get(str(c["m"]), lm["default"]))


def published():
    return load(PUBLISHED, {"posts": {}})


def legacy():
    return load(LEGACY)["posts"]


def post_file(slug):
    return POSTS / f"{slug}.json"


def article(slug):
    """(post dict, file dict or None) — the copy of an article, from the factory file or blog-posts.json."""
    f = post_file(slug)
    if f.is_file():
        d = load(f)
        return d.get("post"), d
    lp = legacy().get(slug)
    return lp, None


def today_msk():
    return datetime.datetime.now(TZ_MSK).date()


def ru_date(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def dates():
    """slug → ориентировочная дата выхода (по порядку плана, с start, только дни weekdays)."""
    p = plan()
    d = datetime.date.fromisoformat(p["start"])
    days = set(p.get("weekdays", [0, 1, 2, 3, 4]))
    out = {}
    for c in p["cards"]:
        while d.weekday() not in days:
            d += datetime.timedelta(days=1)
        out[c["slug"]] = d
        d += datetime.timedelta(days=1)
    return out


def state(c, pub=None, posts_on_disk=None):
    """published | approved | draft | hold | ready (написана раньше, blog-posts.json) | todo"""
    pub = pub if pub is not None else published()["posts"]
    if c["slug"] in pub:
        return "published"
    if c["slug"] in published().get("hold", []):
        return "hold"
    if c.get("ready"):
        return "ready"
    f = post_file(c["slug"])
    if f.is_file():
        try:
            return load(f).get("status", "draft")
        except ValueError:
            return "draft"
    return "todo"


def site_pages():
    """Матчер выложенных страниц сайта (src/data/publish.json) — куда можно ставить ссылку кроме статей."""
    pages = load(PUBLISH_JSON)["pages"]
    exact = {p for p in pages if not p.endswith("*")}
    prefixes = tuple(p[:-1] for p in pages if p.endswith("*"))
    return lambda u: u in exact or (bool(prefixes) and u.startswith(prefixes))


# ---------------------------------------------------------------- photos
def imgsize(path):
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:2] != b"\xff\xd8":
                return None
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    return None
                if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                    continue
                seg = struct.unpack(">H", f.read(2))[0]
                if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">xHH", f.read(5))
                    return (w, h)
                f.seek(seg - 2, 1)
    except OSError:
        return None


def _walk_alts(o, out):
    if isinstance(o, dict):
        src = o.get("src")
        if isinstance(src, str) and src.startswith("/assets/img/") and isinstance(o.get("alt"), str) and o["alt"]:
            out.setdefault(src, []).append(o["alt"])
        for v in o.values():
            _walk_alts(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_alts(v, out)


def _auto_alt(name):
    parts = Path(name).stem.split("-")
    breed = next((BREED_WORDS[p] for p in parts if p in BREED_WORDS), None)
    colour = next((COLOUR_WORDS[p] for p in parts if p in COLOUR_WORDS), None)
    if not breed:
        return None
    return f"{'Щенок' if parts[0] in ('pup', 'ml', 'cl') else 'Собака'} {breed}" + (f", {colour} окрас" if colour else "")


def build_catalog():
    """content/blog/photos.json: каждое фото сайта с подписью (из данных сайта, иначе по имени файла), породой,
    ориентацией и тем, сколько раз оно уже стоит в статьях блога."""
    alts = {}
    for f in sorted((ROOT / "src" / "data").glob("*.json")):
        _walk_alts(load(f), alts)
    blog_use = {}
    for slug, p in legacy().items():
        _count_photos(p, blog_use)
    for f in sorted(POSTS.glob("*.json")):
        try:
            d = load(f)
        except ValueError:
            continue
        _walk_alts(d, alts)
        _count_photos(d.get("post") or {}, blog_use)
    items = []
    for path in sorted(IMG.rglob("*")):
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp") or "og" in path.relative_to(IMG).parts[:1]:
            continue
        src = "/" + path.relative_to(ROOT).as_posix()
        size = imgsize(path)
        if not size or min(size) < 500:
            continue  # иконки, миниатюры
        alt_list = alts.get(src) or []
        alt = max(alt_list, key=len) if alt_list else _auto_alt(path.name)
        if not alt:
            continue
        parts = path.stem.split("-")
        breed = next((BREED_SLUG[p] for p in parts if p in BREED_SLUG), None)
        if not breed:
            low = alt.lower()
            breed = next((s for w, s in (("мальтипу", "maltipu"), ("пудел", "toj-pudel"), ("колли", "border-kolli"),
                                         ("бульдог", "francuzskij-buldog")) if w in low), None)
        w, h = size
        items.append(dict(src=src, alt=alt, breed=breed, w=w, h=h,
                          shape="land" if w >= h * 1.15 else ("port" if h >= w * 1.1 else "square"),
                          generated=path.parent.name == "blog", auto_alt=not alt_list, in_blog=blog_use.get(src, 0)))
    save(PHOTOS, {"_note": "Каталог фото для статей. Собирает tools/blog/factory.py photos --rebuild из подписей в "
                           "src/data и статьях. auto_alt — подпись по имени файла, проверьте по самому фото. in_blog — "
                           "в скольких статьях уже стоит. generated — иллюстрация (assets/img/blog/).", "photos": items})
    return items


def _count_photos(p, use):
    seen = set()
    for s in p.get("sections", []):
        for b in s.get("blocks", []):
            for ph in ([b["figure"]] if "figure" in b else []) + (b.get("photos") or []):
                if ph.get("src") and ph["src"] not in seen:
                    seen.add(ph["src"])
                    use[ph["src"]] = use.get(ph["src"], 0) + 1


def stems(text):
    return {w[:max(4, len(w) - 2)] for w in WORD_RE.findall(text.lower()) if len(w) >= 3}


def candidates(c, n_land=10, n_port=8):
    items = load(PHOTOS, {"photos": []})["photos"] or build_catalog()
    want = stems(" ".join([c.get("photo", ""), c.get("pk", ""), c.get("h1", "")]))

    def score(it):
        s = 0
        if c.get("breed"):
            s += 6 if it["breed"] == c["breed"] else -6
        a = stems(it["alt"])
        s += 2 * len(want & a)
        s -= 2 * it["in_blog"]
        s -= 1 if it["auto_alt"] else 0
        return s

    ranked = sorted(items, key=lambda it: (-score(it), it["src"]))
    land = [it for it in ranked if it["shape"] in ("land", "square")][:n_land]
    port = [it for it in ranked if it["shape"] in ("port", "square") and it not in land][:n_port]
    return land, port


# ---------------------------------------------------------------- text helpers
def post_texts(p, with_faq=True):
    out = [p.get("intro", "")]
    for s in p.get("sections", []):
        out.append(s.get("h2", ""))
        for b in s.get("blocks", []):
            for k in ("p", "h3"):
                if k in b:
                    out.append(b[k])
            for k in ("ul", "ol"):
                if k in b:
                    out += b[k]
            if "table" in b:
                out += b["table"].get("head", []) + [" ".join(r) for r in b["table"].get("rows", [])]
            if "callout" in b:
                out += [b["callout"].get("title") or "", b["callout"].get("text", "")]
            if "proscons" in b:
                out += b["proscons"].get("pros", []) + b["proscons"].get("cons", [])
            if "figure" in b:
                out.append(b["figure"].get("caption", ""))
    if with_faq:
        out += [q.get("q", "") + " " + q.get("a", "") for q in p.get("faq", [])]
    return out


def body_photos(p):
    out = []
    for s in p.get("sections", []):
        for b in s.get("blocks", []):
            if "figure" in b:
                out.append(b["figure"])
            if "photos" in b:
                out += b["photos"]
    return out


def text_links(p):
    return [m for t in post_texts(p) for m in LINK_RE.findall(t)]


# ---------------------------------------------------------------- lint
def lint_one(slug, pub=None, for_publish=False):
    """(errors, warnings) for content/blog/posts/<slug>.json. for_publish: links must lead to what is out today."""
    errors, warns = [], []
    f = post_file(slug)
    try:
        d = load(f)
    except FileNotFoundError:
        return [f"нет файла {f.relative_to(ROOT)}"], []
    except ValueError as e:
        return [f"битый JSON: {e}"], []
    c = next((x for x in cards() if x["slug"] == slug), None)
    if c is None:
        errors.append("темы нет в plan.json")
        c = {"slug": slug, "m": 99, "pk": ""}
    p = d.get("post") or {}
    if d.get("slug") != slug:
        errors.append(f"slug в файле «{d.get('slug')}» ≠ имени файла")
    if not SLUG_RE.match(slug):
        errors.append("slug: только латиница, цифры и дефисы")
    if d.get("breed") not in (None, "maltipu", "francuzskij-buldog", "toj-pudel", "border-kolli"):
        errors.append(f"breed «{d.get('breed')}»: одна из четырёх пород или null")
    if c.get("breed", None) != d.get("breed", None) and "breed" in c:
        warns.append(f"breed {d.get('breed')} ≠ карточке ({c.get('breed')})")
    if d.get("status") not in ("draft", "approved", "hold"):
        errors.append("status: draft | approved | hold")
    req = ("title", "description", "h1", "crumb", "eyebrow", "lead", "topic", "card_line", "cover", "intro",
           "sections", "faq_title", "faq", "cta")
    miss = [k for k in req if not p.get(k)]
    if miss:
        errors.append("нет полей post: " + ", ".join(miss))
        return errors, warns
    tags = [t["label"] for t in load(LEGACY)["hub"]["tags"]]
    if p["topic"] not in tags:
        errors.append(f"topic «{p['topic']}» — один из: {', '.join(tags)}")
    if c.get("topic") and p["topic"] != c["topic"]:
        warns.append(f"topic «{p['topic']}» ≠ карточке «{c['topic']}»")
    if len(p["title"]) > 60:
        errors.append(f"title {len(p['title'])} знаков > 60")
    if not p["title"].endswith(" | домщенков.рф"):
        errors.append("title заканчивается на « | домщенков.рф»")
    if not 110 <= len(p["description"]) <= 160:
        errors.append(f"description {len(p['description'])} знаков: нужно 110–160")
    if len(p["h1"]) > 60:
        warns.append(f"h1 {len(p['h1'])} знаков: на телефоне больше двух строк")
    if len(p["card_line"]) > 60:
        errors.append(f"card_line {len(p['card_line'])} знаков > 60")
    pk = c.get("pk", "")
    if pk:
        need = stems(pk)
        if not need <= stems(p["title"] + " " + p["h1"] + " " + p["lead"]):
            errors.append(f"главный запрос «{pk}» не виден в title/h1/lead")
        if not need <= stems(p["intro"]):
            errors.append(f"главный запрос «{pk}» не виден во вступлении (intro)")
    for k in ("cover",):
        if not isinstance(p[k], dict) or not p[k].get("src") or not p[k].get("alt"):
            errors.append(f"{k}: нужны src и alt")
    secs = p["sections"]
    if not 4 <= len(secs) <= 8:
        errors.append(f"разделов {len(secs)}: нужно 4–8")
    ids = [s.get("id", "") for s in secs]
    if len(set(ids)) != len(ids) or not all(SLUG_RE.match(i) for i in ids):
        errors.append("id разделов: уникальные, латиница через дефис")
    for s in secs:
        for k in ("id", "toc", "h2", "blocks"):
            if not s.get(k):
                errors.append(f"раздел «{s.get('h2', '?')}»: нет {k}")
        if len(s.get("toc", "")) > 28:
            warns.append(f"toc «{s.get('toc')}» длиннее 28 знаков")
        for b in s.get("blocks", []):
            kinds = [k for k in ("p", "h3", "ul", "ol", "table", "callout", "proscons", "figure", "photos") if k in b]
            if len(kinds) != 1:
                errors.append(f"раздел «{s.get('h2')}»: блок {sorted(b)} — ровно один тип из p/h3/ul/ol/table/callout/proscons/figure/photos")
            if "photos" in b and len(b["photos"]) != 2:
                errors.append(f"раздел «{s.get('h2')}»: photos — ровно две фотографии")
            if "table" in b:
                t = b["table"]
                if not t.get("caption") or not t.get("head") or not t.get("rows"):
                    errors.append(f"таблица в «{s.get('h2')}»: нужны caption, head, rows")
                elif any(len(r) != len(t["head"]) for r in t["rows"]):
                    errors.append(f"таблица в «{s.get('h2')}»: в строке не столько ячеек, сколько в head")
            if "callout" in b and b["callout"].get("kind", "info") not in ("info", "warn", "love", "ok"):
                errors.append("callout.kind: info | warn | love | ok")
    kinds_used = {k for s in secs for b in s.get("blocks", []) for k in b}
    for k, label in (("table", "таблицы"), ("callout", "врезки (callout)")):
        if k not in kinds_used:
            warns.append(f"нет {label}")
    if not kinds_used & {"ul", "ol"}:
        warns.append("нет списка (ul/ol)")
    if c.get("check") and not d.get("sources"):
        warns.append("тема о здоровье: заполните sources (что проверено)")
    if not 3 <= len(p["faq"]) <= 6:
        errors.append(f"вопросов {len(p['faq'])}: нужно 3–6")
    if not p["cta"].get("title") or not p["cta"].get("line"):
        errors.append("cta: нужны title и line")

    text = " ".join(post_texts(p))
    words = len(WORD_RE.findall(LINK_RE.sub(r"\1", text)))
    if words < WORDS_MIN:
        errors.append(f"текст {words} слов < {WORDS_MIN}")
    elif words < WORDS_OK:
        warns.append(f"текст {words} слов: цель {WORDS_OK}–{WORDS_MAX}")
    elif words > WORDS_MAX:
        warns.append(f"текст {words} слов > {WORDS_MAX}: длинно для сайта")
    for pat, why in BANNED:
        m = re.search(pat, text, re.I)
        if m:
            errors.append(f"«{m.group(0)}» — {why}")
    if DOSE.search(text):
        errors.append(f"доза «{DOSE.search(text).group(0)}»: дозы лекарств не пишем — только «подберёт ветеринар»")

    # photos: ≥3 in the body, all files exist, alt everywhere, no repeats
    ph = body_photos(p)
    if len(ph) < PHOTOS_MIN:
        errors.append(f"фото в тексте {len(ph)} < {PHOTOS_MIN} (figure = 1, photos = 2)")
    srcs = [x.get("src", "") for x in ph]
    if len(set(srcs)) != len(srcs):
        errors.append("одно и то же фото дважды в тексте")
    for x in ph + [p["cover"]] + ([p["hero"]] if p.get("hero") else []):
        if not x.get("alt"):
            errors.append(f"нет alt у {x.get('src')}")
        if not (ROOT / x.get("src", "/").lstrip("/")).is_file():
            errors.append(f"нет файла {x.get('src')}")

    # links: month 1 — none; later ≤ links_max, only to what is out (or comes out earlier by the plan)
    lmax = links_max(c) if c.get("m") != 99 else 0
    links = text_links(p)
    if len(links) > lmax:
        errors.append(f"ссылок в тексте {len(links)} > {lmax} (месяц {c.get('m')})")
    pub = pub if pub is not None else published()["posts"]
    order = {x["slug"]: x["n"] for x in cards()}
    on_site = site_pages()
    for label, url in links:
        m = re.fullmatch(r"/blog/([a-z0-9-]+)/", url)
        if m:
            target = m.group(1)
            if target == slug:
                errors.append(f"ссылка на саму себя: {url}")
            elif for_publish and target not in pub:
                errors.append(f"ссылка на статью, которой ещё нет на сайте: {url}")
            elif not for_publish and target not in pub and order.get(target, 10 ** 6) >= order.get(slug, 0):
                errors.append(f"ссылка на статью, которая выйдет позже: {url}")
        elif not on_site(url.split("#")[0]):
            errors.append(f"ссылка на страницу, которой нет на сайте: {url}")
    return errors, warns


# ---------------------------------------------------------------- commands
def cmd_status(a):
    p = plan()
    pub = published()["posts"]
    rows = [(c, state(c, pub)) for c in p["cards"]]
    count = {}
    for _, s in rows:
        count[s] = count.get(s, 0) + 1
    buffer = [c for c, s in rows if s in ("approved", "ready")]
    print(f"Контент-план: {len(rows)} тем · вышло {count.get('published', 0)} · в буфере {len(buffer)} "
          f"(готово к выходу) · черновики {count.get('draft', 0)} · отложено {count.get('hold', 0)} · "
          f"написать {count.get('todo', 0)}")
    days = len(buffer)
    print(f"Буфера хватит на {days} {'публикацию' if days == 1 else 'публикаций'} "
          f"({'нужно писать' if days < 5 else 'ок'}: держим 5+ готовых)")
    last = max(pub.values(), key=lambda e: e["date"])["date"] if pub else "—"
    print(f"Последняя публикация: {last}")
    if buffer:
        print(f"Следующая к выходу: {buffer[0]['slug']} (№{buffer[0]['n']})")
    for c, s in rows:
        if s == "draft":
            e, _ = lint_one(c["slug"], pub)
            print(f"  черновик №{c['n']} {c['slug']}: {'проверка ок, ждёт редактора' if not e else f'{len(e)} ошибок'}")
        if s == "hold":
            print(f"  отложена №{c['n']} {c['slug']}")
    return 0


def cmd_plan(a):
    p = plan()
    pub = published()["posts"]
    ds = dates()
    mark = {"published": "✅ вышла", "approved": "🟢 готова", "ready": "🟢 готова (написана раньше)",
            "draft": "🟡 черновик", "hold": "⏸ отложена", "todo": "⚪ написать"}
    lines = ["# Контент-план блога домщенков.рф", "",
             "Сгенерировано: `python3 tools/blog/factory.py plan` из `content/blog/plan.json`. Руками не править.", "",
             f"Ритм: {len(p.get('weekdays', []))} публикаций в неделю (пн–пт), ~{p['per_month']} в месяц. "
             "Даты ориентировочные: статья выходит в первый рабочий день, когда она готова и её очередь подошла.",
             "Месяц 1 — без ссылок в тексте. С месяца 2 — до 3 ссылок, только на то, что уже вышло.", ""]
    for m in sorted({c["m"] for c in p["cards"]}):
        mc = [c for c in p["cards"] if c["m"] == m]
        lm = links_max(mc[0], p)
        n_word = "статья" if len(mc) % 10 == 1 and len(mc) % 100 != 11 else (
            "статьи" if 2 <= len(mc) % 10 <= 4 and not 12 <= len(mc) % 100 <= 14 else "статей")
        lines += [f"## Месяц {m}: {ru_date(ds[mc[0]['slug']])} — {ru_date(ds[mc[-1]['slug']])} · {len(mc)} {n_word} · "
                  + ("без ссылок в тексте" if lm == 0 else f"до {lm} ссылок в тексте"), "",
                  "| № | Дата | Тема (H1) | Главный запрос | Рубрика | Порода | Ссылки | Статус |",
                  "|---|---|---|---|---|---|---|---|"]
        for c in mc:
            title = c.get("h1") or (legacy().get(c["slug"], {}).get("h1", c["slug"]))
            out = pub.get(c["slug"])
            date = datetime.date.fromisoformat(out["date"]) if out else ds[c["slug"]]
            lines.append(f"| {c['n']} | {date.strftime('%d.%m')} | {title} | {c.get('pk', '')} | {c['topic']} | "
                         f"{c.get('breed') or '—'} | {', '.join(c.get('links', [])) or '—'} | "
                         f"{mark[state(c, pub)]}{' · ⚕ сверка' if c.get('check') else ''} |")
        lines.append("")
    (BLOG / "план.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"content/blog/план.md: {len(p['cards'])} тем")
    return 0


def cmd_next(a):
    pub = published()["posts"]
    todo = [c for c in cards() if state(c, pub) == "todo"][: a.n]
    if a.json:
        print(json.dumps([dict(slug=c["slug"], n=c["n"], m=c["m"], h1=c.get("h1"), check=bool(c.get("check")),
                               illus=c.get("illus") or "") for c in todo], ensure_ascii=False))
    else:
        for c in todo:
            print(f"№{c['n']} (месяц {c['m']}) {c['slug']} — {c.get('h1')}{' · ⚕' if c.get('check') else ''}")
    return 0


def cmd_brief(a):
    c = card_of(a.slug)
    p = plan()
    pub = published()["posts"]
    lmax = links_max(c, p)
    order = {x["slug"]: x for x in p["cards"]}
    lines = [f"ЗАДАНИЕ: статья №{c['n']} блога домщенков.рф (месяц {c['m']} плана)",
             f"Файл: content/blog/posts/{c['slug']}.json (создать; status «draft»)",
             f"Правила: content/blog/ПРАВИЛА.md · факты питомника: content/blog/факты.md", "",
             f"• slug: {c['slug']}",
             f"• breed: {json.dumps(c.get('breed'))}",
             f"• topic (рубрика): {c['topic']}",
             f"• H1: {c.get('h1')}",
             f"• Главный запрос: «{c.get('pk')}» — в title, h1 или lead, и во вступлении (intro), естественно",
             f"• Дополнительные запросы (keywords + по разделам): {' · '.join(c.get('sk', []))}",
             f"• Угол: {c.get('angle')}",
             f"• Призыв в конце (cta): {c.get('cta')}"]
    if c.get("check"):
        lines.append("• ⚕ ТЕМА О ЗДОРОВЬЕ: только проверенные факты; доз, названий лекарств и диагнозов нет; "
                     "«решает ветеринар» там, где цена ошибки высока. Можно до 3 веб-поисков, источники — в поле sources.")
    if lmax == 0:
        lines.append("• ССЫЛОК В ТЕКСТЕ НЕТ (месяц 1). Названия других статей можно упоминать без ссылки — лучше вообще не упоминать.")
    else:
        allowed = [s for s in c.get("links", []) if s in pub or order[s]["n"] < c["n"]]
        lines.append(f"• Ссылки в тексте: до {lmax}, формат [текст](/blog/slug/) внутри абзаца, там, где читателю это нужно.")
        lines.append("  Можно: " + (", ".join(f"/blog/{s}/" for s in allowed) or "—") +
                     "; страницы сайта: /maltipu/ /francuzskij-buldog/ /toj-pudel/ /border-kolli/ /shchenki/ "
                     "/dostavka/ /dokumenty-i-garantii/ /podbor-porody/ /faq/")
    land, port = candidates(c)
    lines += ["", f"ФОТО: в тексте не меньше {PHOTOS_MIN} (figure — горизонтальное, photos — пара вертикальных), "
                  "плюс cover (и hero, если не порода). Бери src и alt отсюда, alt можно уточнить, но не выдумывать "
                  "того, чего на фото нет.",
              "Горизонтальные (figure, cover, hero):"]
    lines += [f"  {it['src']} — {it['alt']}{' (подпись по имени файла)' if it['auto_alt'] else ''}"
              f"{' · уже в ' + str(it['in_blog']) + ' ст.' if it['in_blog'] else ''}" for it in land]
    lines.append("Вертикальные (photos — по две):")
    lines += [f"  {it['src']} — {it['alt']}{' (подпись по имени файла)' if it['auto_alt'] else ''}"
              f"{' · уже в ' + str(it['in_blog']) + ' ст.' if it['in_blog'] else ''}" for it in port]
    if c.get("illus"):
        lines.append(f"Иллюстрация (если сделана): /assets/img/blog/{c['slug']}-1.jpg — сцена: {c['illus']}")
    print("\n".join(lines))
    return 0


def cmd_photos(a):
    if a.rebuild or not PHOTOS.is_file():
        items = build_catalog()
        print(f"content/blog/photos.json: {len(items)} фото "
              f"({sum(1 for i in items if i['auto_alt'])} с подписью по имени файла)")
    if a.slug:
        land, port = candidates(card_of(a.slug))
        for it in land + port:
            print(f"{it['shape']:6} {it['src']} — {it['alt']}")
    return 0


def cmd_img(a):
    """Иллюстрация (картинка из Figma или своя) → assets/img/blog/<slug>-<n>.jpg, до 1600 px, JPEG 82."""
    try:
        from PIL import Image
    except ImportError:
        print("нужен Pillow: pip install pillow", file=sys.stderr)
        return 2
    card_of(a.slug)
    dst = IMG / "blog" / f"{a.slug}-{a.n}.jpg"
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(a.file).convert("RGB")
    im.thumbnail((1600, 1600))
    im.save(dst, "JPEG", quality=82, optimize=True, progressive=True)
    src = "/" + dst.relative_to(ROOT).as_posix()
    print(json.dumps({"src": src, "alt": a.alt, "w": im.width, "h": im.height}, ensure_ascii=False))
    return 0


def cmd_lint(a):
    slugs = a.slugs or sorted(f.stem for f in POSTS.glob("*.json"))
    pub = published()["posts"]
    bad = 0
    for s in slugs:
        e, w = lint_one(s, pub)
        print(f"{'✗' if e else '✓'} {s}" + (f" — {len(w)} замечаний" if w and not e else ""))
        for x in e:
            print(f"    ошибка: {x}")
        for x in w:
            print(f"    замечание: {x}")
        bad += bool(e)
    return 1 if bad else 0


def _set_status(slug, status, note=None):
    """Статус статьи завода; у написанных раньше (blog-posts.json) — только hold и снятие hold (published.json → hold)."""
    data = published()
    hold = data.setdefault("hold", [])
    if slug in hold and status != "hold":
        hold.remove(slug)
        save(PUBLISHED, data)
    f = post_file(slug)
    if not f.is_file():
        if slug not in legacy():
            raise SystemExit(f"нет статьи {slug}")
        if status == "hold" and slug not in hold:
            hold.append(slug)
            save(PUBLISHED, data)
        return
    d = load(f)
    d["status"] = status
    if note is not None:
        d.setdefault("review", {})
        d["review"].update(at=today_msk().isoformat(), note=note)
    save(f, d)


def cmd_approve(a):
    if not post_file(a.slug).is_file():
        _set_status(a.slug, "approved")  # написана раньше: просто снимаем hold
        print(f"{a.slug}: снова в очереди")
        return 0
    e, _ = lint_one(a.slug)
    if e:
        print(f"{a.slug}: не одобрена — ошибки проверки:", *e, sep="\n  ")
        return 1
    _set_status(a.slug, "approved", a.note or "")
    print(f"{a.slug}: approved")
    return 0


def cmd_hold(a):
    _set_status(a.slug, "hold")
    print(f"{a.slug}: hold — не выйдет, пока не approve")
    return 0


def cmd_draft(a):
    _set_status(a.slug, "draft")
    print(f"{a.slug}: draft")
    return 0


def cmd_publish(a):
    """Выпустить одну статью: первая по плану, которая готова (approved / ready), не отложена и проходит проверку."""
    day = datetime.date.fromisoformat(a.date) if a.date else today_msk()
    data = published()
    pub = data["posts"]
    if not a.force and any(e["date"] == day.isoformat() for e in pub.values()):
        print(f"{day}: сегодня статья уже вышла — пропускаю (--force, чтобы выпустить ещё одну)")
        return 0
    p = plan()
    skipped = []
    for c in p["cards"]:
        s = state(c, pub)
        if s not in ("approved", "ready"):
            continue
        if s == "approved":
            e, _ = lint_one(c["slug"], pub, for_publish=True)
            if e:
                skipped.append((c["slug"], e))
                continue
        entry = {"date": day.isoformat(), "links": links_max(c, p)}
        if a.dry_run:
            print(f"--dry-run: вышла бы {c['slug']} (№{c['n']}) {entry}")
        else:
            pub[c["slug"]] = entry
            save(PUBLISHED, data)
            print(f"опубликована {c['slug']} (№{c['n']}) {day}")
        for slug, e in skipped:
            print(f"  пропущена {slug}: {'; '.join(e)}", file=sys.stderr)
        if a.github_output:
            with open(a.github_output, "a", encoding="utf-8") as g:
                g.write(f"slug={c['slug']}\n")
        return 0
    for slug, e in skipped:
        print(f"  пропущена {slug}: {'; '.join(e)}", file=sys.stderr)
    print("БУФЕР ПУСТ: нет одобренных статей. Запустите /статьи в Claude Code.", file=sys.stderr)
    return 3


def cmd_unpublish(a):
    data = published()
    if data["posts"].pop(a.slug, None) is None:
        print(f"{a.slug}: не опубликована")
        return 1
    save(PUBLISHED, data)
    print(f"{a.slug}: снята с сайта после следующей сборки (файл статьи остался). Чтобы не вышла снова: hold {a.slug}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Контент-завод блога домщенков.рф")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("plan")
    x = sub.add_parser("next")
    x.add_argument("n", nargs="?", type=int, default=3)
    x.add_argument("--json", action="store_true")
    x = sub.add_parser("brief")
    x.add_argument("slug")
    x = sub.add_parser("photos")
    x.add_argument("slug", nargs="?")
    x.add_argument("--rebuild", action="store_true")
    x = sub.add_parser("img")
    x.add_argument("slug")
    x.add_argument("n", type=int)
    x.add_argument("file")
    x.add_argument("--alt", required=True)
    x = sub.add_parser("lint")
    x.add_argument("slugs", nargs="*")
    x = sub.add_parser("approve")
    x.add_argument("slug")
    x.add_argument("--note")
    for name in ("hold", "draft", "unpublish"):
        sub.add_parser(name).add_argument("slug")
    x = sub.add_parser("publish")
    x.add_argument("--date")
    x.add_argument("--dry-run", action="store_true")
    x.add_argument("--force", action="store_true")
    x.add_argument("--github-output", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    return globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
