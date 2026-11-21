"""First-home Lifetime ISA withdrawal assumed for the dated synthetic phone household."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phone_provider import PhoneInputs


@dataclass(frozen=True)
class FirstHomeWithdrawal:
    """Published first-home withdrawal terms used by this illustration."""

    version: str
    effective_from: str
    charge_free_limit: Decimal
    above_limit_charge_rate: Decimal
    source: str


FIRST_HOME = FirstHomeWithdrawal(
    'uk-lisa-first-home-2026-10-29', '2026-10-29', Decimal('450000'), Decimal('.20'),
    'https://www.gov.uk/guidance/conveyancers-first-time-residential-purchase-with-a-lifetime-isa',
)


def apply_lisa_policy(inputs: PhoneInputs) -> PhoneInputs:
    """Withdraw the declared LISA once for the purchase and ring-fence its net proceeds."""
    if inputs.lisa == 0 or inputs.price <= FIRST_HOME.charge_free_limit:
        return inputs
    charge = (inputs.lisa * FIRST_HOME.above_limit_charge_rate).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return replace(inputs, lisa=inputs.lisa-charge, total=inputs.total-charge, lisa_charge=charge)


def savings_report(inputs: PhoneInputs) -> dict:
    """Report gross balances, the charge and net GBP used by all comparison pages."""
    return dict(version=FIRST_HOME.version, effective_from=FIRST_HOME.effective_from, source=FIRST_HOME.source,
                charge_free_limit=FIRST_HOME.charge_free_limit, above_limit_charge_rate=FIRST_HOME.above_limit_charge_rate,
                above_limit=inputs.price > FIRST_HOME.charge_free_limit,
                gross_total=inputs.total+inputs.lisa_charge, available_total=inputs.total,
                lisa_entered=inputs.lisa+inputs.lisa_charge, lisa_available=inputs.lisa, lisa_charge=inputs.lisa_charge)
