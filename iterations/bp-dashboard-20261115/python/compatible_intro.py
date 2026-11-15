"""Shared-model adapter for the approved compatibility copy of the live story.

Retains the live minimum-versus-maximum demonstration policy. Mortgage term is
30 years, comparison is 120 months. No separate mortgage or investment model.
"""
from dataclasses import fields
from decimal import Decimal as D, ROUND_CEILING
from functools import lru_cache
import model as m
import intro_provider as a
from target_reporting import composition

VERSION='published-story-compatible-2026-11-15-v1'
COMPARISON_MONTH=a.OBJECTIVE_MONTH
TERM_YEARS=a.TERM_YEARS
GROWTH=a.GROWTH_SETTINGS[0]


@lru_cache(maxsize=128)
@m.fixed
def scene(deposit: D) -> dict:
    """Map exact provider balances to the unchanged published scene contract."""
    i=a.example_inputs(GROWTH)
    plan=m.project(i,deposit,TERM_YEARS)
    if not plan['valid']:raise ValueError('Choose a funded deposit within the illustrated household.')
    source=a.build_response(GROWTH,deposit)
    data={**source['data']}
    parts=composition(i,plan)
    rows=[]
    for raw,lot in zip(plan['rows'][:COMPARISON_MONTH+1],parts):
        row=m.present({**plan,'rows':[raw]})['rows'][0]
        row.update(net_exact=str(raw['position']),net_position=m.money(raw['position']),
                   opening_value=m.money(D(lot['day_one'])),later_value=m.money(D(lot['monthly'])),
                   investment_value=m.money(raw['investment']),cash_value=m.money(raw['cash']),
                   contributions=m.money(raw['contributed']),
                   investment_change=m.money(raw['investment']-plan['opening_investment']-raw['contributed']))
        rows.append(row)
    data.update(version=VERSION,rows=rows,minimum_display=m.money(a.minimum_deposit(i)),
                comparison_month=COMPARISON_MONTH,term_years=TERM_YEARS,home_gbp=m.money(i.price),
                handoff=dict(version=VERSION,inputs=m.serial({f.name:getattr(i,f.name) for f in fields(i)}),
                             choice=dict(deposit=m.money(deposit),term=TERM_YEARS),objective_month=COMPARISON_MONTH))
    return data


@lru_cache(maxsize=1)
@m.fixed
def comparison() -> dict:
    """Compare only the live story's two cases; never imply a complete search."""
    i=a.example_inputs(GROWTH)
    smaller=scene(a.minimum_deposit(i));larger=scene(i.total-i.reserve-i.costs)
    av=D(smaller['rows'][-1]['net_exact']);bv=D(larger['rows'][-1]['net_exact'])
    difference=av-bv
    viewports=[]
    for left,right in zip(smaller['rows'],larger['rows']):
        x,y=D(left['net_exact']),D(right['net_exact'])
        span=max(D('100000'),abs(x-y)*D('2.2'));centre=(x+y)/2
        viewports.append(dict(min=str(centre-span/2),max=str(centre+span/2)))
    investment_max=max(D(row['investment_value']) for item in (smaller,larger) for row in item['rows'])
    position_max=max(D(row['net_exact']) for item in (smaller,larger) for row in item['rows'])
    # Bounds affect geometry only, not the financial values or their rounding.
    pot_scale=max(D('10000'),(investment_max/D('10000')).to_integral_value(rounding=ROUND_CEILING)*D('10000'))
    plot_scale=(position_max/D('10000')).to_integral_value(rounding=ROUND_CEILING)*D('10000')
    return dict(status='ok',version=VERSION,comparison_month=COMPARISON_MONTH,
                comparison=dict(smaller={**smaller,'scale_gbp':str(pot_scale)},larger={**larger,'scale_gbp':str(pot_scale)},
                                max_month=COMPARISON_MONTH,full_scale_gbp=str(plot_scale),viewports=viewports,
                                winner='smaller' if difference>0 else 'larger' if difference<0 else 'tie',
                                final_difference=m.money(abs(difference)),final_difference_display=m.position_money(abs(difference))))


@lru_cache(maxsize=1)
@m.fixed
def opening() -> dict:
    """Prepare compact exact facts for immediate pointer frames; no interpolation."""
    i=a.example_inputs(GROWTH)
    lookup=m.opening_lookup(i,TERM_YEARS)
    points=[]
    for row in lookup['points']:
        facts=a.interest_facts(D(row[0]),a.LESSON_RATE)
        points.append(row+[facts['interest'],facts['lesson_interest'],m.money(i.reserve+D(row[2]))])
    return {**lookup,'version':VERSION,'points':points}


@m.fixed
def respond(request: dict) -> dict:
    """Serve bounded scenes, exact transition frames and the two-choice comparison."""
    i=a.example_inputs(GROWTH);minimum=a.minimum_deposit(i);maximum=i.total-i.reserve-i.costs
    if request.get('action')=='opening':return opening()
    if request.get('comparison') is True:return comparison()
    if 'transition_from' in request:
        start=D(str(request['transition_from']))
        if not start.is_finite() or not minimum<=start<=maximum:raise ValueError('Choose a funded starting deposit.')
        values=[(start+(minimum-start)*D(n)/40).quantize(m.PENNY,rounding=ROUND_CEILING) for n in range(40)]+[minimum]
        return dict(status='ok',transition=[scene(value) for value in values])
    raw=request.get('deposit',str(maximum))
    deposit=minimum if raw=='minimum' else D(str(raw))
    if not deposit.is_finite() or deposit!=deposit.quantize(m.PENNY) or not minimum<=deposit<=maximum:
        raise ValueError('Choose a penny deposit within the funded example range.')
    return scene(deposit)
