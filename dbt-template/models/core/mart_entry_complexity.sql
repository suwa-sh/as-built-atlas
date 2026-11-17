-- 入口ごとの複雑度。1 つの点数にまとめず、いまの分析結果から数えられる数を並べる (重みの根拠が無いため)。
-- 使い道は、直すときの影響の見積もり。分析済みの入口だけを出す
with recursive frames as (
  select entry_id, frame_id, layer, source_file, name, coalesce(caller_id, '') as caller_id from {{ ref('stg_frames') }}   -- 入口のフレームの呼び出し元は、空 (NULL)
), walk as (
  -- 入口のフレーム (呼び出し元が無い) を深さ 1 として、呼び出しを辿る
  select entry_id, frame_id, 1 as depth from frames where caller_id = ''
  union all
  select f.entry_id, f.frame_id, w.depth + 1
  from frames f join walk w on f.entry_id = w.entry_id and f.caller_id = w.frame_id
  -- 上限は置かない。フレームの呼び出し元は 1 つなので、入口から辿る道は輪にならない (輪は、入口から届かないフレームとして、形式の検査が落とす)
), depth as (
  select entry_id, max(depth) as max_depth from walk group by entry_id
), crossing as (
  -- 呼び出し元と層が違う呼び出しの数
  select f.entry_id, count(*) as layer_crossings
  from frames f join frames c on f.entry_id = c.entry_id and f.caller_id = c.frame_id
  where f.layer <> c.layer
  group by f.entry_id
), shared_def as (
  -- 2 件以上の入口が通る処理 (同じ定義場所。mart_shared_frames と同じ数え方)
  select source_file, name, layer
  from frames where caller_id <> ''
  group by source_file, name, layer
  having count(distinct entry_id) >= 2
), shared as (
  select f.entry_id, count(distinct f.source_file || '|' || f.name || '|' || f.layer) as shared_frame_count
  from frames f join shared_def s using (source_file, name, layer)
  where f.caller_id <> ''
  group by f.entry_id
), neighbors as (
  -- 同じ処理を通る、ほかの入口の数 (その処理を直すと、一緒に確かめることになる入口)
  select a.entry_id, count(distinct b.entry_id) as sharing_entry_count
  from frames a
  join shared_def s using (source_file, name, layer)
  join frames b on b.source_file = a.source_file and b.name = a.name and b.layer = a.layer and b.entry_id <> a.entry_id and b.caller_id <> ''
  where a.caller_id <> ''
  group by a.entry_id
), io as (
  select entry_id,
    count(distinct case when kind <> 'external_api' then kind || ':' || resource_path end) as datastore_count,
    count(distinct case when kind <> 'external_api' and op_direction = 'out' then kind || ':' || resource_path end) as written_datastore_count,
    count(distinct case when kind = 'external_api' then resource_path end) as external_count
  from {{ ref('stg_io') }} group by entry_id
), claims as (
  select entry_id, count(*) filter (where status = 'unknown') as unknown_count
  from {{ ref('stg_claims') }} group by entry_id
)
select
  e.entry_id, e.path, e.name, e.layer,
  coalesce(r.frame_count, 0) as frame_count,
  coalesce(d.max_depth, 0) as max_depth,
  coalesce(x.layer_crossings, 0) as layer_crossings,
  coalesce(i.datastore_count, 0) as datastore_count,
  coalesce(i.written_datastore_count, 0) as written_datastore_count,
  coalesce(i.external_count, 0) as external_count,
  coalesce(s.shared_frame_count, 0) as shared_frame_count,
  coalesce(n.sharing_entry_count, 0) as sharing_entry_count,
  coalesce(c.unknown_count, 0) as unknown_count
from {{ ref('stg_entries') }} e
join {{ ref('stg_results') }} r using (entry_id)
left join depth d using (entry_id)
left join crossing x using (entry_id)
left join io i using (entry_id)
left join shared s using (entry_id)
left join neighbors n using (entry_id)
left join claims c using (entry_id)
order by coalesce(n.sharing_entry_count, 0) desc, coalesce(i.written_datastore_count, 0) desc, coalesce(r.frame_count, 0) desc, e.path
