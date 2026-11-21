"""Exact component reporting for the isolated target-layout prototype.

The existing 50-digit projection is authoritative. The monthly-investment component
is the residual of that position after equity, cash and the opening investment lot,
so fixed-context arithmetic residue is assigned once, never hidden in the Why total.
"""
from decimal import Decimal as D, localcontext
from typing import Any

REPORTING_VERSION = 'component-reporting-v1'
COMPONENTS = (('equity','Home equity'),('cash','Cash'),('day_one','Day-one investments'),('monthly','Monthly investing'))

def composition(inputs: Any, plan: dict) -> list[dict[str,str]]:
    """Return exact GBP balance components at each existing projected month."""
    from model import factors
    if not plan or not plan['rows']: return []
    path,_=factors(inputs)
    opening=plan['opening_investment']; out=[]
    for row in plan['rows']:
        if row['month']:
            with localcontext() as ctx:
                ctx.prec=50
                opening*=path[row['month']-1]
        if row['position'] is None:
            out.append({});continue
        with localcontext() as ctx:
            ctx.prec=150
            monthly=row['position']-row['equity']-row['cash']-opening
        out.append(dict(equity=str(row['equity']),cash=str(row['cash']),day_one=str(opening),monthly=format(monthly,'f')))
    return out

def contributions(inputs: Any, selected: dict, reference: dict, month: int) -> dict | None:
    """Reconcile selected-minus-reference GBP components before display rounding."""
    from model import position_money
    if not selected or not reference or not selected['valid'] or not reference['valid']:return None
    a,b=composition(inputs,selected)[month],composition(inputs,reference)[month]
    with localcontext() as ctx:
        ctx.prec=150
        difference=selected['rows'][month]['position']-reference['rows'][month]['position']
        items=[dict(key=key,label=label,exact=str(D(a[key])-D(b[key])),display=position_money(D(a[key])-D(b[key]))) for key,label in COMPONENTS]
        assert sum(D(item['exact']) for item in items)==difference
    return dict(version=REPORTING_VERSION,month=month,selected_deposit=str(selected['deposit']),reference_deposit=str(reference['deposit']),term=selected['term'],items=items,exact_difference=str(difference),difference=position_money(difference),direction='equal' if difference==0 else 'higher' if difference>0 else 'lower')
