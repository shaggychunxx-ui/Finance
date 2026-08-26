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
    assert card["holder_ticker"] == "MSFT"
    assert card["holders"][0]["ticker"] == "MSFT"
    assert "Software" in card["industry"] or "AI" in card["industry"]
    assert card["intended_use"]
    assert card["possible_uses"]
    assert card["market_impacts"]
    overlay = {t for row in card["market_impacts"] for t in row.get("tickers") or []}
    assert "QQQ" in overlay
    assert "MSFT" not in overlay


def test_holdings_include_brve_and_sofi() -> None:
    cards = holdings_landscape(["BRVE", "SOFI", "BRVE"])
    by_sym = {c["symbol"]: c for c in cards}
    assert by_sym["BRVE"]["company"] == "Braveheart Bio"
    assert by_sym["BRVE"]["holder_ticker"] == "BRVE"
    assert "HCM" in by_sym["BRVE"]["intended_use"] or "myosin" in by_sym["BRVE"]["intended_use"]
    assert by_sym["SOFI"]["company"] == "SoFi Technologies"
    assert by_sym["SOFI"]["holder_ticker"] == "SOFI"
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
    held = [c for c in result["landscape"] if c.get("holder_ticker") in {"BRVE", "SOFI"}]
    assert held, "landscape should look at companies that hold the live-book patents"
    findings = result["findings"]
    assert findings[0].get("intended_use")


def test_holder_tickers_are_in_patents_domain() -> None:
    from agent_fusion import agent_in_domain

    assert agent_in_domain("patents", "BRVE", sector_hint="biotech")
    assert agent_in_domain("patents", "SOFI", sector_hint="fintech")
    assert agent_in_domain("patents", "MSFT", sector_hint="software")


def test_patents_live_extract_does_not_queue_labels() -> None:
    from prediction_accuracy import _extract_from_agent_file

    pending: list = []
    data = {
        "market_signals": [
            {"bias": "BULLISH", "tickers": ["QQQ", "BRVE"], "sector": "Innovation"},
        ],
        "predictions": {
            "1wk": [
                {
                    "symbol": "BRVE",
                    "predicted_direction": "up",
                    "predicted_return_pct": 1.6,
                    "confidence": 0.48,
                }
            ],
            "1yr": [
                {
                    "symbol": "SOFI",
                    "predicted_direction": "up",
                    "predicted_return_pct": 14.0,
                    "confidence": 0.46,
                }
            ],
        },
        "landscape": [
            {"holder_ticker": "BRVE", "company": "Braveheart Bio", "source": "held-lot landscape"},
        ],
    }
    _extract_from_agent_file(
        "patents",
        data,
        cycle_id="test",
        recorded_at="2026-08-26T00:00:00+00:00",
        quotes={"QQQ": 400.0, "BRVE": 27.0, "SOFI": 19.0},
        pending=pending,
    )
    assert pending == []


def test_landscape_stamps_short_and_long_windows_not_predictions() -> None:
    from agents.patents.expert import PatentLandscapeAnalyst

    result = PatentLandscapeAnalyst().run(output=None)
    assert not result.get("predictions")
    cards = result.get("landscape") or []
    assert cards
    held = [c for c in cards if c.get("holder_ticker") in {"BRVE", "SOFI"}]
    assert held
    for c in held:
        terms = c.get("impact_terms") or []
        assert "short" in terms and "long" in terms
        windows = c.get("impact_windows") or {}
        assert windows.get("short") == ["24h", "1wk"]
        assert windows.get("long") == ["1mo", "1yr"]
