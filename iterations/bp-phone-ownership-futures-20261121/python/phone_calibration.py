"""Phone-only calibration of the dated illustrative LTV curve. Rates are decimal fractions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal as D, ROUND_CEILING
from functools import lru_cache

import model as m
from quotes import MAX_QUOTE_RATE, Quote


@dataclass(frozen=True)
class Band:
    """One maximum-inclusive LTV band, with inclusive GBP deposit bounds."""

    max_ltv: D
    low: D
    high: D
    rate: D
    minimum_rate: D
    source_kind: str
    product: Quote | None = None
    capped: bool = False

    def report(self, market_fix: int) -> dict:
        """Describe calibration and product conditions for the phone editor and slider."""
        q = self.product
        return dict(max_ltv=self.max_ltv, low=self.low, high=self.high, rate=self.rate,
                    deposit_share=1-self.max_ltv, source_kind=self.source_kind,
                    source_label='your quote' if self.source_kind=='quote' else 'estimate',
                    fee=q.fee if q else m.ZERO, fee_mode=q.fee_mode if q else 'upfront',
                    fixed_months=q.fixed_months if q else market_fix, quote_id=q.id if q else None,
                    allowance=q.allowance if q else None, capped=self.capped)


def prepare_quotes(raw: dict) -> dict:
    """Normalise the selected entry method before the common field parser validates it."""
    quotes = []
    for q in raw.get('quotes', ()):
        if not isinstance(q, dict):
            raise ValueError('Each quote needs its own details.')
        mode = q.get('quote_input', 'deposit')
        if mode not in ('ltv','deposit') or q.get('scope','exact') != 'exact':
            raise ValueError('Choose a deposit or an LTV band for each quote.')
        if mode == 'ltv' and q.get('max_ltv') in (None,''):
            raise ValueError('Choose the LTV band for this quote.')
        quotes.append({**q, 'deposit':q.get('deposit') if mode=='deposit' else None,
                       'max_ltv':q.get('max_ltv') if mode=='ltv' else None,
                       'price':q.get('price') or raw['price'],
                       'term_years':q.get('term_years') or m.TERMS[-1],
                       'obtained':q.get('obtained') or raw['as_of']})
    return {**raw, 'quotes':quotes, 'pricing_mode':raw['pricing_mode'] if quotes else 'assumed'}


def quote_band(i: m.Inputs, q: Quote) -> D:
    """Resolve entry against its recorded home price, using the loan before fees."""
    if q.rate is None or q.fixed_months is None or q.fee is None:
        raise ValueError('Enter the rate, fixed period and product fee for each quote.')
    if q.obtained > i.as_of or (q.expires and q.expires < i.as_of):
        raise ValueError('Check the quote date and expiry against the comparison date.')
    if q.term_years not in m.TERMS:
        raise ValueError('Enter a quoted repayment term between 15 and 35 years.')
    limits = [ltv for ltv, _ in i.bands]
    if q.max_ltv is not None and q.max_ltv in limits:
        return q.max_ltv
    if q.deposit is not None and q.price and 0 <= q.deposit < q.price:
        for limit in limits:
            if q.price-q.deposit <= q.price*limit:
                return limit
    raise ValueError('Choose a listed LTV band or enter a deposit that fits one of those bands.')


@lru_cache(maxsize=256)
@m.fixed
def curve(i: m.Inputs) -> tuple[Band, ...]:
    """Calibrate by LTV distance and preserve actual quotes at their own thresholds."""
    market = dict(i.bands)
    anchors: dict[D, Quote] = {}
    if i.pricing_mode == 'quotes':
        chosen = getattr(i,'pinned_quote_id','') or i.quote_id
        for q in i.quotes:
            limit = quote_band(i,q)
            if limit not in anchors or anchors[limit].id != chosen:
                anchors[limit] = q
    high = i.price-m.PENNY
    bands = []
    for limit, average in i.bands:
        low = (i.price*(1-limit)).quantize(m.PENNY, rounding=ROUND_CEILING)
        product, rate, floor, capped = anchors.get(limit), average, m.ZERO, False
        kind = 'assumed'
        if product:
            kind, rate = 'quote', product.rate
        elif anchors:
            kind = 'estimate'
            left = max((a for a in anchors if a < limit), default=None)
            right = min((a for a in anchors if a > limit), default=None)
            nearest = min(anchors, key=lambda a:(abs(a-limit), a))
            product = anchors[nearest]
            shift = product.rate-market[nearest]
            if left is not None and right is not None:
                weight = (limit-left)/(right-left)
                shift = (anchors[left].rate-market[left])*(1-weight)+(anchors[right].rate-market[right])*weight
            lower = max((a for a in anchors if a < limit), key=lambda a:anchors[a].rate, default=None)
            upper = min((a for a in anchors if a > limit), key=lambda a:anchors[a].rate, default=None)
            floor = anchors[lower].rate if lower is not None else m.ZERO
            ceiling = anchors[upper].rate if upper is not None else MAX_QUOTE_RATE
            if floor > ceiling:
                raise ValueError(f'The {lower*100:g}% and {upper*100:g}% LTV quotes give conflicting '
                                 f'bounds for the {limit*100:g}% estimate. Check the rates or add that band’s quote.')
            rate = min(ceiling, max(floor, average+shift))
            capped = rate != average+shift
        bands.append(Band(limit,low,high,rate,floor,kind,product,capped))
        high = low-m.PENNY
    return tuple(reversed(bands))


def at_deposit(i: m.Inputs, deposit: D) -> Band | None:
    """Return the mortgage band covering this exact deposit penny."""
    return next((b for b in curve(i) if b.low<=deposit<=b.high), None)


@lru_cache(maxsize=512)
def projection_inputs(i: m.Inputs, band: Band | None) -> m.Inputs:
    """Give the existing monthly projection the rate, fee, allowance and fix for one band."""
    if band is None or band.product is None:
        return replace(i, pricing_mode='assumed',quotes=(),quote_id='') if i.pricing_mode=='quotes' else i
    q = band.product
    financed = q.fee if q.fee_mode=='loan' else m.ZERO
    # The existing projector checks financed loan bounds. Express the same deposit interval
    # in its units; the fee affects borrowing without changing the buyer's quoted LTV band.
    applied = replace(q, rate=band.rate, scope='range', price=i.price, deposit=band.low,
                      min_ltv=m.ZERO, max_ltv=1+financed/i.price,
                      min_loan=i.price+financed-band.high, max_loan=i.price+financed-band.low,
                      min_term=m.TERMS[0], max_term=m.TERMS[-1])
    return replace(i, pricing_mode='quotes', quotes=(applied,), quote_id=q.id,
                   continuation=i.continuation if i.deals else band.rate)
