-- 入口どうしのつながり。1 行 = 入口 (から) × 種類 × 行き先。行き先が入口の一覧と結べたときは to_path が入る。結べないときは空 (target に、コードに書いてあるとおりの行き先)
select
  e.entry_id, e.path, l.kind, l.target,
  coalesce(t.path, '') as to_path,
  e.entry_id || '|' || l.kind || '|' || l.target || '|' || coalesce(t.entry_id, '') as link_key,
  (t.entry_id is not null) as resolved,
  count(*) as link_count,
  string_agg(distinct fr.name, ', ' order by fr.name) as frames,
  bool_or(l.status = 'unknown') as has_unknown
from {{ ref('stg_links') }} l
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_frames') }} fr on fr.entry_id = l.entry_id and fr.frame_id = l.frame_id
left join {{ ref('stg_entries') }} t on t.entry_id = nullif(l.target_entry_id, '')
group by e.entry_id, e.path, l.kind, l.target, t.path, t.entry_id
order by e.path, l.kind, l.target
