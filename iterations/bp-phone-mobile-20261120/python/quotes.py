"""Bounded synthetic quote evidence for the isolated design provider only."""
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal as D


@dataclass(frozen=True)
class Quote:
    """GBP amounts, annual decimal rates, months and inclusive supplied bounds."""
    id: str = ''
    name: str = ''
    rate: D | None = None
    fixed_months: int | None = None
    fee: D | None = None
    fee_mode: str = 'upfront'
    price: D | None = None
    deposit: D | None = None
    term_years: int | None = None
    scope: str = 'exact'
    min_ltv: D | None = None
    max_ltv: D | None = None
    min_loan: D | None = None
    max_loan: D | None = None
    min_term: int | None = None
    max_term: int | None = None
    obtained: str = ''
    expires: str = ''
    allowance: D | None = None
    charges: str = ''


def parse_quote(raw: dict) -> Quote:
    """Preserve missing conditions as unknown, rejecting malformed supplied values."""
    if not isinstance(raw, dict): raise ValueError('Each quote must be an object.')
    decimals = {'rate','fee','price','deposit','min_ltv','max_ltv','min_loan','max_loan','allowance'}
    integers = {'fixed_months','term_years','min_term','max_term'}
    values = {}
    for f in fields(Quote):
        v = raw.get(f.name, f.default)
        if f.name in decimals | integers:
            if v in ('',None): v = None
            else:
                v = D(str(v))
                if not v.is_finite() or len(v.as_tuple().digits)>16 or v<0: raise ValueError('Quote values must be finite and non-negative.')
                limit = D('.25') if f.name=='rate' else D(1) if f.name in {'min_ltv','max_ltv','allowance'} else D('10000000')
                if v>limit: raise ValueError('Quote value exceeds this prototype’s supported range.')
                if f.name in integers:
                    if v!=v.to_integral_value(): raise ValueError('Quote durations must be whole numbers.')
                    v=int(v)
                elif f.name in {'fee','price','deposit','min_loan','max_loan'} and v!=v.quantize(D('.01')): raise ValueError('Quote money uses pounds and pence.')
        else:
            v=str(v or '')
            if len(v)>160: raise ValueError('Keep quote references and notes under 160 characters.')
        values[f.name]=v
    q=Quote(**values)
    if not q.id or q.scope not in ('exact','range') or q.fee_mode not in ('upfront','loan'): raise ValueError('Choose a quote identity, applicability and fee treatment.')
    for v in (q.obtained,q.expires):
        if v: date.fromisoformat(v)
    if q.obtained and q.expires and q.expires<q.obtained: raise ValueError('Expiry cannot precede the date obtained.')
    if q.fixed_months is not None and not 1<=q.fixed_months<=120: raise ValueError('Initial fixed deal: 1–120 months.')
    for a,b in ((q.min_ltv,q.max_ltv),(q.min_loan,q.max_loan),(q.min_term,q.max_term)):
        if a is not None and b is not None and a>b: raise ValueError('Quote minimum cannot exceed maximum.')
    return q


def coverage(q: Quote | None, price: D, deposit: D, term_years: int, as_of: str) -> tuple[str,str]:
    """Classify evidence independently of funding or lender approval."""
    if q is None: return 'missing','Add or select a quote for this deposit and term.'
    if any(v is None for v in (q.rate,q.fixed_months,q.fee,q.price,q.deposit,q.term_years)) or not q.obtained:
        return 'incomplete','Complete the quote’s rate, fee, fixed duration, quoted case and date.'
    if q.obtained>as_of: return 'stale','The quote date is after the comparison date.'
    if q.expires and q.expires<as_of: return 'stale','Quote expired. Obtain an updated quote or choose assumed rates.'
    if q.scope=='exact':
        if (price,deposit,term_years)!=(q.price,q.deposit,q.term_years): return 'missing','This quote covers only its exact house price, deposit and term.'
    else:
        bounds=(q.min_ltv,q.max_ltv,q.min_loan,q.max_loan,q.min_term,q.max_term)
        if any(v is None for v in bounds): return 'incomplete','Supply the product’s LTV, loan and term bounds, or use exact quoted case only.'
        loan=price-deposit
        financed=loan+(q.fee if q.fee_mode=='loan' else 0)
        if not (q.min_ltv<=financed/price<=q.max_ltv and q.min_loan<=financed<=q.max_loan and q.min_term<=term_years<=q.max_term):
            return 'missing','No coverage for this deposit and term. Add a quote or choose assumed rates.'
    if q.fixed_months>term_years*12: return 'incomplete','The initial fixed deal exceeds the repayment term.'
    return 'supplied','Supplied synthetic quote; lender approval and verification are not assessed.'
