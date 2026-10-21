# домщенков.рф — working conventions for page builders

Static site, built by `tools/build.py` (Python 3 stdlib + Jinja2 3.1) into `<url>/index.html` in the repo root.
GitHub Pages serves it from `https://vseleznev54.github.io/puppyhouse/` (subpath `/puppyhouse/`).
Stage 3 (client revisions 13.10, `docs/brief.md` → «Правки клиента 13.10»): the homepage is redesigned (full-screen hero,
«О нашем питомнике», breeds two per row, photo/video carousel, advantages, video reviews, 12 FAQ, articles) — the old
pixel-parity baseline no longer applies. Reference inner page: `/shchenki/`.

## Stage 3 rules for every page (client 13.10) — read first

- **Brand: «домщенков.рф»** — lowercase, no hyphen, from `site.brand`. Never «Puppy House» (the build warns on it).
  `<title>` suffix: ` | домщенков.рф`; titles stay ≤ 60 characters.
- **SEO is automatic** (`tools/seo.py`, `docs/seo.md`): every page gets canonical, robots, Open Graph, icons and
  BreadcrumbList from its `title`, `description`, `breadcrumbs` and first photo in `<main>`; sitemap.xml, robots.txt,
  404.html, site.webmanifest are written by the build. Write one H1 with the page's main query (≤ 2 lines),
  a title with the query + «в Москве» where it fits, a 110–160-character description. Optional context:
  `robots="noindex, follow"`, `og_image="/assets/img/…"`, `og_title`, `og_type`. Add JSON-LD only for what the page
  really shows (FAQ via `faq_section(ld=true)`); no Product/Offer while prices are not published.
- **Header** (shared, `partials/header.html.j2`): logo · «Меню» (site map panel `#mega`, data `site.menu`) · «Породы ▾» ·
  `site.nav` links · phone · Telegram / WhatsApp / MAX · «Написать в Telegram» (`.btn--tg`, Telegram blue darkened to
  ≥ 4,5:1 with white text — tokens `--tg-a` / `--tg-b`). Round messenger buttons without a text label use
  `m.get('round_icon') or m.icon` (MAX → the «MAX» wordmark `#i-max-word`) and `title`. On narrower
  desktops links hide from the end (`prio`), they stay in «Меню»; below 1100 px a burger opens the full-screen `#mmenu` with
  the same groups as accordions. Mobile sticky bar: Позвонить · Telegram · Узнать цену.
- **No phone and messengers yet** (client 20.10): `site.contacts_ready = false` hides the kennel's number and its Telegram /
  WhatsApp / MAX links everywhere — header, «Меню», burger, sticky bar, footer, lead form, contact tiles, «Не получилось
  отправить», lead band, video viewer, puppy hero, JSON-LD (`telephone`, `sameAs`). In their place: the coral «Оставить
  заявку» (`ui.request_button()`, `.btn--coral`, modal kind `lead`) in the header (hidden ≤ 560 px — the sticky bar has it),
  «Меню», burger, sticky bar (`.mbar--2`: Оставить заявку · Узнать цену) and video viewer. The visitor's «Куда написать»
  chips stay. Wrap any new phone / messenger output in `{% if site.contacts_ready %}`; set `true` once they are known.
- **Forms: one column.** Every field on its own row at every width (`forms.lead_form`, the price modal, any form you add:
  use `.form__grid` — it is a single column). Contact chips: Telegram / WhatsApp / MAX / Звонок (`forms.contact_field`).
- **Phones (≤ 760 px): no sideways scrolling of cards.** Cards go down the page: one per row, or two small ones (colour
  faces, `.stiles--pair`). Chips and filters wrap. The ONLY swipeable rows are photo/video carousels (`media.media_carousel`);
  video reviews (`media.video_reviews`) stack on phones (three cards + «Все отзывы»), wide comparison tables (`ui.cmp_table`
  with 3+ columns) stay a horizontal table that scrolls sideways, first column sticky, «Листайте таблицу вбок» above it
  (client 21.10 — the second exception). `.scroller` is a no-op now — don't use it. The crawler flags any other
  sideways scroll container and any link/button cut off by an `overflow: hidden` parent (`control-clipped`).
- **RULE — the SEO text stands right before the lead form, after the articles (client 21.10).** On every page:
  … → «Полезные статьи» / blog block → SEO text (`blocks.seo_block`) → lead form. Inner pages put the seo_block call
  into `{% block seo %}` of `layouts/page.html.j2` (never into `body`); the layout places it after `pups` and `blog`.
- **RULE — links to a section or page are coral pill buttons (client 19.10, 21.10; automatic — main.css).** No underlined
  text links with an arrow anywhere on the site. «Все отзывы», «Все статьи», «Документы и гарантии», «Задать свой вопрос»,
  «Весь каталог», «Узнать цену», «Получить консультацию» — every such link is a rounded coral button: `ui.link_button(url,
  label)` (`.btn.btn--coral`), and `ui.section_head(link=…)` and `blocks.faq_section` (its «Задать свой вопрос») render it themselves (the old
  `button=` argument changes nothing). On phones ≤ 760 px the button of a block head leaves the head and stands under the
  whole block, full width, 52 px. Nothing to do per page: keep the head as `section.section > .sec-head` (or
  `.faq > .faq__aside`) and the rule applies. Don't add a second, hand-made bottom button. Exceptions that stay as
  they are (client 21.10): links to the legal documents in «Другие документы» on the consent / privacy pages
  (`ui.text_link` — underlined with an arrow, used nowhere else) and the plain links of the header, menus and footer.
- **CTA wording: no arrow-only buttons.** Every clickable tile/card ends with a text pill (`ui.tile_cta`) or a coral
  button (`ui.link_button`): «Перейти к породе» (breed tiles), «Подробнее» (help / link / studio tiles, puppy cards),
  «Все окрасы» / «Смотреть окрас» (colours), «Читать» (articles). `ui.round_arrow` is decorative only.
- **Advantages everywhere it fits**: `ui.advantages()` (привиты по возрасту, ветпаспорт и договор, пожизненная гарантия,
  пожизненная консультация, видео до покупки, доставка — `site.advantages`). Used on /, hubs, catalog, puppy pages,
  /dokumenty-i-garantii/, /dostavka/, /otzyvy/, /o-pitomnike/, /rassrochka/, /shchenok-v-podarok/, /faq/.
  The guarantee is **lifetime** everywhere («Пожизненная гарантия на врождённые и генетические заболевания — условия в договоре»).
- **Promises** (client 21.10): no «за 1 час». The offer is «Пришлём варианты щенков» / «Оставьте заявку, и мы пришлём варианты ваших будущих питомцев: фото, видео и цены» (`forms.lead_form` default,
  modals, blog form; breed pages «Пришлём варианты мальтипу»); «за 15 минут» is only
  the reply time («Ответим за 15 минут», «Цену пришлём за 15 минут»).
- **City pages** (client 21.10): `/shchenki-v-<город>/` (`/shchenki-v-novosibirske/`, address = `cities.json → url`) for
  every city is the homepage — the same template `pages/home.html.j2` with `city` (route `home.py`, copy `home-city.json`).
  It differs only by the heading («Щенки в Новосибирске напрямую от заводчика»). No «доставка в <город>», and the
  kennel's own city is never named: context `hide_city=true` drops «Москва» from the logo caption (`site.tagline_plain`),
  the footer address and «по московскому времени» (modal; `forms.lead_form(local_time=false)`); the eyebrow and texts
  lose «Москва»; reviews from Moscow and its region are left out; the SEO text's Moscow paragraph is the city's own;
  under the form only the e-mail tile (`forms.contact_tiles(address=false)`).
- **First screen**: `ui.page_hero(..., full=true)` = the whole screen (breed pages); homepage hero: `.hero--full`.
  Studio photos in page heroes are larger on desktop (≥ 1200 px the tile is taller; the photo is never cropped).
- **Images.** Placeholders come from `assets/img/` (`src/data/media.json` lists sets per page/breed); a video is a
  poster + play button until the client sends files (`"video": null` → the lightbox says «Видео появится здесь»).
  Client 15.10 (maltipu page): missing studio colours may be generated in the same style (Figma `generate_image`, peach
  backdrop, puppy centred) — list them in `tools/images.json` (the fetch workflow downloads them), measure the backdrop into
  `tools/photo-tones.json`. Client's live photos: pick them from the contact sheets in `tools/yadisk/` into
  `tools/yadisk-pick.json` (the Yandex Disk workflow downloads them).
- **Breed page v2** (client 15.10, all four breeds): `"layout": "v2"` in `breeds-hub.json` → `breeds/breed.html.j2`, body
  `.page-breed` (coral main buttons, homepage-size photo carousel and SEO text — the `.page-home` rules in `main.css` cover both).
  Order: hero («Щенки в наличии» + «Получить консультацию») · every puppy of the breed + «Помочь с выбором» · photo / video
  carousel + lead band (round faces of the breed's colours) · colour cards to scroll (`.brd-cols`, a `[data-carousel]` with
  `data-align="start"`, each card «Подобрать кремового мальтипу» — `pick` in `breedsub.json`) · «Какой он» · «Как мы отдаём
  щенка» (what travels with the puppy + photo tiles: documents, guarantee, delivery, price) · FAQ · «Всё о <породе>» (articles +
  the breed's colours and price pages: `part.post_carousel` — four wide cards in a row, the rest beyond the edge with arrows,
  a list on phones) · SEO text · lead form with contact tiles (`forms.contact_tiles()`), as on the homepage. 15 puppies per
  breed with the client's real photos (`puppies.json`), no studio renders in the catalog. `breeds/hub.html.j2` is unused now.
  Colour pages `/<breed>/<colour>/` (`breeds/colour.html.j2`, copy in `breedsub.json` colour items: `title`, `short`,
  `rarity` / `age` / `nose`, `about`, `care`; `colour_price` in `breeds-hub.json` = what the price depends on). Colour photos
  `okras-<breed>-<colour>.jpg` (cards) and `okras-<breed>-<colour>-big.jpg` (the same puppy close up for the colour page
  hero) from `tools/okras_tiles.py`: one backdrop tone per breed, varied poses (sitting, lying, standing sideways, from
  behind). Rerun it after replacing a source photo, then measure the backdrop into `tools/photo-tones.json`.

## Build and look

```
python3 tools/build.py            # PUBLISHED pages only (src/data/publish.json); deletes the other generated pages
python3 tools/build.py --all      # every route → _all/ (git-ignored, never deployed) to look at unpublished pages:
                                  #   python3 -m http.server 8767 --directory _all; the published tree is not touched
python3 tools/build.py --verbose  # + which pages link to each unbuilt / not-yet-published URL
python3 tools/build.py --clean    # + delete pages from earlier builds that no route produces (manifest only; skipped if errors)
python3 tools/build.py --kit      # + /_kit/ — every macro with sample data (git-ignored, never deployed)
```

**Staged release (client 19.10).** The repo = what GitHub Pages and the server show. Out now: the homepage, the four
breed pages and the privacy policy (the forms link to it). Everything else stays in `src/` and is built with `--all`.
Links to an unpublished page go to a block on the published page (`publish.json → link_fallbacks`: «Каталог щенков» →
`#shchenki` on a breed page or the homepage `#porody`, «Контакты» → `#zayavka`, «Отзывы», «О питомнике», «Все вопросы»);
the rest show the toast «Раздел скоро откроется. Пока напишите нам — пришлём фото и видео щенков» and carry `rel="nofollow"`. sitemap.xml lists only
published pages. To release a page: add its URL to `src/data/publish.json → pages` (`/maltipu/*` = the whole section),
build, commit. A malformed publish.json stops the build before anything is written (a typo must not publish the whole
site). The full site as of 19.10 is the branch `backup/full-site-2026-10-19`.
Static server: `http://127.0.0.1:8765/` serves the repo (`cd /home/user/puppyhouse && python3 -m http.server 8765 --bind 127.0.0.1 &`).
Open `/_kit/` before writing new CSS: most things you need already exist.

Two builds in a row must give no diff. Commit the generated `index.html` files together with the sources and `.build-manifest.json`.
Several agents may build at the same time: every page and the manifest are written atomically, and a full build always
renders every published group, so the files on disk reflect whichever build ran last — rebuild (without `--all`) right
before you commit. Merging a branch that still carries unpublished pages: resolve by deleting them (`git rm`) and
running the normal build.

## Typography rule from the client (12.10) — enforced by the build

- **No capitals.** Never `text-transform: uppercase`, small-caps or text typed in capitals (headlines, labels, eyebrows, badges, buttons, tables). Normal sentence case everywhere. Abbreviations like РКФ, FCI, ДНК are fine.
- **No heavy weights.** Geist is loaded only in 400 and 500. Headings, numbers, names, buttons: 500. Body: 400. Never 600/700/bold; `<b>`/`<strong>` render at 500. Hierarchy comes from size, colour (`--muted`) and spacing, not weight.
- The build warns on every CSS line with uppercase or a weight above 500 and on every page with words in capitals — fix these warnings in your files.

## Ownership — who may edit what

Shared, **read-only** for page groups (list any change you need in your final report instead):
`tools/build.py`, `src/templates/base.html.j2`, `layouts/`, `partials/`, `macros/`, `src/routes/_lib.py`,
`src/data/site.json`, `breeds.json`, `puppies.json`, `reviews.json`, `faq.json`, `cities.json`, `blog.json`, `media.json`,
`assets/css/main.css`, `assets/css/pages.css`, `assets/js/main.js`, `tools/photo-tones.json`, `assets/img/`.
The homepage (group `home`: `src/routes/home.py`, `src/templates/pages/home.html.j2`, `src/data/home.json`; its own classes
in `main.css` are prefixed `.hm-`) extends `base.html.j2` directly and
loads only `main.css` — every stage-3 shared block lives in `main.css`; if you need the inner-page kit too, add
`{% block head_css %}<link rel="stylesheet" href="/assets/css/pages.css">{% endblock %}` and import `macros/media.html.j2` yourself.

Your group `<group>` (short latin name, e.g. `breeds`, `delivery`, `trust`, `choice`, `blog`, `puppy`) owns only:

| What | Where |
|---|---|
| route module | `src/routes/<group>.py` |
| templates | `src/templates/<group>/*.html.j2` |
| own data | `src/data/<group>.json`, `src/data/<group>-*.json` (key in `data`: name with `-` → `_`) |
| styles (only if pages.css lacks it) | `assets/css/<group>.css` |
| script (only if needed) | `assets/js/<group>.js` |

Never edit another group's files. Never write into `assets/`, `src/`, `tools/`, `docs/`, `content/` from a route.

## Add a route module

```python
# src/routes/delivery.py — every *.py here without a leading "_" is discovered automatically
from _lib import crumbs, by_id, sort_puppies

def routes(data):            # data = deep copy of all src/data/*.json, enriched (see below)
    out = [dict(
        url="/dostavka/",                       # /lowercase-latin/…/ with trailing slash
        template="delivery/hub.html.j2",
        context=dict(
            title="…",                          # <title>, ≤ 60 chars
            description="…",                    # meta description, ≤ 160 chars
            breadcrumbs=crumbs(("Доставка", None)),   # Главная is added; last item = current page (→ BreadcrumbList)
            # SEO extras (optional): robots="noindex, follow", og_image="/assets/img/…" (else the first photo in <main>)
            # anything else your template needs; optional: pups_breed=<breed dict>, pups_strip=False, lead_breed="maltipu"
        ),
    )]
    for c in data["cities"]:
        out.append(dict(url=c["url"], template="delivery/city.html.j2", context=dict(city=c, …)))
    return out
```
An exception in your module (or a template error on one page) is reported, the build exits with 1 and those pages
are not rebuilt: their files from the previous build stay on disk and links to them stay relative (the build reads them
from `.build-manifest.json`), so other groups' pages are not damaged. Never commit while the build shows an ERROR.
Fix every ERROR and every warning about your pages.

## Templates

```jinja
{% extends "layouts/page.html.j2" %}            {# ui / cards / forms / blocks are already imported #}
{% block page_css %}  <link rel="stylesheet" href="/assets/css/delivery.css">{% endblock %}
{% block page_js %}  <script src="/assets/js/delivery.js" defer></script>{% endblock %}
{% block hero %}{{ ui.page_hero('Доставка щенков', lead='…', tone='sand', faces=true) }}{% endblock %}
{% block body %}
  <section class="section container" id="sposoby" aria-labelledby="sposoby-title">
    {{ ui.section_head('Как привезём', id='sposoby-title') }}
    …
  </section>
{% endblock %}
{# optional overrides: {% block pups %} (strip «Щенки в наличии»), {% block lead %} (final form) #}
```
`layouts/page.html.j2` imports `ui`, `cards`, `forms`, `blocks` and `media`.
The layout renders: breadcrumbs → hero → body → «Щенки в наличии» (4 cards, `pups_breed` narrows to a breed, `pups_strip=False` hides it) → lead form (`#zayavka`, `lead_breed` preselects) → footer, modal, menu, mobile bar, toast.

- File names: `src/templates/<group>/<page>.html.j2`, kebab-case. One H1 per page — `ui.page_hero` renders it.
- Every `<section>`: `class="section container"`, an `id`, `aria-labelledby` → its H2. `section--tight` = smaller top gap.
- Jinja runs with `StrictUndefined`: an unknown variable is an error. Optional context: `{{ x | default(none) }}`.
- Extra icons for your pages: `{% block sprite_extra %}<symbol id="i-…" viewBox="0 0 24 24">…</symbol>{% endblock %}`.

## URLs and links

- Write every URL **root-absolute, as in production**: `/maltipu/`, `/shchenki/?breed=maltipu`, `/assets/img/x.jpg`, `/assets/css/x.css`.
  The build rewrites them per page: built routes and `/assets/` → relative (`../maltipu/`), CSS/JS get `?v=<hash>`.
- A link to a page that is **not built in this build** stays root-absolute → `main.js` shows the toast «Раздел скоро откроется. Пока напишите нам — пришлём фото и видео щенков» (see «Staged release»).
  So link to final URLs from the brief even before they exist. Never write relative paths by hand.
- Rewritten attributes: `href src srcset poster action data-src data-href` and `url(...)` in inline styles. Not inside `<script>`.

## Data (`data` in routes, globals in templates)

Globals: `site`, `breeds` (list), `breed_map` (slug → breed), `puppies`, `data` (everything, incl. your files), `imgsize(src)`, `photo_tone(src)`, `tone_style(src)`.
`site.json` (stage 3): `brand` «домщенков.рф», `nav` (header links, `prio` 2–6 = hide order on narrow desktops), `menu` (site-map
groups for «Меню» and the burger: items `{label, url}` + `breed` face / `count` / `icon`, or `{label, sub: [...]}` — a caption
with a short list of links, one per row, thin rule on the left; client 15.10: no pills; phones: every item on its own row, the
burger's top bar with the close button never scrolls away — only `.mmenu__scroll` scrolls; footer links on phones: one per row, 46 px),
`tg_cta` («Написать в Telegram»), `messengers.telegram|whatsapp|max` (`url_placeholder` marks placeholder links; `icon` — `tg` / `wa` / `max`: the official mark shapes
in one colour; in a `.msgr` circle they are dark brown on a soft peach gradient — client sample 15.10, no brand-colour logos),
`advantages`, `stats`; `domain` «домщенков.рф» + `domain_ascii` (punycode `xn--b1adduihee9g.xn--p1ai`, for JSON-LD URLs),
`email` «main@домщенков.рф» (client 20.10; on the page) + `email_ascii` (the same in punycode — `mailto:` links use it).
`media.json`: photo/video sets for carousels — `home`, `maltipu`, `francuzskij-buldog`, `toj-pudel`, `border-kolli`; item
`{src, alt, kind: photo|video, caption, video: null|file, pos?}` (`data.media.home`, `data.media[b.slug]`).
`reviews.json`: + `poster {src, alt, pos?}` (placeholder lifestyle photo), `video: null`, `short` (≤ 160 chars) for every review.
Computed by the build:
- breed: `tone_class` (`tone--peach`…), `puppies` (its puppies), `stock` (= number of its puppies). Every puppy count on the
  site comes from `puppies.json` (breed tiles «В наличии: 7», «Весь каталог — 19», the catalog) — never type a number;
- puppy: `age_weeks` (from `birth_date` on `site.as_of`), `url`, `breed_name`, `tone`, `tone_class`, `sex_label`, `status_label` (Забронирован/а), `status_dot` (ok/res/soon), `status_order`, `meta` («Мальтипу · 10 недель · мальчик»), `desc` (+ generation, for the modal), `photo` (= `photos[0]`).

`puppies.json`: 19 sample puppies (maltipu 7, bulldog 4, toy poodle 5, border collie 3); the homepage has no puppy strip since
13.10 (it links to the catalog: «Все щенки в наличии — 19»). Photo fields: `kind` (`studio` | `life`), `class`, optional `pos` (object-position for a lifestyle shot),
`backdrop: "token"` (only the four approved homepage cards — every other studio photo takes its measured backdrop in the card).
Live photos for the catalog (client 13.10, waiting for the client's files): put the real photo first in `photos` with
`kind: "life"` (+ `pos` if needed) — every card then shows it cropped to cover (default `object-position: 50% 60%`), no code change.
Values in `[square brackets]` are placeholders (see `site.placeholders`); keep them bracketed until the client gives real data.
`cities.json`: `name`, `prep` («в Казани»), `acc` («в Казань»), `gen` («из Казани»), `url` (`/shchenki-v-<город>/` — the city page), `km_approx` (rough road distance, groups on /dostavka/), `methods` (car/plane/train).
`breeds.json` also has `facts`, `compare` (comparison rows), `docs`, `studio` / `mood` / `adult` photos, `varieties`, `colours` (drafts — check, some with `standard` and `photo`).
**Colour anchors** (stage 3): every colour has its own card on `/<breed>/vidy-i-okrasy/#<colour-slug>` (e.g. `/maltipu/vidy-i-okrasy/#ryzhij`,
`/francuzskij-buldog/vidy-i-okrasy/#goluboj`); slugs, photos and texts live in `breedsub.json` → `<breed>.varieties` → the `colours`
block (the hubs read the same list). Link a colour there instead of the page top. The hubs' carousels use `data.media[<breed>]`
in the order of `breeds-hub.json` → `media` (+ extra placeholders), so a video file added to `media.json` shows on the hub too.

## Macros (`ui.`, `cards.`, `forms.`, `blocks.`) — text params are plain text, escaped and run through `|typo`

| Macro | Params | Use |
|---|---|---|
| `ui.page_hero` | `title, lead, tone, breed, photo, faces, facts, chips, eyebrow, id, full=false, note, cls` + `call` → buttons | H1 tile. `breed=` → its tone and studio photo blended. `full=true` → the whole screen (100svh − header, min 560), copy centred; phones: photo grows. `note` → one muted line under the buttons. Breed pages: `btn btn--white btn--lg` «Подобрать щенка» + `btn btn--outline btn--lg`. `cls='phero--group'` + `photo` hero-four-breeds.jpg → the wide four-puppies hero (pages.css; /o-pitomnike/, blog «Как выбрать щенка») |
| `ui.section_head` | `title, id, link={url,label}, lead` + `call` → buttons | H2 row |
| `ui.breadcrumbs` | `items` | used by the layout |
| `ui.studio_tile(s)` | `photo{src,alt}, title, line, url, badge, tone, priority, cta='Подробнее'` / `items` (+ `t.cta`), `pair=false` | colour / parent photo tile, backdrop = measured photo tone; `priority=true` on the first screen. Phones: one wide tile per row (photo right); `pair=true` → two small 3:4 tiles per row (titles only) |
| `ui.spec_grid` | `items[{label,value,icon?,color?}], cols=2..4` | facts in white tiles |
| `ui.stat_tiles` | `items[{num,cap,icon,color}]` (`site.stats`) | trust numbers |
| `ui.steps` / `ui.timeline` | `items[{title,text}]`, `cols=3/5` / `items[{when?,title,text?}]` | how-to |
| `ui.link_tiles` | `items[{url,title,line,icon,color \| breed \| image, cta?}], style='white'\|'color'` | related links (don't mix image + icon tiles in one row); each ends with a «Подробнее» pill (`t.cta` to change) |
| `ui.tile_cta` | `label='Подробнее', variant=''\|'soft'\|'ink', url=none` | the CTA pill of a tile/card («Перейти к породе», «Смотреть щенка», «Все окрасы», «Читать»). Inside a link tile → `<span>`; `url` → `<a class="tcta">`. White on colour tiles, `soft` on white, `ink` on photos |
| `ui.advantages` | `items=site.advantages, title, id='preimushchestva', lead, link, cols=3, tight=false` (`tight` → `section--tight`, first block under a hero) | kennel advantages: pastel icon circle + 2–3 word title + one line. `title` → whole section with H2; `cols=6` → six narrow tiles in a row. Phones: one per row |
| `ui.lead_band` | `title, line, label='Оставить заявку', tone='lilac', tag='h3', title_id, faces=true, note, modal_title, submit='Записаться на видеозвонок', done` | CTA band right under a carousel: «Оставить заявку» (modal with its own title + hidden note) + «Написать в Telegram». Inside a section with an H2 keep `tag='h3'`. `faces=[{src, tone}]` → those studio photos as round faces (breed page: its colours) |
| `ui.cta_band` | `title, line, button='modal'\|{url,label}, label, tone, faces, title_id` | mid-page CTA (wrap in a section, `title_id` → its `aria-labelledby`) |
| `ui.keyfacts`, `ui.callout(kind,title)` + call, `ui.toc([[id,label]])` | | articles (`.article`, `.prose`) |
| `ui.cmp_table` | `cols` (names or breed dicts), `rows[[label, v1, v2…]]`, `caption` | comparison table in a white tile; column names never break at a hyphen. first column sticky; 3+ columns: on phones ≤ 760 the table scrolls sideways (min 640 px, labels 100 px) under «Листайте таблицу вбок» (client 21.10) |
| `ui.gallery` | `photos[{src,alt,caption?}]` | 1–5+ photos; phones: a grid (first photo full width, the rest two per row). Swipeable row → `media.media_carousel` |
| `ui.badges`, `ui.empty_state(title,text,button,label,attrs)`, `ui.img(src,alt,…)`, `ui.icon`, `ui.ico`, `ui.face`, `ui.round_arrow`, `ui.link_button(url, label)` (coral pill link) | | small parts |
| `cards.puppy_card(p, tag='h3', eager=false, simple=false)` | puppy | THE puppy card of the whole site (every strip, hub, catalog, «Похожие щенки»): photo (a link), white «Узнать цену» (modal for that puppy) + «Подробнее» with a white outline (`.btn--outline`), no «В избранное» heart (client 21.10); studio photo → card in that photo's measured colours; phones ≤ 560 — a compact row, photo left. `simple=true` (breed pages v2): name, sex · colour, the same two buttons, no age; photo and name are not links. Styles: `main.css` (`.pup` + `.ct-card`) |
| `ct.card(p, eager=false)` / `ct.strip(items, breed)` | `{% import "catalog/_card.html.j2" as ct %}` | `ct.card` = `cards.puppy_card`; `ct.strip` = a strip of cards + «Ждёте другого щенка?» («Похожие щенки») |
| `cards.pups_section` | `title, breed, limit=4, id, exclude=slug` | «Щенки в наличии» strip (`.pups--strip`: at 3 columns a lone 4th card is hidden) |
| `cards.breed_tile(s)` | `b, count=false, cta='Перейти к породе'` / `items, count=false, cols=4` | pastel breed tiles; `cols=2` → two wide tiles per row on desktop (photo right). «В наличии» only with `count=true` (removed from the homepage 13.10). Phones: one wide tile per row |
| `cards.review_card(r, short)`, `cards.ratings()`, `cards.soon_tile()` | | |
| `media.media_carousel` | `items, title, id='media', lead, link, label, start, priority` + `call` → content under it | row of 9:16 photo/video cards, centred card larger, arrows (a pair under the row from 561 px; over the row on phones), swipe, ← →, snap; opens `#lightbox`. Starts on the middle card. `title` → whole section; `caller()` → e.g. `ui.lead_band()` under the carousel |
| `media.media_card` | `m` (media.json item) | one 9:16 card (button → lightbox); video = poster + play |
| `media.video_review_card` | `r, full=false, cls=''` | 9:16 poster + play + review text (`r.short`; `full=true` → `r.text` + source and puppy) + name, city, breed on a white panel. In `ul.vrev-grid` (or `cls='vrev--stack'`) the card grows with its text. /otzyvy/ (21.10) shows the homepage photo reviews (`media.photo_review_card`, `home.json → reviews_home`) in `.tr-rvws`: 12, «Показать ещё отзывы» opens the rest |
| `media.video_reviews` | `reviews, title='Отзывы владельцев', id='otzyvy', title_id, link, lead, ratings=true` | section: rating tiles + row of video review cards (arrows under it); phones: first three stacked + «Все отзывы» |
| `blocks.blog_teasers` | `slugs` (or `posts[{url,title,line,cover,topic}]`), `title='Гид по породам', id='blog', lead, link, limit=3` | article cards: photo, title, one line, «Читать»; phones — compact list |
| `forms.lead_form` | `title='Пришлём варианты щенков', line='Оставьте заявку, и мы пришлём варианты ваших будущих питомцев: фото, видео и цены', tone, breed, id='zayavka', contacts=true, cls=''` | one per page (the layout adds it); phones: phone number on its own line, three messengers (`.lead__msgrs`, never split) under it. `contacts=false` — no phone/messengers in the tile (a «ответим за 15 минут» note instead); `{% call %}` content goes after the tile in the same section (homepage: contact tiles `.hm-cts`) |
| `forms.price_button(label, cls, breed)`, `forms.msgr(kind)` | `kind = telegram \| whatsapp \| max` | generic «Узнать цену» / messenger round button |
| `forms.contact_tiles()` | | phone, messengers, e-mail, address — four white tiles under `forms.lead_form(contacts=false, cls='hm-lead')` (homepage, breed pages v2) |
| `forms.contact_field(prefix)` | `'lf' \| 'pm' \| yours` | «Куда написать» chips Telegram / WhatsApp / MAX / Звонок |
| `forms.consent_check(prefix, kind='processing', name='consent', privacy=true)` | `kind = processing \| distribution` | 152-ФЗ consent checkbox from `data/consent.json` (current version): «Даю согласие на …» linking `/soglasie/` (or `/soglasie-na-publikaciyu/`), privacy link on the next line. Every form that sends personal data needs it |
| `forms.honeypot(prefix)`, `forms.send_fail(what, saved)` | | hidden `hp_note` field (off-screen, out of the Tab order); «Не получилось отправить…» + phone / Telegram / MAX (shown by JS when the API is unreachable) |
| `blocks.faq_section` / `faq_list` | `items` (faq.json or `{q,a}`), `title, id, ask=true, short, ld=true` | accordion + «Задать свой вопрос» (client 21.10, instead of «Все вопросы»): a coral button under the H2 (phones: under all the questions) that opens the shared modal with the required «Ваш вопрос» field (`data-modal-question="1"`, kind consult; the API keeps the text in `details.question`, the e-mail carries it, Telegram only says «Есть вопрос» unless personal data may go there); `ask=false` hides it (/faq/); `ld=true` also emits FAQPage JSON-LD for its questions (one FAQ section per page — pass `ld=false` where the page outputs its own FAQPage: /faq/, blog articles) |
| `blocks.reviews_section` | `reviews, title, id, title_id, link, short` | text reviews (one per row on phones); for video reviews use `media.video_reviews` |
| `blocks.seo_block` | `title, lead, id, key` + `call` → hidden `<h3>/<p>` | collapsed SEO text |

## CSS and JS

- Design tokens, the header, every homepage class and the stage-3 shared blocks live in `main.css`
  (`.btn--tg .btn--outline .tcta .media-carousel .mcard .vrev .lightbox .advs .lband .bteasers .breeds--2 .hero--full`,
  pastel tints `.tone--sun/sky/mint/lilac/coral/sand`, `.sec-head__lead`, the puppy card `.pup` + `.ct-card`); the inner-page kit in `pages.css`
  (`.crumbs .phero .phero--full .specs .kpis .badges .tline .ltiles .cta-band .empty .article .prose .table-wrap .keyfacts .callout .toc .cmp .gallery .filters .fseg .pups--grid .soon-tile .stiles .stiles--pair .tile .grid .split`).
- Your CSS: only page-specific layout, prefix classes with your group (`.dlv-…`). Use tokens (`var(--gap)`, `--r-tile`, `--tile-pad`, `--sec`, colours). No new fonts, no shadows/colours outside the palette.
- Breakpoints used everywhere: 1199 / 1000 / 900 / 760 (phones: everything stacks, no ribbons) / 560 / 420. Check 360–1920, no horizontal page scroll.
  Header: logo caption ≥ 1600; phone text ≥ 1440 («Блог» gives way to it at 1440–1519); «Блог» ≥ 1340, «Контакты» ≥ 1280, round Telegram ≥ 1200, «Отзывы» ≥ 1150; burger < 1100.
- `main.js` (all pages) gives you, by markup: header panels `[data-mega]` / `[data-dd]` (hover with intent, click pins, ↓ ↑, Esc),
  `[data-burger]` + `#mmenu` accordions (`.mmenu__acc` → `aria-controls`), `[data-carousel]` (arrows, swipe, keys, active card,
  far images preloaded; `data-align="start"` — cards snap to the left edge, no centred card: colour cards), `[data-lightbox]` → `#lightbox` (`data-kind`, `data-src` = video file, `data-caption`),
  `[data-open-modal]` (inside `[data-pup]` card → prefilled; `data-modal-title` / `-sub` / `-breed` / `-note` on the button set the title, subtitle, breed and hidden note;
  every trigger also carries `data-modal-kind` = the request type for the API: price · puppy · consult · help · colour · waitlist · video_call · litter · shop; colour buttons add `data-modal-colour="<colour slug>"`), `.faq__btn` accordions, `[data-seo-toggle]`, `.fav`, `[data-phone]` mask, `#lead-form`, toast for root-absolute links, `[data-hero-ctas]` (mobile bar appears after it), `[data-reveal]` / `[data-reveal="items"]` (fade-in on scroll), Own logic → `assets/js/<group>.js`, vanilla, wrapped in an IIFE, no libraries.

## Forms → API (backend/)

`base.html.j2` renders `<meta name="dsh-api" content="/api/v1" data-origins="…" data-consent="…">` from `site.api` and
`consent.json`. `main.js` is in live mode only on a production origin (or with `localStorage['dsh:api']` = an absolute API
URL for local testing): the price modal and `#lead-form` POST `/leads`, `/otzyvy/` POSTs `/reviews` (trust.js). Every `form[data-lead-form]` is a lead form (main.js: `data-prefix` of its field ids, `data-kind`, `data-note`; «Спасибо» / «Не получилось» in its `[data-lead-box]`) — the bottom form and the open form in a blog article's right column (`blg.aside_form`, kind `help`), anonymous
events (page_view, form_open, contact_click, quiz_complete) go to `/events`. GitHub Pages stays in prototype mode (fake
send, no tracking). Helpers for page scripts: `window.DSH` (`live`, `submit(path, payload, state)`, `context()`, `track()`).
Breed `<select>` values are slugs (`forms.breed_options`). Never put the API URL into `href` / `src` / `action`.

## Photos and tones

- Files and descriptions: `tools/images.json`; sizes are read by `ui.img` / `imgsize()`. First screen: `priority=true`, everything else lazy.
- Studio photos (`studio-*`, `color-*`, `parent-*`) are shot on a pastel backdrop. Their real backdrop is measured in
  `tools/photo-tones.json`: `top`, `wall` (left), `wall_right`, `floor`, `floor_line` (0–1 of height where the floor starts).
  The tile must take **that photo's** colours — never the prompt HEX, never a «close enough» token. `tone_style(src)` turns
  a measurement into `--tone-top --tone-hi --tone-floor --fa --fb`; `ui.page_hero(photo=…)` and `ui.studio_tile` apply it.
- Two blending techniques (both used on the approved homepage):
  1. **Tile**: photo full width standing on the tile bottom, only its top edge fades (`mask … transparent 0, #000 18%`), tile background = `top` → `ui.studio_tile`, homepage breed tiles.
  2. **Wide tile**: photo square at the right, full height, pushed 8% out to hide the darker right vignette; left 34% and top 14% fade into `wall`; tile floor gradient at `floor_line` → `ui.page_hero(photo|breed)`.
  A visible rectangle or halo around the dog is a defect — check screenshots with raised contrast.
- Lifestyle photos (`pup-*`, `family-*`, `grad-*`, `delivery-*`…) never blend: put them inside a tile with 8 px inset and 20 px radius, or full-bleed in a 28 px tile (`.split__media`, `.gallery`, `.ltile__img`).
- Breed tones: maltipu `peach`, bulldog `powder`, toy poodle `butter`, border collie `sage`; general pages `cream` (homepage hero) or tints `sun sky mint lilac coral sand`.

## Copy

Russian, short sentences, warm and concrete. No prices of puppies anywhere (every puppy → «Узнать цену»); the price pages /<breed>/cena/ show only approximate ranges (client 21.10, breedsub.json → price_cheap / price_kennel), no «лучший», «№1». H2 ≤ 5 words, one-line lead ≤ 90 chars,
card line ≤ 60 chars, long SEO text only in `blocks.seo_block`, FAQ or article prose. Keywords: the semantic core CSV, target URL column.
Facts about breeds — from `breeds.json` / `content/home.md`; anything unverified stays in `[brackets]`.
`|typo` adds non-breaking spaces (after 1–2 letter words, before dashes, number + unit) and a word joiner after the hyphen of
«что-то», «как-нибудь», «кое-где» (no line break there); in hand-written HTML use `&nbsp;` the same way.
The build warns about prices, banned words, the old brand («Puppy House», «puppyhouse», «дом-щенков.рф») in visible text, duplicate ids, broken aria references, `<img>` without alt/size, missing title/description,
`<title>` over 60 and meta description over 160 characters.

## QA before you report

Tools live in the session scratchpad `$S = /tmp/claude-0/-home-user-puppyhouse/ef09f4b1-ff64-5c2b-9188-1625c3a0cc3f/scratchpad` (not in the repo).

1. `python3 tools/build.py` twice → no errors, no warnings for your pages, second run «0 changed», `git status` shows only your files + generated pages.
2. Screenshots at 1440, 1024, 768, 390 (and 360): `node $S/shot/shot.mjs <url> $S/<name> 1440,1024,768,390 1600` → JSON (overflowX, brokenImages, consoleErrors) + PNG slices: read them. (After a scroll pass the viewport is stretched to the whole page, so every lazy image is decoded; the mobile sticky bar is therefore not in the shots.)
3. Homepage: the stage-2 pixel baseline is retired (redesign 13.10). Review it with screenshots like any page.
4. Interaction test for your JS: copy the pattern of `$S/qa-catalog.mjs`.
5. Subpath: `python3 $S/found/subpath_server.py 8766 &` serves the repo at `http://127.0.0.1:8766/puppyhouse/`; `node $S/found/qa-subpath.mjs` shows the checks.
6. Full crawl: `node $S/qa-crawl.mjs` (all pages × 360/768/1440 + subpath + interactions: header «Меню» hover / click / keyboard /
   Esc, header layout 360–1920, burger groups, one-column forms, carousels + lightbox, `mobile-card-scroll` = a sideways
   scroll container on a phone outside `.media-carousel`). `--skip crawl,sub` runs only the interactions.
7. Final report: pages built, unbuilt link targets you introduced, shared changes you need (file + exact change + why), placeholders added.
