"""Versioned fictional teaching inputs, not market assumptions or a forecast."""
from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Scenario:
    """Identical annual-effective returns and dates apply to both deposits."""
    version: str = 'r3-v7-teaching-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    deposit_gbp: int = 60000
    investment_gbp: int = 100000
    # Authored market-informed schedule; source and interpolation in RESEARCH.md.
    bands: tuple[tuple[D, D], ...] = ((D('.60'),D('.051')),(D('.65'),D('.052')),
        (D('.70'),D('.053')),(D('.75'),D('.0543')),(D('.80'),D('.0547')),
        (D('.85'),D('.055')),(D('.90'),D('0.057462291930297756704304569051232431967669258788645')))
    reserve_gbp: D = D('5000')
    budget_gbp: D = D('2100')
    cash_return: D = D('.02')
    annual_returns: tuple[D, ...] = (D('.08'),) * 19 + (D('-.12'),) + (D('.08'),) * 10


SCENARIO = Scenario()
