import unittest

from repolens.domain import TreeEntry, source_lines, stable_id
from repolens.parsing import CHUNK_LINES, parse_file


def parse(path, text):
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return parse_file(TreeEntry(path, "a" * 40, "100644", len(raw)), raw)


class ParsingTests(unittest.TestCase):
    def assert_valid_spans(self, file):
        lines = source_lines(file.text)
        for chunk in file.chunks:
            self.assertGreaterEqual(chunk.line_start, 1)
            self.assertLessEqual(chunk.line_end, len(lines))
            self.assertLessEqual(chunk.line_end - chunk.line_start + 1, CHUNK_LINES)
            self.assertEqual(chunk.text, "".join(lines[chunk.line_start - 1:chunk.line_end]))

    def test_ast_symbols_include_decorators_methods_and_nested_functions(self):
        source = (
            "import os\n\n@decorate\nclass Service:\n    \"\"\"Service docs.\"\"\"\n"
            "    @cached\n    async def fetch(self):\n"
            "        def nested():\n            return 1\n        return nested()\n"
        )
        file = parse("src/service.py", source)
        symbols = {symbol.name: symbol for symbol in file.symbols}
        self.assertEqual(symbols["Service"].line_start, 3)
        self.assertEqual(symbols["Service.fetch"].line_start, 6)
        self.assertEqual(symbols["Service.fetch"].kind, "async_method")
        self.assertIn("Service.fetch.nested", symbols)
        class_chunk = next(chunk for chunk in file.chunks if chunk.kind == "class")
        self.assertEqual(class_chunk.line_end, 5)
        self.assertTrue(any(chunk.kind == "module" and "import os" in chunk.text for chunk in file.chunks))
        self.assert_valid_spans(file)

    def test_long_function_is_bounded_and_every_line_remains_covered(self):
        file = parse("long.py", "def long():\n" + "    value = 1\n" * 210)
        covered = {line for chunk in file.chunks for line in range(chunk.line_start, chunk.line_end + 1)}
        self.assertEqual(covered, set(range(1, 212)))
        self.assertGreater(len(file.chunks), 1)
        self.assert_valid_spans(file)

    def test_syntax_failure_is_explicit_but_still_searchable(self):
        file = parse("new_syntax.py", "def broken(:\n    pass\n")
        self.assertEqual(file.status, "parse_fallback")
        self.assertEqual(file.symbols, ())
        self.assertEqual(file.chunks[0].kind, "python_fallback")
        self.assert_valid_spans(file)

    def test_python_encoding_and_newline_normalization(self):
        file = parse("encoded.py", b"# coding: latin-1\r\ndef caf\xe9():\r\n    return 1\r\n")
        self.assertEqual(file.status, "indexed")
        self.assertEqual(file.symbols[0].name, "caf\u00e9")
        self.assertEqual(file.symbols[0].line_start, 2)
        self.assertNotIn("\r", file.text)
        self.assert_valid_spans(file)

    def test_unicode_separator_does_not_change_python_line_numbers(self):
        file = parse("separators.py", 'text = "a\u2028b"\ndef later():\n    return text\n')
        self.assertEqual(file.symbols[0].line_start, 2)
        self.assert_valid_spans(file)

    def test_markdown_headings_ignore_fenced_code(self):
        file = parse("README.md", "# Root\nIntro\n```python\n# Not a section\n```\n## Child\nDetails\n")
        self.assertEqual([chunk.symbol for chunk in file.chunks], ["Root", "Root / Child"])
        self.assertEqual(file.chunks[1].line_start, 6)
        self.assert_valid_spans(file)

    def test_empty_binary_and_invalid_encoding_are_explicit(self):
        self.assertEqual(parse("empty.py", "").chunks, ())
        self.assertEqual(parse("binary.py", b"\x00abc").status, "binary")
        self.assertEqual(parse("bad.md", b"\xff").status, "decode_error")
        self.assertEqual(parse("bad.py", b"# coding: nonexistent\nvalue=1\n").status, "decode_error")

    def test_stable_id_is_structured_and_version_sensitive(self):
        self.assertEqual(stable_id("e", "repo", "sha", 1), stable_id("e", "repo", "sha", 1))
        self.assertNotEqual(stable_id("e", "a:b", "c"), stable_id("e", "a", "b:c"))
        self.assertNotEqual(stable_id("e", "sha1"), stable_id("e", "sha2"))


if __name__ == "__main__":
    unittest.main()
