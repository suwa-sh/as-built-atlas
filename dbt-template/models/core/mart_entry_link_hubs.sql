-- 入口どうしのつながりを、入口 1 件を真ん中にして見る。1 行 = 入口 1 件 (行き先が入口の一覧と結べたつながりを、1 つでも持つもの)
-- incoming = この入口へ来る入口、outgoing = この入口から行く入口 (どちらも、パスを ", " で連ねる)。自分自身へのつながりは含めない
with l as (
  select distinct path as from_path, to_path from {{ ref('mart_entry_links') }} where to_path <> '' and to_path <> path
), n as (
  select from_path as path from l union select to_path from l
), i as (
  select to_path as path, count(*) as incoming_count, string_agg(from_path, ', ' order by from_path) as incoming from l group by to_path
), o as (
  select from_path as path, count(*) as outgoing_count, string_agg(to_path, ', ' order by to_path) as outgoing from l group by from_path
)
select
  n.path,
  coalesce(i.incoming_count, 0) as incoming_count, coalesce(i.incoming, '') as incoming,
  coalesce(o.outgoing_count, 0) as outgoing_count, coalesce(o.outgoing, '') as outgoing
from n
left join i using (path)
left join o using (path)
order by coalesce(i.incoming_count, 0) + coalesce(o.outgoing_count, 0) desc, n.path
