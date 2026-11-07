"""Regression checks for CSS pruning, deferred delivery and cache-safe assets."""
import tempfile
import unittest
from pathlib import Path

from web_assets import WebAssets, filter_css


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


if __name__ == "__main__":
    unittest.main()
