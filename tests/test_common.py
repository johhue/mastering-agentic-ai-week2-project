"""Regression checks for shared corpus helpers."""

import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

from utils.common import (
    compact_text, iter_text_files, read_source, read_text, split_text,
    stable_vector_id, tokenize,
)


class CorpusHelperTests(unittest.TestCase):
    """Verify chunk identity, file handling, and retrieval normalization."""

    def test_chunk_boundaries(self):
        """Keep overlapping chunks identical to the ingestion format."""
        self.assertEqual(list(split_text("abcdefghij", 6, 2)), ["abcdef", "efghij"])
        self.assertEqual(list(split_text("  ", 6, 2)), [])
        for size, overlap in ((0, 0), (6, -1), (6, 6)):
            with self.assertRaises(ValueError):
                list(split_text("abc", size, overlap))

    def test_vector_identity(self):
        """Preserve the existing SHA-256 and UUID5 vector ID formula."""
        path = Path("data/example.md")
        digest = hashlib.sha256(f"{path}:2:example".encode()).hexdigest()
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, digest))
        self.assertEqual(stable_vector_id(path, 2, "example"), expected)
        self.assertNotEqual(stable_vector_id(path, 3, "example"), expected)

    def test_source_loading(self):
        """Normalize JSON, retain malformed JSON, and skip unreadable files."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text('{"message": "hello"}')
            self.assertEqual(read_source(path), '{\n  "message": "hello"\n}')
            path.write_text("{broken")
            self.assertEqual(read_source(path), "{broken")
            with self.assertLogs("project2.common", level="WARNING"):
                self.assertEqual(read_text(Path(directory) / "missing"), "")
            (Path(directory) / "ignore.txt").write_text("ignored")
            self.assertEqual(list(iter_text_files([Path(directory)], {".json"})), [path])

    def test_keyword_normalization(self):
        """Keep token and excerpt normalization shared across callers."""
        self.assertEqual(tokenize("Hello, TEST_case foo-bar!"), ["hello", "test_case", "foo-bar"])
        self.assertEqual(compact_text(" a\n\t b "), "a b")
