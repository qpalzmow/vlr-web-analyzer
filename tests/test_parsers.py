import pytest
from app.scraper.parsers import (
    clean_text, safe_int, safe_float, parse_live_score
)

def test_clean_text():
    assert clean_text("  hello   world \n\t ") == "hello world"
    assert clean_text("") == ""
    assert clean_text(None) == ""

def test_safe_int():
    assert safe_int("123") == 123
    assert safe_int("Score: -45 pts") == -45
    assert safe_int(None, default=99) == 99
    assert safe_int("invalid") == 0

def test_safe_float():
    assert safe_float("12.34") == 12.34
    assert safe_float("ACS: 245.8") == 245.8
    assert safe_float(None, default=1.5) == 1.5
    assert safe_float("abc") == 0.0

def test_parse_live_score_html():
    sample_html = """
    <div class="match-header">
        <div class="match-header-vs-score" data-vlr-score="2:1">
            <span>2</span><span>:</span><span>1</span>
        </div>
        <div class="match-header">Final</div>
    </div>
    <div class="vm-stats-game">
        <div class="vm-stats-game-header">
            <div class="map"><span>Ascent</span></div>
            <div class="score">13</div>
            <div class="score">9</div>
        </div>
    </div>
    """
    res = parse_live_score(sample_html)
    assert res["series_score_a"] == "2"
    assert res["series_score_b"] == "1"
    assert res["status"] == "final"
    assert len(res["maps"]) == 1
    assert res["maps"][0]["map"] == "Ascent"
    assert res["maps"][0]["score_a"] == "13"
    assert res["maps"][0]["score_b"] == "9"

def test_parse_match_details_id():
    from app.scraper.parsers import parse_match_details
    sample_html = "<div><span class='wf-title-team'>DRX</span><span class='wf-title-team'>PRX</span></div>"
    res1 = parse_match_details(sample_html, "https://www.vlr.gg/12345/drx-vs-prx")
    assert res1["match_id"] == "12345"
    res2 = parse_match_details(sample_html, "https://www.vlr.gg/67890")
    assert res2["match_id"] == "67890"

def test_parse_tournament_and_stage():
    from app.scraper.parsers import parse_tournament_and_stage
    t, s, r = parse_tournament_and_stage("Week 1 Group Stage VCT 2026: Pacific Stage 2")
    assert t == "VCT 2026: Pacific Stage 2"
    assert "그룹 스테이지" in s
    assert r == "1주차"

    t2, s2, r2 = parse_tournament_and_stage("Upper Round 1 Play-Ins VCT 2026: EMEA Stage 2")
    assert t2 == "VCT 2026: EMEA Stage 2"
    assert "플레이인" in s2
    assert r2 == "상위 1R"

    t3, s3, r3 = parse_tournament_and_stage("Grand Final Playoffs VCT 2026: China Stage 2")
    assert t3 == "VCT 2026: China Stage 2"
    assert "플레이오프" in s3
    assert r3 == "결승전"
