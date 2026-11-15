-- 入口を包む入口 (entry-list の entries[].within)。1 行 = 包まれる入口 × 包む入口。ord は外側からの順 (1 が最も外側)
select
  w.entry_id, e.path, w.ord,
  w.within_entry_id, we.path as within_path
from {{ ref('entry_within') }} w
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_entries') }} we on we.entry_id = w.within_entry_id
