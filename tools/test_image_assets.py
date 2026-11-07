"""Regression checks for responsive HTML and source/variant cache invalidation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from image_assets import MANIFEST, PROFILE, ResponsiveImages


class ResponsiveImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / MANIFEST).parent.mkdir(parents=True)
        self.src = "/assets/img/puppy.jpg"
        (self.root / self.src.lstrip("/")).write_bytes(b"source-photo")
        self.variant = "/assets/img/responsive/puppy-test-640.webp"
        (self.root / self.variant.lstrip("/")).write_bytes(b"encoded-photo")
        manifest = {"profile": PROFILE, "images": {self.src: {
            "sha256": hashlib.sha256(b"source-photo").hexdigest(),
            "variants": [{"src": self.variant, "width": 640}],
        }}}
        (self.root / MANIFEST).write_text(json.dumps(manifest))
        self.images = ResponsiveImages(self.root)

    def image(self, extra=""):
        return f'<img src="{self.src}" alt="Щенок" width="1200" height="1600" {extra}>'

    def test_preserves_full_source_dimensions_and_other_html(self):
        page = '<main>Текст\n<figure>' + self.image('loading="lazy"') + '</figure></main>'
        transformed = self.images.process(page)
        self.assertIn(f'src="{self.src}"', transformed)
        self.assertIn('width="1200" height="1600"', transformed)
        self.assertIn(f'srcset="{self.variant} 640w"', transformed)
        self.assertIn('sizes="auto, ', transformed)
        self.assertTrue(transformed.startswith('<main>Текст\n<figure>'))
        self.assertEqual(self.images.process(transformed), transformed)

    def test_eager_hero_and_scaled_faces_use_explicit_sizes(self):
        hero = self.images.process('<div class="hero__photo">' + self.image() + '</div>')
        face = self.images.process('<span class="face">' + self.image('loading="lazy"') + '</span>')
        self.assertIn('sizes="(max-width: 1000px) 100vw,', hero)
        self.assertIn('sizes="128px"', face)
        self.assertNotIn('sizes="auto,', hero)

    def test_does_not_override_dynamic_or_existing_sources(self):
        cases = [
            '<span data-pm-thumb>' + self.image() + '</span>',
            self.image('data-lb-img'),
            self.image('srcset="existing.webp 640w"'),
            '<picture><source srcset="existing.webp">' + self.image() + '</picture>',
            '<script>const html = \'<img src="/assets/img/puppy.jpg">\';</script>',
            '<img src="https://example.com/remote.jpg">',
        ]
        for page in cases:
            with self.subTest(page=page):
                self.assertEqual(self.images.process(page), page)

    def test_context_resets_between_sibling_elements(self):
        page = '<span class="face">' + self.image() + '</span>' + self.image('loading="lazy"')
        transformed = self.images.process(page)
        self.assertEqual(transformed.count('sizes="128px"'), 1)
        self.assertEqual(transformed.count('sizes="auto, '), 1)

    def test_changed_source_requires_regeneration(self):
        (self.root / self.src.lstrip("/")).write_bytes(b"new-photo")
        with self.assertRaisesRegex(ValueError, "missing/outdated"):
            self.images.process(self.image())

    def test_missing_variant_requires_regeneration(self):
        (self.root / self.variant.lstrip("/")).unlink()
        with self.assertRaisesRegex(ValueError, "variants missing"):
            self.images.process(self.image())


if __name__ == "__main__":
    unittest.main()
