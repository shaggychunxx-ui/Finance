"""Unit tests for the DCA sleeve (no network, no orders)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ET = ZoneInfo("America/New_York")


class DcaEngineTests(unittest.TestCase):
    def test_period_key_weekly_and_monthly(self) -> None:
        from dca_engine import period_key

        friday = datetime(2026, 8, 21, 11, 0, tzinfo=ET)
        self.assertEqual(period_key({"cadence": "weekly"}, now=friday), "2026-W34")
        self.assertEqual(period_key({"cadence": "monthly"}, now=friday), "2026-08")

    def test_is_period_due_respects_weekday_and_clock(self) -> None:
        from dca_engine import is_period_due

        settings = {
            "cadence": "weekly",
            "weekday": "Friday",
            "execute_after_et": "10:30",
            "month_day": 1,
        }
        too_early = datetime(2026, 8, 21, 9, 0, tzinfo=ET)
        friday = datetime(2026, 8, 21, 11, 0, tzinfo=ET)
        thursday = datetime(2026, 8, 20, 11, 0, tzinfo=ET)
        saturday = datetime(2026, 8, 22, 11, 0, tzinfo=ET)
        self.assertFalse(is_period_due(settings, now=too_early))
        self.assertFalse(is_period_due(settings, now=thursday))
        self.assertFalse(is_period_due(settings, now=saturday))
        self.assertTrue(is_period_due(settings, now=friday))

    def test_planned_lots_whole_shares_and_leftover(self) -> None:
        from dca_engine import planned_lots

        settings = {
            "enabled": True,
            "amount_usd": 100.0,
            "min_trade_usd": 10.0,
            "vix_overlay": "off",
            "universe": [
                {"symbol": "VTI", "weight_pct": 70.0, "name": "US"},
                {"symbol": "VXUS", "weight_pct": 20.0, "name": "Intl"},
                {"symbol": "BND", "weight_pct": 10.0, "name": "Bonds"},
            ],
        }
        prices = {"VTI": 280.0, "VXUS": 65.0, "BND": 73.0}
        lots = planned_lots(settings, prices=prices)
        by_sym = {row["symbol"]: row for row in lots}
        self.assertEqual(by_sym["VTI"]["shares"], 0)
        self.assertEqual(by_sym["VXUS"]["shares"], 0)
        self.assertEqual(by_sym["BND"]["shares"], 0)
        self.assertEqual(by_sym["VTI"]["leftover_usd"], 70.0)

        fat = dict(settings)
        fat["amount_usd"] = 1000.0
        lots2 = planned_lots(fat, prices=prices)
        by2 = {row["symbol"]: row for row in lots2}
        self.assertEqual(by2["VTI"]["shares"], 2)
        self.assertEqual(by2["VXUS"]["shares"], 3)
        self.assertGreaterEqual(by2["BND"]["shares"], 1)

    def test_reserved_cash_only_when_enabled_and_due(self) -> None:
        import dca_engine as de

        td = Path(tempfile.mkdtemp())
        old = de.STATE_FILE
        de.STATE_FILE = td / "dca_state.json"
        try:
            friday = datetime(2026, 8, 21, 11, 0, tzinfo=ET)
            settings = {
                "enabled": False,
                "amount_usd": 150.0,
                "cadence": "weekly",
                "weekday": "Friday",
                "execute_after_et": "10:30",
                "use_score": False,
            }
            self.assertEqual(de.reserved_cash_usd(settings, now=friday), 0.0)
            settings["enabled"] = True
            self.assertEqual(de.reserved_cash_usd(settings, now=friday), 150.0)
            de.save_dca_state({"filled_periods": ["2026-W34"], "lots": [], "protected": {}})
            self.assertEqual(de.reserved_cash_usd(settings, now=friday), 0.0)
        finally:
            de.STATE_FILE = old

    def test_record_fills_protects_qty(self) -> None:
        import dca_engine as de
        from strategy_engine import TradeOrder

        td = Path(tempfile.mkdtemp())
        old = de.STATE_FILE
        de.STATE_FILE = td / "dca_state.json"
        try:
            order = TradeOrder(
                symbol="VTI",
                action="BUY",
                quantity=2,
                target_weight_pct=70.0,
                current_weight_pct=0.0,
                target_value_usd=560.0,
                current_value_usd=0.0,
                estimated_price=280.0,
                status="placed",
            )
            de.record_fills(
                [order],
                period="2026-W34",
                now=datetime(2026, 8, 21, 11, 0, tzinfo=ET),
            )
            self.assertTrue(de.already_filled("2026-W34"))
            self.assertEqual(de.protected_quantities()["VTI"], 2)
        finally:
            de.STATE_FILE = old

    def test_disabled_plan_has_no_orders(self) -> None:
        import dca_engine as de

        td = Path(tempfile.mkdtemp())
        old = de.PLAN_FILE
        de.PLAN_FILE = td / "dca_plan.json"
        try:
            plan = de.build_dca_plan(
                None,
                "acct",
                "test",
                settings={
                    "enabled": False,
                    "amount_usd": 1000.0,
                    "cadence": "weekly",
                    "weekday": "Friday",
                    "execute_after_et": "10:30",
                    "universe": [{"symbol": "VTI", "weight_pct": 100.0, "name": "US"}],
                },
                now=datetime(2026, 8, 21, 11, 0, tzinfo=ET),
            )
            self.assertEqual(plan.orders, [])
            self.assertIn("enabled is false", str(plan.meta.get("skip_reason") or ""))
        finally:
            de.PLAN_FILE = old

    def test_agent_runner_writes_knowledge(self) -> None:
        from agents.dca_strategy import run_dca_strategy_analysis

        td = Path(tempfile.mkdtemp())
        out = td / "dca_strategy.json"
        result = run_dca_strategy_analysis(output=out)
        self.assertEqual(result["meta"]["agent_id"], "dca-strategy")
        self.assertIn("definition", result["knowledge"])
        self.assertTrue(out.exists())
        self.assertTrue((td / "dca_methodology.json").exists())
        body = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(body["meta"]["pipeline_lane"], "research")

    def test_pipeline_wiring(self) -> None:
        from agent_groups import AGENT_GROUPS, AGENT_TO_GROUP
        from agent_pipelines import RESEARCH_AGENTS, pipeline_id_for_agent
        from main import RUNNERS

        self.assertIn("dca-strategy", RUNNERS)
        self.assertIn("dca-strategy", RESEARCH_AGENTS)
        self.assertEqual(pipeline_id_for_agent("dca-strategy"), "research")
        self.assertEqual(AGENT_TO_GROUP["dca-strategy"], "dca_invest")
        self.assertFalse(AGENT_GROUPS["dca_invest"]["directional"])
        scoring = AGENT_GROUPS["dca_invest"]["scoring"]
        metric_ids = {m["id"] for m in scoring["metrics"]}
        self.assertIn("use_decision", metric_ids)

    def test_use_score_skip_half_full_lean(self) -> None:
        from dca_engine import score_dca_use

        settings = {
            "amount_usd": 100.0,
            "skip_if_cash_below_usd": 200.0,
            "use_score": True,
            "min_score_half": 40.0,
            "min_score_full": 60.0,
            "min_score_lean": 85.0,
            "lean_multiplier": 1.5,
        }
        skip = score_dca_use(
            settings,
            cash=50.0,
            vix=11.0,
            spy_day_chg_pct=2.5,
            risk_on_score=0.90,
            breadth_score=0.80,
            posture="risk-on",
        )
        self.assertEqual(skip["action"], "skip")
        self.assertEqual(skip["multiplier"], 0.0)
        self.assertLess(skip["score"], 40.0)

        half = score_dca_use(
            settings,
            cash=250.0,
            vix=13.0,
            spy_day_chg_pct=1.2,
            risk_on_score=0.70,
            breadth_score=0.70,
            posture="risk-on",
        )
        self.assertEqual(half["action"], "half")
        self.assertEqual(half["multiplier"], 0.5)

        full = score_dca_use(
            settings,
            cash=600.0,
            vix=19.0,
            spy_day_chg_pct=-0.4,
            risk_on_score=0.50,
            breadth_score=0.50,
            posture="neutral",
        )
        self.assertEqual(full["action"], "full")
        self.assertEqual(full["multiplier"], 1.0)
        self.assertGreaterEqual(full["score"], 60.0)

        lean = score_dca_use(
            settings,
            cash=8000.0,
            vix=32.0,
            spy_day_chg_pct=-2.5,
            risk_on_score=0.20,
            breadth_score=0.30,
            posture="risk-off",
        )
        self.assertEqual(lean["action"], "lean")
        self.assertEqual(lean["multiplier"], 1.5)
        self.assertGreaterEqual(lean["score"], 85.0)

    def test_score_skip_plan_has_no_orders(self) -> None:
        import dca_engine as de
        from unittest.mock import patch

        td = Path(tempfile.mkdtemp())
        old_plan = de.PLAN_FILE
        old_score = de.SCORE_FILE
        old_state = de.STATE_FILE
        de.PLAN_FILE = td / "dca_plan.json"
        de.SCORE_FILE = td / "dca_use_score.json"
        de.STATE_FILE = td / "dca_state.json"
        skip = {
            "score": 22.0,
            "action": "skip",
            "multiplier": 0.0,
            "thresholds": {"min_score_half": 40.0},
            "note": "use_score=22 action=skip x0",
        }
        try:
            with patch.object(de, "score_dca_use", return_value=skip):
                plan = de.build_dca_plan(
                    None,
                    "acct",
                    "test",
                    settings={
                        "enabled": True,
                        "amount_usd": 1000.0,
                        "cadence": "weekly",
                        "weekday": "Friday",
                        "execute_after_et": "10:30",
                        "skip_if_cash_below_usd": 0.0,
                        "use_score": True,
                        "universe": [{"symbol": "VTI", "weight_pct": 100.0, "name": "US"}],
                    },
                    now=datetime(2026, 8, 21, 11, 0, tzinfo=ET),
                )
            self.assertEqual(plan.orders, [])
            self.assertIn("use_score 22", str(plan.meta.get("skip_reason") or ""))
        finally:
            de.PLAN_FILE = old_plan
            de.SCORE_FILE = old_score
            de.STATE_FILE = old_state

    def test_leftover_rolls_into_next_budget(self) -> None:
        import dca_engine as de
        from strategy_engine import StrategyPlan

        td = Path(tempfile.mkdtemp())
        old_state = de.STATE_FILE
        de.STATE_FILE = td / "dca_state.json"
        try:
            plan = StrategyPlan(
                generated_at="2026-08-21T15:00:00Z",
                account_id_key="acct",
                account_name="t",
                sandbox=True,
                total_account_value=0.0,
                investable_usd=100.0,
                cash_buffer_pct=0.0,
                regime={},
                target_holdings=[],
                current_positions=[],
                orders=[],
                meta={
                    "period_key": "2026-W34",
                    "lots": [
                        {"symbol": "VTI", "leftover_usd": 70.0},
                        {"symbol": "VXUS", "leftover_usd": 20.0},
                        {"symbol": "BND", "leftover_usd": 10.0},
                    ],
                },
            )
            de.settle_dca_period(plan)
            self.assertEqual(de.leftover_usd(), 100.0)
            self.assertTrue(de.already_filled("2026-W34"))
        finally:
            de.STATE_FILE = old_state


if __name__ == "__main__":
    unittest.main()
