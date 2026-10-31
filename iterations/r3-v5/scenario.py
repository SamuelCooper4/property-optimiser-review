"""Versioned fictional teaching inputs, not market assumptions or a forecast."""
from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Scenario:
    """Identical annual-effective returns and dates apply to both deposits."""
    version: str = 'r3-v5-teaching-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    deposit_gbp: int = 100000
    investment_gbp: int = 55000
    cash_return: D = D('.02')
    annual_returns: tuple[D, ...] = (D('.08'),) * 19 + (D('-.12'),) + (D('.08'),) * 10


SCENARIO = Scenario()
