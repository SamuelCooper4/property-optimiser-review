"""Private, illustrative dashboard arithmetic; no production engine imports.

Annuity and inclusive band conventions derive from the preserved R4-v4 lab.
Monthly allocation/search are local design aids, not accepted financial oracles.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from decimal import Decimal as D, Context, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, localcontext, InvalidOperation
from functools import lru_cache, wraps
from typing import Callable, Any
from datetime import date
from quotes import Quote, parse_quote, coverage

VERSION = 'bp-illustrative-v1.6-owner-clarification'
EFFECTIVE = '2026-11-15'
HORIZON_MONTHS = 420
OBJECTIVE_MONTHS = (60, 120, 360, 420)
DEFAULT_OBJECTIVE_MONTH = 120
POSITION_PRECISION = D('1E3')
GRID_INTERVALS = 24
PENNY = D('.01')
ZERO = D(0)
TERMS = tuple(range(15, 36))


def fixed(function: Callable) -> Callable:
    """Use a private 50-digit context, independent of the calling thread."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=50)):
            return function(*args, **kwargs)
    return wrapped


@dataclass(frozen=True)
class Inputs:
    """Synthetic resources in GBP and annual rates as decimal fractions."""
    price: D = D('350000')
    total: D = D('120000')
    reserve: D = D('15000')
    costs: D = D('10000')
    monthly: D = D('2200')
    lisa: D = ZERO
    gift: D = ZERO
    investment_return: D = D('.05')
    cash_return: D = D('.025')
    bands: tuple = ((D('.60'),D('.0375')),(D('.75'),D('.04')),(D('.80'),D('.043')),(D('.85'),D('.047')),(D('.90'),D('.052')),(D('.95'),D('.058')))
    allocation: tuple = (D(1), ZERO, ZERO, ZERO)
    cap: D = D('.10')
    fallback: str = 'investment'
    pricing_mode: str = 'assumed'
    quotes: tuple[Quote, ...] = ()
    quote_id: str = ''
    as_of: str = EFFECTIVE
    deals: tuple = ()
    continuation: D = D('.045')
    stress_month: int = 0
    loss: D = D('.35')
    recovery_months: int = 60
    recovery_return: D = D('.10')


@fixed
def repayment(principal: D, annual_rate: D, months: int) -> D:
    """Level nominal-rate monthly annuity, GBP/month (R4 convention)."""
    if not principal: return ZERO
    if not annual_rate: return principal / months
    rate = annual_rate / 12
    return principal * rate / (1-(1+rate)**(-months))


@fixed
def rate_for(i: Inputs, deposit: D, term_years: int = 35) -> D | None:
    """Return a covered supplied rate or an explicitly assumed inclusive-band rate."""
    if deposit == i.price: return ZERO
    if i.pricing_mode=='quotes':
        q=active_quote(i)
        return q.rate if coverage(q,i.price,deposit,term_years,i.as_of)[0]=='supplied' else None
    return next((r for b,r in i.bands if (i.price-deposit)/i.price <= b),None)


def active_quote(i: Inputs) -> Quote | None:
    """The explicitly selected product, never a silently substituted quote."""
    return next((q for q in i.quotes if q.id==i.quote_id),None) if i.pricing_mode=='quotes' else None


@lru_cache(maxsize=128)
@fixed
def factors(i: Inputs, offset: D = ZERO) -> tuple:
    """Shared monthly paths; only assets already present receive a month's return."""
    regular = (1+i.investment_return+offset)**(D(1)/12)
    recovery = (1+i.recovery_return+offset)**(D(1)/12)
    path=[]
    for month in range(1,HORIZON_MONTHS+1):
        f = recovery if i.stress_month and i.stress_month < month <= i.stress_month+i.recovery_months else regular
        if month == i.stress_month: f *= 1-i.loss
        path.append(f)
    return tuple(path), (1+i.cash_return)**(D(1)/12)


def renewals(i: Inputs) -> dict[int,D]:
    """Map first affected payment months to explicit common future rates."""
    elapsed=0; result={}
    q=active_quote(i)
    deals=(((q.fixed_months,None),)+i.deals[1:]) if q and q.fixed_months else i.deals
    for duration,rate in deals:
        if elapsed: result[elapsed+1]=rate
        elapsed+=duration
    if elapsed: result[elapsed+1]=i.continuation
    return result


def opening_issues(i: Inputs, deposit: D, term_years: int = 35) -> list[str]:
    """Explain expected input failures without an opaque arithmetic exception."""
    issues=[]
    if deposit==i.price and i.lisa: issues.append('Assumed eligible LISA funds require a mortgage in this prototype.')
    if deposit < i.lisa+i.gift: issues.append('Deposit-only funds must stay in the deposit.')
    if deposit > i.total-i.costs-i.reserve: issues.append('This deposit would use the protected cash or money needed for costs.')
    if deposit < 0 or deposit > i.price: issues.append('Deposit must be between zero and the house price.')
    if rate_for(i,deposit,term_years) is None:
        issues.append(coverage(active_quote(i),i.price,deposit,term_years,i.as_of)[1] if i.pricing_mode=='quotes' else 'No illustrative mortgage band covers this deposit.')
    return issues


@fixed
def display_ltv(i: Inputs, ltv: D) -> str:
    """Round a label to 0.01 percentage points without disguising a band edge."""
    shown=ltv.quantize(D('.0001'),rounding=ROUND_HALF_UP)
    prefix='>' if i.pricing_mode=='assumed' and any(shown==b and ltv>b for b,_ in i.bands) else ''
    return prefix+format((shown*100).normalize(),'f')+'%'


@fixed
def project(i: Inputs, deposit: D, term_years: int, offset: D = ZERO, detailed: bool = True, objective_month: int = HORIZON_MONTHS, through_month: int = HORIZON_MONTHS) -> dict:
    """Project month-end balances and each budget use through the common horizon."""
    issues=opening_issues(i,deposit,term_years)
    q=active_quote(i) if deposit<i.price else None
    coverage_status=coverage(q,i.price,deposit,term_years,i.as_of)[0] if i.pricing_mode=='quotes' and deposit<i.price else 'assumed' if deposit<i.price else 'cash'
    upfront=q.fee if q and q.fee is not None and q.fee_mode=='upfront' else ZERO
    financed=q.fee if q and q.fee is not None and q.fee_mode=='loan' else ZERO
    if deposit+upfront>i.total-i.costs-i.reserve: issues.append('The upfront product fee would use protected cash or exceed available money.')
    identity=f'{deposit}@{term_years}'
    if issues:return dict(id=identity,deposit=deposit,term=term_years,valid=False,issues=issues,rows=[],first_shortfall=None,coverage_status=coverage_status)
    debt=i.price-deposit+financed; opening_debt=debt; cash=i.reserve
    investment=i.total-i.costs-i.reserve-deposit-upfront
    rate=rate_for(i,deposit,term_years); payment=repayment(debt,rate,term_years*12)
    first_payment=payment; remaining_months=term_years*12
    path,cash_factor=factors(i,offset); changes=renewals(i)
    allowance=ZERO; interest_total=ZERO; spent_total=ZERO; additions=ZERO
    first_shortfall=None; payoff=0 if debt==0 else None
    ledger=[dict(source='Assumed eligible LISA',use='Deposit',amount=i.lisa),dict(source='Deposit-restricted gift',use='Deposit',amount=i.gift),dict(source='Unrestricted money',use='Costs',amount=i.costs),dict(source='Unrestricted money',use='Protected cash',amount=i.reserve),dict(source='Unrestricted money',use='Deposit',amount=deposit-i.lisa-i.gift),dict(source='Unrestricted money',use='Investments',amount=investment)]
    if upfront:ledger.append(dict(source='Unrestricted money',use='Upfront mortgage product fee',amount=upfront))
    row=dict(month=0,debt=debt,cash=cash,investment=investment,position=i.price+cash+investment-debt,equity=i.price-debt,payment=ZERO,required=first_payment,surplus=i.monthly-first_payment,overpay=ZERO,invest_add=ZERO,cash_add=ZERO,spend=ZERO,spent_total=ZERO,interest_total=ZERO,contributed=ZERO,fallback_add=ZERO,rate=rate)
    rows=[row] if detailed else []; objective_row=row
    for month in range(1,through_month+1):
        known_cap=q.allowance if q and month<=q.fixed_months else i.cap
        if (month-1)%12==0:allowance=debt*(known_cap if known_cap is not None else ZERO)
        if q and month==q.fixed_months+1:allowance=debt*i.cap
        if month in changes and debt:
            rate=changes[month]; payment=repayment(debt,rate,max(1,remaining_months-month+1))
        interest=debt*rate/12
        required=min(payment,debt+interest) if month<remaining_months else debt+interest
        if required>i.monthly and first_shortfall is None:
            first_shortfall=dict(month=month,amount=required-i.monthly)
        paid=min(required,i.monthly)
        debt=max(ZERO,debt+interest-paid)
        surplus=i.monthly-paid
        invest_add=surplus*i.allocation[0]; cash_add=surplus*i.allocation[1]
        proposed=surplus*i.allocation[2]
        # Residual assignment preserves the monthly resource even at fixed precision.
        spend=surplus-invest_add-cash_add-proposed
        overpay=min(proposed,allowance,debt) if known_cap is not None else ZERO
        fallback=proposed-overpay
        redirect_reason=''
        cash_fallback=bool(q) or i.fallback=='cash'
        if fallback:
            cause='Mortgage paid off' if debt==overpay else 'Allowance unknown' if known_cap is None else 'Allowance reached'
            redirect_reason=cause+(': retained in cash' if cash_fallback else ': redirected to investments')
        if cash_fallback:cash_add+=fallback
        else:invest_add+=fallback
        debt-=overpay; allowance-=overpay
        if debt==0 and payoff is None:payoff=month
        investment=investment*path[month-1]+invest_add
        cash=cash*cash_factor+cash_add
        interest_total+=interest; spent_total+=spend; additions+=invest_add
        row=dict(month=month,debt=debt,cash=cash,investment=investment,position=None if first_shortfall else i.price+cash+investment-debt,equity=i.price-debt,payment=paid,required=required,surplus=surplus,overpay=overpay,invest_add=invest_add,cash_add=cash_add,spend=spend,spent_total=spent_total,interest_total=interest_total,contributed=additions,fallback_add=fallback,requested_overpay=proposed,redirect_reason=redirect_reason,rate=rate)
        if detailed:rows.append(row)
        if month==objective_month:objective_row=row
    if not detailed:rows=[objective_row]
    return dict(id=identity,deposit=deposit,term=term_years,valid=first_shortfall is None,issues=issues,rows=rows,ledger=ledger,first_payment=first_payment,opening_investment=i.total-i.costs-i.reserve-deposit-upfront,opening_debt=opening_debt,rate=rate_for(i,deposit,term_years),ltv=opening_debt/i.price,ltv_label=display_ltv(i,opening_debt/i.price),coverage_status=coverage_status,quote_id=q.id if q else None,product_fee=upfront+financed,fee_mode=q.fee_mode if q else None,initial_months=q.fixed_months if q else None,payoff_month=payoff,first_shortfall=first_shortfall)


@lru_cache(maxsize=512)
@fixed
def regions(i: Inputs, term_years: int, *, penny_edges: bool = False) -> tuple:
    """Inclusive penny ranges per band, checking all future required payments.

Within a band, larger deposits reduce debt/payment; the surplus-only cap policy
never reverses this ordering. Direct projections verify cutoff pennies.
"""
    if i.pricing_mode=='quotes':return quote_regions(i,term_years)
    cap=min(i.price,i.total-i.costs-i.reserve)
    result=[]; previous=ZERO
    for bound,rate in i.bands:
        low=max(i.lisa+i.gift,i.price*(1-bound))
        boundary=i.price*(1-previous)
        # A phone price may place the next inclusive threshold between pennies.
        if penny_edges:boundary=boundary.quantize(PENNY,rounding=ROUND_CEILING)
        high=min(cap,boundary-PENNY)
        previous=bound
        low=low.quantize(PENNY,rounding=ROUND_CEILING); high=high.quantize(PENNY,rounding=ROUND_FLOOR)
        if high<low:continue
        if not i.allocation[2]:
            # A unit-principal mortgage gives every future scheduled payment.
            unit=replace(i,price=D(1),total=D(1),reserve=ZERO,costs=ZERO,lisa=ZERO,gift=ZERO,monthly=D('100000'),bands=((D(1),rate),),allocation=(D(1),ZERO,ZERO,ZERO))
            schedule=project(unit,ZERO,term_years)
            maximum=max(r['required'] for r in schedule['rows'][1:])
            if maximum:low=max(low,(i.price-i.monthly/maximum).quantize(PENNY,rounding=ROUND_CEILING))
            if low>high:continue
            if not project(i,low,term_years,detailed=False)['valid']:low+=PENNY
            if low>high:continue
        else:
            if not project(i,high,term_years,detailed=False)['valid']:continue
            if not project(i,low,term_years,detailed=False)['valid']:
                a=int(low*100); b=int(high*100)
                while a<b:
                    mid=(a+b)//2
                    if project(i,D(mid)/100,term_years,detailed=False)['valid']:b=mid
                    else:a=mid+1
                low=D(a)/100
        result.append((low,high,rate))
    if cap==i.price and i.lisa==0:result.append((i.price,i.price,ZERO))
    return tuple(sorted(result))


@fixed
def quote_bounds(i: Inputs, q: Quote, term_years: int) -> tuple[D,D] | None:
    """Explicit supplied coverage in deposit GBP, before household funding."""
    if q.scope=='exact':
        if q.deposit is None:return None
        return (q.deposit,q.deposit) if coverage(q,i.price,q.deposit,term_years,i.as_of)[0]=='supplied' else None
    if any(v is None for v in (q.fee,q.min_ltv,q.max_ltv,q.min_loan,q.max_loan,q.min_term,q.max_term)):return None
    financed=q.fee if q.fee_mode=='loan' else ZERO
    low=max(ZERO,i.price+financed-i.price*q.max_ltv,i.price+financed-q.max_loan).quantize(PENNY,rounding=ROUND_CEILING)
    high=min(i.price-PENNY,i.price+financed-i.price*q.min_ltv,i.price+financed-q.min_loan).quantize(PENNY,rounding=ROUND_FLOOR)
    if high<low or coverage(q,i.price,low,term_years,i.as_of)[0]!='supplied':return None
    return low,high


@fixed
def pricing_steps(i: Inputs, term_years: int) -> list[dict]:
    """Diagram geometry derived from actual selected coverage, not raw bounds."""
    q=active_quote(i)
    if q is None:return []
    bounds=quote_bounds(i,q,term_years)
    if bounds is None:return []
    low,high=bounds
    financed=q.fee if q.fee_mode=='loan' else ZERO
    return [dict(low_ltv=(i.price-high+financed)/i.price,high_ltv=(i.price-low+financed)/i.price,rate=q.rate)]


@fixed
def quote_regions(i: Inputs, term_years: int) -> tuple:
    """Selected product coverage intersected with full-horizon household funding."""
    q=active_quote(i)
    bounds=quote_bounds(i,q,term_years) if q else None
    if bounds is None:return ()
    upfront=q.fee if q.fee_mode=='upfront' else ZERO
    low=max(bounds[0],i.lisa+i.gift)
    high=min(bounds[1],i.total-i.costs-i.reserve-upfront)
    if high<low or not project(i,high,term_years,detailed=False)['valid']:return ()
    if not project(i,low,term_years,detailed=False)['valid']:
        a=int(low*100);b=int(high*100)
        while a<b:
            mid=(a+b)//2
            if project(i,D(mid)/100,term_years,detailed=False)['valid']:b=mid
            else:a=mid+1
        low=D(a)/100
    return ((low,high,q.rate),)


@fixed
def sample_deposits(low: D, high: D) -> tuple[D, ...]:
    """Disclosed finite sample, retaining endpoints and their adjacent pennies."""
    grid={low,high}
    grid.update((low+(high-low)*n/GRID_INTERVALS).quantize(PENNY,rounding=ROUND_HALF_UP) for n in range(GRID_INTERVALS+1))
    grid.update(d for d in (low+PENNY,high-PENNY) if low<=d<=high)
    return tuple(sorted(grid))


@lru_cache(maxsize=8)
@fixed
def evaluated(i: Inputs, terms: tuple = TERMS, objective_month: int = HORIZON_MONTHS) -> tuple:
    """Evaluate a disclosed finite deposit set, never interpolate across bands."""
    candidates=[]
    for term in terms:
        rr=regions(i,term)
        for low,high,_ in rr:
            for deposit in sample_deposits(low,high):
                p=project(i,deposit,term,detailed=False,objective_month=objective_month)
                if p['valid']:candidates.append((deposit,term,p['rows'][-1]['position']))
    return tuple(candidates)


@fixed
def search(i: Inputs, choice: tuple[D,int] | None = None, terms: tuple = TERMS, objective_month: int = HORIZON_MONTHS) -> dict:
    """Rank the disclosed finite sample at one date, funded through month 420."""
    validate_objective_month(objective_month)
    candidates=list(evaluated(i,terms,objective_month)); keep=project(i,*choice) if choice else None
    if keep and keep['valid']:candidates.append((*choice,keep['rows'][objective_month]['position']))
    if not candidates:return dict(best=None,keep=keep,count=0,ties=[],delta=None,choice_delta=None,objective_month=objective_month)
    maximum=max(c[2] for c in candidates)
    ties=list(dict.fromkeys((d,t) for d,t,v in candidates if v==maximum))
    best_choice=choice if choice in ties else min(ties,key=lambda x:(x[0],x[1]))
    best=project(i,*best_choice)
    if keep is None:keep=best
    return dict(best=best,keep=keep,count=len(candidates),ties=ties,delta=best['rows'][objective_month]['position']-keep['rows'][objective_month]['position'] if keep['valid'] else None,choice_delta=best['deposit']-keep['deposit'],term_delta=best['term']-keep['term'],objective_month=objective_month)


def validate_objective_month(month: int) -> None:
    """Keep the UI comparison dates separate from the month inspector."""
    if type(month) is not int or month not in OBJECTIVE_MONTHS:
        raise ValueError('Choose a comparison date of 5, 10, 30 or 35 years.')


def parse(raw: dict) -> Inputs:
    """Validate the bounded design inputs, retaining monetary strings exactly."""
    if not isinstance(raw,dict):raise ValueError('Inputs must be an object.')
    defaults=Inputs(); values={}
    for f in fields(defaults):
        v=raw.get(f.name,getattr(defaults,f.name))
        if f.name=='quotes':v=tuple(parse_quote(q) for q in v)
        elif f.name=='bands':v=tuple((D(str(a)),D(str(b))) for a,b in v)
        elif f.name=='allocation':v=tuple(D(str(a)) for a in v)
        elif f.name=='deals':
            if any(D(str(a))!=D(str(a)).to_integral_value() for a,_ in v):raise ValueError('Use whole months for deal durations.')
            v=tuple((int(a),None if b is None else D(str(b))) for a,b in v)
        elif f.name in ('stress_month','recovery_months'):
            if D(str(v))!=D(str(v)).to_integral_value():raise ValueError('Use whole months for scenario timing.')
            v=int(v)
        elif f.name not in ('fallback','pricing_mode','quote_id','as_of'):v=D(str(v))
        values[f.name]=v
    i=Inputs(**values)
    if i.pricing_mode not in ('quotes','assumed'):raise ValueError('Choose supplied quotes or assumed rates.')
    date.fromisoformat(i.as_of)
    if len(i.quotes)>12 or len({q.id for q in i.quotes})!=len(i.quotes):raise ValueError('Use up to 12 quotes with distinct references.')
    numbers=[getattr(i,f.name) for f in fields(i) if isinstance(getattr(i,f.name),D)]+list(i.allocation)+[v for row in i.bands for v in row]+[r for _,r in i.deals if r is not None]
    if any(not v.is_finite() or len(v.as_tuple().digits)>16 for v in numbers):raise ValueError('Enter finite numbers with at most 16 digits.')
    if not D('1000')<=i.price<=D('10000000'):raise ValueError('House price: £1,000–£10,000,000 for this prototype.')
    if any(not 0<=getattr(i,k)<=D('10000000') or getattr(i,k)!=getattr(i,k).quantize(PENNY) for k in ('price','monthly','total','reserve','costs','lisa','gift')):raise ValueError('Enter non-negative amounts in pounds and pence.')
    if not 0<=i.monthly<=D('100000'):raise ValueError('Monthly budget: £0–£100,000.')
    if i.total-i.lisa-i.gift<i.costs+i.reserve:raise ValueError('Unrestricted money cannot cover purchase costs and the protected reserve.')
    if i.lisa+i.gift>i.price:raise ValueError('Deposit-only funds exceed the house price.')
    if len(i.allocation)!=4 or any(v<0 for v in i.allocation) or sum(i.allocation)!=1:raise ValueError('Monthly shares must total 100%.')
    if not D('-.4')<=i.investment_return<=D('.3') or not 0<=i.cash_return<=D('.2'):raise ValueError('Prototype annual return range: investments −40%–30%; cash 0%–20%.')
    if not 0<=i.cap<=1 or i.fallback not in ('cash','investment'):raise ValueError('Choose a valid cap and fallback destination.')
    if not 1<=len(i.bands)<=8 or any(not 0<b<=1 or not 0<=r<=D('.25') for b,r in i.bands) or any(i.bands[n][0]>=i.bands[n+1][0] for n in range(len(i.bands)-1)):raise ValueError('Use ascending inclusive LTV bands and rates from 0% to 25%.')
    if i.deals and (len(i.deals)>12 or i.deals[0][1] is not None or any(d not in (24,60) and not (n==0 and active_quote(i) and d==active_quote(i).fixed_months) for n,(d,_) in enumerate(i.deals)) or any(r is None or not 0<=r<=D('.25') for _,r in i.deals[1:])):raise ValueError('Use 2- or 5-year deals; opening rate follows LTV and later rates must be 0%–25%.')
    if not 0<=i.continuation<=D('.25'):raise ValueError('Continuation rate must be 0%–25%.')
    if not 0<=i.stress_month<=420 or not 0<=i.loss<=D('.95') or not 0<=i.recovery_months<=240 or not D('-.4')<=i.recovery_return<=D('.3'):raise ValueError('Check the investment fall and recovery assumptions.')
    return i


def serial(value: Any) -> Any:
    """Serialize Decimal without binary arithmetic; money rounds only here."""
    if isinstance(value,Quote):return {f.name:serial(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,D):return format(value,'f')
    if isinstance(value,dict):return {k:serial(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [serial(v) for v in value]
    return value


@fixed
def money(value: D | None) -> str | None:
    """Round a monetary result to GBP pence at the presentation boundary."""
    return None if value is None else format(value.quantize(PENNY,rounding=ROUND_HALF_UP),'f')


@fixed
def position_money(value: D | None) -> str | None:
    """Approximate projected GBP at nearest thousand, without altering arithmetic."""
    return None if value is None else format(value.quantize(POSITION_PRECISION,rounding=ROUND_HALF_UP),'f')


@fixed
def comparison_display(selected: dict | None, reference: dict | None, objective_month: int) -> dict:
    """Round the raw delta independently; suppress distinctions hidden by display."""
    def position(plan: dict | None) -> D | None:
        return plan['rows'][objective_month]['position'] if plan and plan['valid'] else None
    raw_a=position(selected); raw_b=position(reference)
    a=position_money(raw_a); b=position_money(raw_b)
    difference=D(position_money(raw_a-raw_b)) if raw_a is not None and raw_b is not None else None
    if difference==0:difference=ZERO
    direction='unavailable' if difference is None else 'equal' if not difference or a==b else 'higher' if difference>0 else 'lower'
    return dict(objective_month=objective_month,objective_year=objective_month//12,
                selected_position=a,reference_position=b,difference=position_money(difference),
                direction=direction,precision_gbp='1000')


@fixed
def reference_differences(selected: dict | None, reference: dict | None) -> list:
    """Presentation deltas reconcile the displayed penny totals at each month."""
    if not selected or not reference:return []
    return [None if a['position'] is None or b['position'] is None else money(D(money(a['position']))-D(money(b['position']))) for a,b in zip(selected['rows'],reference['rows'])]


@fixed
def near_best(value: D, best: D) -> bool:
    """Descriptive 1%-of-absolute-best band, with a minimum one-penny width."""
    return best-value<=max(abs(best)*D('.01'),PENNY)


@lru_cache(maxsize=8)
@fixed
def curve_samples(i: Inputs, term_years: int) -> tuple:
    """Cache only directly evaluated monthly positions for this term's sample."""
    return tuple((low,high,rate,tuple((d,tuple(r['position'] for r in project(i,d,term_years)['rows'])) for d in sample_deposits(low,high))) for low,high,rate in regions(i,term_years))


@fixed
def deposit_curve(i: Inputs, term_years: int, month: int, selected_deposit: D, objective_month: int = HORIZON_MONTHS) -> dict:
    """A finite, fixed-term/date comparison, split at rate steps and funding gaps."""
    if term_years not in TERMS or type(month) is not int or not 0<=month<=HORIZON_MONTHS:raise ValueError('Choose a supported term and whole viewed month from 0 to 420.')
    selected=project(i,selected_deposit,term_years)
    segments=[]; all_points=[]; gaps=[]
    low_domain=max(i.lisa+i.gift,i.price*(1-i.bands[-1][0]) if i.pricing_mode=='assumed' else ZERO).quantize(PENNY,rounding=ROUND_CEILING)
    high_domain=min(i.price,i.total-i.costs-i.reserve).quantize(PENNY,rounding=ROUND_FLOOR)
    funded=regions(i,term_years)
    if i.pricing_mode=='assumed' and funded:low_domain=funded[0][0];high_domain=funded[-1][1]
    cursor=low_domain
    for low,high,rate,samples in curve_samples(i,term_years):
        if cursor<low:gaps.append(dict(low=money(cursor),high=money(low-PENNY),reason='Quote coverage is missing or required payments exceed the budget.'))
        points={d:path[month] for d,path in samples}
        if selected['valid'] and low<=selected_deposit<=high:points[selected_deposit]=selected['rows'][month]['position']
        rows=[dict(deposit=money(d),position=money(v),term_years=term_years,rate=serial(rate),_raw=v) for d,v in sorted(points.items())]
        segments.append(dict(low=money(low),high=money(high),rate=serial(rate),points=rows));all_points.extend(rows);cursor=high+PENNY
    if cursor<=high_domain:gaps.append(dict(low=money(cursor),high=money(high_domain),reason='Missing quote coverage or funding under this comparison.'))
    best=max(all_points,key=lambda p:(p['_raw'],p['deposit']==money(selected_deposit))) if all_points else None
    best_value=best['_raw'] if best else None
    for point in all_points:
        point['near_best']=near_best(point.pop('_raw'),best_value)
        point['difference']=money(D(point['position'])-D(best['position']))
    reason=' '.join(selected['issues']) or (f"Budget exceeded in month {selected['first_shortfall']['month']}." if selected['first_shortfall'] else '')
    return dict(status='ok',version=VERSION,context=serial((i.price,i.total,i.reserve,i.monthly)),term_years=term_years,month=month,objective_month=objective_month,objective_year=objective_month//12,segments=segments,gaps=gaps,best=best,sample_count=len(all_points),domain=[money(low_domain),money(max(low_domain,high_domain))],near_best_floor=money(best_value-max(abs(best_value)*D('.01'),PENNY)) if best else None,selected=dict(deposit=money(selected_deposit),position=money(selected['rows'][month]['position']) if selected['valid'] else None,valid=selected['valid'],reason=reason))


def plan_budget(row: dict) -> D:
    """Recover the exact conserved monthly budget from provider flows."""
    return row['payment']+row['surplus']


@fixed
def present(plan: dict | None) -> dict | None:
    """Return display-rounded money and unrounded rates/identities for one plan."""
    if plan is None:return None
    raw=serial(plan)
    if 'ltv' in plan and 'ltv_label' not in plan:
        ltv=plan['ltv']; shown=ltv.quantize(D('.0001'),rounding=ROUND_HALF_UP)
        raw['ltv_label']=format((shown*100).normalize(),'f')+'%'
    rounded=money
    for key in ('first_payment','opening_investment','opening_debt'):
        if key in plan:raw[key]=rounded(plan[key])
    for original,row in zip(plan['rows'],raw['rows']):
        row['position_display']=position_money(original['position'])
        for key,v in original.items():
            if isinstance(v,D) and key!='rate':row[key]=rounded(v)
    # Reconcile displayed uses to displayed surplus. Largest remainders allocate
    # pence only at the presentation boundary; no rounded value feeds projection.
    for original,row in zip(plan['rows'][1:],raw['rows'][1:]):
        row['surplus']=money(D(money(plan_budget(original)))-D(row['payment']))
        keys=('invest_add','cash_add','overpay','spend')
        parts={k:original[k].quantize(PENNY,rounding=ROUND_FLOOR) for k in keys}
        remaining=int((D(row['surplus'])-sum(parts.values()))/PENNY)
        order=sorted(keys,key=lambda k:original[k]-parts[k],reverse=True)
        for k in order[:remaining]:parts[k]+=PENNY
        for k in keys:row[k]=money(parts[k])
    if plan.get('first_shortfall'):raw['first_shortfall']['amount']=rounded(plan['first_shortfall']['amount'])
    return raw


@lru_cache(maxsize=4)
@fixed
def opening_lookup(i: Inputs, term_years: int) -> dict:
    """Bounded directly evaluated opening facts, never interpolated by the UI.

    Whole pounds across ordinary ranges; wider ranges use a labelled stepped
    control. Exact endpoints and both adjacent pennies at rate edges survive.
    Arbitrary typed pennies use direct evaluation, independent of this grid.
    """
    rr = regions(i, term_years)
    if not rr:
        return dict(status='ok', version=VERSION, points=[], segments=[], edges=[])
    low, high = rr[0][0], rr[-1][1]
    step = max(D(1), ((high-low)/30000).to_integral_value(rounding=ROUND_CEILING))
    deposits = set()
    for a, b, _ in rr:
        deposits.update((a,b))
        deposits.update(D(n)*step for n in range(int((a/step).to_integral_value(rounding=ROUND_CEILING)), int(b/step)+1))
    edges = sorted({i.price*(1-bound) for bound,_ in i.bands if low < i.price*(1-bound) < high}) if i.pricing_mode=='assumed' else []
    for edge in edges:
        deposits.update(edge+d for d in (-PENNY,ZERO,PENNY) if any(a<=edge+d<=b for a,b,_ in rr))
    points=[]
    for deposit in sorted(deposits):
        p=present(project(i,deposit,term_years,through_month=1))
        row=p['rows'][1]
        ltv=D(p['ltv']); rounded=ltv.quantize(D('.0001'),rounding=ROUND_HALF_UP)
        ltv_label=p['ltv_label']
        points.append([format(deposit.normalize(),'f'),*[p[k] for k in ('opening_debt','opening_investment','rate','ltv','first_payment')],row['surplus'],row['invest_add'],row['cash_add'],row['overpay'],row['spend'],row['redirect_reason'],row['fallback_add'],ltv_label])
    return dict(status='ok',version=VERSION,term=term_years,points=points,step=str(step),
                low=str(low),high=str(high),edges=[str(e) for e in edges],edge_labels={str(e):display_ltv(i,(i.price-e)/i.price) for e in edges},
                segments=[dict(low=str(a),high=str(b),rate=str(r),label=format((r*100).normalize(),'f')+'%') for a,b,r in rr])


@fixed
def respond(request: dict) -> dict:
    """Standalone UI/provider boundary; no finance lives in HTTP or React."""
    try:
        i=parse(request.get('inputs',{})); choice=request.get('choice')
        objective_month=request.get('objective_month',DEFAULT_OBJECTIVE_MONTH)
        validate_objective_month(objective_month)
        if request.get('operation')=='validate':return dict(status='ok',version=VERSION)
        if choice:
            if D(str(choice['term']))!=D(str(choice['term'])).to_integral_value():raise ValueError('Use a whole-year mortgage term.')
            deposit=D(str(choice['deposit'])); term=int(choice['term'])
            if not deposit.is_finite() or deposit!=deposit.quantize(PENNY) or term not in TERMS:raise ValueError('Use an exact penny deposit and a whole-year term from 15 to 35.')
            choice=(deposit,term)
        if request.get('operation')=='comparison_quote':
            from quote_guidance import comparison_request
            if not choice:raise ValueError('Choose the current deposit and repayment term.')
            return comparison_request(i,*choice,request)
        if request.get('operation')=='quote_case':
            if request.get('fee_mode')=='loan' and request.get('fee') in (None,''):
                return dict(status='unknown',loan=None,ltv=None,reason='Enter the financed product fee to calculate the loan and LTV.')
            deposit=D(str(request['deposit']));fee=D(str(request.get('fee') or '0'))
            loan=i.price-deposit+(fee if request.get('fee_mode')=='loan' else ZERO)
            if deposit<ZERO or loan<ZERO:raise ValueError('Check the quoted deposit and fee.')
            return dict(status='ok',loan=money(loan),ltv=serial(loan/i.price),ltv_label=display_ltv(i,loan/i.price))
        if request.get('operation')=='curve':
            if not choice:raise ValueError('Choose a deposit and term for the curve.')
            return deposit_curve(i,choice[1],request.get('month',objective_month),choice[0],objective_month)
        if request.get('operation')=='opening':
            return opening_lookup(i,choice[1] if choice else 30)
        choice_only=request.get('operation')=='choice'
        result=(dict(keep=project(i,*(choice or (D('67500'),30))),best=None,count=0,ties=[],delta=None,choice_delta=None)
                if choice_only else search(i,choice,terms=((choice or (ZERO,30))[1],) if request.get('comparison_scope')=='selected_term' else TERMS,objective_month=objective_month))
        selected=result['keep']; best=result['best']
        baseline_inputs=parse(request['baseline_inputs']) if 'baseline_inputs' in request else None
        baseline=project(baseline_inputs,selected['deposit'],selected['term']) if baseline_inputs and selected else None
        term=selected['term'] if selected else 35
        rr=regions(i,term)
        alternative=[]
        if selected and not choice_only:
            for t in (25,30,35):alternative.append(present(project(i,selected['deposit'],t)))
        envelope=[]
        if selected and selected['valid'] and not choice_only:
            envelope=[present(project(i,selected['deposit'],selected['term'],offset)) for offset in (D('-.03'),D('.03'))]
        quote_comparison=[]
        comparison_choice=choice or ((selected['deposit'],selected['term']) if selected else (D('87500'),35))
        for q in i.quotes:
            status,reason=coverage(q,i.price,*comparison_choice,i.as_of)
            qp=project(replace(i,pricing_mode='quotes',quote_id=q.id),*comparison_choice) if status=='supplied' else None
            quote_comparison.append(dict(id=q.id,status=status,reason=reason,plan=present(qp)))
        report={}
        if request.get('comparison_scope')=='selected_term' and selected and not choice_only:
            from target_reporting import composition, contributions
            funded_terms=[p for t in (25,30,35) if (p:=project(i,selected['deposit'],t))['valid']]
            highest_term=max(funded_terms,key=lambda p:p['rows'][objective_month]['position'])['term'] if funded_terms else None
            report=dict(composition=composition(i,selected),why=contributions(i,selected,best,objective_month),highest_term=highest_term,curve=deposit_curve(i,term,objective_month,selected['deposit'],objective_month))
            if baseline_inputs:report['base_curve']=deposit_curve(baseline_inputs,term,objective_month,selected['deposit'],objective_month)
        return dict(**report,status='ok',pricing_steps=serial(pricing_steps(i,term)),exploration_domain=serial((max(i.lisa+i.gift,ZERO),min(i.price,i.total-i.costs-i.reserve))),quote_comparison=quote_comparison,version=VERSION,effective=EFFECTIVE,horizon_months=HORIZON_MONTHS,objective_month=objective_month,objective_year=objective_month//12,comparison_display=None if choice_only else comparison_display(selected,best,objective_month),baseline=present(baseline),base_future_difference=comparison_display(selected,baseline,objective_month) if baseline_inputs else None,search_scope=(f'Finite deposit sample at the selected {term}-year term; selected product only in quote mode.' if request.get('comparison_scope')=='selected_term' else 'Finite deposit samples across supported terms; selected product only in quote mode.'),inputs=serial({f.name:getattr(i,f.name) for f in fields(i)}),selected=present(selected),best=present(best),regions=serial(rr),terms=list(TERMS),candidate_count=result['count'],ties=serial(result['ties']),delta=money(result['delta']),choice_delta=money(result['choice_delta']),term_delta=result.get('term_delta'),term_comparison=alternative,envelope=envelope,reference_differences=reference_differences(selected,best))
    except (ValueError,TypeError,InvalidOperation,KeyError,OverflowError) as e:
        return dict(status='invalid',version=VERSION,issues=[str(e) or 'Check the entered amounts.'])
