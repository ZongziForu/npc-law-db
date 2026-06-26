#!/usr/bin/env python3
"""Unit tests for scripts/region_classifier.py."""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import region_classifier as rc


class TestClassifyByAuthority(unittest.TestCase):
    def test_national(self):
        r = rc.classify_by_authority("国务院")
        self.assertEqual(r["province"], "全国")
        self.assertEqual(r["level"], "national")

    def test_municipality(self):
        r = rc.classify_by_authority("北京市人民代表大会常务委员会")
        self.assertEqual(r["province"], "北京市")
        self.assertEqual(r["level"], "provincial")
        self.assertTrue(r["is_municipality"])

    def test_autonomous_region_irregular(self):
        r = rc.classify_by_authority("宁夏回族自治区人大常务委员会")
        self.assertEqual(r["province"], "宁夏回族自治区")
        self.assertEqual(r["level"], "provincial")

    def test_city_without_province_name(self):
        r = rc.classify_by_authority("广州市人民代表大会常务委员会")
        self.assertEqual(r["province"], "广东省")
        self.assertEqual(r["city"], "广州市")
        self.assertEqual(r["level"], "city")

    def test_prefecture(self):
        r = rc.classify_by_authority("临夏回族自治州人大常务委员会")
        self.assertEqual(r["province"], "甘肃省")
        self.assertEqual(r["city"], "临夏回族自治州")
        self.assertEqual(r["level"], "city")

    def test_empty(self):
        r = rc.classify_by_authority("")
        self.assertIsNone(r["province"])
        self.assertEqual(r["level"], "unknown")


class TestClassifySearchResults(unittest.TestCase):
    def test_batch(self):
        items = [
            {"bbbs": "1", "title": "A", "authority": "北京市人民代表大会常务委员会"},
            {"bbbs": "2", "title": "B", "authority": "广州市人民代表大会常务委员会"},
        ]
        out = rc.classify_search_results(items)
        self.assertEqual(out[0]["classified_province"], "北京市")
        self.assertEqual(out[0]["classified_level"], "provincial")
        self.assertEqual(out[1]["classified_province"], "广东省")
        self.assertEqual(out[1]["classified_level"], "city")


class TestBuildExistenceMatrix(unittest.TestCase):
    def test_matrix(self):
        items = [
            {"bbbs": "1", "title": "Provincial", "classified_province": "广东省", "classified_city": "广东省", "classified_level": "provincial", "status_code": 3},
            {"bbbs": "2", "title": "City", "classified_province": "广东省", "classified_city": "深圳市", "classified_level": "city", "status_code": 3},
        ]
        matrix = rc.build_existence_matrix(items)
        guangdong = next((m for m in matrix if m["province"] == "广东省"), None)
        self.assertIsNotNone(guangdong)
        self.assertTrue(guangdong["has_provincial_regulation"])
        self.assertEqual(guangdong["city_count"], 1)
        self.assertIn("深圳市", guangdong["cities_with_regulation"])


class TestCLI(unittest.TestCase):
    def test_test_command(self):
        out = StringIO()
        with mock.patch("sys.stdout", new=out):
            sys.argv = ["region_classifier.py", "--test"]
            rc.main()
        self.assertIn("All tests passed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
