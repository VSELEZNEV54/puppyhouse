# домщенков.рф — working conventions for page builders

Static site, built by `tools/build.py` (Python 3 stdlib + Jinja2 3.1) into `<url>/index.html` in the repo root.
GitHub Pages serves it from `https://vseleznev54.github.io/puppyhouse/` (subpath `/puppyhouse/`).
Stage 3 (client revisions 13.10, `docs/brief.md` → «Правки клиента 13.10»): the homepage is redesigned (full-screen hero,
«О нашем питомнике», breeds two per row, photo/video carousel, advantages, video reviews, 12 FAQ, articles) — the old
pixel-parity baseline no longer applies. Reference inner page: `/shchenki/`.

## Stage 3 rules for every page (client 13.10) — read first

- **Brand: «домщенков.рф»** — lowercase, no hyphen, from `site.brand`. Never «Puppy House» (the build warns on it).
  `<title>` suffix: ` | домщенков.рф`; titles stay ≤ 60 characters.
- **Header** (shared, `partials/header.html.j2`): logo · «Меню» (site map panel `#mega`, data `site.menu`) · «Породы ▾» ·
  `site.nav` links · phone · Telegram / WhatsApp / MAX · «Написать в Telegram» (`.btn--tg`, Telegram gradient). On narrower
  desktops links hide from the end (`prio`), they stay in «Меню»; below 1100 px a burger opens the full-screen `#mmenu` with
  the same groups as accordions. Mobile sticky bar: Позвонить · Telegram · Узнать цену.
- **Forms: one column.** Every field on its own row at every width (`forms.lead_form`, the price modal, any form you add:
  use `.form__grid` — it is a single column). Contact chips: Telegram / WhatsApp / MAX / Звонок (`forms.contact_field`).
- **Phones (≤ 760 px): no sideways scrolling of cards.** Cards go down the page: one per row, or two small ones (colour
  faces, `.stiles--pair`). Chips and filters wrap. The ONLY swipeable rows are photo/video carousels (`media.media_carousel`,
  `media.video_reviews`). `.scroller` is a no-op now — don't use it. The crawler flags any other sideways scroll container.
- **CTA wording: no arrow-only buttons.** Every clickable tile/card ends with a text pill (`ui.tile_cta`) or a text link
  (`ui.text_link`): «Перейти к породе» (breed tiles), «Подробнее» (help / link / studio tiles), «Смотреть щенка» (a puppy),
  «Все окрасы» / «Смотреть окрас» (colours), «Читать» (articles). `ui.round_arrow` is decorative only.
- **Advantages everywhere it fits**: `ui.advantages()` (привиты по возрасту, ветпаспорт и договор, пожизненная гарантия,
  пожизненная консультация, видео до покупки, доставка — `site.advantages`).
- **First screen**: `ui.page_hero(..., full=true)` = the whole screen (breed pages); homepage hero: `.hero--full`.
  Studio photos in page heroes are larger on desktop (≥ 1200 px the tile is taller; the photo is never cropped).
- **No new images.** Placeholders come from `assets/img/` (`src/data/media.json` lists sets per page/breed); a video is a
  poster + play button until the client sends files (`"video": null` → the lightbox says «Видео появится здесь»).

## Build and look

```
python3 tools/build.py            # all routes; prints pages, unbuilt link targets, warnings, errors (exit 1 on errors)
python3 tools/build.py --verbose  # + which pages link to each unbuilt URL
python3 tools/build.py --clean    # + delete pages from earlier builds that no route produces (manifest only; skipped if errors)
python3 tools/build.py --kit      # + /_kit/ — every macro with sample data (git-ignored, never deployed)
```
Static server: `http://127.0.0.1:8765/` serves the repo (`cd /home/user/puppyhouse && python3 -m http.server 8765 --bind 127.0.0.1 &`).
Open `/_kit/` before writing new CSS: most things you need already exist.

Two builds in a row must give no diff. Commit the generated `index.html` files together with the sources and `.build-manifest.json`.
Several agents may build at the same time: every page and the manifest are written atomically, and a full build always
renders every group, so the files on disk reflect whichever build ran last — rebuild right before you commit.

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
            breadcrumbs=crumbs(("Доставка", None)),   # Главная is added; last item = current page
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
- A link to a page that is **not built in this build** stays root-absolute → `main.js` shows the toast «Раздел появится на следующем этапе».
  So link to final URLs from the brief even before they exist. Never write relative paths by hand.
- Rewritten attributes: `href src srcset poster action data-src data-href` and `url(...)` in inline styles. Not inside `<script>`.

## Data (`data` in routes, globals in templates)

Globals: `site`, `breeds` (list), `breed_map` (slug → breed), `puppies`, `data` (everything, incl. your files), `imgsize(src)`, `photo_tone(src)`, `tone_style(src)`.
`site.json` (stage 3): `brand` «домщенков.рф», `nav` (header links, `prio` 2–6 = hide order on narrow desktops), `menu` (site-map
groups for «Меню» and the burger: items `{label, url}` + `breed` face / `count` / `icon`, or `{label, sub: [...]}` pills),
`tg_cta` («Написать в Telegram»), `messengers.telegram|whatsapp|max` (`max.url` is a placeholder), `advantages`, `stats`.
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
Values in `[square brackets]` are placeholders (see `site.placeholders`); keep them bracketed until the client gives real data.
`cities.json`: `name`, `prep` («в Казани»), `acc` («в Казань»), `gen` («из Казани»), `km_approx` (rough road distance), `methods` (car/plane/train), `duration` (bracketed estimate from distance and the first method, to confirm).
`breeds.json` also has `facts`, `compare` (comparison rows), `docs`, `studio` / `mood` / `adult` photos, `varieties`, `colours` (drafts — check, some with `standard` and `photo`).

## Macros (`ui.`, `cards.`, `forms.`, `blocks.`) — text params are plain text, escaped and run through `|typo`

| Macro | Params | Use |
|---|---|---|
| `ui.page_hero` | `title, lead, tone, breed, photo, faces, facts, chips, eyebrow, id, full=false, note` + `call` → buttons | H1 tile. `breed=` → its tone and studio photo blended. `full=true` → the whole screen (100svh − header, min 560), copy centred; phones: photo grows. `note` → one muted line under the buttons. Breed pages: `btn btn--white btn--lg` «Подобрать щенка» + `btn btn--outline btn--lg` |
| `ui.section_head` | `title, id, link={url,label}, lead` + `call` → buttons | H2 row |
| `ui.breadcrumbs` | `items` | used by the layout |
| `ui.studio_tile(s)` | `photo{src,alt}, title, line, url, badge, tone, priority, cta='Подробнее'` / `items` (+ `t.cta`), `pair=false` | colour / parent photo tile, backdrop = measured photo tone; `priority=true` on the first screen. Phones: one wide tile per row (photo right); `pair=true` → two small 3:4 tiles per row (titles only) |
| `ui.spec_grid` | `items[{label,value,icon?,color?}], cols=2..4` | facts in white tiles |
| `ui.stat_tiles` | `items[{num,cap,icon,color}]` (`site.stats`) | trust numbers |
| `ui.steps` / `ui.timeline` | `items[{title,text}]`, `cols=3/5` / `items[{when?,title,text?}]` | how-to |
| `ui.link_tiles` | `items[{url,title,line,icon,color \| breed \| image, cta?}], style='white'\|'color'` | related links (don't mix image + icon tiles in one row); each ends with a «Подробнее» pill (`t.cta` to change) |
| `ui.tile_cta` | `label='Подробнее', variant=''\|'soft'\|'ink', url=none` | the CTA pill of a tile/card («Перейти к породе», «Смотреть щенка», «Все окрасы», «Читать»). Inside a link tile → `<span>`; `url` → `<a class="tcta">`. White on colour tiles, `soft` on white, `ink` on photos |
| `ui.advantages` | `items=site.advantages, title, id='preimushchestva', lead, link, cols=3` | kennel advantages: pastel icon circle + 2–3 word title + one line. `title` → whole section with H2; `cols=6` → six narrow tiles in a row. Phones: one per row |
| `ui.lead_band` | `title, line, label='Оставить заявку', tone='lilac', tag='h3', title_id, faces=true, note, modal_title` | CTA band right under a carousel: «Оставить заявку» (modal with its own title + hidden note) + «Написать в Telegram». Inside a section with an H2 keep `tag='h3'` |
| `ui.cta_band` | `title, line, button='modal'\|{url,label}, label, tone, faces, title_id` | mid-page CTA (wrap in a section, `title_id` → its `aria-labelledby`) |
| `ui.keyfacts`, `ui.callout(kind,title)` + call, `ui.toc([[id,label]])` | | articles (`.article`, `.prose`) |
| `ui.cmp_table` | `cols` (names or breed dicts), `rows[[label, v1, v2…]]`, `caption` | comparison, scrolls inside its tile; column names never break at a hyphen |
| `ui.gallery` | `photos[{src,alt,caption?}]` | 1–5+ photos; phones: a grid (first photo full width, the rest two per row). Swipeable row → `media.media_carousel` |
| `ui.badges`, `ui.empty_state(title,text,button,label,attrs)`, `ui.img(src,alt,…)`, `ui.icon`, `ui.ico`, `ui.face`, `ui.round_arrow`, `ui.text_link` | | small parts |
| `cards.puppy_card(p)` | puppy | the homepage card; «Узнать цену» opens the modal for that puppy; studio photo → card in that photo's measured colours |
| `cards.pups_section` | `title, breed, limit=4, id, exclude=slug` | «Щенки в наличии» strip (`.pups--strip`: at 3 columns a lone 4th card is hidden) |
| `cards.breed_tile(s)` | `b, count=false, cta='Перейти к породе'` / `items, count=false, cols=4` | pastel breed tiles; `cols=2` → two wide tiles per row on desktop (photo right). «В наличии» only with `count=true` (removed from the homepage 13.10). Phones: one wide tile per row |
| `cards.review_card(r, short)`, `cards.ratings()`, `cards.soon_tile()` | | |
| `media.media_carousel` | `items, title, id='media', lead, link, label, start, priority` + `call` → content under it | row of 9:16 photo/video cards, centred card larger, arrows, swipe, ← →, snap; opens `#lightbox`. Starts on the middle card. `title` → whole section; `caller()` → e.g. `ui.lead_band()` under the carousel |
| `media.media_card` | `m` (media.json item) | one 9:16 card (button → lightbox); video = poster + play |
| `media.video_review_card` | `r` (reviews.json item) | 9:16 poster + play + review text (`r.short`) + name, city, breed on a white panel |
| `media.video_reviews` | `reviews, title='Отзывы владельцев', id='otzyvy', title_id, link, lead, ratings=true` | section: rating tiles + swipeable row of video review cards |
| `blocks.blog_teasers` | `slugs` (or `posts[{url,title,line,cover,topic}]`), `title='Гид по породам', id='blog', lead, link, limit=3` | article cards: photo, title, one line, «Читать»; phones — compact list |
| `forms.lead_form` | `title, line, tone, breed, id='zayavka'` | one per page (the layout adds it) |
| `forms.price_button(label, cls, breed)`, `forms.msgr(kind)` | `kind = telegram \| whatsapp \| max` | generic «Узнать цену» / messenger round button |
| `forms.contact_field(prefix)` | `'lf' \| 'pm' \| yours` | «Куда написать» chips Telegram / WhatsApp / MAX / Звонок |
| `blocks.faq_section` / `faq_list` | `items` (faq.json or `{q,a}`), `title, id, link, short` | accordion |
| `blocks.reviews_section` | `reviews, title, id, title_id, link, short` | text reviews (one per row on phones); for video reviews use `media.video_reviews` |
| `blocks.seo_block` | `title, lead, id, key` + `call` → hidden `<h3>/<p>` | collapsed SEO text |

## CSS and JS

- Design tokens, the header, every homepage class and the stage-3 shared blocks live in `main.css`
  (`.btn--tg .btn--outline .tcta .media-carousel .mcard .vrev .lightbox .advs .lband .bteasers .breeds--2 .hero--full`,
  pastel tints `.tone--sun/sky/mint/lilac/coral/sand`); the inner-page kit in `pages.css`
  (`.crumbs .phero .phero--full .specs .kpis .badges .tline .ltiles .cta-band .empty .article .prose .table-wrap .keyfacts .callout .toc .cmp .gallery .filters .fseg .pups--grid .soon-tile .stiles .stiles--pair .tile .grid .split`).
- Your CSS: only page-specific layout, prefix classes with your group (`.dlv-…`). Use tokens (`var(--gap)`, `--r-tile`, `--tile-pad`, `--sec`, colours). No new fonts, no shadows/colours outside the palette.
- Breakpoints used everywhere: 1199 / 1000 / 900 / 760 (phones: everything stacks, no ribbons) / 560 / 420. Check 360–1920, no horizontal page scroll.
  Header: phone text ≥ 1600; logo caption ≥ 1380; «Блог» ≥ 1340, «Контакты» ≥ 1280, round Telegram ≥ 1200, «Отзывы» ≥ 1150; burger < 1100.
- `main.js` (all pages) gives you, by markup: header panels `[data-mega]` / `[data-dd]` (hover with intent, click pins, ↓ ↑, Esc),
  `[data-burger]` + `#mmenu` accordions (`.mmenu__acc` → `aria-controls`), `[data-carousel]` (arrows, swipe, keys, active card,
  far images preloaded), `[data-lightbox]` → `#lightbox` (`data-kind`, `data-src` = video file, `data-caption`),
  `[data-open-modal]` (inside `[data-pup]` card → prefilled; `data-modal-title` / `-sub` / `-breed` / `-note` on the button set the title, subtitle, breed and hidden note), `.faq__btn` accordions, `[data-seo-toggle]`, `.fav`, `[data-phone]` mask, `#lead-form`, toast for root-absolute links, `[data-hero-ctas]` (mobile bar appears after it), `[data-reveal]` / `[data-reveal="items"]` (fade-in on scroll), Own logic → `assets/js/<group>.js`, vanilla, wrapped in an IIFE, no libraries.

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

Russian, short sentences, warm and concrete. No prices anywhere (every puppy → «Узнать цену»), no «лучший», «№1». H2 ≤ 5 words, one-line lead ≤ 90 chars,
card line ≤ 60 chars, long SEO text only in `blocks.seo_block`, FAQ or article prose. Keywords: the semantic core CSV, target URL column.
Facts about breeds — from `breeds.json` / `content/home.md`; anything unverified stays in `[brackets]`.
`|typo` adds non-breaking spaces (after 1–2 letter words, before dashes, number + unit); in hand-written HTML use `&nbsp;` the same way.
The build warns about prices, banned words, duplicate ids, broken aria references, `<img>` without alt/size, missing title/description,
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
