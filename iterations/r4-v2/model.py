"""R4 isolated exploratory model. No production engine imports or probability model.

All finance is Python Decimal at fixed50. Renderer receives display strings only;
ranking, eligibility, deltas, ledgers and stress comparisons are computed here.
"""
from __future__ import annotations
from dataclasses import dataclass, fields, replace
from decimal import Decimal as D, Context, ROUND_HALF_UP, localcontext, InvalidOperation
from functools import wraps
from typing import Callable

VERSION = 'r4-exploratory-v2'
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
    return {f.name:([[str(a),str(b)] for a,b in i.bands] if f.name=='bands' else
                   str(getattr(i,f.name)) if isinstance(getattr(i,f.name),D) else getattr(i,f.name)) for f in fields(i)}


def parse_inputs(raw: dict) -> tuple[Inputs | None,list[str]]:
    """Validate bounded prototype input; never silently relax a constraint."""
    errors=[]; values={}
    defaults=Inputs()
    try:
        for f in fields(defaults):
            v=raw.get(f.name,getattr(defaults,f.name))
            if f.name=='bands':values[f.name]=tuple((D(str(a)),D(str(b))) for a,b in v)
            elif f.name=='post_rate':values[f.name]=None if v in ('',None) else D(str(v))
            elif f.name in ('fixed_months','term_min','term_max','term_step'):
                if isinstance(v,bool) or D(str(v))!=D(str(v)).to_integral_value():raise ValueError('Time values must be whole months or years.')
                values[f.name]=int(v)
            else:values[f.name]=D(str(v))
        i=Inputs(**values)
        decimals=[getattr(i,f.name) for f in fields(i) if isinstance(getattr(i,f.name),D)]+[v for band in i.bands for v in band]
        if not all(x.is_finite() for x in decimals):raise ValueError('All amounts and rates must be finite numbers.')
        if not D('1000')<=i.price<=D('10000000'):errors.append('House price must be £1,000–£10,000,000 for this experiment.')
        for name in ('savings','costs','reserve','committed','fee'):
            if not 0<=getattr(i,name)<=D('10000000'):errors.append(f'{name.title()} must be £0–£10,000,000.')
        if not 0<=i.monthly<=D('100000'):errors.append('Monthly funding must be £0–£100,000.')
        if not D('-.5')<=i.investment_return<=D('.5') or not D('-.1')<=i.cash_return<=D('.25'):errors.append('Experiment return range: investment −50% to 50%; cash −10% to 25%.')
        if i.post_rate is not None and not 0<=i.post_rate<=D('.25'):errors.append('Post-deal rate must be 0%–25%.')
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


@fixed
def project(i: Inputs, deposit: D, term_years: int, overpayment: dict | None = None, stress: str = 'base') -> dict:
    """Project 480 monthly ledgers for one fixed plan under explicit assumptions."""
    rate=rate_for(i,deposit)
    if rate is None or not i.committed<=deposit<=min(i.price,i.savings-i.costs-i.fee-i.reserve+i.committed):
        return {'id':plan_id(deposit,term_years),'status':'unavailable','issues':['Deposit is outside the funded purchase/product domain.'],'rows':[]}
    months=term_years*12; debt=i.price-deposit; opening_debt=debt
    if debt and i.fixed_months==0 and i.post_rate is not None:rate=i.post_rate
    investment=i.savings-i.costs-i.fee-i.reserve-deposit+i.committed; opening=investment
    cash=i.reserve; cumulative_contributions=D(0); interest_total=D(0); principal_total=D(0)
    withdrawal_total=D(0); total_charges=D(0); payoff=0 if not debt else None
    first_breach=None; issues=[]
    ledger=[{'source':'savings','use':name,'amount':value} for name,value in [('costs',i.costs),('fee',i.fee),('deposit',deposit-i.committed),('cash',i.reserve),('investment',investment)]]
    if i.committed:ledger.append({'source':'committed','use':'deposit','amount':i.committed})
    op=overpayment or {}; lump=D(str(op.get('lump','0'))); regular=D(str(op.get('regular','0')))
    op_month=int(op.get('month',60)); allowance=D(str(op.get('allowance','1'))); charge_rate=D(str(op.get('charge_rate','0')))
    source=op.get('source','investment'); treatment=op.get('treatment','term')
    if min(lump,regular,allowance,charge_rate)<0 or allowance>1 or charge_rate>1 or not 1<=op_month<=480 or source not in ('investment','monthly') or treatment not in ('term','payment'):
        return {'id':plan_id(deposit,term_years),'status':'unavailable','issues':['Invalid overpayment amount, month, source, allowance or treatment.'],'rows':[]}
    cash_factor=(1+i.cash_return)**(D(1)/12)
    annual=i.investment_return if stress!='low_return' else D('0')
    normal_factor=(1+annual)**(D(1)/12)
    recovery_factor=(1+D('.12'))**(D(1)/12)
    payment=repayment(debt,i.post_rate if i.fixed_months==0 and i.post_rate is not None else rate,months)
    initial_payment=payment; yearly_extra=D(0); year_open=debt
    rows=[dict(month=0,debt=debt,investment=investment,cash=cash,net=i.price+cash+investment-debt,equity=deposit,accessible=cash+investment,payment=D(0),contribution=D(0),extra=D(0),lump=D(0),charge=D(0),interest=D(0),interest_total=D(0),principal_total=D(0),contributions=D(0),opening=opening,growth=D(0),headroom=i.monthly,rate=rate,eligible=True,withdrawals=D(0))]
    for month in range(1,MAX_MONTHS+1):
        if (month-1)%12==0:yearly_extra=D(0);year_open=debt
        active_rate=i.post_rate if i.post_rate is not None and month>i.fixed_months else rate
        if debt and i.post_rate is not None and month==i.fixed_months+1:payment=repayment(debt,active_rate,months-month+1)
        factor=normal_factor
        shock_month={'early_fall':24,'late_fall':240,'slow_recovery':120}.get(stress)
        if shock_month and shock_month<month<=shock_month+60 and stress!='slow_recovery':factor=recovery_factor
        if shock_month==month:factor*=D('.65')
        if factor!=1:investment*=factor
        if cash_factor!=1:cash*=cash_factor
        interest=debt*active_rate/12; paid=min(payment,exact_sum(debt,interest)) if debt else D(0)
        if month==months:paid=exact_sum(debt,interest)
        headroom=exact_sum(i.monthly,paid.copy_negate())
        if headroom<0 and first_breach is None:first_breach=month
        interest_total=exact_sum(interest_total,interest);principal_total=exact_sum(principal_total,paid,interest.copy_negate());debt=max(D(0),exact_sum(debt,interest,paid.copy_negate()))
        extra=D(0);lump_paid=D(0);charge=D(0); available=max(D(0),headroom)
        requested_regular=min(regular,debt)
        free=max(D(0),year_open*allowance-yearly_extra)
        regular_charge=max(D(0),requested_regular-free)*charge_rate
        if requested_regular+regular_charge<=available:
            extra=requested_regular;charge=regular_charge;debt=exact_sum(debt,extra.copy_negate());available=exact_sum(available,extra.copy_negate(),charge.copy_negate());yearly_extra=exact_sum(yearly_extra,extra)
        elif requested_regular and 'Regular overpayment exceeds monthly surplus; skipped in affected months.' not in issues:issues.append('Regular overpayment exceeds monthly surplus; skipped in affected months.')
        if month==op_month and lump:
            requested=min(lump,debt);free=max(D(0),year_open*allowance-yearly_extra)
            cost=max(D(0),requested-free)*charge_rate
            funding=investment if source=='investment' else available
            if requested+cost<=funding:
                lump_paid=requested;debt=exact_sum(debt,requested.copy_negate());yearly_extra=exact_sum(yearly_extra,requested);charge=exact_sum(charge,cost)
                if source=='investment':investment=exact_sum(investment,requested.copy_negate(),cost.copy_negate());withdrawal_total=exact_sum(withdrawal_total,requested,cost)
                else:available=exact_sum(available,requested.copy_negate(),cost.copy_negate())
            else:issues.append('Lump sum exceeds its selected funding source; no lump sum was applied.')
        total_charges+=charge
        if treatment=='payment' and debt and (extra or lump_paid):payment=repayment(debt,active_rate,max(1,months-month))
        contribution=available;investment=exact_sum(investment,contribution);cumulative_contributions=exact_sum(cumulative_contributions,contribution)
        if debt==0 and payoff is None:payoff=month
        rows.append(dict(month=month,debt=debt,investment=investment,cash=cash,net=exact_sum(i.price,cash,investment,debt.copy_negate()),equity=exact_sum(i.price,debt.copy_negate()),accessible=exact_sum(cash,investment),payment=paid,contribution=contribution,extra=extra,lump=lump_paid,charge=charge,interest=interest,interest_total=interest_total,principal_total=principal_total,contributions=cumulative_contributions,opening=opening,growth=exact_sum(investment,opening.copy_negate(),cumulative_contributions.copy_negate(),withdrawal_total),headroom=headroom,rate=active_rate,eligible=first_breach is None,withdrawals=withdrawal_total))
    return {'id':plan_id(deposit,term_years),'status':'ok','deposit':deposit,'term':term_years,'rate':rate,'ltv':opening_debt/i.price,'payment':initial_payment,'opening_investment':opening,'opening_cash':i.reserve,'opening_debt':opening_debt,'ledger':ledger,'rows':rows,'first_breach':first_breach,'payoff_month':payoff,'issues':issues,'interest_total':interest_total,'charges':total_charges}


def serial_row(row: dict) -> dict:
    """Serialize a monthly state for chart/presentation; no client calculations."""
    with localcontext(Context(prec=50)):
        enriched={**row,'negative_debt':-row['debt'],'principal':row['payment']-row['interest']}
        return {k:(str(v) if k=='rate' else money(v)) if isinstance(v,D) else v for k,v in enriched.items()}


def serial_plan(p: dict, monthly: bool = False) -> dict:
    """Serialize one plan; annual chart samples use the same monthly authority."""
    if p['status']!='ok':return p
    result={k:(money(v) if k!='rate' and k!='ltv' else str(v)) if isinstance(v,D) else v for k,v in p.items() if k not in ('rows','ledger')}
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
    best_by_term={str(term):[] for term in terms}
    for term in terms:
        family=[p for p in plans if p['term']==term]
        for year in range(41):
            eligible=[p for p in family if p['rows'][year*12]['eligible']]
            winner=max(eligible,key=lambda p:p['rows'][year*12]['net'],default=None)
            best_by_term[str(term)].append(winner['id'] if winner else None)
    boundaries=[{'ltv':str(bound),'deposit':str(i.price*(1-bound)),
                 'rate':str(i.post_rate if i.fixed_months==0 and i.post_rate is not None else rate)}
                for bound,rate in i.bands]
    return {'best_by_term':best_by_term,'boundaries':boundaries,'status':'ok','version':VERSION,'effective_from':EFFECTIVE,'inputs':input_json(i),'plans':serial,'best':best,'best_value_exact':best_values,'ties':ties,'terms':terms,'deposits':[str(d) for d in deposits],'near_best_tolerance_gbp':'5000.00','issues':[] if plans else ['No deposit can meet the entered capital and LTV limits.'],'search':f'{len(deposits)} deposits × {len(terms)} terms; inclusive thresholds ±£0.01, endpoints and {GRID_INTERVALS} grid intervals. Best among evaluated options only.'}


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
        stress.append({'key':key,'label':label,'plan':serial_plan(path),'pin':serial_plan(other),'difference':money(path['rows'][month]['net']-other['rows'][month]['net'])})
    return_curve=[]
    for n in range(-4,13):
        rate=D(n)/100;a=project(replace(i,investment_return=rate),deposit,term);b=project(replace(i,investment_return=rate),D(pin_d),int(pin_t))
        difference=exact_sum(a['rows'][month]['net'],b['rows'][month]['net'].copy_negate())
        return_curve.append({'return':str(rate),'net':money(a['rows'][month]['net']),'pin':money(b['rows'][month]['net']),'difference':money(difference),'difference_exact':str(difference)})
    brackets=[{'from':a['return'],'to':b['return']} for a,b in zip(return_curve,return_curve[1:]) if D(a['difference_exact'])*D(b['difference_exact'])<0]
    rate=D(str(options.get('rate','.07')))
    if not rate.is_finite() or not 0<=rate<=D('.25'):return {'status':'invalid','issues':['Stress rate must be 0%–25%.']}
    changed=replace(i,post_rate=rate);rate_plan=project(changed,deposit,term);rate_pin=project(changed,D(pin_d),int(pin_t))
    op=options.get('overpayment',{'lump':'10000','month':60,'regular':'100','source':'investment','treatment':'term','allowance':'0.1','charge_rate':'0'})
    over=project(i,deposit,term,op)
    variants={}
    for key,settings in [('lump_only',{**op,'regular':'0'}),('regular_only',{**op,'lump':'0'})]:
        variant=project(i,deposit,term,settings)
        variants[key]={'plan':serial_plan(variant,True),'difference':money(exact_sum(variant['rows'][month]['net'],base['rows'][month]['net'].copy_negate())) if variant['status']=='ok' else None}
    schedules=[]
    start=int(op.get('window_start',12));end=int(op.get('window_end',120))
    if not 1<=start<=end<=480:return {'status':'invalid','issues':['Overpayment search window must be ordered months from 1 to 480.']}
    for when in (start,(start+end)//2,end):
        for multiplier in (D('0'),D('.5'),D('1')):
            candidate={**op,'month':when,'lump':str(D(str(op.get('lump','0')))*multiplier)}
            p=project(i,deposit,term,candidate)
            valid=p['status']=='ok' and not p['issues'] and p['rows'][month]['eligible']
            schedules.append({'month':when,'amount':candidate['lump'],'eligible':valid,'net':money(p['rows'][month]['net']) if p['status']=='ok' else None,'net_exact':str(p['rows'][month]['net']) if p['status']=='ok' else None,'issues':p['issues']})
    feasible=[s for s in schedules if s['eligible']];best_schedule=max(feasible,key=lambda s:D(s['net_exact']),default=None)
    schedule_ties=[s for s in feasible if best_schedule and D(s['net_exact'])==D(best_schedule['net_exact'])]
    sensitivity=[]
    for key,label,change in [('return','Investment return −2 percentage points',replace(i,investment_return=i.investment_return-D('.02'))),('later','Post-deal mortgage rate +2 percentage points',replace(i,post_rate=(i.post_rate if i.post_rate is not None else base['rate'])+D('.02'))),('cash','Cash return +1 percentage point',replace(i,cash_return=i.cash_return+D('.01'))),('monthly','Monthly funding −£200',replace(i,monthly=max(D(0),i.monthly-D(200))))]:
        p=project(change,deposit,term)
        sensitivity.append({'key':key,'label':label,'difference':money(p['rows'][month]['net']-base['rows'][month]['net']),'eligible':p['rows'][month]['eligible']})
    sensitivity.sort(key=lambda x:abs(D(x['difference'])),reverse=True)
    terms=sorted(set(range(i.term_min,i.term_max+1,i.term_step))|{i.term_max})
    term_plans=[serial_plan(project(i,deposit,t)) for t in terms]
    return {'term_plans':term_plans,'status':'ok','version':VERSION,'selected':selected,'pinned':pinned,'year':year,'base':serial_plan(base,True),'pin':serial_plan(pin,True),'pair_difference':[money(a['net']-b['net']) for a,b in zip(base['rows'],pin['rows'])],'stress':stress,'returns':return_curve,'break_even_brackets':brackets,'identical_plans':selected==pinned or pinned is None,'rate':{'value':str(rate),'plan':serial_plan(rate_plan,True),'pin':serial_plan(rate_pin,True),'difference':money(rate_plan['rows'][month]['net']-rate_pin['rows'][month]['net'])},'overpayment':{**variants,'options':op,'plan':serial_plan(over,True),'difference':money(over['rows'][month]['net']-base['rows'][month]['net']) if over['status']=='ok' else None,'schedules':schedules,'best_schedule':best_schedule,'ties':schedule_ties},'sensitivity':sensitivity}


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
        if request.get('action')=='analyse':return analyse(i,request['selected'],request.get('pinned'),request.get('options',{}))
        return {'status':'invalid','issues':['Unknown operation.'],'version':VERSION}
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):
        return {'status':'invalid','issues':['The requested plan or module settings are outside this experiment’s supported domain.'],'version':VERSION}
