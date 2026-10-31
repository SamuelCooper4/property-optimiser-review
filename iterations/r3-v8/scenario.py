"""Versioned fictional teaching inputs, not market assumptions or a forecast."""
from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Scenario:
    """Identical annual-effective returns and dates apply to both deposits."""
    version: str = 'r3-v8-teaching-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    deposit_gbp: int = 60000
    investment_gbp: int = 100000
    # Authored teaching bands, never current market product quotes.
    bands: tuple[tuple[D, D], ...] = ((D('.60'),D('.0413')),(D('.85'),D('.05')),
        (D('.90'),D('0.061790644996156946405850111049975317622900123470775')))
    reserve_gbp: D = D('5000')
    budget_gbp: D = D('2200')
    cash_return: D = D('.02')
    annual_returns: tuple[D, ...] = (D('.08'),) * 19 + (D('-.12'),) + (D('.08'),) * 10


SCENARIO = Scenario()
