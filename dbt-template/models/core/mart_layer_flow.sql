-- 層のつながり (構成の図の線)。分析結果にある実際の呼び出しと読み書きを、層の単位に集める
--   呼び出し: 呼ぶ側の処理の層 → 呼ばれる側の処理の層 (同じ層の中の呼び出しも 1 行。from_node = to_node)
--   読み書き: 読み書きした処理の層 → データの種類 (to_node は '/' + 種類。層の id と取り違えないよう、データのパスと同じ書き方にする)
-- calls = 箇所の数、entries = それを含む入口の数。分析済みの入口だけから集まる
-- unknowns = そのうち確かめられていない箇所の数 (呼び出しは呼ばれる側の call_status、読み書きは status が unknown)。1 つでもあれば status = 'unknown' (図は点線にする)
with calls as (
  select c.layer as from_node, f.layer as to_node, 'call' as edge_kind, f.entry_id, f.call_status as status
  from {{ ref('stg_frames') }} f
  join {{ ref('stg_frames') }} c on c.entry_id = f.entry_id and c.frame_id = f.caller_id
), ios as (
  select f.layer as from_node, '/' || i.kind as to_node, 'io' as edge_kind, i.entry_id, i.status
  from {{ ref('stg_io') }} i
  join {{ ref('stg_frames') }} f on f.entry_id = i.entry_id and f.frame_id = i.frame_id
  where not i.is_repeat   -- もう一度書いたフレームの読み書きは、数えない
), edges as (
  select * from calls union all select * from ios
)
select from_node, to_node, edge_kind, count(*) as calls, count(distinct entry_id) as entries,
  count(*) filter (where status = 'unknown') as unknowns,
  case when count(*) filter (where status = 'unknown') > 0 then 'unknown' else 'known' end as status
from edges
group by from_node, to_node, edge_kind
order by edge_kind, from_node, to_node
