"""Patent landscape cards: intended use, possible uses, company, industry, market."""

from __future__ import annotations

from agents.patents.landscape import holdings_landscape, research_finding


def test_research_finding_fills_use_company_industry_market() -> None:
    card = research_finding(
        title="Transformer-based multimodal model training with sparse attention",
        assignee="Microsoft Research",
        sector="artificial-intelligence",
    )
    assert card["company"] == "Microsoft"
    assert "Software" in card["industry"] or "AI" in card["industry"]
    assert card["intended_use"]
    assert card["possible_uses"]
    assert card["market_impacts"]
    tickers = {t for row in card["market_impacts"] for t in row.get("tickers") or []}
    assert "QQQ" in tickers


def test_holdings_include_brve_and_sofi() -> None:
    cards = holdings_landscape(["BRVE", "SOFI", "BRVE"])
    by_sym = {c["symbol"]: c for c in cards}
    assert by_sym["BRVE"]["company"] == "Braveheart Bio"
    assert "HCM" in by_sym["BRVE"]["intended_use"] or "myosin" in by_sym["BRVE"]["intended_use"]
    assert by_sym["SOFI"]["company"] == "SoFi Technologies"
    assert "XLV" in {t for row in by_sym["BRVE"]["market_impacts"] for t in row["tickers"]}
    assert "XLF" in {t for row in by_sym["SOFI"]["market_impacts"] for t in row["tickers"]}


def test_patents_agent_emits_landscape() -> None:
    from agents.patents.expert import PatentLandscapeAnalyst

    result = PatentLandscapeAnalyst().run(output=None)
    assert result["landscape"]
    first = result["landscape"][0]
    assert first.get("intended_use")
    assert first.get("industry")
    assert first.get("company")
    assert first.get("possible_uses")
    assert first.get("market_impacts")
    findings = result["findings"]
    assert findings[0].get("intended_use")
