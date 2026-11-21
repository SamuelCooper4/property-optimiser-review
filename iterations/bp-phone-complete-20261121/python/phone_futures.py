"""One-term phone scenario previews in the isolated illustrative provider.

The existing projection owns payment changes, contributions, shocks and recovery.
Both futures are ranked at the same date using the phone's funded sample.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D, InvalidOperation

import model as m
import phone_provider as phone


# Starting control positions from the numbered phone design, November 2026.
DEFAULT_RENEWAL_INCREASE = D('.01')
DEFAULT_FALL = D('.30')
DEFAULT_FALL_MONTH = 36


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


def _rank(i: m.Inputs, term: int, deposit: D, month: int, preferred: D | None) -> tuple:
    """Rank the affordable sample, adding the exact explored deposit once."""
    points = {p['deposit']:p for group in phone._sample(i, term, month) for p in group
              if p['status'] == 'funded'}
    exact = phone._plan(i, term, deposit, month)
    if exact['status'] == 'funded':
        points[deposit] = exact
    if not points:
        return None, 0, ()
    highest = max(p['position'] for p in points.values())
    ties = tuple(sorted(d for d,p in points.items() if p['position'] == highest))
    chosen = next((d for d in (preferred, deposit) if d in ties), ties[0])
    return points[chosen], len(points), ties


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
    base_selected = phone._plan(i, term, deposit, month)
    base_leader, _, base_ties = _rank(i, term, deposit, month, deposit)
    if page == 8:
        fallback = base_selected['rate']
        if fallback is None and base_leader:
            fallback = base_leader['rate']
        default_rate = i.continuation if i.deals or fallback is None else min(
            D('.25'), fallback + DEFAULT_RENEWAL_INCREASE)
        rate = _fraction(scenario.get('renewal_rate', default_rate), D('.25'),
                         'Choose a renewal rate between 0% and 25%.')
        # Each supplied quote overrides this illustrative first fix with its own duration.
        patch = dict(deals=((phone.FIXTURE['source']['fixed_months'], None),), continuation=rate)
        applied = dict(renewal_rate=rate)
        label = _percent(rate) + ' renewal'
    else:
        default_loss = i.loss if i.stress_month else DEFAULT_FALL
        loss = _fraction(scenario.get('loss', default_loss), D('.95'), 'Choose a fall from 0% to 95%.')
        when = scenario.get('stress_month', i.stress_month or DEFAULT_FALL_MONTH)
        if type(when) is not int or not 1 <= when <= m.HORIZON_MONTHS:
            raise ValueError('Choose a fall month from 1 to 420.')
        patch = dict(loss=loss, stress_month=when if loss else 0)
        applied = dict(loss=loss, stress_month=when)
        timing = f'year {when//12}' if when % 12 == 0 else f'month {when}'
        label = f'{_percent(loss)} fall · {timing}' if loss else 'No fall'
    changed = replace(i, **patch)
    base_choice = phone._choice_inputs(i, base_selected)
    changed_choice = phone._choice_inputs(changed, base_selected)
    selected = phone._plan(changed_choice, term, deposit, month)
    comparison_inputs = (replace(changed, pinned_quote_id='')
                         if getattr(changed, 'pinned_quote_id', '') else changed)
    leader, count, ties = _rank(comparison_inputs, term, deposit, month,
                                base_leader['deposit'] if base_leader else deposit)
    result = dict(status='ok', page=page, scenario=applied, scenario_label=label,
                  objective_month=month, term_years=term, adoption_patch=patch,
                  base_selected=_compact(base_selected), selected=_compact(selected),
                  base_leader=_compact(base_leader), leader=_compact(leader), candidate_count=count,
                  base_ties=base_ties, ties=ties)
    # Full funding check and the first contractual renewal are relevant even when
    # the comparison date precedes the end of the fix.
    changed_plan = m.project(changed_choice, deposit, term, objective_month=month,
                             through_month=m.HORIZON_MONTHS if page == 8 else month)
    if page == 8:
        result['renewal'] = _renewal(changed_choice, selected, changed_plan)
    else:
        base_plan = m.project(base_choice, deposit, term, objective_month=month, through_month=month)
        path = _investment_path(base_plan, changed_plan, month)
        last = path[-1] if path and path[-1]['month'] == month else {}
        difference = (last['changed']-last['base'] if last.get('base') is not None
                      and last.get('changed') is not None else None)
        result.update(path=path, investment_difference=difference, recovery_months=i.recovery_months,
                      recovery_return=i.recovery_return, investment_return=i.investment_return)
    return result
