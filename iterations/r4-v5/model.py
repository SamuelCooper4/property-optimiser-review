"""R4 isolated exploratory model. No production engine imports or probability model.

All finance is Python Decimal at fixed50. Renderer receives display strings only;
ranking, eligibility, deltas, ledgers and stress comparisons are computed here.
"""
from __future__ import annotations
from dataclasses import dataclass, fields, replace
from decimal import Decimal as D, Context, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, localcontext, InvalidOperation
from functools import wraps
from typing import Callable

VERSION = 'r4-exploratory-v4'
EFFECTIVE = '2026-11-04'
MAX_MONTHS = 480
GRID_INTERVALS = 16
PENNY = D('.01')


def exact_sum(*values: D) -> D:
    """Sum finite Decimal monetary components without losing cancellation digits."""
    nonzero=[v for v in values if v]
    if not nonzero:return D(0)
    if len(nonzero)==1:return nonzero[0]
    precision=max(v.adjusted() for v in nonzero)-min(v.as_tuple().exponent for v in nonzero)+len(str(len(values)))+2
    with localcontext(Context(prec=max(50,precision))):return sum(values,D(0))


def fixed(function: Callable) -> Callable:
    """Make the standalone model independent of ambient Decimal context."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=50)):
            return function(*args, **kwargs)
    return wrapped


@dataclass(frozen=True)
class Inputs:
    """Immutable fictional assumptions. GBP, decimal annual rates, explicit months."""
    price: D = D('450000')
    savings: D = D('150000')
    costs: D = D('0')
    reserve: D = D('10000')
    committed: D = D('0')
    monthly: D = D('2000')
    fee: D = D('0')
    investment_return: D = D('.05')
    cash_return: D = D('0')
    fixed_months: int = 60
    post_rate: D | None = None
    rate_path: tuple[tuple[int,D], ...] = ()
    renewal_months: int = 60
    fixed_deals: tuple[tuple[int,D | None], ...] = ()
    continuation_rate: D | None = None
    term_min: int = 15
    term_max: int = 35
    term_step: int = 5
    bands: tuple[tuple[D,D], ...] = ((D('.75'),D('.04')),(D('.85'),D('.05')),(D('.90'),D('.06')))


@fixed
def money(value: D) -> str:
    """GBP presentation only, ROUND_HALF_UP to pence."""
    result=value.quantize(PENNY,rounding=ROUND_HALF_UP)
    return '0.00' if not result else str(result)


def input_json(i: Inputs) -> dict:
    """Return complete replayable assumptions without float conversion."""
    return {f.name:([[str(a),str(b)] for a,b in i.bands] if f.name=='bands' else [[a,None if b is None else str(b)] for a,b in i.fixed_deals] if f.name=='fixed_deals' else [[a,str(b)] for a,b in i.rate_path] if f.name=='rate_path' else
                   str(getattr(i,f.name)) if isinstance(getattr(i,f.name),D) else getattr(i,f.name)) for f in fields(i)}


@fixed
def parse_inputs(raw: dict) -> tuple[Inputs | None,list[str]]:
    """Validate bounded prototype input; never silently relax a constraint."""
    errors=[]; values={}
    defaults=Inputs()
    try:
        if not isinstance(raw,dict):return None,['Inputs must be an object.']
        unknown=set(raw)-{f.name for f in fields(defaults)}
        if unknown:return None,['Unsupported input fields: '+', '.join(sorted(unknown))+'.']
        for f in fields(defaults):
            v=raw.get(f.name,getattr(defaults,f.name))
            if f.name=='bands':values[f.name]=tuple((D(str(a)),D(str(b))) for a,b in v)
            elif f.name=='rate_path':
                if any(isinstance(a,bool) or D(str(a))!=D(str(a)).to_integral_value() for a,b in v):raise ValueError('Rate dates must be whole elapsed months.')
                values[f.name]=tuple((int(a),D(str(b))) for a,b in v)
            elif f.name=='fixed_deals':values[f.name]=tuple((whole_month(a),None if b is None else D(str(b))) for a,b in v)
            elif f.name in ('post_rate','continuation_rate'):values[f.name]=None if v in ('',None) else D(str(v))
            elif f.name in ('fixed_months','renewal_months','term_min','term_max','term_step'):
                if isinstance(v,bool) or D(str(v))!=D(str(v)).to_integral_value():raise ValueError('Time values must be whole months or years.')
                values[f.name]=int(v)
            else:values[f.name]=D(str(v))
        i=Inputs(**values)
        decimals=[getattr(i,f.name) for f in fields(i) if isinstance(getattr(i,f.name),D)]+[v for band in i.bands for v in band]+[r for _,r in i.rate_path]+[r for _,r in i.fixed_deals if r is not None]
        if not all(x.is_finite() for x in decimals):raise ValueError('All amounts and rates must be finite numbers.')
        if not D('1000')<=i.price<=D('10000000'):errors.append('House price must be £1,000–£10,000,000 for this experiment.')
        for name in ('savings','costs','reserve','committed','fee'):
            if not 0<=getattr(i,name)<=D('10000000'):errors.append(f'{name.title()} must be £0–£10,000,000.')
        if not 0<=i.monthly<=D('100000'):errors.append('Monthly funding must be £0–£100,000.')
        if not D('-.5')<=i.investment_return<=D('.5') or not D('-.1')<=i.cash_return<=D('.25'):errors.append('Experiment return range: investment −50% to 50%; cash −10% to 25%.')
        if i.post_rate is not None and not 0<=i.post_rate<=D('.25'):errors.append('Post-deal rate must be 0%–25%.')
        if i.continuation_rate is not None and not 0<=i.continuation_rate<=D('.25'):errors.append('Continuation rate must be 0%–25%.')
        if i.fixed_deals and (len(i.fixed_deals)>24 or sum(a for a,_ in i.fixed_deals)>480 or any(a not in (24,60) for a,_ in i.fixed_deals) or i.fixed_deals[0][1] is not None or any(r is None or not 0<=r<=D('.25') for _,r in i.fixed_deals[1:]) or i.continuation_rate is None):
            errors.append('Use up to 24 fixed deals of 24 or 60 months, totalling at most 480 months; opening rate must be null, later and continuation rates explicit 0%–25%.')
        if not 1<=i.renewal_months<=480:errors.append('Renewal interval must be 1?480 months.')
        if len(i.rate_path)>24 or any(not 0<=a<=480 or not 0<=r<=D('.25') for a,r in i.rate_path) or any(i.rate_path[n][0]>=i.rate_path[n+1][0] for n in range(len(i.rate_path)-1)):errors.append('Use up to 24 ascending distinct rate dates, months 0?480, rates 0%?25%.')
        if not 0<=i.fixed_months<=480:errors.append('Fixed period must be 0–480 months.')
        if not 1<=i.term_min<=i.term_max<=40 or not 1<=i.term_step<=10:errors.append('Terms must be ordered whole years from 1 to 40; step 1–10 years.')
        if not 1<=len(i.bands)<=8 or any(not 0<b<=1 or not 0<=r<=D('.25') for b,r in i.bands) or any(i.bands[n][0]>=i.bands[n+1][0] for n in range(len(i.bands)-1)):
            errors.append('Use 1–8 ascending, inclusive maximum-LTV bands with rates 0%–25%.')
        if i.savings<i.reserve+i.costs+i.fee:errors.append('Unrestricted savings cannot cover costs, fee and protected emergency cash.')
        if i.committed>i.price:errors.append('Purchase-committed funds cannot exceed the house price.')
        return (None if errors else i),errors
    except (ValueError,TypeError,InvalidOperation,OverflowError):
        return None,['Enter valid finite numbers; time values must be whole months or years.']


@fixed
def rate_for(i: Inputs, deposit: D) -> D | None:
    """Inclusive maximum LTV lookup; None means unsupported borrowing."""
    if deposit==i.price:return D(0)
    ltv=(i.price-deposit)/i.price
    return next((rate for bound,rate in i.bands if ltv<=bound),None)


def repayment(principal: D, annual_rate: D, months: int) -> D:
    """Month-based annuity for the isolated reset/overpayment model, GBP/month."""
    if not principal:return D(0)
    if not annual_rate:return principal/D(months)
    rate=annual_rate/12
    return principal*rate/(1-(1+rate)**(-months))


@fixed
def deposit_grid(i: Inputs) -> list[D]:
    """Sample penny deposits plus exact threshold neighbours and capital endpoints."""
    low=max(i.committed,i.price*(1-i.bands[-1][0]));high=min(i.price,i.savings-i.costs-i.fee-i.reserve+i.committed)
    if high<low:return []
    grid={low,high}
    for n in range(GRID_INTERVALS+1):grid.add((low+(high-low)*n/GRID_INTERVALS).quantize(PENNY,rounding=ROUND_HALF_UP))
    for b,_ in i.bands:
        threshold=i.price*(1-b)
        grid.update((threshold-PENNY,threshold,threshold+PENNY))
    return sorted(x for x in grid if low<=x<=high)


def plan_id(deposit: D, term_years: int) -> str:
    """Stable identity independent of display rounding."""
    return format(deposit.normalize(),'f')+'@'+str(term_years)


def available_rate(i: Inputs, elapsed_month: int, initial_rate: D) -> D:
    """External annual rate known at an elapsed month; no immediate mortgage reset."""
    if i.fixed_deals:
        end=0
        for duration,rate in i.fixed_deals:
            end+=duration
            if elapsed_month<end:return initial_rate if rate is None else rate
        return i.continuation_rate
    points=[rate for month,rate in i.rate_path if month<=elapsed_month]
    return points[-1] if points else (i.post_rate if i.post_rate is not None else initial_rate)


def whole_month(value: object) -> int:
    """Reject fractional month inputs rather than silently truncating them."""
    amount=D(str(value))
    if isinstance(value,bool) or not amount.is_finite() or amount!=amount.to_integral_value():raise ValueError('Whole month required.')
    return int(amount)


def overpayment_settings(op: dict) -> tuple[D,int,int,D,D,str,list[dict]]:
    """Normalize bounded event schedules; funds are existing assets or monthly surplus."""
    regular=D(str(op.get('regular','0')));start=whole_month(op.get('regular_start',1));end=whole_month(op.get('regular_end',480))
    allowance=D(str(op.get('allowance','1')));charge=D(str(op.get('charge_rate','0')));treatment=op.get('treatment','term')
    if not all(v.is_finite() for v in (regular,allowance,charge)) or min(regular,allowance,charge)<0 or max(allowance,charge)>1 or not 1<=start<=end<=480 or treatment not in ('term','payment'):raise ValueError('Invalid regular overpayment or charge settings.')
    events=list(op.get('events',[]))
    if D(str(op.get('lump','0'))):events.append({'month':op.get('month',60),'amount':op['lump'],'source':op.get('source','investment'),'available_month':op.get('available_month',1)})
    if len(events)>24:raise ValueError('At most 24 one-off events are supported.')
    normalized=[]
    for event in events:
        month=whole_month(event['month']);available=whole_month(event.get('available_month',1));amount=D(str(event['amount']));source=event.get('source','investment')
        if not amount.is_finite() or not 0<=amount<=D('10000000') or not 1<=month<=480 or not 1<=available<=480 or source not in ('investment','monthly','cash'):raise ValueError('Invalid event date, source or amount.')
        normalized.append(dict(month=month,available_month=available,amount=amount,source=source))
    return regular,start,end,allowance,charge,treatment,normalized


@fixed
def project(i: Inputs, deposit: D, term_years: int, overpayment: dict | None = None, stress: str = 'base', stop_ineligible_at_month: int | None = None) -> dict:
    """Monthly existing-resource ledger; unfunded debt remains outstanding and ineligible."""
    unavailable={'id':plan_id(deposit,term_years),'deposit':money(deposit) if deposit.is_finite() else str(deposit),'deposit_exact':str(deposit),'term':term_years,'status':'unavailable','rows':[]}
    if not isinstance(term_years,int) or not 1<=term_years<=40 or not deposit.is_finite():return {**unavailable,'issues':['Choose a finite deposit and a whole-year term from 1 to 40.']}
    rate=rate_for(i,deposit)
    if rate is None or not i.committed<=deposit<=min(i.price,i.savings-i.costs-i.fee-i.reserve+i.committed):return {**unavailable,'issues':['Deposit is outside the funded purchase/product domain.']}
    try:regular,start,end,allowance,charge_rate,treatment,events=overpayment_settings(overpayment or {})
    except (ValueError,TypeError,KeyError,InvalidOperation):return {**unavailable,'issues':['Invalid overpayment dates, amounts, sources, allowance or treatment.']}
    months=term_years*12;debt=i.price-deposit;opening_debt=debt;initial_rate=rate
    if not i.fixed_deals and i.fixed_months==0:rate=available_rate(i,0,initial_rate)
    opening=i.savings-i.costs-i.fee-i.reserve-deposit+i.committed
    opening_cohort=opening;later_cohort=D(0);investment=opening;cash=i.reserve
    cumulative_contributions=D(0);interest_total=D(0);withdrawal_total=D(0);total_charges=D(0);shortfall_total=D(0)
    payoff=0 if not debt else None;first_breach=None;issues=[];event_results=[];skipped=[]
    ledger=[{'source':'savings','use':name,'amount':value} for name,value in [('costs',i.costs),('fee',i.fee),('deposit',deposit-i.committed),('cash',i.reserve),('investment',investment)]]
    if i.committed:ledger.append({'source':'committed','use':'deposit','amount':i.committed})
    cash_factor=(1+i.cash_return)**(D(1)/12)
    annual=i.investment_return if stress!='low_return' else D('0')
    normal_factor=(1+annual)**(D(1)/12);recovery_factor=(1+D('.12'))**(D(1)/12)
    payment=repayment(debt,rate,months);initial_payment=payment;yearly_extra=D(0);year_open=debt;active_rate=rate
    rows=[dict(month=0,debt=debt,investment=investment,cash=cash,net=i.price+cash+investment-debt,equity=deposit,accessible=cash+investment,payment=D(0),required_payment=D(0),shortfall=D(0),shortfall_total=D(0),contribution=D(0),extra=D(0),lump=D(0),charge=D(0),interest=D(0),interest_total=D(0),principal_total=D(0),repaid_fraction=D(0),contributions=D(0),opening=opening,opening_cohort=opening,later_cohort=D(0),growth=D(0),headroom=i.monthly,rate=rate,assumed_rate=available_rate(i,0,initial_rate),renewal=False,eligible=True,withdrawals=D(0))]
    rows[0]['monthly_outflow']=D(0)
    deal_boundaries=set();elapsed_deals=0
    for duration,_ in i.fixed_deals:
        elapsed_deals+=duration;deal_boundaries.add(elapsed_deals)
    for month in range(1,MAX_MONTHS+1):
        if (month-1)%12==0:yearly_extra=D(0);year_open=debt
        elapsed=month-1
        renewal=elapsed in deal_boundaries if i.fixed_deals else (elapsed==i.fixed_months and (bool(i.rate_path) or i.post_rate is not None)) or (bool(i.rate_path) and elapsed>i.fixed_months and (elapsed-i.fixed_months)%i.renewal_months==0)
        if renewal and debt and elapsed<months:
            active_rate=available_rate(i,elapsed,initial_rate);payment=repayment(debt,active_rate,months-elapsed)
        factor=normal_factor;shock_month={'early_fall':24,'late_fall':240,'slow_recovery':120}.get(stress)
        if shock_month and shock_month<month<=shock_month+60 and stress!='slow_recovery':factor=recovery_factor
        if shock_month==month:factor*=D('.65')
        if factor!=1:opening_cohort*=factor;later_cohort*=factor
        investment=exact_sum(opening_cohort,later_cohort)
        if cash_factor!=1:cash*=cash_factor
        interest=debt*active_rate/12
        required=min(payment,exact_sum(debt,interest)) if debt else D(0)
        if month>=months:required=exact_sum(debt,interest)
        paid=min(required,i.monthly);shortfall=exact_sum(required,paid.copy_negate());shortfall_total=exact_sum(shortfall_total,shortfall)
        headroom=exact_sum(i.monthly,required.copy_negate())
        if shortfall and first_breach is None:first_breach=month
        interest_total=exact_sum(interest_total,interest);debt=max(D(0),exact_sum(debt,interest,paid.copy_negate()))
        extra=D(0);lump_paid=D(0);charge=D(0);available=exact_sum(i.monthly,paid.copy_negate())
        requested_regular=min(regular,debt) if start<=month<=end else D(0)
        free=max(D(0),year_open*allowance-yearly_extra);cost=max(D(0),requested_regular-free)*charge_rate
        if requested_regular+cost<=available:
            extra=requested_regular;charge=cost;debt=exact_sum(debt,extra.copy_negate());available=exact_sum(available,extra.copy_negate(),cost.copy_negate());yearly_extra=exact_sum(yearly_extra,extra)
        elif requested_regular:
            issue='Regular overpayment exceeds monthly surplus; skipped in affected months.'
            if issue not in issues:issues.append(issue)
            skipped.append({'month':month,'kind':'regular','amount':requested_regular,'available':available,'issue':issue})
        for event in events:
            if event['month']!=month or not event['amount']:continue
            requested=min(event['amount'],debt);free=max(D(0),year_open*allowance-yearly_extra);cost=max(D(0),requested-free)*charge_rate
            if not requested:
                event_results.append({**event,'paid':D(0),'charge':D(0),'issue':None});continue
            source=event['source'];funding=investment if source=='investment' else max(D(0),cash-i.reserve) if source=='cash' else available
            if month<event['available_month'] or requested+cost>funding:
                reason='Event is before its funding availability date.' if month<event['available_month'] else 'Event exceeds its selected funding source; no payment applied.'
                issues.append(reason);event_results.append({**event,'paid':D(0),'charge':D(0),'issue':reason});skipped.append({**event,'kind':'event','available':funding,'issue':reason});continue
            lump_paid=exact_sum(lump_paid,requested);debt=exact_sum(debt,requested.copy_negate());yearly_extra=exact_sum(yearly_extra,requested);charge=exact_sum(charge,cost)
            total=exact_sum(requested,cost)
            if source=='investment' and total:
                opening_share=total*opening_cohort/investment
                opening_cohort=exact_sum(opening_cohort,opening_share.copy_negate());later_cohort=exact_sum(later_cohort,total.copy_negate(),opening_share)
                investment=exact_sum(opening_cohort,later_cohort);withdrawal_total=exact_sum(withdrawal_total,total)
            elif source=='cash':cash=exact_sum(cash,total.copy_negate())
            else:available=exact_sum(available,total.copy_negate())
            event_results.append({**event,'paid':requested,'charge':cost,'issue':None})
        total_charges=exact_sum(total_charges,charge)
        if treatment=='payment' and debt and (extra or lump_paid) and month<months:payment=repayment(debt,active_rate,months-month)
        contribution=available;later_cohort=exact_sum(later_cohort,contribution);investment=exact_sum(opening_cohort,later_cohort);cumulative_contributions=exact_sum(cumulative_contributions,contribution)
        if debt==0 and payoff is None:payoff=month
        principal_total=exact_sum(opening_debt,debt.copy_negate());repaid_fraction=max(D(0),min(D(1),principal_total/opening_debt)) if opening_debt else D(0)
        rows.append(dict(month=month,debt=debt,investment=investment,cash=cash,net=exact_sum(i.price,cash,investment,debt.copy_negate()),equity=exact_sum(i.price,debt.copy_negate()),accessible=exact_sum(cash,investment),payment=paid,required_payment=required,shortfall=shortfall,shortfall_total=shortfall_total,contribution=contribution,extra=extra,lump=lump_paid,charge=charge,interest=interest,interest_total=interest_total,principal_total=principal_total,repaid_fraction=repaid_fraction,contributions=cumulative_contributions,opening=opening,opening_cohort=opening_cohort,later_cohort=later_cohort,growth=exact_sum(investment,opening.copy_negate(),cumulative_contributions.copy_negate(),withdrawal_total),headroom=headroom,rate=active_rate,assumed_rate=available_rate(i,elapsed,initial_rate),renewal=renewal,eligible=first_breach is None,withdrawals=withdrawal_total))
        rows[-1]['monthly_outflow']=exact_sum(i.monthly,available.copy_negate())
        # Search-only rejection shortcut. Never expose an incomplete original or winner.
        if stop_ineligible_at_month is not None and (issues or (first_breach is not None and first_breach<=stop_ineligible_at_month)):break
    return {'id':plan_id(deposit,term_years),'status':'ok','deposit':deposit,'term':term_years,'rate':rate,'ltv':opening_debt/i.price,'payment':initial_payment,'opening_investment':opening,'opening_cash':i.reserve,'opening_debt':opening_debt,'ledger':ledger,'rows':rows,'first_breach':first_breach,'payoff_month':payoff,'issues':issues,'interest_total':interest_total,'charges':total_charges,'events':event_results,'skipped':skipped}


def serial_row(row: dict) -> dict:
    """Serialize a monthly state for chart/presentation; no client calculations."""
    with localcontext(Context(prec=50)):
        enriched={**row,'negative_debt':-row['debt'],'principal':row['payment']-row['interest'],'paid_interest':min(row['payment'],row['interest']),'paid_principal':max(D(0),row['payment']-row['interest']),'unpaid_interest':max(D(0),row['interest']-row['payment'])}
        return {k:(str(v) if k in ('rate','assumed_rate','repaid_fraction') else money(v)) if isinstance(v,D) else v for k,v in enriched.items()}


def serial_plan(p: dict, monthly: bool = False) -> dict:
    """Serialize one plan; annual chart samples use the same monthly authority."""
    if p['status']!='ok':return p
    result={k:(money(v) if k!='rate' and k!='ltv' else str(v)) if isinstance(v,D) else v for k,v in p.items() if k not in ('rows','ledger','events','skipped')}
    result['events']=[{k:money(v) if isinstance(v,D) else v for k,v in event.items()} for event in p.get('events',[])]
    result['skipped']=[{k:money(v) if isinstance(v,D) else v for k,v in event.items()} for event in p.get('skipped',[])]
    result['deposit_exact']=str(p['deposit'])
    result['schedule_eligible']=not p['issues']
    result['monthly_investment']=money(p['rows'][1]['contribution'])
    result['first_monthly_outflow']=money(p['rows'][1]['monthly_outflow'])
    result['monthly_shortfall']=money(max(D(0),-p['rows'][1]['headroom']))
    result['ledger']=[{**entry,'amount':money(entry['amount'])} for entry in p['ledger']]
    result['rows']=[serial_row(r) for r in p['rows'] if monthly or r['month']%12==0]
    return result


@fixed
def calculate(i: Inputs, context: dict | None = None) -> dict:
    """Evaluate the disclosed joint sampled domain; keep exact ties and exclusions."""
    terms=list(range(i.term_min,i.term_max+1,i.term_step))
    if terms[-1]!=i.term_max:terms.append(i.term_max)
    context=normal_context(context)
    deposits=deposit_grid(i);plans=[context_project(i,d,t,context) for t in terms for d in deposits]
    best=[];best_values=[];ties=[]
    for year in range(41):
        eligible=[p for p in plans if p['rows'][year*12]['eligible'] and (context['overpayment'] is None or not p['issues'])]
        maximum=max((p['rows'][year*12]['net'] for p in eligible),default=None)
        matching=[p['id'] for p in eligible if p['rows'][year*12]['net']==maximum]
        best.append(matching[0] if matching else None);best_values.append(str(maximum) if maximum is not None else None);ties.append(matching)
    serial=[]
    for p in plans:
        item=serial_plan(p)
        item['difference']=[money(p['rows'][year*12]['net']-D(best_values[year])) if best_values[year] is not None else None for year in range(41)]
        item['near_best']=[p['rows'][year*12]['eligible'] and (context['overpayment'] is None or not p['issues']) and best_values[year] is not None and D(best_values[year])-p['rows'][year*12]['net']<=D('5000') for year in range(41)]
        serial.append(item)
    best_by_term={str(term):[] for term in terms};ties_by_term={str(term):[] for term in terms};ridge_by_term={str(term):[] for term in terms}
    for term in terms:
        family=[p for p in plans if p['term']==term]
        for year in range(41):
            eligible=[p for p in family if p['rows'][year*12]['eligible'] and (context['overpayment'] is None or not p['issues'])]
            winner=max(eligible,key=lambda p:p['rows'][year*12]['net'],default=None)
            best_by_term[str(term)].append(winner['id'] if winner else None)
            matches=[p['id'] for p in eligible if winner and p['rows'][year*12]['net']==winner['rows'][year*12]['net']]
            ties_by_term[str(term)].append(matches)
            ridge_by_term[str(term)].append({'year':year,'ids':matches,'unique':matches[0] if len(matches)==1 else None,'eligible_count':len(eligible)})
    boundaries=[{'ltv':str(bound),'deposit':str(i.price*(1-bound)),
                 'rate':str(available_rate(i,0,rate) if i.fixed_months==0 else rate)}
                for bound,rate in i.bands]
    return {'ties_by_term':ties_by_term,'ridge_by_term':ridge_by_term,'best_by_term':best_by_term,'boundaries':boundaries,'status':'ok','version':VERSION,'effective_from':EFFECTIVE,'inputs':input_json(i),'context':context,'plans':serial,'best':best,'best_value_exact':best_values,'ties':ties,'terms':terms,'deposits':[str(d) for d in deposits],'near_best_tolerance_gbp':'5000.00','issues':[] if plans else ['No deposit can meet the entered capital and LTV limits.'],'search':f'{len(deposits)} deposits × {len(terms)} terms; inclusive thresholds ±£0.01, endpoints and {GRID_INTERVALS} grid intervals. Best among evaluated options only.'}


@fixed
def compare(i: Inputs, selected: str, pinned: str, context: dict | None = None) -> dict:
    """Compare two fixed complete plans over all monthly dates with shared resources."""
    d,t=selected.split('@');pd,pt=pinned.split('@')
    if not 1<=int(t)<=40 or not 1<=int(pt)<=40:raise ValueError('Invalid term.')
    base=context_project(i,D(d),int(t),context);pin=context_project(i,D(pd),int(pt),context)
    if base['status']!='ok':return base
    if pin['status']!='ok':return pin
    return {'status':'ok','version':VERSION,'selected':selected,'pinned':pinned,'base':serial_plan(base,True),'pin':serial_plan(pin,True),'pair_difference':[money(exact_sum(a['net'],b['net'].copy_negate())) for a,b in zip(base['rows'],pin['rows'])]}


@fixed
def return_comparison(i: Inputs, deposit: D, term: int, other_deposit: D, other_term: int, month: int, context: dict | None = None) -> tuple[list[dict],list[dict]]:
    """Fixed-plan annual-return grid; strict sign changes yield sampled intervals."""
    context=normal_context(context)
    # The sweep itself supplies the return; zero-growth is a scalar assumption,
    # while named shock/recovery paths remain common to both tested plans.
    if context['stress']=='low_return':context={**context,'stress':'base'}
    curve=[]
    for n in range(-4,13):
        rate=D(n)/100;a=context_project(replace(i,investment_return=rate),deposit,term,context);b=context_project(replace(i,investment_return=rate),other_deposit,other_term,context)
        difference=exact_sum(a['rows'][month]['net'],b['rows'][month]['net'].copy_negate())
        eligible=a['rows'][month]['eligible'] and b['rows'][month]['eligible'] and not a['issues'] and not b['issues']
        curve.append({'return':str(rate),'eligible':eligible,'net':money(a['rows'][month]['net']) if eligible else None,'pin':money(b['rows'][month]['net']) if eligible else None,'difference':money(difference) if eligible else None,'difference_exact':str(difference) if eligible else None})
    brackets=[{'from':a['return'],'to':b['return']} for a,b in zip(curve,curve[1:]) if a['eligible'] and b['eligible'] and D(a['difference_exact'])*D(b['difference_exact'])<0]
    return curve,brackets


@fixed
def analyse(i: Inputs, selected: str, pinned: str | None, options: dict, context: dict | None = None) -> dict:
    """Fixed-plan analyses; never silently reoptimise a stress scenario."""
    context=normal_context(context)
    def evaluate(inputs, deposit, years, overpayment=None, stress=None):
        return project(inputs,deposit,years,context['overpayment'] if overpayment is None else overpayment,context['stress'] if stress is None else stress)
    d,t=selected.split('@');deposit=D(d);term=int(t)
    base=evaluate(i,deposit,term)
    if base['status']!='ok':return base
    pin_d,pin_t=(pinned or selected).split('@');pin=evaluate(i,D(pin_d),int(pin_t))
    year=int(options.get('year',30));month=year*12
    if not 1<=year<=40:return {'status':'invalid','issues':['Comparison year must be 1–40.']}
    if pin['status']!='ok':return pin
    base_eligible=base['rows'][month]['eligible'] and not base['issues']
    stress=[]
    for key,label in [('base','Entered return'),('low_return','No investment growth'),('early_fall','Early fall · year 2'),('late_fall','Late fall · year 20'),('slow_recovery','Fall · slow recovery')]:
        path=evaluate(i,deposit,term,stress=key);other=evaluate(i,D(pin_d),int(pin_t),stress=key)
        eligible=path['rows'][month]['eligible'] and other['rows'][month]['eligible'] and not path['issues'] and not other['issues']
        stress.append({'key':key,'label':label,'eligible':eligible,'shock_month':{'early_fall':24,'late_fall':240,'slow_recovery':120}.get(key),'recovery_end_month':{'early_fall':84,'late_fall':300}.get(key),'shock_fraction':'0.35' if key in ('early_fall','late_fall','slow_recovery') else None,'recovery_rate':'0.12' if key in ('early_fall','late_fall') else None,'plan':serial_plan(path),'pin':serial_plan(other),'difference':money(path['rows'][month]['net']-other['rows'][month]['net']) if eligible else None})
    return_curve,brackets=return_comparison(i,deposit,term,D(pin_d),int(pin_t),month,context)
    rate=D(str(options.get('rate','.07')))
    if not rate.is_finite() or not 0<=rate<=D('.25'):return {'status':'invalid','issues':['Stress rate must be 0%–25%.']}
    changed=replace(i,post_rate=rate,rate_path=())
    if i.fixed_deals:
        changed=replace(i,fixed_deals=tuple((duration,None if r is None else rate) for duration,r in i.fixed_deals),continuation_rate=rate)
    if 'rate_path' in options:
        changed,errors=parse_inputs({**input_json(i),'fixed_deals':[],'rate_path':options['rate_path'],'renewal_months':options.get('renewal_months',i.renewal_months),'fixed_months':options.get('fixed_months',i.fixed_months)})
        if errors:return {'status':'invalid','issues':errors}
    rate_plan=evaluate(changed,deposit,term);rate_pin=evaluate(changed,D(pin_d),int(pin_t))
    op=options.get('overpayment',{'lump':'10000','month':60,'regular':'100','source':'investment','treatment':'term','allowance':'0.1','charge_rate':'0'})
    over=evaluate(i,deposit,term,op)
    variants={}
    for key,settings in [('lump_only',{**op,'regular':'0'}),('regular_only',{**op,'lump':'0','events':[]})]:
        variant=evaluate(i,deposit,term,settings)
        variants[key]={'plan':serial_plan(variant,True),'difference':money(exact_sum(variant['rows'][month]['net'],base['rows'][month]['net'].copy_negate())) if variant['status']=='ok' else None}
    schedules=[]
    timing=timing_variants(op)
    for spec in ([] if op.get('search_requested') is False else timing):
        p=evaluate(i,deposit,term,spec['overpayment'])
        valid=p['status']=='ok' and not p['issues'] and p['rows'][month]['eligible']
        schedules.append({**spec,'eligible':valid,'net':money(p['rows'][month]['net']) if p['status']=='ok' else None,'net_exact':str(p['rows'][month]['net']) if p['status']=='ok' else None,'issues':p['issues']})
    feasible=[s for s in schedules if s['eligible']];best_schedule=max(feasible,key=lambda s:D(s['net_exact']),default=None)
    schedule_ties=[s for s in feasible if best_schedule and D(s['net_exact'])==D(best_schedule['net_exact'])]
    sensitivity=[]
    later=replace(i,post_rate=(i.post_rate if i.post_rate is not None else base['rate'])+D('.02'),rate_path=tuple((m,r+D('.02')) for m,r in i.rate_path))
    if i.fixed_deals:
        later=replace(i,fixed_deals=tuple((duration,None if r is None else r+D('.02')) for duration,r in i.fixed_deals),continuation_rate=i.continuation_rate+D('.02'))
    for key,label,change in [('return','Investment return −2 percentage points',replace(i,investment_return=i.investment_return-D('.02'))),('later','Future deal and continuation rates +2 percentage points' if i.fixed_deals else 'Post-deal mortgage rate +2 percentage points',later),('cash','Cash return +1 percentage point',replace(i,cash_return=i.cash_return+D('.01'))),('monthly','Monthly funding −£200',replace(i,monthly=max(D(0),i.monthly-D(200))))]:
        p=evaluate(change,deposit,term)
        eligible=base_eligible and p['rows'][month]['eligible'] and not p['issues']
        sensitivity.append({'key':key,'label':label,'difference':money(p['rows'][month]['net']-base['rows'][month]['net']) if eligible else None,'eligible':eligible})
    sensitivity.sort(key=lambda x:abs(D(x['difference'])) if x['difference'] is not None else D(0),reverse=True)
    terms=sorted(set(range(i.term_min,i.term_max+1,i.term_step))|{i.term_max})
    term_plans=[serial_plan(evaluate(i,deposit,t)) for t in terms]
    recommended_term=whole_month(options.get('recommended_term',pin_t))
    if not 1<=recommended_term<=40:return {'status':'invalid','issues':['Recommended term must be 1?40 years.']}
    if term==recommended_term:
        shorter=[evaluate(i,deposit,t) for t in reversed(terms) if t<term]
        reference=next((p for p in shorter if p['status']=='ok' and p['rows'][month]['eligible'] and not p['issues']),None)
        reason='Nearest shorter funded tested term at the same deposit.'
    else:
        candidate=evaluate(i,deposit,recommended_term)
        reference=candidate if candidate['status']=='ok' and candidate['rows'][month]['eligible'] and not candidate['issues'] else None
        reason='Recommended term at the same deposit.'
    if reference is None:
        term_comparison={'status':'no_shorter','selected':serial_plan(base,True),'reference':None,'reference_available':False,'reference_reason':'No shorter tested term is funded at this deposit.' if term==recommended_term else 'The recommended term is not funded at this deposit.','payment_constraint':money(i.monthly),'returns':[],'break_even_brackets':[],'identical_plans':False,'pair_difference':[],'longest_evaluated_term':i.term_max}
    else:
        term_returns,term_brackets=return_comparison(i,deposit,term,deposit,reference['term'],month,context)
        left=base['rows'][month];right=reference['rows'][month]
        term_comparison={'status':'ok','reference_available':True,'reference_reason':reason,'selected':serial_plan(base,True),'reference':serial_plan(reference,True),'difference':money(exact_sum(left['net'],right['net'].copy_negate())),'investment_difference':money(exact_sum(left['investment'],right['investment'].copy_negate())),'cash_difference':money(exact_sum(left['cash'],right['cash'].copy_negate())),'debt_difference':money(exact_sum(left['debt'],right['debt'].copy_negate())),'debt_effect':money(exact_sum(right['debt'],left['debt'].copy_negate())),'returns':term_returns,'break_even_brackets':term_brackets,'identical_plans':term==reference['term'],'pair_difference':[money(exact_sum(a['net'],b['net'].copy_negate())) for a,b in zip(base['rows'],reference['rows'])],'common_period_months':month,'selected_interest':money(left['interest_total']),'reference_interest':money(right['interest_total']),'longest_evaluated_term':i.term_max}
    return {'term_comparison':term_comparison,'term_plans':term_plans,'status':'ok','version':VERSION,'selected':selected,'pinned':pinned,'year':year,'base':serial_plan(base,True),'pin':serial_plan(pin,True),'pair_difference':[money(a['net']-b['net']) for a,b in zip(base['rows'],pin['rows'])],'stress':stress,'returns':return_curve,'break_even_brackets':brackets,'identical_plans':selected==pinned or pinned is None,'rate':{'value':str(rate),'plan':serial_plan(rate_plan,True),'pin':serial_plan(rate_pin,True),'difference':money(rate_plan['rows'][month]['net']-rate_pin['rows'][month]['net'])},'overpayment':{**variants,'options':op,'plan':serial_plan(over,True),'difference':money(over['rows'][month]['net']-base['rows'][month]['net']) if over['status']=='ok' else None,'search_scope':'Final one-off event only; zero once, half/full entered amount at availability-clipped start/mid/end. Earlier events and recurring schedule fixed. Existing resources only.','interest_saving':money(exact_sum(base['rows'][month]['interest_total'],over['rows'][month]['interest_total'].copy_negate())) if over['status']=='ok' else None,'common_period_months':month,'schedules':schedules,'best_schedule':best_schedule,'ties':schedule_ties},'sensitivity':sensitivity}


def normal_context(context: dict | None = None) -> dict:
    """Validate projection assumptions that sit outside household inputs."""
    if context is None:context={}
    if not isinstance(context,dict) or set(context)-{'stress','overpayment'}:raise ValueError('Unsupported context fields.')
    stress=context.get('stress','base');op=context.get('overpayment')
    if stress not in ('base','low_return','early_fall','late_fall','slow_recovery'):raise ValueError('Unsupported investment path.')
    if op is not None:
        if not isinstance(op,dict):raise ValueError('Overpayment settings must be an object.')
        allowed={'regular','regular_start','regular_end','events','treatment','allowance','charge_rate','lump','month','source','available_month','window_start','window_end','search_requested'}
        if set(op)-allowed:raise ValueError('Unsupported overpayment settings.')
        overpayment_settings(op)
        if any(set(e)-{'month','amount','source','available_month'} for e in op.get('events',[])):raise ValueError('Unsupported event fields.')
    return {'stress':stress,'overpayment':op}


def context_project(i: Inputs, deposit: D, term: int, context: dict | None = None, stop_ineligible_at_month: int | None = None) -> dict:
    """Project a complete purchase plan under one reusable assumption context."""
    c=normal_context(context)
    return project(i,deposit,term,c['overpayment'],c['stress'],stop_ineligible_at_month)


def chronological_schedule(op: dict) -> dict:
    """Unify explicit and legacy one-off payments, retaining same-month entered order."""
    normal_context({'overpayment':op})
    events=sorted(overpayment_settings(op)[-1],key=lambda event:event['month'])
    return {**op,'lump':'0','events':[{k:str(v) if isinstance(v,D) else v for k,v in event.items()} for event in events]}


@fixed
def timing_variants(op: dict) -> list[dict]:
    """Vary the latest chronological event only, preserving all earlier payments."""
    entered=chronological_schedule(op)
    start=whole_month(op.get('window_start',12));end=whole_month(op.get('window_end',120))
    if not 1<=start<=end<=480:raise ValueError('Search window must be ordered months 1–480.')
    events=entered['events'];target=events[-1] if events else {'amount':'0','source':op.get('source','investment'),'available_month':op.get('available_month',1)}
    lower=max(start,whole_month(target.get('available_month',1)))
    times=sorted({lower,(lower+end)//2,end}) if lower<=end else []
    candidates=[];seen=set()
    for when,amount in [(start,D(0))]+[(when,D(str(target['amount']))*fraction) for when in times for fraction in (D('.5'),D(1)) if D(str(target['amount']))]:
        key=(when,amount) if amount else (None,D(0))
        if key in seen:continue
        seen.add(key)
        candidate={**entered,'events':events[:-1]+([{**target,'month':when,'amount':str(amount)}] if amount else [])}
        candidates.append({'month':when,'amount':str(amount),'source':target['source'],'available_month':whole_month(target.get('available_month',1)),'overpayment':candidate})
    return candidates


def optional_schedules(op: dict) -> list[dict | None]:
    """Bounded optional domain: no extras, entered, final-event timing/amount variants."""
    candidates=[None,chronological_schedule(op)]
    for spec in timing_variants(op):
        if spec['overpayment'] not in candidates:candidates.append(spec['overpayment'])
    return candidates


@fixed
def scenario(i: Inputs, request: dict, context: dict | None = None) -> dict:
    """Search all disclosed purchase choices under one changed scenario, preserving origin."""
    c=normal_context(context);spec=request.get('scenario',{})
    if not isinstance(spec,dict):raise ValueError('Scenario must be an object.')
    kind=spec.get('kind')
    allowed={'investment':{'kind','investment_return','stress'},'rates':{'kind','fixed_deals','continuation_rate','rate_path','post_rate','fixed_months','renewal_months'},'household':{'kind','changes'},'overpayment':{'kind','intent','overpayment'}}
    if kind not in allowed or set(spec)-allowed[kind]:raise ValueError('Unsupported scenario kind or fields.')
    changes={};intent=None
    if kind=='investment':
        if 'investment_return' in spec:changes['investment_return']=spec['investment_return']
        c=normal_context({**c,'stress':spec.get('stress',c['stress'])})
    elif kind=='rates':
        changes={k:v for k,v in spec.items() if k!='kind'}
        if 'fixed_deals' not in changes:changes['fixed_deals']=[]
    elif kind=='household':
        changes=spec.get('changes',{})
        if not isinstance(changes,dict):raise ValueError('Household changes must be an object.')
    else:
        intent=spec.get('intent')
        if intent not in ('commitment','optional'):raise ValueError('Choose commitment or optional overpayments.')
        c=normal_context({**c,'overpayment':spec.get('overpayment',{})})
    working,errors=parse_inputs({**input_json(i),**changes})
    if errors:return {'status':'invalid','issues':errors,'version':VERSION}
    year=whole_month(request.get('year',30))
    if not 0<=year<=40:raise ValueError('Scenario year must be 0–40.')
    raw_d,raw_t=request['original'].split('@');deposit=D(raw_d);term=whole_month(raw_t)
    if not deposit.is_finite() or not 1<=term<=40 or deposit!=deposit.quantize(PENNY):raise ValueError('Invalid original purchase choice.')
    original_id=plan_id(deposit,term);month=year*12
    terms=sorted(set(range(working.term_min,working.term_max+1,working.term_step))|{working.term_max})
    choices=[(d,t) for t in terms for d in deposit_grid(working)]
    if (deposit,term) not in choices:choices.append((deposit,term))
    schedules=optional_schedules(c['overpayment']) if intent=='optional' else [c['overpayment']]
    evaluated=[]
    for d,t in choices:
        variants=[]
        for op in schedules:
            candidate_context={**c,'overpayment':op}
            p=context_project(working,d,t,candidate_context,None if (d,t)==(deposit,term) else month)
            funded=p['status']=='ok' and not p['issues'] and len(p['rows'])>month and p['rows'][month]['eligible']
            variants.append((p,candidate_context,funded))
        eligible=[v for v in variants if v[2]]
        winner=max(eligible,key=lambda v:v[0]['rows'][month]['net'],default=None)
        evaluated.append(winner or variants[0])
    original,original_context,original_funded=next(v for v in evaluated if v[0]['id']==original_id)
    funded=[v for v in evaluated if v[2] and working.term_min<=v[0]['term']<=working.term_max]
    best=max(funded,key=lambda v:v[0]['rows'][month]['net'],default=None)
    if best and original_funded and working.term_min<=term<=working.term_max and original['rows'][month]['net']==best[0]['rows'][month]['net']:
        best=(original,original_context,True)
    best_plan,best_context=(best[0],best[1]) if best else (None,c)
    maximum=best_plan['rows'][month]['net'] if best else None
    ties=[p['id'] for p,_,_ in funded if p['rows'][month]['net']==maximum]
    near=[{'id':p['id'],'deposit':money(p['deposit']),'deposit_exact':str(p['deposit']),'term':p['term'],'cost':money(maximum-p['rows'][month]['net']),'accessible':money(p['rows'][month]['accessible'])} for p,_,_ in funded if maximum-p['rows'][month]['net']<=D(5000)]
    shortfall=None
    if original['status']=='ok' and original['first_breach'] is not None and original['first_breach']<=month:
        row=original['rows'][original['first_breach']]
        shortfall={'month':row['month'],'amount':money(row['shortfall']),'required':money(row['required_payment']),'limit':money(working.monthly)}
    outcome='no_funded' if best is None else 'original_unfunded' if not original_funded else 'same' if original_id in ties else 'changed'
    scope=f'{len(choices)} evaluated purchase choices: sampled deposits × tested terms, plus exact original. Original outside the changed permitted term range is reference only. Best evaluated only.'
    if intent=='optional':scope+=' Optional schedules: no overpayments at all, entered schedule, final event omitted or half/full at availability-clipped start/mid/end; earlier events and regular payments fixed in other variants. Original compared using its best eligible schedule; full planned schedule delivery required, mortgage funding through target year.'
    elif intent=='commitment':scope+=' Entered overpayments held fixed; full planned schedule delivery required, mortgage funding through target year.'
    fixed_comparison=None
    if kind=='overpayment':
        without=context_project(working,deposit,term,{**c,'overpayment':None});entered=context_project(working,deposit,term,c)
        comparable=without['status']=='ok' and entered['status']=='ok' and without['rows'][month]['eligible'] and entered['rows'][month]['eligible'] and not entered['issues']
        fixed_comparison={'without':serial_plan(without,True),'with':serial_plan(entered,True),'net_difference':money(entered['rows'][month]['net']-without['rows'][month]['net']) if comparable else None,'interest_saving':money(without['rows'][month]['interest_total']-entered['rows'][month]['interest_total']) if comparable else None,'common_period_months':month}
    original_serial=serial_plan(original)
    return {'status':'ok','version':VERSION,'effective_from':EFFECTIVE,'outcome':outcome,'original_plan':original_serial,'best_plan':serial_plan(best_plan) if best_plan else None,'original_monthly':serial_plan(original,True),'best_monthly':serial_plan(best_plan,True) if best_plan else None,'original_funded':original_funded,'cost_to_keep':money(maximum-original['rows'][month]['net']) if best and original_funded else None,'first_shortfall':shortfall,'ties':ties,'near_best':near,'tolerance':'5000.00','candidate_count':len(choices),'schedule_count':len(schedules),'issues':original.get('issues',[]) if not original_funded else [],'skipped':original_serial.get('skipped',[]),'working_inputs':input_json(working),'context':c,'best_context':best_context,'original_context':original_context,'fixed_plan_comparison':fixed_comparison,'search_scope':scope}


@fixed
def bounds(i: Inputs, term: int, year: int, context: dict | None = None, deposit: D | None = None) -> dict:
    """Exact penny deposit regions per LTV slice; source-constrained schedules disclose samples."""
    if not 1<=term<=40 or not 0<=year<=40:raise ValueError('Term 1–40 and year 0–40 required.')
    c=normal_context(context);op=c['overpayment']
    if deposit is not None and (not deposit.is_finite() or deposit!=deposit.quantize(PENNY)):raise ValueError('Exact deposit must be a finite penny amount.')
    common={'version':VERSION,'term':term,'year':year,'context':c,'nearest':None,'issues':[]}
    if op and (D(str(op.get('regular','0'))) or D(str(op.get('lump','0'))) or any(D(str(e['amount'])) for e in op.get('events',[]))):
        deposits=set(deposit_grid(i))
        if deposit is not None:deposits.add(deposit)
        funded=[]
        for d in sorted(deposits):
            p=context_project(i,d,term,c)
            if p['status']=='ok' and p['rows'][year*12]['eligible'] and not p['issues']:funded.append(d)
        nearest=min(funded,key=lambda x:abs(x-deposit)) if funded and deposit is not None else None
        return {**common,'status':'unavailable','regions':[],'funded_choices':[money(d) for d in funded],'nearest_tested':money(nearest) if nearest is not None else None,'issues':['Exact continuous bounds unavailable for overpayment source/allowance constraints; funded tested deposits are discrete choices.'],'search_scope':'Sampled deposits plus requested exact deposit; full planned overpayment schedule and funding through the target year.'}
    ceil=lambda value:value.quantize(PENNY,rounding=ROUND_CEILING)
    floor=lambda value:value.quantize(PENNY,rounding=ROUND_FLOOR)
    capital=min(i.price,i.savings-i.costs-i.fee-i.reserve+i.committed)
    high=floor(capital);regions=[];previous=None
    # The required-payment envelope is homogeneous in opening principal inside a band.
    # Unlimited unit funding prevents arrears feedback; assets do not affect repayments.
    for bound,rate in i.bands:
        low=ceil(max(i.committed,i.price*(1-bound)))
        upper=high if previous is None else min(high,ceil(i.price*(1-previous))-PENNY)
        previous=bound
        if low>upper:continue
        initial_low=low
        unit=replace(i,price=D(1),savings=D(1),reserve=D(0),costs=D(0),fee=D(0),committed=D(0),monthly=D(100000),bands=((D(1),rate),))
        p=project(unit,D(0),term)
        envelope=max((r['required_payment'] for r in p['rows'][1:year*12+1]),default=D(0))
        if envelope:low=max(low,ceil(i.price-i.monthly/envelope))
        if low>upper:continue
        def eligible(d):
            plan=context_project(i,d,term,c)
            return plan['status']=='ok' and plan['rows'][year*12]['eligible']
        # Direct authority resolves fixed50 cancellation at the penny endpoint.
        while low<=upper and not eligible(low):low+=PENNY
        while low>initial_low and eligible(low-PENNY):low-=PENNY
        if low>upper:continue
        minimum_reason=f'£{money(i.monthly)} monthly limit' if low>initial_low else 'Purchase-committed funds' if low==ceil(i.committed) and i.committed else f'{bound*100}% maximum LTV'
        maximum_reason=f'£{money(i.reserve)} kept in reserve; costs and fee paid' if upper==high and high<i.price else 'Property price / available purchase capital' if upper==high else 'LTV band boundary'
        regions.append({'min':money(low),'max':money(upper),'min_reason':minimum_reason,'max_reason':maximum_reason})
    # Cash purchase is supported even when no mortgage band covers its zero principal.
    if high>=i.price and not any(D(r['min'])<=i.price<=D(r['max']) for r in regions):
        regions.append({'min':money(i.price),'max':money(i.price),'min_reason':'Cash purchase','max_reason':'Property price / available purchase capital'})
    regions.sort(key=lambda r:D(r['min']))
    candidates=[]
    if deposit is not None:
        candidates=[max(D(r['min']),min(D(r['max']),deposit)) for r in regions]
    nearest=min(candidates,key=lambda d:abs(d-deposit)) if candidates else None
    return {**common,'status':'ok','regions':regions,'nearest':money(nearest) if nearest is not None else None,'issues':[] if regions else [f'No deposit meets the £{money(i.monthly)} monthly limit and available purchase capital.']}


def respond(request: dict) -> dict:
    """Validated worker/library entry point with structured expected input outcomes."""
    i,issues=parse_inputs(request.get('inputs',{}))
    if issues:return {'status':'invalid','issues':issues,'version':VERSION}
    try:
        context=normal_context(request.get('context'))
        if request.get('action','calculate')=='calculate':return calculate(i,context)
        if request.get('action')=='scenario':return scenario(i,request,context)
        if request.get('action')=='bounds':return bounds(i,whole_month(request['term']),whole_month(request.get('year',30)),context,D(str(request['deposit'])) if 'deposit' in request else None)
        if request.get('action')=='select':
            deposit=D(str(request['deposit'])); raw_term=D(str(request['term']))
            if not deposit.is_finite() or not raw_term.is_finite() or raw_term!=raw_term.to_integral_value() or not 1<=raw_term<=40:
                return {'status':'invalid','issues':['Choose a finite deposit and a whole-year term from 1 to 40.']}
            if request.get('enforce_funding'):
                if deposit!=deposit.quantize(PENNY):raise ValueError('Penny deposit required.')
                year=whole_month(request.get('year',30))
                if not 0<=year<=40:raise ValueError('Year must be 0–40.')
                assessment=bounds(i,int(raw_term),year,context,deposit)
                exact=context_project(i,deposit,int(raw_term),context)
                if exact['status']!='ok' or not exact['rows'][year*12]['eligible'] or exact['issues']:
                    return {'status':'unfunded','version':VERSION,'plan':serial_plan(exact),'nearest':assessment['nearest'],'nearest_tested':assessment.get('nearest_tested'),'regions':assessment['regions'],'issues':exact.get('issues') or assessment['issues'] or ['Required payments exceed the household monthly limit.'],'reasons':assessment['issues'] or ['Deposit, monthly funding or overpayment commitment constraints.']}
            plan=context_project(i,deposit,int(raw_term),context)
            if plan['status']!='ok':return plan
            result=serial_plan(plan)
            reference=request.get('best_values',[])
            result['difference']=[money(plan['rows'][y*12]['net']-D(reference[y])) if len(reference)>y and reference[y] is not None else None for y in range(41)]
            result['near_best']=[False]*41
            return {'status':'ok','version':VERSION,'plan':result}
        if request.get('action')=='compare':return compare(i,request['selected'],request['pinned'],context)
        if request.get('action')=='analyse':return analyse(i,request['selected'],request.get('pinned'),request.get('options',{}),context)
        return {'status':'invalid','issues':['Unknown operation.'],'version':VERSION}
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):
        return {'status':'invalid','issues':['The requested plan or module settings are outside this experiment’s supported domain.'],'version':VERSION}
