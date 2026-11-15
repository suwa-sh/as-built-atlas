-- 同じ処理 (同じ定義場所のフレーム) を 2 件以上の入口が呼んでいる
select
  f.source_file, f.name, f.layer,
  count(distinct f.entry_id) as entry_count,
  string_agg(distinct e.path, ', ' order by e.path) as entries
from {{ ref('stg_frames') }} f
join {{ ref('stg_entries') }} e using (entry_id)
where f.caller_id <> ''
group by f.source_file, f.name, f.layer
having count(distinct f.entry_id) >= 2
order by entry_count desc, f.source_file
