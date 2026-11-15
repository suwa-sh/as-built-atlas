select
  coalesce(nullif(i.lv_host, ''), '(不明)') as host,
  i.lv_path as api_path,
  count(distinct i.entry_id) as entry_count,
  string_agg(distinct e.path, ', ' order by e.path) as entries,
  bool_or(i.status = 'unknown') as has_unknown
from {{ ref('stg_io') }} i
join {{ ref('stg_entries') }} e using (entry_id)
where i.kind = 'external_api'
group by host, i.lv_path
order by host, api_path
