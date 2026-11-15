-- プロファイル (batch-kestra) 固有の mart の例。namespace (階層の第 1 段) ごとの Flow 数と I/O の内訳
with flows as (
  select e.level1, count(distinct e.entry_id) as flows, count(distinct r.entry_id) as analyzed_flows
  from {{ ref('stg_entries') }} e
  left join {{ ref('stg_results') }} r using (entry_id)
  group by e.level1
), io as (
  select e.level1,
    count(*) filter (where i.kind = 'rdb') as rdb_io,
    count(*) filter (where i.kind = 'filesystem') as filesystem_io,
    count(*) filter (where i.kind = 'external_api') as external_api_io
  from {{ ref('stg_io') }} i
  join {{ ref('stg_entries') }} e using (entry_id)
  group by e.level1
)
select
  f.level1 as namespace, f.flows, f.analyzed_flows,
  coalesce(io.rdb_io, 0) as rdb_io,
  coalesce(io.filesystem_io, 0) as filesystem_io,
  coalesce(io.external_api_io, 0) as external_api_io
from flows f
left join io using (level1)
order by f.level1
