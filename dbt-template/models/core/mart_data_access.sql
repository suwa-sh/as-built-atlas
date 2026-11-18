-- 読み書きするデータ (入口の階層 × データの階層)。データの種類 (kind) を列に持つ 1 枚。
-- ops は種類ごとの操作の 1 文字を語彙の並び順に連ねたもの (例: RDB なら "CRU"、ファイルなら "RWD")。
-- 画面は kind で絞って種類ごとの表にし、行 (path) と列 (resource_path) を節ごとに畳む (畳んだ値は API の pivot が集計する)
with letters as (
  select i.entry_id, i.kind, i.resource_path, i.op_letter, min(i.op_rank) as op_rank,
    count(*) filter (where not i.is_repeat) as io_count, bool_or(i.status = 'unknown') as has_unknown   -- 箇所の数は、もう一度書いたフレームの分を除く。不明の印は、写しの分も合わせる (落とさない)
  from {{ ref('stg_io') }} i
  where i.kind <> 'external_api'
  group by i.entry_id, i.kind, i.resource_path, i.op_letter
)
select
  e.entry_id, e.path, e.level1, e.level2,
  l.kind, l.resource_path,
  string_agg(l.op_letter, '' order by l.op_rank) as ops,
  sum(l.io_count) as io_count,
  bool_or(l.has_unknown) as has_unknown
from letters l
join {{ ref('stg_entries') }} e using (entry_id)
group by e.entry_id, e.path, e.level1, e.level2, l.kind, l.resource_path
order by e.path, l.kind, l.resource_path
