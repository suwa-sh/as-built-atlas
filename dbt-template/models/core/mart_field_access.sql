-- 列の単位の読み書き。1 行 = 入口 × データ × 列。uses は、使い方の 1 文字を連ねたもの (R = 読む、W = 書く、F = 絞り込み・結合・並べ替えに使う)
-- 列が * の行は、全部の列を触る読み書き (select *、行ごとの削除など)。writes は、書くなら真 (物ごとのまとめで、書く入口を数えるのに使う)
select
  e.entry_id, e.path, f.kind, f.resource_path, f.name as field,
  f.resource_path || '#' || f.name as field_key,
  (case when bool_or(f.use_read) then 'R' else '' end) || (case when bool_or(f.use_write) then 'W' else '' end) || (case when bool_or(f.use_filter) then 'F' else '' end) as uses,
  coalesce(string_agg(distinct nullif(f.set_to, ''), ', ' order by nullif(f.set_to, '')), '') as set_to,
  count(*) as io_count,
  bool_or(f.io_status = 'unknown') as has_unknown,
  bool_or(f.use_write) as writes
from {{ ref('stg_io_fields') }} f
join {{ ref('stg_entries') }} e using (entry_id)
group by e.entry_id, e.path, f.kind, f.resource_path, f.name
order by f.resource_path, f.name, e.path
