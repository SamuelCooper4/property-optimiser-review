"""Standalone bounded design-data provider; NOT the production successor engine.

Python Decimal only. The React/animation layer never evaluates this accounting.
M1/M4 normalized facts are authored offline and identified by source and hashes.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from decimal import Decimal as D, Context, ROUND_HALF_UP, ROUND_CEILING, localcontext
from functools import lru_cache
from pathlib import Path
from scenario import SCENARIO


@dataclass(frozen=True)
class Policy:
    """Immutable, effective-dated fictional assumptions, in GBP and decimal rates."""
    version: str = 'r3-v5-illustration-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    capital: D = D('160000')
    home: D = D('400000')
    budget: D = D('2000')
    bands: tuple = ((D('.60'),D('.033')),(D('.65'),D('.035')),(D('.70'),D('.037')),
                    (D('.75'),D('.039')),(D('.80'),D('.041')),(D('.85'),D('.043')),(D('.90'),D('.045')))


POLICY = Policy()
FACTS = json.loads((Path(__file__).parent/'facts.json').read_text(encoding='utf-8'))


def money(amount: D) -> str:
    """Round only presentation GBP to pennies, HALF_UP."""
    return str(amount.quantize(D('.01'),rounding=ROUND_HALF_UP))


def percentage(amount: D) -> str:
    """Concise percentage; no binary float conversion."""
    return format(amount*100,'f').rstrip('0').rstrip('.')+'%' if amount else '0%'


def ltv_label(ltv: D) -> str:
    """One decimal, marking any near-boundary value above the exact boundary."""
    rounded=ltv.quantize(D('.001'),rounding=ROUND_HALF_UP)
    if any(rounded==bound and ltv>bound for bound,_ in POLICY.bands):
        return '>'+percentage(rounded)
    return percentage(rounded)


def _plan(deposit: D, investment: D) -> dict:
    ltv=(POLICY.home-deposit)/POLICY.home
    rate=next(rate for maximum,rate in POLICY.bands if ltv<=maximum)
    facts=FACTS['mortgages'][str(rate)]; debt=POLICY.home-deposit
    payment=debt*D(facts['payment']); interest=debt*D(facts['interest'])
    base=FACTS['mortgages']['0.045']
    return {'deposit':money(deposit),'debt':money(debt),'retained':money(POLICY.capital-deposit),
            'investment':money(investment),'cash':money(POLICY.capital-deposit-investment),
            'rate':str(rate),'rate_label':percentage(rate),'ltv':str(ltv),
            'ltv_label':ltv_label(ltv),'ltv_exact_label':percentage(ltv),
            'payment':money(payment),'contribution':money(POLICY.budget-D(money(payment))),
            'interest':money(interest),'baseline_interest':money(debt*D(base['interest'])),
            'deposit_fraction':str(deposit/POLICY.home),'retained_fraction':str((POLICY.capital-deposit)/POLICY.capital),
            'payment_fraction':str(payment/POLICY.budget),'interest_fraction':str(interest/(debt*D(base['interest']))),
            'max_investment':int(POLICY.capital-deposit)}


def _rows(plan: dict) -> list[dict]:
    debt=D(plan['debt']); initial=D(plan['investment']); cash=D(plan['cash'])
    facts=FACTS['mortgages'][plan['rate']]; payment=debt*D(facts['payment'])
    capacity=POLICY.budget-payment
    rows=[]
    for month, factors in enumerate(FACTS['factors']):
        opening_factor,later_factor,cash_factor=map(D,factors)
        closing,actual,interest=(debt,D(0),D(0)) if month==0 else tuple(debt*D(x) for x in facts['months'][month-1])
        # Only a sub-precision final payment adjustment differs from the regular
        # payment in this fixed-rate design. Include it in the final contribution.
        adjustment=payment-actual if month==360 else D(0)
        total=money(initial*opening_factor+capacity*later_factor+adjustment)
        later=money(capacity*later_factor+adjustment)
        opening=money(D(total)-D(later))
        contributed=money(capacity*month+adjustment)
        display_payment=money(actual if month else payment)
        contribution=money(POLICY.budget-D(display_payment))
        rows.append({'month':month,'debt':money(closing),'repaid':money(debt-D(money(closing))),
            'payment':display_payment,'contribution_month':contribution,'interest_paid':money(interest),
            'cash_value':money(cash*cash_factor),'opening_value':opening,'later_value':later,
            'outside_total':money(D(money(cash*cash_factor))+D(total)),
            'outside_exact':str(cash*cash_factor+initial*opening_factor+capacity*later_factor+adjustment),
            'investment_value':total,'contributions':contributed,
            'opening_change':money(D(opening)-initial),'later_change':money(D(later)-D(contributed)),
            'investment_change':money(D(total)-initial-D(contributed)),
            'before_investment_value':money(D(total)-D(contribution)) if month else total,
            'before_later_value':money(D(later)-D(contribution)) if month else later,
            'repaid_fraction':str((debt-closing)/POLICY.home)})
    return rows


def respond(request: dict) -> dict:
    """Return exact paired illustration data or structured whole-pound issues.

    Both choices share one policy and all 361 dates. Cached immutable facts are
    Decimal strings, and no caller's ambient Decimal context affects results.
    """
    deposit=request.get('deposit'); investment=request.get('investment')
    if type(deposit) is not int or not 40000<=deposit<=160000:
        return {'status':'invalid','issues':[{'field':'deposit','message':'Enter whole pounds from 40000 to 160000.'}]}
    if type(investment) is not int or not 0<=investment<=160000-deposit:
        return {'status':'invalid','issues':[{'field':'investment','message':'Use whole pounds within retained capital.'}]}
    with localcontext(Context(prec=50)):
        small=_plan(D(deposit),D(investment)); large=_plan(POLICY.capital,D(0))
        result={'status':'ok','version':POLICY.version,'facts_version':FACTS['version'],
            'scale_gbp':'2000000.00','cash_scale_gbp':'240000.00',
            'teaching':{'deposit':SCENARIO.deposit_gbp,'investment':SCENARIO.investment_gbp,'version':SCENARIO.version},
            'effective_from':POLICY.effective_from,'small':small,'large':large,
            'ledger':[{'source':'cash_after_costs_and_reserves','use':use,'amount':small[key]}
                      for use,key in [('deposit','deposit'),('retained_cash','cash'),('investment','investment')]],
            'excluded_sources':{'lisa':'0.00','home_equity':'0.00'},
            'issues':[]}
        if request.get('timeline'):
            a=_rows(small); b=_rows(large)
            result['cash_scale_gbp']=money(max(D(10000),(D(a[-1]['cash_value'])/10000).to_integral_value(rounding=ROUND_CEILING)*10000))
            result['rows']=[{'small':x,'large':y,'month':i} for i,(x,y) in enumerate(zip(a,b))]
            delta=D(a[-1]['outside_exact'])-D(b[-1]['outside_exact'])
            result['final']={'winner':'small' if delta>0 else 'large' if delta<0 else 'tie',
                'difference':money(D(a[-1]['outside_total'])-D(b[-1]['outside_total'])),
                'absolute_difference':money(abs(D(a[-1]['outside_total'])-D(b[-1]['outside_total']))),
                'difference_exact':str(delta)}
            result['before_first']={'month':1}
            for name,rows in [('small',a),('large',b)]:
                result['before_first'][name]={**rows[1],
                    'investment_value':rows[1]['opening_value'],'later_value':'0.00',
                    'outside_total':money(D(rows[1]['cash_value'])+D(rows[1]['opening_value'])),
                    'contributions':'0.00','later_change':'0.00',
                    'investment_change':rows[1]['opening_change']}
        return result
