"""Regression checks for CSS pruning, deferred delivery and cache-safe assets."""
import tempfile
import unittest
from pathlib import Path

from web_assets import WebAssets, filter_css, preload_hero


class CSSFilteringTests(unittest.TestCase):
    def test_required_classes_and_selector_alternatives(self):
        css = ".used,.absent{color:red}.used .absent{color:blue}.used:is(.a,.b):not(.missing){color:green}"
        result = filter_css(css, {"used"}, set())
        self.assertIn(".used{color:red}", result)
        self.assertNotIn("color:blue", result)
        self.assertIn(":is(.a,.b):not(.missing)", result)

    def test_nested_media_runtime_states_and_keyframes(self):
        css = "@media(max-width:760px){.menu.is-open{display:block}.other{display:none}}@keyframes fade{from{opacity:0}to{opacity:1}}"
        result = filter_css(css, {"menu"}, set())
        self.assertIn(".menu.is-open", result)
        self.assertNotIn(".other", result)
        self.assertIn("@keyframes fade", result)

    def test_real_attribute_names_not_text_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets/css").mkdir(parents=True)
            (root / "assets/js").mkdir()
            (root / "assets/css/main.css").write_text('@font-face{src:url(../fonts/test.woff2)}.hero{color:red}.dynamic{color:blue}.absent{color:green}.below{color:pink}')
            (root / "assets/js/main.js").write_text("document.body.classList.add('dynamic'); // comment")
            source = '<html><head><link rel="stylesheet" href="/assets/css/main.css"><script defer src="/assets/js/main.js"></script></head><body><main><section class="hero hero--full">absent</section><section class="below"></section></main></body></html>'
            assets = WebAssets(root)
            result = assets.page(source)
            self.assertEqual(result, assets.page(source))
            self.assertIn("data-critical-css", result)
            self.assertIn("data-site-styles", result)
            self.assertIn("<noscript>", result)
            self.assertIn('/assets/fonts/test.woff2', result)
            self.assertNotIn(".below", result)
            # A short hero exposes part of the following section on a tall screen.
            self.assertIn(".below", assets.page(source.replace("hero hero--full", "hero")))
            css = next((root / "assets/css").glob("*.min.css")).read_text()
            self.assertIn(".dynamic", css)
            self.assertIn(".below", css)
            self.assertNotIn(".absent", css)
            self.assertIn("../fonts/test.woff2", css)
            script = next((root / "assets/js").glob("*.min.js")).read_text()
            self.assertNotIn("comment", script)


class HeroPreloadTests(unittest.TestCase):
    def test_preload_matches_responsive_image_on_nested_routes(self):
        from build import Rewriter
        from html.parser import HTMLParser

        source = '<html><head><meta name="viewport" content="width=device-width"><link rel="preload" as="font" href="/assets/fonts/geist-latin.woff2"></head><body><main><img src="/assets/img/hero-four-breeds.jpg" srcset="/assets/img/responsive/hero-640.webp 640w, /assets/img/responsive/hero-960.webp 960w" sizes="(max-width:760px) 100vw, 70vw" fetchpriority="high"></main></body></html>'
        preloaded = preload_hero(source)
        self.assertEqual(preload_hero(preloaded), preloaded)
        self.assertLess(preloaded.index('data-hero-preload'), preloaded.index('as="font"'))

        class Tags(HTMLParser):
            def __init__(self, text):
                super().__init__()
                self.tags = {}
                self.feed(text)

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == 'img' or 'data-hero-preload' in values:
                    self.tags[tag] = values

        for prefix, url in [('', '/'), ('', '/maltipu/cena/'), ('/full', '/maltipu/')]:
            with self.subTest(prefix=prefix, url=url):
                html = Rewriter({url}, prefix=prefix).page(preloaded, url)
                tags = Tags(html).tags
                self.assertEqual(tags['link']['href'], tags['img']['src'])
                self.assertEqual(tags['link']['imagesrcset'], tags['img']['srcset'])
                self.assertEqual(tags['link']['imagesizes'], tags['img']['sizes'])
                self.assertNotIn('"/assets/', html)

    def test_lazy_or_noncontent_images_are_not_preloaded(self):
        source = '<head><meta name="viewport" content="width=device-width"></head><img src="/assets/img/logo.jpg" fetchpriority="high"><main><img src="/assets/img/photo.jpg" loading="lazy" fetchpriority="high"></main>'
        self.assertEqual(preload_hero(source), source)


if __name__ == "__main__":
    unittest.main()
