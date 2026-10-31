"""Versioned fictional teaching inputs, not market assumptions or a forecast."""
from dataclasses import dataclass
from decimal import Decimal as D


@dataclass(frozen=True)
class Scenario:
    """Identical annual-effective returns and dates apply to both deposits."""
    version: str = 'r3-v6-teaching-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    deposit_gbp: int = 100000
    investment_gbp: int = 55000
    # Authored market-informed schedule; source and interpolation in RESEARCH.md.
    bands: tuple[tuple[D, D], ...] = ((D('.60'),D('.051')),(D('.65'),D('.052')),
        (D('.70'),D('.053')),(D('.75'),D('.0543')),(D('.80'),D('.0547')),
        (D('.85'),D('.055')),(D('.90'),D('.057')))
    cash_return: D = D('.02')
    annual_returns: tuple[D, ...] = (D('.08'),) * 19 + (D('-.12'),) + (D('.08'),) * 10


SCENARIO = Scenario()
