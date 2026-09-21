import datetime as dt

import pytest

from botkit.jobspec import GoogleSheetSource, HttpJsonSource, RssSource
from botkit.sources.google_sheet import apply_filters, build_url, parse_csv
from botkit.sources.http_json import normalize
from botkit.sources.rss import filter_recent, parse_feed

CSV = """접수일시,고객명,문의내용,답변초안
2026-09-21,김민수,배송이 언제 오나요,
2026-09-21,이서연,반품하고 싶어요,처리완료
,,,
"""


def test_parse_csv_adds_sheet_row_number():
    rows = parse_csv(CSV)
    assert rows[0]["_row"] == 2
    assert rows[0]["고객명"] == "김민수"


def test_where_empty_keeps_only_unanswered_rows():
    source = GoogleSheetSource(type="google_sheet", sheet_id="x", where_empty=["답변초안"])
    rows = apply_filters(parse_csv(CSV), source)
    assert [r["고객명"] for r in rows] == ["김민수"]


def test_blank_trailing_rows_are_dropped():
    source = GoogleSheetSource(type="google_sheet", sheet_id="x")
    rows = apply_filters(parse_csv(CSV), source)
    assert len(rows) == 2


def test_where_equals_filters_by_value():
    source = GoogleSheetSource(
        type="google_sheet", sheet_id="x", where_equals={"답변초안": "처리완료"}
    )
    rows = apply_filters(parse_csv(CSV), source)
    assert [r["고객명"] for r in rows] == ["이서연"]


def test_limit_applies_after_filtering():
    source = GoogleSheetSource(type="google_sheet", sheet_id="x", limit=1)
    assert len(apply_filters(parse_csv(CSV), source)) == 1


def test_build_url_prefers_gid_and_encodes_sheet_name():
    assert "gid=123" in build_url(
        GoogleSheetSource(type="google_sheet", sheet_id="s", gid="123", sheet_name="문의접수")
    )
    assert "sheet=%EB%AC%B8%EC%9D%98%EC%A0%91%EC%88%98" in build_url(
        GoogleSheetSource(type="google_sheet", sheet_id="s", sheet_name="문의접수")
    )


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>신제품 출시</title>
    <link>https://news.example/1</link>
    <pubDate>Mon, 21 Sep 2026 09:00:00 +0900</pubDate>
    <description>&lt;p&gt;본문 &lt;b&gt;강조&lt;/b&gt;&lt;/p&gt;</description>
  </item>
</channel></rss>
"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>경쟁사 리뷰</title>
    <link href="https://blog.example/2"/>
    <published>2026-09-21T00:00:00Z</published>
    <summary>요약 본문</summary>
  </entry>
</feed>
"""


def test_parse_rss_strips_html_from_description():
    entries = parse_feed(RSS, summary_chars=100)
    assert entries[0]["title"] == "신제품 출시"
    assert entries[0]["summary"] == "본문 강조"


def test_parse_atom_reads_link_href():
    entries = parse_feed(ATOM, summary_chars=100)
    assert entries[0]["link"] == "https://blog.example/2"


def test_summary_is_truncated_to_configured_length():
    entries = parse_feed(RSS, summary_chars=2)
    assert entries[0]["summary"] == "본문"


def test_filter_recent_drops_old_entries_but_keeps_undated():
    now = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)
    entries = [
        {"title": "old", "published": "Mon, 01 Sep 2026 09:00:00 +0900"},
        {"title": "new", "published": "Mon, 21 Sep 2026 09:00:00 +0900"},
        {"title": "no-date", "published": ""},
    ]
    kept = [e["title"] for e in filter_recent(entries, since_hours=24, now=now)]
    assert kept == ["new", "no-date"]


def test_since_hours_none_keeps_everything():
    entries = [{"title": "old", "published": "Mon, 01 Sep 2026 09:00:00 +0900"}]
    assert filter_recent(entries, since_hours=None) == entries


def test_http_json_digs_into_items_path_and_picks_fields():
    source = HttpJsonSource(
        type="http_json",
        url="https://x",
        items_path="data.items",
        fields=["product_name", "rank"],
    )
    rows = normalize(
        {"data": {"items": [{"product_name": "A", "rank": 3, "noise": "버릴 값"}]}}, source
    )
    assert rows == [{"product_name": "A", "rank": 3}]


def test_http_json_missing_path_names_the_key_that_failed():
    source = HttpJsonSource(type="http_json", url="https://x", items_path="data.items")
    with pytest.raises(RuntimeError, match="items"):
        normalize({"data": {}}, source)


def test_rss_source_requires_at_least_one_feed():
    with pytest.raises(ValueError):
        RssSource(type="rss", feeds=[])


def test_missing_filter_column_is_an_error_not_a_silent_pass():
    """없는 열을 where_empty에 적으면 전체 행이 통과해 중복 발송이 된다."""
    source = GoogleSheetSource(type="google_sheet", sheet_id="x", where_empty=["답변"])
    with pytest.raises(RuntimeError, match="답변초안"):
        apply_filters(parse_csv(CSV), source)


def test_missing_where_equals_column_is_an_error_not_a_silent_zero():
    source = GoogleSheetSource(type="google_sheet", sheet_id="x", where_equals={"상태": "완료"})
    with pytest.raises(RuntimeError, match="상태"):
        apply_filters(parse_csv(CSV), source)
