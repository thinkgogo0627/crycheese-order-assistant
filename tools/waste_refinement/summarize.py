"""Build a shareable aggregate summary from private study exports."""
import argparse,json
from pathlib import Path
from datetime import date,timedelta
from collections import Counter


def summarize(folder):
    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    out={'policy_comparison':{},'lot_diagnosis':{}}
    for name,row in summary.items():
        cuts=[x for x in row['cuts'] if x['day']>=31]
        moves=[x for x in row['preventive_moves'] if x['day']>=31]
        out['policy_comparison'][name]={k:row[k] for k in ('metrics','metrics_aug_sep','by_store','evaluation_aug_sep',
            'max_lot_balance_error','nonworsening_all_store_menu_days','worsened_store_menu_days','additional_lost_menu_qty_on_worse_days','parity') if k in row}
        out['policy_comparison'][name].update(cut_count=len(cuts),preventive_move_count=len(moves),
            move_months=dict(Counter((date(2026,1,1)+timedelta(days=x['day'])).strftime('%Y-%m') for x in moves)))
    for variant in ('oracle_reference','baseline'):
        lots=json.loads((folder/f'{variant}_lots.json').read_text(encoding='utf-8'))
        out['lot_diagnosis'][variant]={}
        for item in ('I009','I017','I020'):
            rows=[b for b in lots if b['item']==item and any(e['day']>=31 and e['store']=='S02' for e in b.get('expiry_events',[]))]
            events=[e for b in rows for e in b['expiry_events'] if e['day']>=31 and e['store']=='S02']
            regular=[b for b in rows if b['kind']=='regular' and b['order']]
            components={c:sum(b['order'][c] for b in regular) for c in ('shortage_component','safety_component','rounding_component','minimum_component')}
            total=sum(components.values())
            out['lot_diagnosis'][variant][item]=dict(expiry_cost=sum(e['cost'] for e in events),
                expired_batch_count=len(rows),expired_days=len({e['day'] for e in events}),
                expired_months=dict(Counter((date(2026,1,1)+timedelta(days=e['day'])).strftime('%Y-%m') for e in events)),
                source_kinds=dict(Counter(b['kind'] for b in rows)),source_stores=dict(Counter(b['origin_store'] for b in rows)),
                regular_order_components=components,
                regular_order_component_pct={k:100*v/total if total else 0 for k,v in components.items()},
                topup_batches=sum(b['order']['minimum_component']>1e-6 for b in regular),
                forecast_lifetime_need=sum(b['order']['expected_use_lifetime'] for b in regular),
                actual_lifetime_need=sum(b['order']['realized_demand_lifetime'] for b in regular),
                actual_lifetime_use=sum(b['order']['realized_use_lifetime'] for b in regular))
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.write_text(json.dumps(summarize(a.folder),ensure_ascii=False,indent=2),encoding='utf-8')
