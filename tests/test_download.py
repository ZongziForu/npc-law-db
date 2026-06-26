#!/usr/bin/env python3
"""Unit tests for scripts/download.py."""

import json
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

# Allow importing scripts/ modules from the parent directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import download as dl


class TestArgumentParser(unittest.TestCase):
    def test_search_default(self):
        args = dl.build_parser().parse_args(["--search", "出租车"])
        self.assertEqual(args.search, "出租车")
        self.assertEqual(args.page, 1)
        self.assertEqual(args.size, 20)
        self.assertFalse(args.exact)
        self.assertFalse(args.urls_only)
        self.assertEqual(args.format, "docx")

    def test_search_exact_and_pagination(self):
        args = dl.build_parser().parse_args([
            "--search", "物业管理条例", "--exact", "--page", "3", "--size", "100", "--urls-only", "--format", "pdf"
        ])
        self.assertEqual(args.search, "物业管理条例")
        self.assertTrue(args.exact)
        self.assertEqual(args.page, 3)
        self.assertEqual(args.size, 100)
        self.assertTrue(args.urls_only)
        self.assertEqual(args.format, "pdf")

    def test_info(self):
        args = dl.build_parser().parse_args(["--info", "abc123"])
        self.assertEqual(args.info, "abc123")

    def test_download_with_output(self):
        args = dl.build_parser().parse_args(["--download", "abc123", "--format", "pdf", "out.pdf"])
        self.assertEqual(args.download, "abc123")
        self.assertEqual(args.format, "pdf")
        self.assertEqual(args.output, "out.pdf")

    def test_mutually_exclusive_modes(self):
        with self.assertRaises(SystemExit):
            dl.build_parser().parse_args(["--info", "a", "--search", "b"])


class TestSearchLawsPayload(unittest.TestCase):
    @mock.patch("download._request")
    def test_fuzzy_payload(self, mock_request):
        mock_request.return_value.json.return_value = {"code": 200, "rows": [], "total": 0}
        dl.search_laws("出租车", page=2, size=50)
        call = mock_request.call_args
        self.assertEqual(call.args[0], "POST")
        self.assertIn("law-search/search/list", call.args[1])
        payload = call.kwargs["json"]
        self.assertEqual(payload["searchContent"], "出租车")
        self.assertEqual(payload["pageNum"], 2)
        self.assertEqual(payload["pageSize"], 50)
        self.assertEqual(payload["searchType"], 2)
        self.assertEqual(payload["searchRange"], 1)

    @mock.patch("download._request")
    def test_exact_payload(self, mock_request):
        mock_request.return_value.json.return_value = {"code": 200, "rows": [], "total": 0}
        dl.search_laws("物业管理条例", search_type=1)
        payload = mock_request.call_args.kwargs["json"]
        self.assertEqual(payload["searchType"], 1)


class TestParseDetail(unittest.TestCase):
    def test_valid_detail(self):
        data = {
            "code": 200,
            "data": {
                "bbbs": "id1",
                "title": "Test Law",
                "flxz": "地方法规",
                "zdjgName": "广州市人民代表大会常务委员会",
                "gbrq": "2020-01-01",
                "sxrq": "2020-02-01",
                "sxx": 3,
                "ossFile": {
                    "ossWordPath": "prod/20200101/uuid.docx",
                    "ossPdfPath": "prod/20200101/uuid.pdf",
                },
            },
        }
        info = dl.parse_detail(data)
        self.assertEqual(info["title"], "Test Law")
        self.assertEqual(info["authority"], "广州市人民代表大会常务委员会")
        self.assertEqual(info["status_code"], 3)
        self.assertIn("prod/20200101/uuid.docx", info["word_url"])
        self.assertIn("prod/20200101/uuid.pdf", info["pdf_url"])

    def test_invalid_detail(self):
        self.assertEqual(dl.parse_detail({}), {})
        self.assertEqual(dl.parse_detail({"code": 500}), {})


class TestCollectSearchUrls(unittest.TestCase):
    @mock.patch("download.get_download_url")
    def test_collect_success_and_failure(self, mock_get_url):
        mock_get_url.side_effect = lambda bbbs, fmt: {
            "id1": "https://example.com/1.doc",
            "id2": RuntimeError("no url"),
        }.get(bbbs) or RuntimeError("no url")
        # Patch RuntimeError for id2 by making side_effect a function
        def side_effect(bbbs, fmt):
            if bbbs == "id1":
                return "https://example.com/1.doc"
            raise RuntimeError("no url")
        mock_get_url.side_effect = side_effect

        data = {
            "code": 200,
            "rows": [
                {"bbbs": "id1", "title": "Law 1", "flxz": "A", "zdjgName": "X", "gbrq": "2020", "sxrq": "2020", "sxx": 3},
                {"bbbs": "id2", "title": "Law 2", "flxz": "B", "zdjgName": "Y", "gbrq": "2020", "sxrq": "2020", "sxx": 3},
            ],
        }
        results = dl.collect_search_urls(data)
        self.assertEqual(results[0]["url"], "https://example.com/1.doc")
        self.assertIsNone(results[0]["error"])
        self.assertIsNone(results[1]["url"])
        self.assertIn("no url", results[1]["error"])


class TestPrintSearchResults(unittest.TestCase):
    def test_output(self):
        data = {
            "code": 200,
            "total": 1,
            "rows": [
                {"bbbs": "id1", "title": "Test <em>Law</em>", "flxz": "地方法规", "zdjgName": "广州市人大", "gbrq": "2020", "sxrq": "2020", "sxx": 3}
            ],
        }
        out = StringIO()
        with mock.patch("sys.stdout", new=out):
            dl.print_search_results(data)
        text = out.getvalue()
        self.assertIn("Total: 1 | Returned: 1", text)
        self.assertIn("id1", text)
        self.assertNotIn("<em>", text)


if __name__ == "__main__":
    unittest.main()
