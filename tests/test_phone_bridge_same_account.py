"""Same-account live pull must replace a fatter stale snapshot."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phone_bridge import same_broker_account


def test_same_account_id_key() -> None:
    prior = {"account_id_key": "KEY8804", "display_label": "Individual Brokerage · CASH · #8804"}
    assert same_broker_account("KEY8804", "Individual Brokerage · CASH · #8804", prior)


def test_same_preferred_tail_8804() -> None:
    prior = {"account_id_key": "old", "display_label": "Individual Brokerage | CASH | #8804"}
    assert same_broker_account("newkey", "Individual Brokerage · CASH · #8804", prior)


def test_different_account_6854_not_same() -> None:
    prior = {"account_id_key": "KEY8804", "display_label": "Individual Brokerage · CASH · #8804"}
    assert not same_broker_account("KEY6854", "Individual Brokerage · CASH · #6854", prior)


def test_empty_prior_is_same() -> None:
    assert same_broker_account("KEY8804", "Individual Brokerage · CASH · #8804", {})
