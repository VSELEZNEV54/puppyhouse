# Puppy House — working conventions for page builders

Static site, built by `tools/build.py` (Python 3 stdlib + Jinja2 3.1) into `<url>/index.html` in the repo root.
GitHub Pages serves it from `https://vseleznev54.github.io/puppyhouse/` (subpath `/puppyhouse/`).
The homepage is **approved** — its look must not change. Reference inner page: `/shchenki/`.

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
`src/data/site.json`, `breeds.json`, `puppies.json`, `reviews.json`, `faq.json`, `cities.json`, `blog.json`,
`assets/css/main.css`, `assets/css/pages.css`, `assets/js/main.js`, `tools/photo-tones.json`, `assets/img/`.

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
Computed by the build:
- breed: `tone_class` (`tone--peach`…), `puppies` (its puppies), `stock` (= number of its puppies). Every puppy count on the
  site comes from `puppies.json` (breed tiles «В наличии: 7», «Весь каталог — 19», the catalog) — never type a number;
- puppy: `age_weeks` (from `birth_date` on `site.as_of`), `url`, `breed_name`, `tone`, `tone_class`, `sex_label`, `status_label` (Забронирован/а), `status_dot` (ok/res/soon), `status_order`, `meta` («Мальтипу · 10 недель · мальчик»), `desc` (+ generation, for the modal), `photo` (= `photos[0]`).

`puppies.json`: 19 sample puppies (maltipu 7, bulldog 4, toy poodle 5, border collie 3); the homepage strip shows the 8 listed
in `routes/home.py`. Photo fields: `kind` (`studio` | `life`), `class`, optional `pos` (object-position for a lifestyle shot),
`backdrop: "token"` (only the four approved homepage cards — every other studio photo takes its measured backdrop in the card).
Values in `[square brackets]` are placeholders (see `site.placeholders`); keep them bracketed until the client gives real data.
`cities.json`: `name`, `prep` («в Казани»), `acc` («в Казань»), `gen` («из Казани»), `km_approx` (rough road distance), `methods` (car/plane/train), `duration` (bracketed estimate from distance and the first method, to confirm).
`breeds.json` also has `facts`, `compare` (comparison rows), `docs`, `studio` / `mood` / `adult` photos, `varieties`, `colours` (drafts — check, some with `standard` and `photo`).

## Macros (`ui.`, `cards.`, `forms.`, `blocks.`) — text params are plain text, escaped and run through `|typo`

| Macro | Params | Use |
|---|---|---|
| `ui.page_hero` | `title, lead, tone, breed, photo, faces, facts, chips, eyebrow, id` + `call` → buttons | H1 tile. `breed=` → its tone and studio photo blended |
| `ui.section_head` | `title, id, link={url,label}, lead` + `call` → buttons | H2 row |
| `ui.breadcrumbs` | `items` | used by the layout |
| `ui.studio_tile(s)` | `photo{src,alt}, title, line, url, badge, tone, priority` / `items` | colour / parent photo tile, backdrop = measured photo tone; `priority=true` on the first screen |
| `ui.spec_grid` | `items[{label,value,icon?,color?}], cols=2..4` | facts in white tiles |
| `ui.stat_tiles` | `items[{num,cap,icon,color}]` (`site.stats`) | trust numbers |
| `ui.steps` / `ui.timeline` | `items[{title,text}]`, `cols=3/5` / `items[{when?,title,text?}]` | how-to |
| `ui.link_tiles` | `items[{url,title,line,icon,color \| breed \| image}], style='white'\|'color'` | related links (don't mix image + icon tiles in one row) |
| `ui.cta_band` | `title, line, button='modal'\|{url,label}, label, tone, faces, title_id` | mid-page CTA (wrap in a section, `title_id` → its `aria-labelledby`) |
| `ui.keyfacts`, `ui.callout(kind,title)` + call, `ui.toc([[id,label]])` | | articles (`.article`, `.prose`) |
| `ui.cmp_table` | `cols` (names or breed dicts), `rows[[label, v1, v2…]]`, `caption` | comparison, scrolls inside its tile; column names never break at a hyphen |
| `ui.gallery` | `photos[{src,alt,caption?}]` | 1–5+ photos, ribbon on mobile |
| `ui.badges`, `ui.empty_state(title,text,button,label,attrs)`, `ui.img(src,alt,…)`, `ui.icon`, `ui.ico`, `ui.face`, `ui.round_arrow`, `ui.text_link` | | small parts |
| `cards.puppy_card(p)` | puppy | the homepage card; «Узнать цену» opens the modal for that puppy; studio photo → card in that photo's measured colours |
| `cards.pups_section` | `title, breed, limit=4, id, exclude=slug` | «Щенки в наличии» strip (`.pups--strip`: at 3 columns a lone 4th card is hidden) |
| `cards.breed_tile(s)`, `cards.review_card(r, short)`, `cards.ratings()`, `cards.soon_tile()` | | |
| `forms.lead_form` | `title, line, tone, breed, id='zayavka'` | one per page (the layout adds it) |
| `forms.price_button(label, cls)`, `forms.msgr(kind)` | | generic «Узнать цену» / messenger button |
| `blocks.faq_section` / `faq_list` | `items` (faq.json or `{q,a}`), `title, id, link, short` | accordion |
| `blocks.reviews_section` | `reviews, title, id, title_id, link, short` | |
| `blocks.seo_block` | `title, lead, id, key` + `call` → hidden `<h3>/<p>` | collapsed SEO text |

## CSS and JS

- Design tokens and every homepage class live in `main.css`; the inner-page kit in `pages.css`
  (`.crumbs .phero .specs .kpis .badges .tline .ltiles .cta-band .empty .article .prose .table-wrap .keyfacts .callout .toc .cmp .gallery .filters .fseg .pups--grid .soon-tile .stiles .tile .grid .split`).
- Your CSS: only page-specific layout, prefix classes with your group (`.dlv-…`). Use tokens (`var(--gap)`, `--r-tile`, `--tile-pad`, `--sec`, colours). No new fonts, no shadows/colours outside the palette.
- Breakpoints used everywhere: 1199 / 1000 / 900 / 760 (mobile: ribbons via `.scroller`) / 560 / 420. Check 360–1920, no horizontal page scroll.
- `main.js` (all pages) gives you, by markup: `[data-open-modal]` (inside `[data-pup]` card → prefilled; `data-modal-title` / `-sub` / `-breed` / `-note` on the button set the title, subtitle, breed and hidden note), `.faq__btn` accordions, `[data-seo-toggle]`, `.fav`, `[data-phone]` mask, `#lead-form`, toast for root-absolute links, `[data-hero-ctas]` (mobile bar appears after it), `[data-reveal]` / `[data-reveal="items"]` (fade-in on scroll), `.scroller` lazy images. Own logic → `assets/js/<group>.js`, vanilla, wrapped in an IIFE, no libraries.

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
3. Homepage must stay pixel-identical: `node $S/shot/shot.mjs http://127.0.0.1:8765/ $S/h 1920,1440,1024,768,390,360 100000`, then `python3 $S/pixcmp.py $S/baseline/v2/home-<w>.png $S/h-<w>.png` → «differing px: 0» (the older `$S/baseline/home-*.png` have blank lazy images — capture artifact, don't use); `node $S/qa-home.mjs` (expected: the same 8 known failures as before the migration — breed white-text contrast ×2, sticker geometry ×2, burger Shift+Tab wrap, «marquee» matching .sticker, 1024/768 breed-title layout ×2; toast checks are skipped while no link points to an unbuilt page).
4. Interaction test for your JS: copy the pattern of `$S/qa-catalog.mjs`.
5. Subpath: `python3 $S/found/subpath_server.py 8766 &` serves the repo at `http://127.0.0.1:8766/puppyhouse/`; `node $S/found/qa-subpath.mjs` shows the checks.
6. Final report: pages built, unbuilt link targets you introduced, shared changes you need (file + exact change + why), placeholders added.
