-- 権限の確認の一覧。1 行 = 確認 1 つ (それを行う入口 × 処理 × 確認)。
-- 入口を包む入口 (枠) の確認は、その中で動く入口にも効く。効く入口の数を inner_entry_count に出す (行は増やさない。入口ごとの効き方は mart_entry_access)
with inner_count as (
  select within_entry_id as entry_id, count(distinct entry_id) as inner_entry_count
  from {{ ref('stg_entry_within') }} group by within_entry_id
)
select
  e.entry_id, e.path, g.kind, g.value,
  fr.name as frame_name, fr.layer,
  coalesce(i.inner_entry_count, 0) as inner_entry_count,
  g.status,
  g.entry_id || '|' || g.frame_id || '|' || cast(g.idx as varchar) as guard_key
from {{ ref('stg_guards') }} g
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_frames') }} fr on fr.entry_id = g.entry_id and fr.frame_id = g.frame_id
left join inner_count i on i.entry_id = g.entry_id
order by e.path, fr.seq, g.idx
