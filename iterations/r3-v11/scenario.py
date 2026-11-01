"""Versioned fictional teaching inputs, not market assumptions or a forecast."""
from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Scenario:
    """Reproducible authored example, separate from production assumptions."""
    version: str = 'r3-v11-teaching-2026-11-01-v1'
    effective_from: str = '2026-11-01'
    deposit_gbp: int = 140000
    investment_gbp: int = 0
    # Authored teaching bands, never current market product quotes.
    bands: tuple[tuple[D, D], ...] = ((D('.75'),D('.04')), (D('.85'),D('.05')), (D('.90'),D('.06')))
    reserve_gbp: D = D('10000')
    home_gbp: D = D('450000')
    savings_gbp: D = D('150000')
    smaller_deposit_gbp: int = 112500
    monthly_budget_gbp: D = D(2000)
    cash_return: D = D('0')
    annual_returns: tuple[D, ...] = (D('.08'),) * 30


SCENARIO = Scenario()
