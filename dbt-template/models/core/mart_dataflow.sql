-- データの流れ (有向グラフ) の辺。操作の向き (語彙の direction) で決める: in (読む側) はデータ → 入口、out (書く側) は入口 → データ
select
  e.entry_id, e.path,
  case when i.op_direction = 'in' then i.resource_path else e.path end as from_node,
  case when i.op_direction = 'in' then e.path else i.resource_path end as to_node,
  i.op, i.op_letter, i.op_direction, i.kind, i.resource_path, i.status, i.reason
from {{ ref('stg_io') }} i
join {{ ref('stg_entries') }} e using (entry_id)
order by e.path, i.op_direction, i.resource_path
