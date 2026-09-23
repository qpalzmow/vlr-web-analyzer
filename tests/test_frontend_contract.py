"""Check real markup as well as the lightweight JS harness' data behavior."""
from pathlib import Path
import re
from bs4 import BeautifulSoup

PUBLIC = Path(__file__).resolve().parents[1] / "public"


def test_frontend_bindings_have_unique_real_destinations():
    soup = BeautifulSoup((PUBLIC / "index.html").read_text(encoding="utf-8"), "html.parser")
    ids = [tag["id"] for tag in soup.select("[id]")]
    assert len(ids) == len(set(ids))
    for source in PUBLIC.glob("*.js"):
        for name in re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", source.read_text(encoding="utf-8")):
            assert name in ids, (source.name, name)
    for team in "ab":
        for field in ["nickname", "acs", "kd", "kd-ratio", "rounds", "coverage", "collected", "agents", "team", "note-team"]:
            assert f"ace-{team}-{field}" in ids
        for field in ["rate", "record", "map", "player", "sample"]:
            assert f"summary-{team}-{field}" in ids
    assert soup.select_one("#team-a-maps-table").name == "th"
    assert soup.select_one("#maps-comparison-body").name == "tbody"
    assert soup.select_one("#career-acs-chart").name == "table"
    assert soup.select_one("#acs-trend-chart").name == "tbody"


def test_navigation_labels_assets_and_disclosures_are_valid():
    soup = BeautifulSoup((PUBLIC / "index.html").read_text(encoding="utf-8"), "html.parser")
    for label in soup.select("label[for]"):
        assert soup.find(id=label["for"])
    for control in soup.select("select"):
        assert soup.select_one(f'label[for="{control["id"]}"]')
    for link in soup.select('a[href^="#"]'):
        assert soup.find(id=link["href"][1:])
    for tag in soup.select("script[src], link[rel=stylesheet]"):
        url = tag.get("src") or tag["href"]
        if not url.startswith("https://"):
            assert (PUBLIC / url.split("?")[0]).is_file()
    for name in ["advanced-filters", "tournament-explorer"]:
        assert not soup.find(id=name).has_attr("open")
    assert soup.select_one("#match-selection-panel").has_attr("open")
    assert soup.select_one("#analysis-status")["role"] == "status"
    assert not soup.select("canvas, [data-lucide]")


def test_new_stylesheet_is_served_without_old_theme_or_tiny_fonts(client):
    page = client.get("/").text
    assert "report.css?v=20260923.2" in page
    assert all(name not in page for name in ["ios-theme.css", "tailwind", "lucide", "chart.js", "theme-btn"])
    response = client.get("/report.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    sizes = re.findall(r"font-size:\s*(\d+)px", response.text)
    assert all(int(size) >= 12 for size in sizes)
    assert "backdrop-filter" not in response.text
    assert "gradient(" not in response.text
