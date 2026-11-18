"""strip_hidden_section, match_any and tail (existing behaviour only)."""
import unittest

import hx

TURKISH_SPEC = """# Görev
giriş metni

## Gizli test biçimi
gizli ayrıntı: tests/gizli_test.py
### alt başlık
daha gizli

## Kapsam
hx.py
"""

ENGLISH_SPEC = """# Task
intro

## Hidden Test Format
secret path: tests/hidden_test.py
### subsection
more secret

## Scope
hx.py
"""


class StripHiddenSectionTest(unittest.TestCase):
    def test_turkish_heading_is_removed_with_its_body(self):
        out = hx.strip_hidden_section(TURKISH_SPEC)
        self.assertIn("# Görev", out)
        self.assertIn("giriş metni", out)
        self.assertIn("## Kapsam", out)
        self.assertIn("hx.py", out)
        self.assertNotIn("gizli ayrıntı", out)
        self.assertNotIn("alt başlık", out)
        self.assertNotIn("Gizli test biçimi", out)

    def test_english_heading_is_case_insensitive(self):
        for heading in ("## Hidden Test Format", "## HIDDEN TEST FORMAT", "## hidden test format"):
            spec = ENGLISH_SPEC.replace("## Hidden Test Format", heading)
            out = hx.strip_hidden_section(spec)
            self.assertNotIn("secret path", out, heading)
            self.assertNotIn("more secret", out, heading)
            self.assertIn("## Scope", out, heading)
            self.assertIn("intro", out, heading)

    def test_stops_at_the_next_heading_of_the_same_level(self):
        spec = "## Gizli test biçimi\nsır\n## Kapsam\nkod\n"
        out = hx.strip_hidden_section(spec)
        self.assertEqual("## Kapsam\nkod\n", out)

    def test_stops_at_a_higher_level_heading(self):
        spec = "# Görev\nmetin\n## Gizli test biçimi\nsır\n# Sonraki\nkod\n"
        out = hx.strip_hidden_section(spec)
        self.assertEqual("# Görev\nmetin\n# Sonraki\nkod\n", out)

    def test_heading_with_trailing_text_is_still_matched(self):
        spec = "# Görev\nmetin\n## Gizli test biçimi (sadece tester)\nsır\n## Kapsam\nkod\n"
        out = hx.strip_hidden_section(spec)
        self.assertNotIn("sır", out)
        self.assertNotIn("(sadece tester)", out)
        self.assertIn("## Kapsam", out)

    def test_top_level_heading_is_removed(self):
        spec = "# Gizli test biçimi\nsır\n# Sonraki\nkod\n"
        out = hx.strip_hidden_section(spec)
        self.assertEqual("# Sonraki\nkod\n", out)

    def test_heading_at_the_end_of_the_spec(self):
        spec = "# Görev\nmetin\n## Gizli test biçimi\nsır\n"
        out = hx.strip_hidden_section(spec)
        self.assertEqual("# Görev\nmetin\n", out)

    def test_without_heading_the_text_is_returned_unchanged(self):
        spec = "# Görev\n\nmetin\n\n## Kapsam\nhx.py\n\n"
        self.assertEqual(spec, hx.strip_hidden_section(spec))


class MatchAnyTest(unittest.TestCase):
    def test_matches_a_file_against_globs(self):
        self.assertTrue(hx.match_any("src/a.py", ["src/*.py"]))
        self.assertTrue(hx.match_any("tests/test_a.py", ["tests/*.py"]))

    def test_no_match_returns_false(self):
        self.assertFalse(hx.match_any("a.txt", ["*.py", "*.md"]))

    def test_any_of_the_globs_is_enough(self):
        self.assertTrue(hx.match_any("README.md", ["*.py", "*.md"]))

    def test_empty_glob_list_matches_nothing(self):
        self.assertFalse(hx.match_any("a.py", []))


class TailTest(unittest.TestCase):
    def test_returns_the_last_n_lines(self):
        self.assertEqual("b\nc", hx.tail("a\nb\nc\n", 2))

    def test_default_keeps_thirty_lines(self):
        text = "\n".join(f"line{i}" for i in range(40))
        out = hx.tail(text)
        self.assertEqual(30, len(out.splitlines()))
        self.assertEqual("line10", out.splitlines()[0])
        self.assertEqual("line39", out.splitlines()[-1])

    def test_more_lines_than_available_returns_everything(self):
        self.assertEqual("a\nb", hx.tail("a\nb\n", 10))

    def test_empty_input(self):
        self.assertEqual("", hx.tail(""))


if __name__ == "__main__":
    unittest.main()
