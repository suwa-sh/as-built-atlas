-- 権限の確認。1 行 = 入口 × 確認 1 つ。via は、その確認を行う入口 (自分か、自分を包む入口)。包む入口の確認は、包まれる入口にも効く
with own as (
  select g.entry_id, g.entry_id as via_entry_id, g.frame_id, g.idx, g.kind, g.value, g.status
  from {{ ref('stg_guards') }} g
), inherited as (
  select w.entry_id, g.entry_id as via_entry_id, g.frame_id, g.idx, g.kind, g.value, g.status
  from {{ ref('stg_entry_within') }} w
  join {{ ref('stg_guards') }} g on g.entry_id = w.within_entry_id
), u as (
  select * from own union all select * from inherited
)
select
  e.entry_id, e.path, u.kind, u.value,
  v.path as via,
  (u.via_entry_id <> u.entry_id) as inherited,
  fr.name as frame_name,
  u.status,
  e.entry_id || '|' || u.via_entry_id || '|' || u.frame_id || '|' || cast(u.idx as varchar) as guard_key
from u
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_entries') }} v on v.entry_id = u.via_entry_id
join {{ ref('stg_frames') }} fr on fr.entry_id = u.via_entry_id and fr.frame_id = u.frame_id
order by e.path, u.kind, u.value, v.path
