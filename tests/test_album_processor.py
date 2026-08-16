#!/usr/bin/env python3
"""Unit tests für AlbumProcessor"""
import unittest
from services.downloader.utils.metadata.album_processor import AlbumProcessor

class TestAlbumProcessor(unittest.TestCase):
    def test_extract_year_from_string(self):
        processor = AlbumProcessor()
        self.assertEqual(processor.extract_year_from_string("2024"), 2024)
        self.assertEqual(processor.extract_year_from_string("24.05.2024"), 2024)
        self.assertIsNone(processor.extract_year_from_string("no year"))

if __name__ == '__main__':
    unittest.main()
