-- いつも起きるとは限らない呼び出し。1 行 = 条件つき (conditional) か、失敗のときだけ (on_failure) の呼び出し 1 つ
select
  e.entry_id, e.path, f.call_when, f.call_condition,
  c.name as caller_name, f.name as frame_name, f.layer,
  f.entry_id || '|' || f.frame_id as call_key
from {{ ref('stg_frames') }} f
join {{ ref('stg_entries') }} e using (entry_id)
left join {{ ref('stg_frames') }} c on c.entry_id = f.entry_id and c.frame_id = f.caller_id
where f.call_when in ('conditional', 'on_failure')
order by e.path, f.call_when desc, f.seq
