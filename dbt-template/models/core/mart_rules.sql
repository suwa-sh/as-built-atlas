-- 業務のルールの一覧。1 行 = ルール 1 つ (入口 × 処理 × ルール)。source は、根拠の最初の行
with ev as (
  select entry_id, claim_path, min(file || ':' || lpad(cast(line as varchar), 6, '0')) as first_ev
  from {{ ref('stg_evidence') }} group by entry_id, claim_path
)
select
  e.entry_id, e.path, r.kind, r.value as rule,
  fr.name as frame_name, fr.layer,
  coalesce(regexp_replace(ev.first_ev, ':0*([0-9]+)$', ':\1'), '') as source,
  r.status,
  r.entry_id || '|' || r.frame_id || '|' || cast(r.idx as varchar) as rule_key
from {{ ref('stg_rules') }} r
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_frames') }} fr on fr.entry_id = r.entry_id and fr.frame_id = r.frame_id
left join ev on ev.entry_id = r.entry_id and ev.claim_path = 'callstack/' || r.frame_id || '/rules/' || cast(r.idx as varchar)
order by e.path, fr.seq, r.idx
