#!/usr/bin/env python3
"""Build the presentation page (one self-contained HTML, SVGs inline) from concepts/ + results*.json.

  python3 make_page.py [out.html]
Reads ../results.json (round 1: designs, judges) and, if present, ../results-polish.json (polish + rescore)
and ../verdict.json (the art director's recommendation text).
"""
import html, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
C = os.path.join(ROOT, 'concepts')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'presentation.html')

TITLES = {
    '00-current': 'Сейчас на сайте', '01-puhlyj': 'Пухлый', '02-dom-lapa': 'Дом-лапа', '03-harakter': 'Щенок в буквах',
    '04-emblema': 'Эмблема', '05-rodnoj': 'Родной сайту', '06-chetyre-porody': 'Четыре породы', '07-ot-ruki': 'От руки',
}
LABELS = {
    'lockup': 'основной', 'lockup-inverse': 'на тёмном', 'lockup-mono': 'в один цвет', 'mark': 'знак',
    'mark-mono': 'знак в один цвет', 'stacked': 'вертикальный', 'lockup-short': 'короткий, для телефона',
    'lockup-tagline': 'с подписью', 'lockup-on-coral': 'на коралловом', 'mark-16': 'фавикон 16 px',
    'mark-round': 'для круглых аватаров', 'mark-awake': 'проснулся, при наведении', 'extra-badge': 'печать',
    'extra-passport': 'обложка паспорта щенка', 'extra-sticker': 'наклейка', 'extra-pattern': 'паттерн',
    'extra-collar-tag': 'адресник на ошейник', 'extra-wake': 'просыпается при наведении', 'extra-tag': 'адресник',
    'extra-avatar': 'аватар', 'extra-on-coral': 'на коралловом', 'extra-phone': 'шапка на телефоне',
    'stacked-inverse': 'вертикальный на тёмном', 'extra-favicon': 'фавикон по пикселям', 'extra-sign': 'вывеска',
    'extra-grounds': 'на тёмном и коралловом', 'extra-breeds': 'цвета пород',
}
CRIT = [('memorability', 'запоминается'), ('brand_fit', 'подходит питомнику'), ('craft', 'качество исполнения'),
        ('small_size', 'читается в 16–32 px'), ('site_fit', 'встаёт в сайт')]
ORDER = ['lockup', 'mark', 'lockup-inverse', 'lockup-mono', 'mark-mono', 'stacked', 'lockup-short', 'lockup-tagline',
         'lockup-on-coral', 'mark-16', 'mark-round', 'mark-awake']


SHORT = {k[:2]: v for k, v in TITLES.items()}


def esc(s):
    s = re.sub(r'\b0\d-[a-z]+(?:-[a-z]+)*', lambda m: '«' + TITLES.get(m.group(0), m.group(0)) + '»', str(s))
    s = re.sub(r'\b0\d\s+(?=«)', '', s)                      # «04 «Эмблема»» -> «Эмблема»
    s = re.sub(r'(?<![\d.,])\b(0[1-7])\b(?![\d.,]\d)', lambda m: '«' + SHORT[m.group(1)] + '»', s)  # bare 06 -> «Четыре породы»
    return html.escape(s, quote=True)


def svg(path, cls='', label=''):
    s = open(path, encoding='utf-8').read()
    s = re.sub(r'<\?xml[^>]*>\s*', '', s)
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S).strip()
    attrs = f' class="{cls}"' if cls else ''
    attrs += f' role="img" aria-label="{esc(label)}"' if label else ' aria-hidden="true"'
    return s.replace('<svg ', '<svg' + attrs + ' ', 1)


def files(cid):
    d = os.path.join(C, cid)
    names = [f[:-4] for f in os.listdir(d) if f.endswith('.svg')]
    head = [n for n in ORDER if n in names]
    rest = sorted(n for n in names if n not in ORDER)
    return head + rest


def fills(cid):
    seen = []
    for n in ('lockup', 'mark', 'lockup-inverse'):
        p = os.path.join(C, cid, n + '.svg')
        if not os.path.exists(p): continue
        for h in re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{6})"', open(p).read()):
            h = h.upper()
            if h not in seen: seen.append(h)
    return seen


r1 = json.load(open(os.path.join(ROOT, 'results.json')))
pol_path = os.path.join(ROOT, 'results-polish.json')
pol = json.load(open(pol_path)) if os.path.exists(pol_path) else None
ver_path = os.path.join(ROOT, 'verdict.json')
verdict = json.load(open(ver_path)) if os.path.exists(ver_path) else None

design = {c['id']: c for c in r1['concepts']}
polished = {p['id']: p for p in (pol['polished'] if pol else [])}
if pol:
    rs = pol['rescore']
    score = {c['id']: c for c in rs['concepts']}
    ranking = [i for i in rs['ranking'] if i != '00-current']
else:  # fallback: average the two round-1 judges
    score = {}
    for j in r1['judges']:
        for c in j['concepts']:
            s = score.setdefault(c['id'], {'id': c['id'], 'pros_ru': [], 'cons_ru': [], 'verdict_ru': ''})
            for k, _ in CRIT + [('overall', '')]:
                s[k] = round((s.get(k, 0) * (len(r1['judges']) - 1) + c[k]) / len(r1['judges']), 1) if k in s else c[k]
            s['pros_ru'] += c['pros_ru'][:2]; s['cons_ru'] += c['cons_ru'][:2]
    ranking = sorted([i for i in score if i != '00-current'], key=lambda i: -score[i]['overall'])
    rs = {'best_for_site': r1['judges'][0]['best_for_site'], 'best_overall': r1['judges'][0]['best_overall'],
          'closest_to_reference': '01-puhlyj', 'summary_ru': r1['judges'][0]['summary_ru']}

concept_ids = ranking
all_ids = ['00-current'] + ranking
default = rs.get('best_for_site') or ranking[0]


def idea(cid):
    if cid in polished: return polished[cid]['idea_ru']
    if cid in design: return design[cid]['idea_ru']
    return 'Коралловая плитка с типовой лапкой и название шрифтом сайта.'


def usage(cid):
    return polished.get(cid, {}).get('usage_ru', '')


def fonts(cid):
    if verdict and cid in verdict.get('fonts', {}): return [verdict['fonts'][cid]]
    out = []
    for f in design.get(cid, {}).get('design', {}).get('fonts', []):
        name = re.split(r'[\s\[(,]', f.strip(), maxsplit=1)[0]
        name = {'MPLUSRounded1c': 'M PLUS Rounded 1c', 'M': 'M PLUS Rounded 1c'}.get(name, name)
        if name and name not in out: out.append(name)
    return out


def swatch_for(name):
    if 'inverse' in name: return 'navy'
    if 'mono' in name: return 'white'
    if 'coral' in name: return 'coral'
    return 'page'


# ---------- try-on templates ----------
def lockup_for_phone(cid):
    p = os.path.join(C, cid, 'lockup-short.svg')
    return p if os.path.exists(p) else os.path.join(C, cid, 'lockup.svg')


def favicon(cid):
    p = os.path.join(C, cid, 'mark-16.svg')
    return p if os.path.exists(p) else os.path.join(C, cid, 'mark.svg')


def avatar(cid):
    p = os.path.join(C, cid, 'mark-round.svg')
    return p if os.path.exists(p) else os.path.join(C, cid, 'mark.svg')


def slots(cid):
    return {
        'desk': svg(os.path.join(C, cid, 'lockup.svg'), label=f'{TITLES[cid]}: логотип в шапке'),
        'phone': svg(lockup_for_phone(cid), label=f'{TITLES[cid]}: логотип в шапке на телефоне'),
        'fav': svg(favicon(cid)),
        'ava': svg(avatar(cid), label=f'{TITLES[cid]}: аватар'),
    }


chips = []
templates = []
for cid in all_ids:
    rank = '' if cid == '00-current' else f'<span class="chip__n">{ranking.index(cid) + 1}</span>'
    chips.append(f'<label class="chip"><input type="radio" name="tryon" id="try-{cid}" value="{cid}"'
                 f'{" checked" if cid == default else ""}>{rank}<span>{esc(TITLES[cid])}</span></label>')
    s = slots(cid)
    templates.append(f'<template id="tpl-{cid}">' + ''.join(f'<div data-slot="{k}">{v}</div>' for k, v in s.items()) + '</template>')
d0 = slots(default)

tryon = f'''
<section class="tryon" aria-labelledby="tryon-h">
  <div class="tryon__head">
    <h2 id="tryon-h">Примерка на сайт</h2>
    <p class="muted">Выберите вариант: он встанет в шапку, на вкладку браузера и в аватар. Цифра — место в итоговом рейтинге.</p>
  </div>
  <fieldset class="chips"><legend class="sr">Вариант логотипа</legend>{"".join(chips)}</fieldset>
  <div class="stage">
    <div class="stage__desk">
      <p class="cap">шапка сайта, компьютер</p>
      <div class="site"><div class="site__bar">
        <a class="site__logo" data-slot-target="desk">{d0["desk"]}</a>
        <span class="site__menu">Меню</span>
        <nav class="site__nav" aria-hidden="true"><span class="site__accent">Каталог щенков</span><span>Породы</span><span>Доставка</span><span>Отзывы</span></nav>
        <span class="site__btn">Оставить заявку</span>
      </div>
      <div class="site__hero"><span class="site__eyebrow">питомник в Москве · 9 лет</span><span class="site__h1">Щенки напрямую от заводчика</span></div></div>
    </div>
    <div class="stage__side">
      <div>
        <p class="cap">телефон</p>
        <div class="phone"><div class="phone__bar"><span class="phone__logo" data-slot-target="phone">{d0["phone"]}</span><span class="phone__burger"></span></div></div>
      </div>
      <div>
        <p class="cap">вкладка браузера, 16 px</p>
        <div class="tab"><span class="tab__ico" data-slot-target="fav">{d0["fav"]}</span><span>Щенки мальтипу | домщенков.рф</span></div>
      </div>
      <div>
        <p class="cap">аватар в мессенджере</p>
        <div class="chat"><span class="chat__ava" data-slot-target="ava">{d0["ava"]}</span><span class="chat__txt"><b>домщенков.рф</b><span>Видео щенков отправили вам в чат</span></span></div>
      </div>
    </div>
  </div>
  {"".join(templates)}
</section>'''


# ---------- recommendation ----------
def short_card(cid, role):
    sc = score.get(cid, {})
    return f'''<article class="pick">
      <p class="pick__role">{esc(role)}</p>
      <div class="pick__logo">{svg(os.path.join(C, cid, 'lockup.svg'))}</div>
      <h3><a href="#{cid}">{esc(TITLES[cid])}</a></h3>
      <p>{esc(sc.get('verdict_ru', ''))}</p>
    </article>'''


picks = []
seen = set()
for cid, role in ((rs.get('best_overall'), 'лучший в целом'), (rs.get('best_for_site'), 'лучший для шапки сайта'),
                  (rs.get('closest_to_reference'), 'ближе всех к референсу')):
    if cid and cid in TITLES and cid not in seen:
        seen.add(cid); picks.append(short_card(cid, role))
    elif cid in seen:  # same concept wins twice: add the role to its card
        picks = [p.replace('</p>\n      <div class="pick__logo">', f' · {esc(role)}</p>\n      <div class="pick__logo">', 1)
                 if f'href="#{cid}"' in p else p for p in picks]

ver_html = ''
if verdict:
    opts = ''.join(f'''<li><b>{esc(o["title"])}</b> {esc(o["text"])}
      <span class="pc"><span class="plus">плюсы:</span> {esc(o["plus"])}</span>
      <span class="pc"><span class="minus">минусы:</span> {esc(o["minus"])}</span></li>''' for o in verdict['options'])
    ver_html = f'''<div class="verdict"><h3>Как выбрать</h3><p>{esc(verdict["lead"])}</p><ul class="opts">{opts}</ul></div>'''

recommend = f'''
<section class="rec" aria-labelledby="rec-h">
  <h2 id="rec-h">Итог жюри</h2>
  <p class="lead">{esc(rs.get('summary_ru', ''))}</p>
  <div class="picks">{"".join(picks)}</div>
  {ver_html}
</section>'''


# ---------- concept sections ----------
def bars(cid):
    sc = score.get(cid)
    if not sc: return ''
    rows = ''.join(f'<div class="bar"><span>{lbl}</span><span class="bar__track"><span class="bar__fill" style="width:{sc[k] * 10:.0f}%"></span></span><b>{sc[k]:g}</b></div>' for k, lbl in CRIT)
    return f'<div class="bars" aria-label="Оценки жюри из 10">{rows}</div>'


def plist(items, cls):
    return '<ul class="' + cls + '">' + ''.join(f'<li>{esc(i)}</li>' for i in items) + '</ul>' if items else ''


sections = []
for cid in concept_ids:
    fl = files(cid)
    sc = score.get(cid, {})
    rank = ranking.index(cid) + 1
    tiles = []
    for n in fl:
        if n in ('lockup', 'mark'): continue
        lbl = LABELS.get(n, n)
        if n == 'lockup-inverse':
            tiles.append(f'<figure class="tile tile--wide sw-navy">{svg(os.path.join(C, cid, n + ".svg"), label=lbl)}<figcaption>{lbl}, тёмно-синий</figcaption></figure>')
            tiles.append(f'<figure class="tile tile--wide sw-ink">{svg(os.path.join(C, cid, n + ".svg"))}<figcaption>{lbl}, чёрный</figcaption></figure>')
            continue
        wide = n.startswith('lockup') or n in ('extra-pattern', 'extra-wake')
        tiles.append(f'<figure class="tile{" tile--wide" if wide else ""} sw-{swatch_for(n)}">{svg(os.path.join(C, cid, n + ".svg"), label=lbl)}<figcaption>{lbl}</figcaption></figure>')
    mark = os.path.join(C, cid, 'mark.svg')
    sizes = ''.join(f'<span class="sz" style="--s:{s}px">{svg(favicon(cid) if s == 16 else mark)}<small>{s}</small></span>' for s in (64, 32, 16))
    pal = ''.join(f'<li><span class="dot" style="background:{h}"></span>{h}</li>' for h in fills(cid))
    fnt = ', '.join(fonts(cid))
    status = '' if cid in polished or not pol else '<p class="note">Этот вариант не дорабатывался во втором раунде: жюри поставило его ниже остальных.</p>'
    issues = polished.get(cid, {}).get('remaining_issues_ru', [])
    sections.append(f'''
<section class="concept" id="{cid}" aria-labelledby="h-{cid}">
  <header class="concept__head">
    <p class="concept__rank">место {rank} из {len(ranking)}<span>оценка {sc.get("overall", 0):g} из 10</span></p>
    <h2 id="h-{cid}">{esc(TITLES[cid])}</h2>
    <p class="concept__idea">{esc(idea(cid))}</p>
    {status}
  </header>
  <div class="hero2">
    <figure class="tile tile--hero sw-page">{svg(os.path.join(C, cid, "lockup.svg"), label=TITLES[cid] + ": основной логотип")}<figcaption>основной, на фоне сайта</figcaption></figure>
    <figure class="tile tile--mark sw-white">{svg(mark, label=TITLES[cid] + ": знак")}<figcaption>знак</figcaption></figure>
  </div>
  <div class="sizes"><p class="cap">реальный размер на экране</p><div class="sizes__row">{sizes}</div></div>
  <div class="tiles">{"".join(tiles)}</div>
  <div class="facts">
    <div class="facts__col">
      {bars(cid)}
      <dl class="meta">{f"<dt>шрифт</dt><dd>{esc(fnt)}</dd>" if fnt else ""}<dt>цвета</dt><dd><ul class="pal">{pal}</ul></dd><dt>файлы</dt><dd><code>docs/logo/concepts/{cid}/</code></dd></dl>
    </div>
    <div class="facts__col">
      {f'<h3>Где использовать</h3><p>{esc(usage(cid))}</p>' if usage(cid) else ''}
      <div class="pros"><h3>Плюсы</h3>{plist(sc.get("pros_ru", []), "plus-list")}</div>
      <div class="pros"><h3>Минусы</h3>{plist(sc.get("cons_ru", []), "minus-list")}</div>
    </div>
  </div>
</section>''')

cur = score.get('00-current', {})
baseline = f'''
<section class="concept concept--base" id="00-current" aria-labelledby="h-cur">
  <header class="concept__head"><p class="concept__rank">для сравнения<span>оценка {cur.get("overall", 0):g} из 10</span></p>
  <h2 id="h-cur">Сейчас на сайте</h2><p class="concept__idea">{esc(cur.get("verdict_ru", "Коралловая плитка с типовой лапкой и название шрифтом сайта."))}</p></header>
  <div class="hero2"><figure class="tile tile--hero sw-page">{svg(os.path.join(C, "00-current", "lockup.svg"), label="Текущий логотип")}<figcaption>текущий логотип</figcaption></figure>
  <figure class="tile tile--mark sw-white">{svg(os.path.join(C, "00-current", "mark.svg"))}<figcaption>текущий фавикон</figcaption></figure></div>
</section>'''

nav = ''.join(f'<a href="#{cid}">{esc(TITLES[cid])}</a>' for cid in concept_ids)

CSS = open(os.path.join(HERE, 'page.css'), encoding='utf-8').read()
JS = open(os.path.join(HERE, 'page.js'), encoding='utf-8').read()

page = f'''<title>Логотип домщенков.рф</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <header class="top">
    <p class="eyebrow">домщенков.рф · фирменный знак · октябрь 2026</p>
    <h1>Логотип домщенков.рф</h1>
    <p class="lead">{len(concept_ids)} направлений. Каждое проверено в шапке сайта, на иконке 16 px, на тёмном фоне и в один цвет. Две независимые оценки: бренд и качество исполнения.</p>
    <nav class="toc" aria-label="Варианты">{nav}<a href="#00-current">Сейчас</a></nav>
  </header>
  {tryon}
  {recommend}
  {"".join(sections)}
  {baseline}
  <footer class="end"><p>Все файлы — чистые SVG без шрифтов: буквы переведены в кривые, их можно сразу отдавать в печать и на сайт. Лежат в репозитории сайта, папка <code>docs/logo/concepts/</code>.</p></footer>
</div>
<script>{JS}</script>
'''
open(OUT, 'w', encoding='utf-8').write(page)
print(OUT, f'{len(page) / 1024:.0f} KB')
