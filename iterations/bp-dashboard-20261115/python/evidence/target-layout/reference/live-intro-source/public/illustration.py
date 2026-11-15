"""Standalone bounded design-data provider; NOT the production successor engine.

Python Decimal only. The React/animation layer never evaluates this accounting.
M1/M4 normalized facts are authored offline and identified by source and hashes.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from decimal import Decimal as D, Context, ROUND_HALF_UP, ROUND_CEILING, localcontext
from pathlib import Path
from scenario import SCENARIO


FACTS = json.loads((Path(__file__).parent/'facts.json').read_text(encoding='utf-8'))

@dataclass(frozen=True)
class Policy:
    """Immutable, effective-dated fictional assumptions, in GBP and decimal rates."""
    version: str = 'r3-v12-illustration-2026-11-01-v1'
    effective_from: str = '2026-11-01'
    capital: D = D('140000')
    home: D = SCENARIO.home_gbp
    budget: D = D(FACTS['budget_gbp'])
    bands: tuple[tuple[D, D], ...] = SCENARIO.bands
    money_scale: D = D('1500000')
    reserve: D = SCENARIO.reserve_gbp


POLICY = Policy()



def money(amount: D) -> str:
    """Round only presentation GBP to pennies, HALF_UP."""
    rounded=amount.quantize(D('.01'),rounding=ROUND_HALF_UP)
    return '0.00' if not rounded else str(rounded)


def percentage(amount: D) -> str:
    """Concise percentage; no binary float conversion."""
    return format(amount*100,'f').rstrip('0').rstrip('.')+'%' if amount else '0%'


def rate_label(rate: D) -> str:
    """Explicitly mark abbreviated inputs; exact rates remain in the payload."""
    rounded=rate.quantize(D('.00001'),rounding=ROUND_HALF_UP)
    return ('\u2248' if rounded!=rate else '')+percentage(rounded)


def ltv_label(ltv: D) -> str:
    """One decimal, marking any near-boundary value above the exact boundary."""
    rounded=ltv.quantize(D('.001'),rounding=ROUND_HALF_UP)
    if any(rounded==bound and ltv>bound for bound,_ in POLICY.bands):
        return '>'+percentage(rounded)
    return percentage(rounded)


def minimum_affordable_deposit(budget: D = POLICY.budget) -> D | None:
    """Least fixed50 directly affordable deposit across inclusive LTV bands."""
    with localcontext(Context(prec=50)) as ctx:
        candidates=[]
        for index,(maximum,rate) in enumerate(POLICY.bands):
            low=POLICY.home*(1-maximum)
            high=POLICY.home*(1-POLICY.bands[index-1][0]) if index else POLICY.home
            unit=D(FACTS['mortgages'][str(rate)]['payment'])
            candidate=max(low,POLICY.home-budget/unit)
            while candidate<high and (POLICY.home-candidate)*unit>budget:
                candidate=candidate.next_plus(ctx)
            while candidate>low and (POLICY.home-candidate.next_minus(ctx))*unit<=budget:
                candidate=candidate.next_minus(ctx)
            if candidate<=POLICY.capital and candidate<high:
                candidates.append(candidate)
        return min(candidates) if candidates else None


def _plan(deposit: D, investment: D, fixed_rate: D | None = None) -> dict:
    ltv=(POLICY.home-deposit)/POLICY.home
    rate=fixed_rate if fixed_rate is not None else next(rate for maximum,rate in POLICY.bands if ltv<=maximum)
    facts=FACTS['mortgages'][str(rate)]; debt=POLICY.home-deposit
    payment=debt*D(facts['payment']); interest=debt*D(facts['interest'])
    base=FACTS['mortgages'][str(POLICY.bands[-1][1])]
    index=next(i for i,(maximum,_) in enumerate(POLICY.bands) if ltv<=maximum)
    old_rate=POLICY.bands[min(index+1,len(POLICY.bands)-1)][1]
    old_interest=debt*D(FACTS['mortgages'][str(old_rate)]['interest'])
    comparison={'principal':money(debt),'term_months':360,'old_rate':str(old_rate),
        'old_rate_label':rate_label(old_rate),
        'old_interest':money(old_interest),'new_interest':money(interest),
        'saving':money(old_interest-interest)}
    return {'deposit_exact':str(deposit),'debt_exact':str(debt),'investment_exact':str(investment),'cash_exact':str(POLICY.reserve+POLICY.capital-deposit-investment),'deposit':money(deposit),'debt':money(debt),'retained':money(POLICY.capital-deposit),
            'outside_at_purchase':money(POLICY.reserve+POLICY.capital-deposit),
            'investment':money(investment),'cash':money(POLICY.reserve+POLICY.capital-deposit-investment),
            'rate':str(rate),'rate_label':rate_label(rate),'ltv':str(ltv),
            'ltv_label':ltv_label(ltv),'ltv_exact_label':percentage(ltv),
            'affordable':payment<=POLICY.budget,'payment':money(payment),'payment_exact':str(payment),'contribution':money(POLICY.budget-payment),
            'contribution_exact':str(POLICY.budget-payment),
            'next_threshold':int(next((POLICY.home*(1-b) for b,_ in reversed(POLICY.bands) if POLICY.home*(1-b)>deposit),POLICY.capital)),
            'rate_comparison':comparison,'reserve':money(POLICY.reserve),
            'first_payment':{'interest':money(debt*rate/12),'principal':money(D(money(payment))-D(money(debt*rate/12))),'interest_fraction':str((debt*rate/12)/payment)},
            'interest':money(interest),'baseline_interest':money(debt*D(base['interest'])),
            'deposit_fraction':str(deposit/POLICY.home),'retained_fraction':str((POLICY.capital-deposit)/POLICY.capital),
            'payment_fraction':str(payment/POLICY.budget),'interest_fraction':str(interest/(debt*D(base['interest']))),
            'max_investment':int(POLICY.capital-deposit)}


def _rows(plan: dict, opening_only: bool = False) -> list[dict]:
    debt=D(plan['debt_exact']); initial=D(plan['investment_exact']); cash=D(plan['cash_exact'])
    facts=FACTS['mortgages'][plan['rate']]; payment=debt*D(facts['payment'])
    capacity=D(0) if opening_only else POLICY.budget-payment
    rows=[]
    for month, factors in enumerate(FACTS['factors']):
        opening_factor,later_factor,cash_factor=map(D,factors)
        closing,actual,interest=(debt,D(0),D(0)) if month==0 else tuple(debt*D(x) for x in facts['months'][month-1])
        # Only a sub-precision final payment adjustment differs from the regular
        # payment in this fixed-rate design. Include it in the final contribution.
        residual=(POLICY.budget-payment)*month+(payment-actual if month==360 else D(0)) if opening_only else D(0)
        adjustment=payment-actual if month==360 and not opening_only else D(0)
        total=money(initial*opening_factor+capacity*later_factor+adjustment)
        later=money(capacity*later_factor+adjustment)
        opening=money(D(total)-D(later))
        contributed=money(capacity*month+adjustment)
        display_payment=money(actual if month else payment)
        contribution='0.00' if opening_only else money(D(money(POLICY.budget))-D(display_payment))
        rows.append({'month':month,'debt':money(closing),'repaid':money(debt-D(money(closing))),
            'payment':display_payment,'contribution_month':contribution,'interest_paid':money(interest),
            'payment_exact':str(actual if month else payment),
            'contribution_exact':str(D(0) if opening_only else POLICY.budget-(actual if month else payment)),
            'reconciliation_month_exact':str(POLICY.budget-(actual if month else payment) if opening_only else D(0)),
            'reconciliation_cash_exact':str(residual),
            'net_position':money(POLICY.home+cash*cash_factor+initial*opening_factor+capacity*later_factor+adjustment+residual-closing),
            'net_exact':str(POLICY.home+cash*cash_factor+initial*opening_factor+capacity*later_factor+adjustment+residual-closing),
            'cash_value':money(cash*cash_factor),'opening_value':opening,'later_value':later,
            'outside_total':money(D(money(cash*cash_factor))+D(total)),
            'outside_exact':str(cash*cash_factor+initial*opening_factor+capacity*later_factor+adjustment),
            'investment_value':total,'contributions':contributed,
            'opening_change':money(D(opening)-initial),'later_change':money(D(later)-D(contributed)),
            'investment_change':money(D(total)-initial-D(contributed)),
            'before_investment_value':money(D(total)-D(contribution)) if month else total,
            'before_later_value':money(D(later)-D(contribution)) if month else later,
            'payments_completed_fraction':str(D(month)/360),
            'payments_completed_label':f'{month} of 360 payments',
            'scheduled_payments_total':money(payment*360),
            'payments_made':money(payment*month+actual-payment if month==360 else payment*month),
            'repaid_fraction':str((debt-closing)/debt)})
    return rows


def respond(request: dict) -> dict:
    """Return a single illustrative allocation and optional monthly timeline.

    Inputs are whole-pound integers or the symbolic exact minimum endpoint;
    output money is Decimal text. Ambient
    context cannot alter accounting. Expected input failures are structured.
    """
    if 'transition_from' in request:
        start=request['transition_from']
        minimum=minimum_affordable_deposit()
        if type(start) is not int or not minimum.to_integral_value(rounding=ROUND_CEILING)<=start<=POLICY.capital:
            return {'status':'invalid','issues':[{'field':'transition_from','message':'Use a supported whole-pound selection.'}]}
        with localcontext(Context(prec=50)):
            minimum=minimum_affordable_deposit()
            deposits=[int((D(start)+(minimum-D(start))*D(i)/40).to_integral_value(rounding=ROUND_CEILING)) for i in range(40)]
        return {'status':'ok','transition':[respond({'deposit':d,'investment':0}) for d in deposits]+[respond({'deposit':'minimum','investment':0})]}
    if request.get('comparison') is True:
        larger=respond({'deposit':140000,'investment':0,'timeline':True})
        smaller=respond({'deposit':'minimum','investment':'remaining','timeline':True,'opening_only':True})
        larger['scale_gbp']=smaller['scale_gbp']='800000.00'
        with localcontext(Context(prec=50)):
            differences=[]; viewports=[]
            for a,b in zip(smaller['rows'],larger['rows']):
                av,bv=D(a['net_exact']),D(b['net_exact'])
                differences.append({'month':a['month'],'net_difference':money(av-bv)})
                span=max(D(100000),abs(av-bv)*D('2.2'))
                centre=(av+bv)/2
                viewports.append({'min':str(centre-span/2),'max':str(centre+span/2)})
            difference=D(differences[-1]['net_difference'])
            final_difference=money(abs(difference))
        return {'status':'ok','comparison':{'larger':larger,'smaller':smaller,'differences':differences,
            'viewports':viewports,'winner':'smaller' if difference>0 else 'larger' if difference<0 else 'tie',
            'final_difference':final_difference}}
    raw=request.get('deposit'); investment=request.get('investment')
    if not (type(raw) is int and 45000<=raw<=140000) and raw!='minimum':
        return {'status':'invalid','issues':[{'field':'deposit','message':'Use whole pounds within the supported range or the exact minimum endpoint.'}]}
    with localcontext(Context(prec=50)):
        minimum=minimum_affordable_deposit()
        deposit=minimum if raw=='minimum' else D(raw)
        if deposit<minimum:
            return {'status':'infeasible','issues':[{'field':'deposit','code':'monthly_funding_shortfall','message':'Deposit is below the affordable minimum.'}]}
        if investment=='remaining':
            investment=POLICY.capital-deposit
        elif type(investment) is int and 0<=investment<=POLICY.capital-deposit:
            investment=D(investment)
        else:
            return {'status':'invalid','issues':[{'field':'investment','message':'Use whole pounds within retained capital.'}]}
        opening_only=request.get('opening_only') is True
        if opening_only and raw!='minimum':
            return {'status':'invalid','issues':[{'field':'deposit','message':'Opening-only comparison requires the exact payment boundary.'}]}
        plan=_plan(deposit,investment)
        if opening_only:
            plan['contribution']='0.00'; plan['contribution_exact']='0'
        result={'status':'ok','version':POLICY.version,'facts_version':FACTS['version'],
            'interest_scale_gbp':money(D(405000)*D(FACTS['mortgages']['0.06']['interest'])),
            'scale_gbp':money(POLICY.money_scale),'graph_scale_gbp':'1500000.00',
            'pricing_bands':[{'threshold':int(POLICY.home*(1-b)),'ltv':percentage(b),'rate':str(r),'label':rate_label(r)} for b,r in reversed(POLICY.bands)],
            'minimum_affordable_deposit':str(minimum),'minimum_display':money(minimum),'budget_gbp':money(POLICY.budget),'budget_exact':str(POLICY.budget),
            'teaching':{'deposit':SCENARIO.deposit_gbp,'investment':SCENARIO.investment_gbp,'version':SCENARIO.version},
            'effective_from':POLICY.effective_from,'plan':plan,
            'fixed_rate_plan':_plan(deposit,investment,SCENARIO.interest_lesson_rate),
            'total_resources':money(POLICY.capital+POLICY.reserve),'reserve_gbp':money(POLICY.reserve),
            'ledger':[{'source':'cash_after_costs','use':use,'amount':plan[key],'amount_exact':plan[key+'_exact']}
                for use,key in [('deposit','deposit'),('retained_cash','cash'),('investment','investment')]],
            'excluded_sources':{'lisa':'0.00','home_equity':'0.00'},'issues':[]}
        if request.get('timeline'):
            result['rows']=_rows(plan,opening_only)
        return result
