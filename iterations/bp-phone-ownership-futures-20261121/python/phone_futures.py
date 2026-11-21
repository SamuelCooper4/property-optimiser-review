"""One-term phone scenario previews in the isolated illustrative provider.

The existing projection owns payment changes, contributions, shocks and recovery.
Both futures are ranked at the same date using the phone's funded sample.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D, InvalidOperation

import model as m
import phone_provider as phone


FUTURE_SETTINGS = phone.FIXTURE['future_settings']
DEFAULT_RENEWAL_INCREASE = D(FUTURE_SETTINGS['preset_rate_change'])
DEFAULT_FALL = D(FUTURE_SETTINGS['default_fall'])
DEFAULT_FALL_MONTH = 12*FUTURE_SETTINGS['default_fall_year']


def _fraction(value: object, upper: D, description: str) -> D:
    try:
        fraction = D(str(value))
        if fraction.is_finite() and 0 <= fraction <= upper and len(fraction.as_tuple().digits) <= 16:
            return fraction
    except (InvalidOperation, ValueError):
        pass
    raise ValueError(description)


def _percent(value: D) -> str:
    return format((value * 100).normalize(), 'f') + '%'


def _ranked_curve(i: m.Inputs, term: int, deposit: D, month: int, preferred: D | None) -> tuple:
    """Price each funded region separately and retain the exact explored penny."""
    segments, plans = [], {}
    for (low,high,rate), group in zip(phone._regions(i,term,month), phone._sample(i,term,month)):
        points = {p['deposit']:p for p in group if p['status']=='funded'}
        if low <= deposit <= high and deposit not in points:
            exact = phone._plan(i,term,deposit,month)
            if exact['status']=='funded':
                points[deposit] = exact
        if points:
            plans.update(points)
            segments.append(dict(low=low, high=high, rate=rate,
                                 points=[dict(deposit=d, position=points[d]['position']) for d in sorted(points)]))
    curve = dict(segments=segments)
    if not plans:
        return None, 0, (), curve
    highest = max(p['position'] for p in plans.values())
    ties = tuple(sorted(d for d,p in plans.items() if p['position']==highest))
    chosen = next((d for d in (preferred,deposit) if d in ties), ties[0])
    return plans[chosen], len(plans), ties, curve


def _rank(i: m.Inputs, term: int, deposit: D, month: int, preferred: D | None) -> tuple:
    return _ranked_curve(i,term,deposit,month,preferred)[:3]


def _rate_path(i: m.Inputs, selected: dict, month: int, scenario: dict) -> tuple:
    """Build the requested fixed-period assumptions for the full-horizon funding test."""
    fixed_months = selected['fixed_months'] or i.comparison_fixed_months or phone.FIXTURE['source']['fixed_months']
    opening = selected['rate'] or m.ZERO
    count = (month+fixed_months-1)//fixed_months
    error = 'Choose a renewal rate between 0% and 25%.'
    maximum = D('.25')
    if 'renewal_rate' in scenario and 'rates' not in scenario and 'preset' not in scenario:
        rate = _fraction(scenario['renewal_rate'],maximum,error)
        rates = (opening,) + (rate,)*(count-1)
        patch = dict(deals=((phone.FIXTURE['source']['fixed_months'],None),),continuation=rate,renewal_changes=())
        label = _percent(rate)+' renewal'
    else:
        preset = scenario.get('preset','same')
        if preset not in ('same','rise','fall'):
            raise ValueError('Choose Stay the same, Rates rise or Rates fall.')
        if 'rates' in scenario:
            raw = scenario['rates']
            if not isinstance(raw,(list,tuple)) or not 1 <= len(raw) <= m.HORIZON_MONTHS:
                raise ValueError('Enter one rate per fixed period.')
            reference = D(str(scenario.get('reference_rate',opening)))
            if (not reference.is_finite() or not 0 <= reference <= maximum or D(str(raw[0]))!=reference or
                    ('reference_rate' not in scenario and len(raw)!=count)):
                raise ValueError('Keep the first rate fixed and enter one rate per fixed period.')
            # Preserve the edited path when the selected deposit or comparison date changes.
            # Retain an exact quoted opening rate even for an interpolated band.
            entered = tuple(D(str(v)) for v in raw[1:])
            if any(not r.is_finite() or not 0 <= r <= maximum+DEFAULT_RENEWAL_INCREASE or
                   len(r.as_tuple().digits)>50 for r in entered):
                raise ValueError('Check the rates in the fixed-period path.')
            shifts = tuple(r-reference for r in entered)
            last = shifts[-1] if shifts else m.ZERO
            shifts = (shifts+(last,)*max(0,count-1-len(shifts)))[:count-1]
            rates = (opening,)+tuple(max(phone.MIN_RENEWAL_RATE,opening+shift) for shift in shifts)
            label = 'Edited renewal rates'
        else:
            direction = {'same':0,'rise':1,'fall':-1}[preset]
            shifts = (direction*DEFAULT_RENEWAL_INCREASE,)*(count-1)
            rates = (opening,) + tuple(max(phone.MIN_RENEWAL_RATE,opening+shift) for shift in shifts)
            label = {'same':'Rates stay the same','rise':'Rates rise','fall':'Rates fall'}[preset]
        patch = dict(deals=(),continuation=i.continuation,renewal_period_months=fixed_months,
                     renewal_changes=shifts if any(shifts) else ())
    return fixed_months, rates, patch, label


def _compact(plan: dict | None) -> dict | None:
    if plan is None:
        return None
    keys = ('deposit', 'term_years', 'source', 'position', 'investment', 'equity', 'cash',
            'house_and_cash', 'status', 'reason', 'rate', 'fixed_months')
    return {key:plan[key] for key in keys}


def _renewal(i: m.Inputs, selected: dict, projection: dict) -> dict:
    rows = projection['rows']
    fixed_months = selected['fixed_months']
    renewal_month = fixed_months + 1 if fixed_months is not None else None
    result = dict(budget=i.monthly, before=None, after=None, month=renewal_month,
                  shortfall=projection['first_shortfall'], paid_off=False)
    if not rows:
        return result
    if selected['source']['kind'] == 'cash':
        return {**result, 'paid_off':True}
    if renewal_month is None:
        return result
    payoff = projection['payoff_month']
    if payoff is not None and payoff < renewal_month:
        return {**result, 'before':projection['first_payment'], 'after':m.ZERO, 'paid_off':True}
    return {**result, 'before':rows[renewal_month-1]['required'],
            'after':rows[renewal_month]['required']}


def _investment_path(base: dict, changed: dict, month: int) -> list[dict]:
    """Read investments through each last funded month on a common time axis."""
    def balances(plan: dict) -> dict:
        gap = plan['first_shortfall']
        return {r['month']:r['investment'] for r in plan['rows'] if r['month'] <= month
                and (gap is None or r['month'] < gap['month'])}
    before, after = balances(base), balances(changed)
    return [dict(month=n, base=before.get(n), changed=after.get(n))
            for n in sorted(before.keys() | after.keys())]


@m.fixed
def explore(i: m.Inputs, term: int, deposit: D, month: int, request: dict) -> dict:
    """Preview a renewal or investment fall for one selected pair and comparison month."""
    page = request['page']
    scenario = request.get('scenario') or {}
    if page not in (8,9) or not isinstance(scenario, dict):
        raise ValueError('Choose a renewal or investment fall preview.')
    if request.get('preview_quote_id'):
        i = replace(i,pinned_quote_id=request['preview_quote_id'])
    original = i
    i = replace(i,deals=(),renewal_changes=()) if page==8 else replace(i,stress_month=0)
    base_selected = phone._preview_choice(i, term, deposit, month, request)
    base_leader, _, base_ties, base_curve = _ranked_curve(i, term, deposit, month, deposit)
    if page == 8:
        fixed_months, rates, patch, label = _rate_path(i,base_selected,month,scenario)
        applied = dict(rates=rates,reference_rate=rates[0],renewal_rate=patch['continuation'] if patch['deals'] else rates[-1])
    else:
        default_loss = original.loss if original.stress_month else DEFAULT_FALL
        loss = _fraction(scenario.get('loss', default_loss), D('.95'), 'Choose a fall from 0% to 95%.')
        if 'fall_year' in scenario:
            year = scenario['fall_year']
            if type(year) is not int or not 1 <= year <= month//12:
                raise ValueError('Choose a fall year between year 1 and the comparison year.')
            when = year*12
        else:
            when = scenario.get('stress_month',min(month,original.stress_month or DEFAULT_FALL_MONTH))
        if type(when) is not int or not 1 <= when <= m.HORIZON_MONTHS:
            raise ValueError('Choose a fall month from 1 to 420.')
        patch = dict(loss=loss, stress_month=when if loss else 0)
        applied = dict(loss=loss, stress_month=when, fall_year=(when+11)//12)
        timing = f'year {when//12}' if when % 12 == 0 else f'month {when}'
        label = f'{_percent(loss)} fall · {timing}' if loss else 'No fall'
    changed = replace(i, **patch)
    base_choice = phone._choice_inputs(i, base_selected)
    changed_choice = phone._choice_inputs(changed, base_selected)
    selected = phone._plan(changed, term, deposit, month)
    leader, count, ties, curve = _ranked_curve(changed, term, deposit, month,
                                base_leader['deposit'] if base_leader else deposit)
    result = dict(status='ok', version=phone.VERSION, settings_version=FUTURE_SETTINGS['version'], page=page, scenario=applied, scenario_label=label,
                  objective_month=month, term_years=term, adoption_patch=patch,
                  base_selected=_compact(base_selected), selected=_compact(selected),
                  base_leader=_compact(base_leader), leader=_compact(leader), candidate_count=count,
                  base_ties=base_ties, ties=ties, difference_to_term=phone._difference(leader, selected),
                  terms_at_deposit=phone._terms_at_deposit(changed, deposit, month, selected))
    segments = [*curve['segments'],*base_curve['segments']]
    original_regions = phone._regions(original,term,month)
    left,right = ((original_regions[0][0],original_regions[-1][1]) if original_regions else phone._bounds(original))
    domain = dict(low=min([left,deposit]+[s['low'] for s in segments]),
                  high=max([right,deposit]+[s['high'] for s in segments]))
    result.update(base_curve=base_curve,curve=curve,domain=domain,bands=phone._bands(i,phone._regions(i,term,month)))
    if leader is None:
        # Distinguish known unaffordable payments from a term without a price.
        result['empty_status'] = ('over_budget' if selected['status'] == 'over_budget' else
                                  phone._missing_example(changed, term, month)['status'])
    # Full funding check and the first contractual renewal are relevant even when
    # the comparison date precedes the end of the fix.
    changed_plan = m.project(changed_choice, deposit, term, objective_month=month,
                             through_month=m.HORIZON_MONTHS if page == 8 else month)
    if page == 8:
        renewal = _renewal(changed_choice, selected, changed_plan)
        renewal['headroom'] = i.monthly-renewal['after'] if renewal['after'] is not None else None
        result['renewal'] = renewal
        periods = []
        bar_rates = () if selected['source']['kind']=='cash' or base_selected['rate'] is None else rates
        for index,rate in enumerate(bar_rates):
            start = index*fixed_months+1
            payment = changed_plan['rows'][start]['required'] if changed_plan['rows'] else None
            periods.append(dict(start_month=start,end_month=min(month,start+fixed_months-1),
                                rate=rate,rate_change=rate-rates[0],payment=payment,locked=index==0,
                                over_budget=payment is not None and payment>i.monthly))
        result['periods'] = periods
    else:
        base_plan = m.project(base_choice, deposit, term, objective_month=month, through_month=month)
        path = _investment_path(base_plan, changed_plan, month)
        last = path[-1] if path and path[-1]['month'] == month else {}
        difference = (last['changed']-last['base'] if last.get('base') is not None
                      and last.get('changed') is not None else None)
        result.update(path=path, default_loss=default_loss or DEFAULT_FALL, investment_difference=difference, recovery_months=i.recovery_months,
                      recovery_return=i.recovery_return, investment_return=i.investment_return)
    return result
