"""Standalone bounded design-data provider; NOT the production successor engine.

Python Decimal only. The React/animation layer never evaluates this accounting.
M1/M4 normalized facts are authored offline and identified by source and hashes.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from decimal import Decimal as D, Context, ROUND_HALF_UP, localcontext
from pathlib import Path
from scenario import SCENARIO


FACTS = json.loads((Path(__file__).parent/'facts.json').read_text(encoding='utf-8'))

@dataclass(frozen=True)
class Policy:
    """Immutable, effective-dated fictional assumptions, in GBP and decimal rates."""
    version: str = 'r3-v9-illustration-2026-10-31-v1'
    effective_from: str = '2026-10-31'
    capital: D = D('95000')
    home: D = D('400000')
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


def _plan(deposit: D, investment: D) -> dict:
    ltv=(POLICY.home-deposit)/POLICY.home
    rate=next(rate for maximum,rate in POLICY.bands if ltv<=maximum)
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
    return {'deposit':money(deposit),'debt':money(debt),'retained':money(POLICY.capital-deposit),
            'outside_at_purchase':money(POLICY.reserve+POLICY.capital-deposit),
            'investment':money(investment),'cash':money(POLICY.reserve+POLICY.capital-deposit-investment),
            'rate':str(rate),'rate_label':rate_label(rate),'ltv':str(ltv),
            'ltv_label':ltv_label(ltv),'ltv_exact_label':percentage(ltv),
            'payment':money(payment),'contribution':money(D(money(POLICY.budget))-D(money(payment))),
            'next_threshold':int(next((POLICY.home*(1-b) for b,_ in reversed(POLICY.bands) if POLICY.home*(1-b)>deposit),POLICY.capital)),
            'rate_comparison':comparison,'reserve':money(POLICY.reserve),
            'first_payment':{'interest':money(debt*rate/12),'principal':money(D(money(payment))-D(money(debt*rate/12))),'interest_fraction':str((debt*rate/12)/payment)},
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
        contribution=money(D(money(POLICY.budget))-D(display_payment))
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
            'payments_completed_fraction':str(D(month)/360),
            'payments_completed_label':f'{month} of 360 payments',
            'scheduled_payments_total':money(payment*360),
            'payments_made':money(payment*month+actual-payment if month==360 else payment*month),
            'repaid_fraction':str((debt-closing)/debt)})
    return rows


def respond(request: dict) -> dict:
    """Return a single illustrative allocation and optional monthly timeline.

    Inputs are whole-pound integers; output money is Decimal text. Ambient
    context cannot alter accounting. Expected input failures are structured.
    """
    deposit=request.get('deposit'); investment=request.get('investment')
    if type(deposit) is not int or not 40000<=deposit<=95000:
        return {'status':'invalid','issues':[{'field':'deposit','message':'Enter whole pounds from 40000 to 95000.'}]}
    if type(investment) is not int or not 0<=investment<=95000-deposit:
        return {'status':'invalid','issues':[{'field':'investment','message':'Use whole pounds within retained capital.'}]}
    with localcontext(Context(prec=50)):
        plan=_plan(D(deposit),D(investment))
        result={'status':'ok','version':POLICY.version,'facts_version':FACTS['version'],
            'interest_scale_gbp':money(D(360000)*D(FACTS['mortgages'][str(POLICY.bands[-1][1])]['interest'])),
            'scale_gbp':money(POLICY.money_scale),'tile_gbp':'50000.00',
            'pricing_bands':[{'threshold':int(POLICY.home*(1-b)),'ltv':percentage(b),'rate':str(r),'label':rate_label(r)} for b,r in reversed(POLICY.bands)],
            'budget_gbp':money(POLICY.budget),'budget_exact':str(POLICY.budget),
            'teaching':{'deposit':SCENARIO.deposit_gbp,'investment':SCENARIO.investment_gbp,'version':SCENARIO.version},
            'effective_from':POLICY.effective_from,'plan':plan,
            'total_resources':money(POLICY.capital+POLICY.reserve),'reserve_gbp':money(POLICY.reserve),
            'ledger':[{'source':'cash_after_costs','use':use,'amount':plan[key]}
                for use,key in [('deposit','deposit'),('retained_cash','cash'),('investment','investment')]],
            'excluded_sources':{'lisa':'0.00','home_equity':'0.00'},'issues':[]}
        if request.get('timeline'):
            result['rows']=_rows(plan)
        return result
