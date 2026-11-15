"""Versioned owner-approved comparison requests, never inferred lender offers."""
from decimal import Decimal as D, ROUND_CEILING
from typing import Any

VERSION = 'example-boundary-request-v1'
EFFECTIVE = '2026-11-15'


def comparison_request(inputs: Any, deposit: D, term_years: int, request: dict) -> dict:
    """Suggest an affordable-in-resources GBP case; payment funding is unknown.

    The caller supplies the model's fixed Decimal context. New product fees are
    unknown, so loan is principal before a new fee, and no payment is projected.
    """
    from model import money, PENNY, ZERO
    low=max(inputs.lisa+inputs.gift,ZERO)
    high=min(inputs.price,inputs.total-inputs.reserve-inputs.costs)
    edges=sorted({(inputs.price*(1-band)).quantize(PENNY,rounding=ROUND_CEILING) for band,_ in inputs.bands})
    suggested=next((edge for edge in edges if deposit<edge and low<=edge<=high),None)
    raw=request.get('comparison_deposit')
    chosen=suggested if raw is None else D(str(raw))
    if chosen is not None and (not chosen.is_finite() or chosen!=chosen.quantize(PENNY) or not low<=chosen<=high):
        raise ValueError('Choose a penny deposit within available funds, preserving cash, costs and restricted sources.')
    fix=request.get('fixed_months')
    if fix not in (None,''):
        value=D(str(fix))
        if not value.is_finite() or value!=value.to_integral_value() or not 0<value<=term_years*12:
            raise ValueError('Enter a whole-month fixed period within the repayment term.')
        fix=int(value)
    else:fix=None
    return dict(status='ok',version=VERSION,effective=EFFECTIVE,suggested_deposit=money(suggested),
                deposit=money(chosen),loan=money(inputs.price-chosen) if chosen is not None else None,
                minimum_deposit=money(low),maximum_deposit=money(high),term_years=term_years,
                fixed_months=fix,affordability='unconfirmed',coverage='unconfirmed',
                is_example_boundary=chosen in edges if chosen is not None else False,
                loan_excludes_new_product_fee=True)
