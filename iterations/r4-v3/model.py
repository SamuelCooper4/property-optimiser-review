"""R4 isolated exploratory model. No production engine imports or probability model.

All finance is Python Decimal at fixed50. Renderer receives display strings only;
ranking, eligibility, deltas, ledgers and stress comparisons are computed here.
"""
from __future__ import annotations
from dataclasses import dataclass, fields, replace
from decimal import Decimal as D, Context, ROUND_HALF_UP, localcontext, InvalidOperation
from functools import wraps
from typing import Callable

VERSION = 'r4-exploratory-v3'
EFFECTIVE = '2026-11-03'
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
    return {f.name:([[str(a),str(b)] for a,b in i.bands] if f.name=='bands' else [[a,str(b)] for a,b in i.rate_path] if f.name=='rate_path' else
                   str(getattr(i,f.name)) if isinstance(getattr(i,f.name),D) else getattr(i,f.name)) for f in fields(i)}


def parse_inputs(raw: dict) -> tuple[Inputs | None,list[str]]:
    """Validate bounded prototype input; never silently relax a constraint."""
    errors=[]; values={}
    defaults=Inputs()
    try:
        for f in fields(defaults):
            v=raw.get(f.name,getattr(defaults,f.name))
            if f.name=='bands':values[f.name]=tuple((D(str(a)),D(str(b))) for a,b in v)
            elif f.name=='rate_path':
                if any(isinstance(a,bool) or D(str(a))!=D(str(a)).to_integral_value() for a,b in v):raise ValueError('Rate dates must be whole elapsed months.')
                values[f.name]=tuple((int(a),D(str(b))) for a,b in v)
            elif f.name=='post_rate':values[f.name]=None if v in ('',None) else D(str(v))
            elif f.name in ('fixed_months','renewal_months','term_min','term_max','term_step'):
                if isinstance(v,bool) or D(str(v))!=D(str(v)).to_integral_value():raise ValueError('Time values must be whole months or years.')
                values[f.name]=int(v)
            else:values[f.name]=D(str(v))
        i=Inputs(**values)
        decimals=[getattr(i,f.name) for f in fields(i) if isinstance(getattr(i,f.name),D)]+[v for band in i.bands for v in band]+[r for _,r in i.rate_path]
        if not all(x.is_finite() for x in decimals):raise ValueError('All amounts and rates must be finite numbers.')
        if not D('1000')<=i.price<=D('10000000'):errors.append('House price must be £1,000–£10,000,000 for this experiment.')
        for name in ('savings','costs','reserve','committed','fee'):
            if not 0<=getattr(i,name)<=D('10000000'):errors.append(f'{name.title()} must be £0–£10,000,000.')
        if not 0<=i.monthly<=D('100000'):errors.append('Monthly funding must be £0–£100,000.')
        if not D('-.5')<=i.investment_return<=D('.5') or not D('-.1')<=i.cash_return<=D('.25'):errors.append('Experiment return range: investment −50% to 50%; cash −10% to 25%.')
        if i.post_rate is not None and not 0<=i.post_rate<=D('.25'):errors.append('Post-deal rate must be 0%–25%.')
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
def project(i: Inputs, deposit: D, term_years: int, overpayment: dict | None = None, stress: str = 'base') -> dict:
    """Monthly existing-resource ledger; unfunded debt remains outstanding and ineligible."""
    unavailable={'id':plan_id(deposit,term_years),'status':'unavailable','rows':[]}
    if not isinstance(term_years,int) or not 1<=term_years<=40 or not deposit.is_finite():return {**unavailable,'issues':['Choose a finite deposit and a whole-year term from 1 to 40.']}
    rate=rate_for(i,deposit)
    if rate is None or not i.committed<=deposit<=min(i.price,i.savings-i.costs-i.fee-i.reserve+i.committed):return {**unavailable,'issues':['Deposit is outside the funded purchase/product domain.']}
    try:regular,start,end,allowance,charge_rate,treatment,events=overpayment_settings(overpayment or {})
    except (ValueError,TypeError,KeyError,InvalidOperation):return {**unavailable,'issues':['Invalid overpayment dates, amounts, sources, allowance or treatment.']}
    months=term_years*12;debt=i.price-deposit;opening_debt=debt;initial_rate=rate
    if i.fixed_months==0:rate=available_rate(i,0,initial_rate)
    opening=i.savings-i.costs-i.fee-i.reserve-deposit+i.committed
    opening_cohort=opening;later_cohort=D(0);investment=opening;cash=i.reserve
    cumulative_contributions=D(0);interest_total=D(0);withdrawal_total=D(0);total_charges=D(0);shortfall_total=D(0)
    payoff=0 if not debt else None;first_breach=None;issues=[];event_results=[]
    ledger=[{'source':'savings','use':name,'amount':value} for name,value in [('costs',i.costs),('fee',i.fee),('deposit',deposit-i.committed),('cash',i.reserve),('investment',investment)]]
    if i.committed:ledger.append({'source':'committed','use':'deposit','amount':i.committed})
    cash_factor=(1+i.cash_return)**(D(1)/12)
    annual=i.investment_return if stress!='low_return' else D('0')
    normal_factor=(1+annual)**(D(1)/12);recovery_factor=(1+D('.12'))**(D(1)/12)
    payment=repayment(debt,rate,months);initial_payment=payment;yearly_extra=D(0);year_open=debt;active_rate=rate
    rows=[dict(month=0,debt=debt,investment=investment,cash=cash,net=i.price+cash+investment-debt,equity=deposit,accessible=cash+investment,payment=D(0),required_payment=D(0),shortfall=D(0),shortfall_total=D(0),contribution=D(0),extra=D(0),lump=D(0),charge=D(0),interest=D(0),interest_total=D(0),principal_total=D(0),repaid_fraction=D(0),contributions=D(0),opening=opening,opening_cohort=opening,later_cohort=D(0),growth=D(0),headroom=i.monthly,rate=rate,assumed_rate=available_rate(i,0,initial_rate),renewal=False,eligible=True,withdrawals=D(0))]
    for month in range(1,MAX_MONTHS+1):
        if (month-1)%12==0:yearly_extra=D(0);year_open=debt
        elapsed=month-1
        renewal=(elapsed==i.fixed_months and (bool(i.rate_path) or i.post_rate is not None)) or (bool(i.rate_path) and elapsed>i.fixed_months and (elapsed-i.fixed_months)%i.renewal_months==0)
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
        elif requested_regular and 'Regular overpayment exceeds monthly surplus; skipped in affected months.' not in issues:issues.append('Regular overpayment exceeds monthly surplus; skipped in affected months.')
        for event in events:
            if event['month']!=month or not event['amount']:continue
            requested=min(event['amount'],debt);free=max(D(0),year_open*allowance-yearly_extra);cost=max(D(0),requested-free)*charge_rate
            source=event['source'];funding=investment if source=='investment' else max(D(0),cash-i.reserve) if source=='cash' else available
            if month<event['available_month'] or requested+cost>funding:
                reason='Event is before its funding availability date.' if month<event['available_month'] else 'Event exceeds its selected funding source; no payment applied.'
                issues.append(reason);event_results.append({**event,'paid':D(0),'charge':D(0),'issue':reason});continue
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
    return {'id':plan_id(deposit,term_years),'status':'ok','deposit':deposit,'term':term_years,'rate':rate,'ltv':opening_debt/i.price,'payment':initial_payment,'opening_investment':opening,'opening_cash':i.reserve,'opening_debt':opening_debt,'ledger':ledger,'rows':rows,'first_breach':first_breach,'payoff_month':payoff,'issues':issues,'interest_total':interest_total,'charges':total_charges,'events':event_results}


def serial_row(row: dict) -> dict:
    """Serialize a monthly state for chart/presentation; no client calculations."""
    with localcontext(Context(prec=50)):
        enriched={**row,'negative_debt':-row['debt'],'principal':row['payment']-row['interest'],'paid_interest':min(row['payment'],row['interest']),'paid_principal':max(D(0),row['payment']-row['interest']),'unpaid_interest':max(D(0),row['interest']-row['payment'])}
        return {k:(str(v) if k in ('rate','assumed_rate','repaid_fraction') else money(v)) if isinstance(v,D) else v for k,v in enriched.items()}


def serial_plan(p: dict, monthly: bool = False) -> dict:
    """Serialize one plan; annual chart samples use the same monthly authority."""
    if p['status']!='ok':return p
    result={k:(money(v) if k!='rate' and k!='ltv' else str(v)) if isinstance(v,D) else v for k,v in p.items() if k not in ('rows','ledger','events')}
    result['events']=[{k:money(v) if isinstance(v,D) else v for k,v in event.items()} for event in p.get('events',[])]
    result['deposit_exact']=str(p['deposit'])
    result['monthly_investment']=money(p['rows'][1]['contribution'])
    result['monthly_shortfall']=money(max(D(0),-p['rows'][1]['headroom']))
    result['ledger']=[{**entry,'amount':money(entry['amount'])} for entry in p['ledger']]
    result['rows']=[serial_row(r) for r in p['rows'] if monthly or r['month']%12==0]
    return result


@fixed
def calculate(i: Inputs) -> dict:
    """Evaluate the disclosed joint sampled domain; keep exact ties and exclusions."""
    terms=list(range(i.term_min,i.term_max+1,i.term_step))
    if terms[-1]!=i.term_max:terms.append(i.term_max)
    deposits=deposit_grid(i);plans=[project(i,d,t) for t in terms for d in deposits]
    best=[];best_values=[];ties=[]
    for year in range(41):
        eligible=[p for p in plans if p['rows'][year*12]['eligible']]
        maximum=max((p['rows'][year*12]['net'] for p in eligible),default=None)
        matching=[p['id'] for p in eligible if p['rows'][year*12]['net']==maximum]
        best.append(matching[0] if matching else None);best_values.append(str(maximum) if maximum is not None else None);ties.append(matching)
    serial=[]
    for p in plans:
        item=serial_plan(p)
        item['difference']=[money(p['rows'][year*12]['net']-D(best_values[year])) if best_values[year] is not None else None for year in range(41)]
        item['near_best']=[p['rows'][year*12]['eligible'] and best_values[year] is not None and D(best_values[year])-p['rows'][year*12]['net']<=D('5000') for year in range(41)]
        serial.append(item)
    best_by_term={str(term):[] for term in terms};ties_by_term={str(term):[] for term in terms};ridge_by_term={str(term):[] for term in terms}
    for term in terms:
        family=[p for p in plans if p['term']==term]
        for year in range(41):
            eligible=[p for p in family if p['rows'][year*12]['eligible']]
            winner=max(eligible,key=lambda p:p['rows'][year*12]['net'],default=None)
            best_by_term[str(term)].append(winner['id'] if winner else None)
            matches=[p['id'] for p in eligible if winner and p['rows'][year*12]['net']==winner['rows'][year*12]['net']]
            ties_by_term[str(term)].append(matches)
            ridge_by_term[str(term)].append({'year':year,'ids':matches,'unique':matches[0] if len(matches)==1 else None,'eligible_count':len(eligible)})
    boundaries=[{'ltv':str(bound),'deposit':str(i.price*(1-bound)),
                 'rate':str(available_rate(i,0,rate) if i.fixed_months==0 else rate)}
                for bound,rate in i.bands]
    return {'ties_by_term':ties_by_term,'ridge_by_term':ridge_by_term,'best_by_term':best_by_term,'boundaries':boundaries,'status':'ok','version':VERSION,'effective_from':EFFECTIVE,'inputs':input_json(i),'plans':serial,'best':best,'best_value_exact':best_values,'ties':ties,'terms':terms,'deposits':[str(d) for d in deposits],'near_best_tolerance_gbp':'5000.00','issues':[] if plans else ['No deposit can meet the entered capital and LTV limits.'],'search':f'{len(deposits)} deposits × {len(terms)} terms; inclusive thresholds ±£0.01, endpoints and {GRID_INTERVALS} grid intervals. Best among evaluated options only.'}


@fixed
def compare(i: Inputs, selected: str, pinned: str) -> dict:
    """Compare two fixed complete plans over all monthly dates with shared resources."""
    d,t=selected.split('@');pd,pt=pinned.split('@')
    if not 1<=int(t)<=40 or not 1<=int(pt)<=40:raise ValueError('Invalid term.')
    base=project(i,D(d),int(t));pin=project(i,D(pd),int(pt))
    if base['status']!='ok':return base
    if pin['status']!='ok':return pin
    return {'status':'ok','version':VERSION,'selected':selected,'pinned':pinned,'base':serial_plan(base,True),'pin':serial_plan(pin,True),'pair_difference':[money(exact_sum(a['net'],b['net'].copy_negate())) for a,b in zip(base['rows'],pin['rows'])]}


@fixed
def return_comparison(i: Inputs, deposit: D, term: int, other_deposit: D, other_term: int, month: int) -> tuple[list[dict],list[dict]]:
    """Fixed-plan annual-return grid; strict sign changes yield sampled intervals."""
    curve=[]
    for n in range(-4,13):
        rate=D(n)/100;a=project(replace(i,investment_return=rate),deposit,term);b=project(replace(i,investment_return=rate),other_deposit,other_term)
        difference=exact_sum(a['rows'][month]['net'],b['rows'][month]['net'].copy_negate())
        eligible=a['rows'][month]['eligible'] and b['rows'][month]['eligible']
        curve.append({'return':str(rate),'eligible':eligible,'net':money(a['rows'][month]['net']) if eligible else None,'pin':money(b['rows'][month]['net']) if eligible else None,'difference':money(difference) if eligible else None,'difference_exact':str(difference) if eligible else None})
    brackets=[{'from':a['return'],'to':b['return']} for a,b in zip(curve,curve[1:]) if a['eligible'] and b['eligible'] and D(a['difference_exact'])*D(b['difference_exact'])<0]
    return curve,brackets


@fixed
def analyse(i: Inputs, selected: str, pinned: str | None, options: dict) -> dict:
    """Fixed-plan analyses; never silently reoptimise a stress scenario."""
    d,t=selected.split('@');deposit=D(d);term=int(t)
    base=project(i,deposit,term)
    if base['status']!='ok':return base
    pin_d,pin_t=(pinned or selected).split('@');pin=project(i,D(pin_d),int(pin_t))
    year=int(options.get('year',30));month=year*12
    if not 1<=year<=40:return {'status':'invalid','issues':['Comparison year must be 1–40.']}
    if pin['status']!='ok':return pin
    stress=[]
    for key,label in [('base','Entered return'),('low_return','No investment growth'),('early_fall','Early fall · year 2'),('late_fall','Late fall · year 20'),('slow_recovery','Fall · slow recovery')]:
        path=project(i,deposit,term,stress=key);other=project(i,D(pin_d),int(pin_t),stress=key)
        stress.append({'key':key,'label':label,'shock_month':{'early_fall':24,'late_fall':240,'slow_recovery':120}.get(key),'recovery_end_month':{'early_fall':84,'late_fall':300}.get(key),'shock_fraction':'0.35' if key in ('early_fall','late_fall','slow_recovery') else None,'recovery_rate':'0.12' if key in ('early_fall','late_fall') else None,'plan':serial_plan(path),'pin':serial_plan(other),'difference':money(path['rows'][month]['net']-other['rows'][month]['net'])})
    return_curve,brackets=return_comparison(i,deposit,term,D(pin_d),int(pin_t),month)
    rate=D(str(options.get('rate','.07')))
    if not rate.is_finite() or not 0<=rate<=D('.25'):return {'status':'invalid','issues':['Stress rate must be 0%–25%.']}
    changed=replace(i,post_rate=rate,rate_path=())
    if 'rate_path' in options:
        changed,errors=parse_inputs({**input_json(i),'rate_path':options['rate_path'],'renewal_months':options.get('renewal_months',i.renewal_months),'fixed_months':options.get('fixed_months',i.fixed_months)})
        if errors:return {'status':'invalid','issues':errors}
    rate_plan=project(changed,deposit,term);rate_pin=project(changed,D(pin_d),int(pin_t))
    op=options.get('overpayment',{'lump':'10000','month':60,'regular':'100','source':'investment','treatment':'term','allowance':'0.1','charge_rate':'0'})
    over=project(i,deposit,term,op)
    variants={}
    for key,settings in [('lump_only',{**op,'regular':'0'}),('regular_only',{**op,'lump':'0','events':[]})]:
        variant=project(i,deposit,term,settings)
        variants[key]={'plan':serial_plan(variant,True),'difference':money(exact_sum(variant['rows'][month]['net'],base['rows'][month]['net'].copy_negate())) if variant['status']=='ok' else None}
    schedules=[]
    start=whole_month(op.get('window_start',12));end=whole_month(op.get('window_end',120))
    if not 1<=start<=end<=480:return {'status':'invalid','issues':['Overpayment search window must be ordered months from 1 to 480.']}
    events=list(op.get('events',[]));target=events[-1] if events else {'amount':op.get('lump','0'),'source':op.get('source','investment'),'available_month':op.get('available_month',1)}
    available_month=whole_month(target.get('available_month',1));lower=max(start,available_month)
    times=sorted({lower,(lower+end)//2,end}) if lower<=end else []
    # Omit the targeted event once; retaining those resources is the fair baseline.
    candidate_specs=[(start,D(0))]+[(when,D(str(target['amount']))*multiplier) for when in times for multiplier in (D('.5'),D(1)) if D(str(target['amount']))]
    if op.get('search_requested') is False:candidate_specs=[]
    seen=set()
    for when,amount in candidate_specs:
        key=(when,amount) if amount else (None,D(0))
        if key in seen:continue
        seen.add(key)
        if events:candidate={**op,'lump':'0','events':events[:-1]+([{**target,'month':when,'amount':str(amount)}] if amount else [])}
        else:candidate={**op,'month':when,'lump':str(amount)}
        p=project(i,deposit,term,candidate)
        valid=p['status']=='ok' and not p['issues'] and p['rows'][month]['eligible']
        schedules.append({'month':when,'amount':str(amount),'source':target.get('source','investment'),'available_month':available_month,'eligible':valid,'net':money(p['rows'][month]['net']) if p['status']=='ok' else None,'net_exact':str(p['rows'][month]['net']) if p['status']=='ok' else None,'issues':p['issues']})
    feasible=[s for s in schedules if s['eligible']];best_schedule=max(feasible,key=lambda s:D(s['net_exact']),default=None)
    schedule_ties=[s for s in feasible if best_schedule and D(s['net_exact'])==D(best_schedule['net_exact'])]
    sensitivity=[]
    for key,label,change in [('return','Investment return −2 percentage points',replace(i,investment_return=i.investment_return-D('.02'))),('later','Post-deal mortgage rate +2 percentage points',replace(i,post_rate=(i.post_rate if i.post_rate is not None else base['rate'])+D('.02'),rate_path=tuple((m,r+D('.02')) for m,r in i.rate_path))),('cash','Cash return +1 percentage point',replace(i,cash_return=i.cash_return+D('.01'))),('monthly','Monthly funding −£200',replace(i,monthly=max(D(0),i.monthly-D(200))))]:
        p=project(change,deposit,term)
        sensitivity.append({'key':key,'label':label,'difference':money(p['rows'][month]['net']-base['rows'][month]['net']),'eligible':p['rows'][month]['eligible']})
    sensitivity.sort(key=lambda x:abs(D(x['difference'])),reverse=True)
    terms=sorted(set(range(i.term_min,i.term_max+1,i.term_step))|{i.term_max})
    term_plans=[serial_plan(project(i,deposit,t)) for t in terms]
    recommended_term=whole_month(options.get('recommended_term',pin_t))
    if not 1<=recommended_term<=40:return {'status':'invalid','issues':['Recommended term must be 1?40 years.']}
    reference=project(i,deposit,recommended_term)
    term_returns,term_brackets=return_comparison(i,deposit,term,deposit,recommended_term,month)
    left=base['rows'][month];right=reference['rows'][month]
    term_comparison={'selected':serial_plan(base,True),'reference':serial_plan(reference,True),'difference':money(exact_sum(left['net'],right['net'].copy_negate())),'investment_difference':money(exact_sum(left['investment'],right['investment'].copy_negate())),'cash_difference':money(exact_sum(left['cash'],right['cash'].copy_negate())),'debt_difference':money(exact_sum(left['debt'],right['debt'].copy_negate())),'debt_effect':money(exact_sum(right['debt'],left['debt'].copy_negate())),'returns':term_returns,'break_even_brackets':term_brackets,'identical_plans':term==recommended_term,'pair_difference':[money(exact_sum(a['net'],b['net'].copy_negate())) for a,b in zip(base['rows'],reference['rows'])],'common_period_months':month,'selected_interest':money(left['interest_total']),'reference_interest':money(right['interest_total']),'longest_evaluated_term':i.term_max}
    return {'term_comparison':term_comparison,'term_plans':term_plans,'status':'ok','version':VERSION,'selected':selected,'pinned':pinned,'year':year,'base':serial_plan(base,True),'pin':serial_plan(pin,True),'pair_difference':[money(a['net']-b['net']) for a,b in zip(base['rows'],pin['rows'])],'stress':stress,'returns':return_curve,'break_even_brackets':brackets,'identical_plans':selected==pinned or pinned is None,'rate':{'value':str(rate),'plan':serial_plan(rate_plan,True),'pin':serial_plan(rate_pin,True),'difference':money(rate_plan['rows'][month]['net']-rate_pin['rows'][month]['net'])},'overpayment':{**variants,'options':op,'plan':serial_plan(over,True),'difference':money(over['rows'][month]['net']-base['rows'][month]['net']) if over['status']=='ok' else None,'search_scope':'Final one-off event only; zero once, half/full entered amount at availability-clipped start/mid/end. Earlier events and recurring schedule fixed. Existing resources only.','interest_saving':money(exact_sum(base['rows'][month]['interest_total'],over['rows'][month]['interest_total'].copy_negate())) if over['status']=='ok' else None,'common_period_months':month,'schedules':schedules,'best_schedule':best_schedule,'ties':schedule_ties},'sensitivity':sensitivity}


def respond(request: dict) -> dict:
    """Validated worker/library entry point with structured expected input outcomes."""
    i,issues=parse_inputs(request.get('inputs',{}))
    if issues:return {'status':'invalid','issues':issues,'version':VERSION}
    try:
        if request.get('action','calculate')=='calculate':return calculate(i)
        if request.get('action')=='select':
            deposit=D(str(request['deposit'])); raw_term=D(str(request['term']))
            if not deposit.is_finite() or not raw_term.is_finite() or raw_term!=raw_term.to_integral_value() or not 1<=raw_term<=40:
                return {'status':'invalid','issues':['Choose a finite deposit and a whole-year term from 1 to 40.']}
            plan=project(i,deposit,int(raw_term))
            if plan['status']!='ok':return plan
            result=serial_plan(plan)
            reference=request.get('best_values',[])
            result['difference']=[money(plan['rows'][y*12]['net']-D(reference[y])) if len(reference)>y and reference[y] is not None else None for y in range(41)]
            result['near_best']=[False]*41
            return {'status':'ok','version':VERSION,'plan':result}
        if request.get('action')=='compare':return compare(i,request['selected'],request['pinned'])
        if request.get('action')=='analyse':return analyse(i,request['selected'],request.get('pinned'),request.get('options',{}))
        return {'status':'invalid','issues':['Unknown operation.'],'version':VERSION}
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):
        return {'status':'invalid','issues':['The requested plan or module settings are outside this experiment’s supported domain.'],'version':VERSION}
