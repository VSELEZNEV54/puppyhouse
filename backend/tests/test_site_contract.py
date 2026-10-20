"""Contract between the built static site and the API: every form trigger and value the pages send must be
something the backend understands. Runs over the committed */index.html (build the site first: tools/build.py)."""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.enums import LeadKind
from app.services import catalog, consent

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "src" / "data"
# the published pages of this stage (tools/build.py → .build-manifest.json), not stale builds left on disk
PAGES = sorted(REPO / f for f in json.loads((REPO / ".build-manifest.json").read_text(encoding="utf-8"))["files"])


class Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self._select: str | None = None
        self.options: list[tuple[str | None, str | None]] = []  # (select name, value)

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        self.tags.append((tag, a))
        if tag == "select":
            self._select = a.get("name")
        elif tag == "option":
            self.options.append((self._select, a.get("value")))

    def handle_endtag(self, tag):
        if tag == "select":
            self._select = None


@pytest.fixture(scope="module")
def site():
    if not PAGES:
        pytest.skip("the site is not built")
    out = {}
    for p in PAGES:
        c = Collector()
        c.feed(p.read_text(encoding="utf-8"))
        out[p.relative_to(REPO).as_posix()] = c
    return out


@pytest.fixture(scope="module")
def cat():
    return catalog.load(DATA)


def test_every_page_has_the_api_meta(site):
    cur = json.loads((DATA / "consent.json").read_text(encoding="utf-8"))["current"]
    for page, c in site.items():
        metas = [a for t, a in c.tags if t == "meta" and a.get("name") == "dsh-api"]
        assert len(metas) == 1, f"{page}: one <meta name=dsh-api> expected"
        m = metas[0]
        assert m.get("content") == "/api/v1", page
        assert "https://xn--b1adduihee9g.xn--p1ai" in m.get("data-origins", "").split(), page
        assert "github.io" not in m.get("data-origins", ""), f"{page}: the preview must stay in prototype mode"
        assert m.get("data-consent") == cur["processing"], page
        assert m.get("data-consent-publish") == cur["distribution"], page
        assert m.get("data-consent-review") == cur["review"], page


def test_every_modal_trigger_has_a_valid_kind(site):
    kinds = {k.value for k in LeadKind}
    bad = []
    for page, c in site.items():
        for t, a in c.tags:
            if "data-open-modal" in a:
                k = a.get("data-modal-kind")
                if k not in kinds:
                    bad.append((page, a.get("class"), k))
    assert not bad, bad[:10]


def test_puppy_cards_reference_real_puppies(site, cat):
    slugs = {p["slug"]: p["breed"] for p in cat.puppies}
    seen = 0
    for page, c in site.items():
        for t, a in c.tags:
            if "data-pup" in a:
                seen += 1
                assert a.get("data-slug") in slugs, (page, a.get("data-slug"))
                assert a.get("data-breed") == slugs[a["data-slug"]], (page, a.get("data-slug"), a.get("data-breed"))
    assert seen > 0


def test_colour_buttons_reference_real_colours(site, cat):
    seen = 0
    for page, c in site.items():
        for t, a in c.tags:
            col = a.get("data-modal-colour")
            if col:
                seen += 1
                breed = cat.breed_by_any(a.get("data-modal-breed"))
                assert breed is not None, (page, a.get("data-modal-breed"))
                assert col in cat.colours.get(breed["slug"], {}), (page, breed["slug"], col)
    assert seen > 0


def test_breed_options_are_slugs(site, cat):
    allowed = {b["slug"] for b in cat.breeds} | {"undecided", ""}
    seen = 0
    for page, c in site.items():
        for name, value in c.options:
            if name == "breed":
                seen += 1
                assert value is not None and value in allowed, (page, value)
    assert seen > 0


def test_forms_have_honeypot_and_consent(site):
    for page, c in site.items():
        names = [a.get("name") for t, a in c.tags if t == "input"]
        assert names.count("hp_note") >= 1, f"{page}: no honeypot"
        assert "consent" in names, f"{page}: no consent checkbox"
        links = [a.get("href", "") for t, a in c.tags if t == "a"]
        assert any("soglasie" in h for h in links), f"{page}: no link to the consent document"


def test_review_form_collects_the_authors_phone_and_links_the_review_consent(site):
    if "otzyvy/index.html" not in site:  # staged release: the reviews page is not published yet (src/data/publish.json)
        pytest.skip("/otzyvy/ is not in this stage of the site")
    c = site["otzyvy/index.html"]
    form_inputs = {a.get("name") for t, a in c.tags if t in ("input", "textarea")}
    assert {"name", "phone", "text", "consent", "consent_publish", "hp_note"} <= form_inputs
    links = {a.get("href", "") for t, a in c.tags if t == "a"}
    assert any("soglasie-na-otzyv" in h for h in links) and any("soglasie-na-publikaciyu" in h for h in links)


def test_consent_pages_are_built():
    docs = consent.load(DATA / "consent.json")["versions"]
    for doc in docs.values():
        page = REPO / doc["url"].strip("/") / "index.html"
        assert page.is_file(), doc["url"]
        html = page.read_text(encoding="utf-8")
        assert doc["version"] in html or doc["title"] in html


_PLACEHOLDER = re.compile(r"\[[^\[\]\n\"<>]{2,90}\]")   # «[6 или 12]» — the shape tools/check_launch.py counts
_LD_JSON = re.compile(r"(<script[^>]*application/ld\+json[^>]*>)(.*?)(</script>)", re.S | re.I)
_CODE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_TEXT_ATTRS = re.compile(r'\s(?:alt|title|aria-label|placeholder|content)="([^"]*)"')


def test_published_pages_show_no_placeholders():
    """A [заглушка] in the text of a published page, its alt/meta texts or its JSON-LD (the FAQ snippet in search):
    fill it in src/data or reword it before the page goes out."""
    for p in PAGES:
        src = p.read_text(encoding="utf-8")
        ld = " ".join(json.dumps(json.loads(m.group(2)), ensure_ascii=False) for m in _LD_JSON.finditer(src))
        page = _CODE.sub(" ", src)
        text = " ".join([re.sub(r"<[^>]+>", " ", page), *_TEXT_ATTRS.findall(page), ld])
        found = sorted(set(_PLACEHOLDER.findall(html.unescape(text))))
        assert not found, f"{p.relative_to(REPO).as_posix()}: {found}"


_META_TEXT = re.compile(r'<(?:meta (?:name|property)="(?:description|og:title|og:description|twitter:title|twitter:description)" '
                        r'content="([^"]*)"|title>([^<]*)</title)')


def test_titles_and_descriptions_carry_no_markup():
    """Search snippets show the text as is: a <span class="nw"> from |typo would be printed literally."""
    for p in PAGES:
        for m in _META_TEXT.finditer(p.read_text(encoding="utf-8")):
            val = html.unescape(m.group(1) if m.group(1) is not None else m.group(2))
            assert "<" not in val and ">" not in val, f"{p.relative_to(REPO).as_posix()}: {val[:120]}"
