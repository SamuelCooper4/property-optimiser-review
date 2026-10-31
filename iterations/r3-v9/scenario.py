"""Versioned fictional teaching inputs, not market assumptions or a forecast."""
from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Scenario:
    """Reproducible authored example, separate from production assumptions."""
    version: str = 'r3-v9-teaching-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    deposit_gbp: int = 60000
    investment_gbp: int = 35000
    # Authored teaching bands, never current market product quotes.
    bands: tuple[tuple[D, D], ...] = ((D('.80'),D('.04')),(D('.85'),D('.05')),
        (D('.90'),D('.065')))
    reserve_gbp: D = D('5000')
    budget_gbp: D = D('2400')
    cash_return: D = D('0')
    annual_returns: tuple[D, ...] = (D('.08'),) * 30


SCENARIO = Scenario()
