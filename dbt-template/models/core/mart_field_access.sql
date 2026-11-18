-- 列の単位の読み書き。1 行 = 入口 × データ × 列。uses は、使い方の 1 文字を連ねたもの (R = 読む、W = 書く、F = 絞り込み・結合・並べ替えに使う)
-- 列が * の行は、全部の列を触る読み書き (select *、行ごとの削除など)。writes は、書くなら真 (物ごとのまとめで、書く入口を数えるのに使う)
select
  e.entry_id, e.path, f.kind, f.resource_path, f.name as field,
  f.resource_path || '#' || f.name as field_key,
  (case when bool_or(f.use_read) then 'R' else '' end) || (case when bool_or(f.use_write) then 'W' else '' end) || (case when bool_or(f.use_filter) then 'F' else '' end) as uses,
  coalesce(string_agg(distinct nullif(f.set_to, ''), ', ' order by nullif(f.set_to, '')), '') as set_to,
  -- 箇所の数は、もう一度書いたフレームの分を除く。列が、もう一度書いたフレームにだけ書いてあるときは、1 と数える (同じ読み書きの写しなので、箇所は 1 つある)
  -- 使い方・入れる値・不明の印は、写しの分も合わせる (写しにだけ書いてある情報を、落とさない)
  greatest(count(*) filter (where not f.is_repeat), 1) as io_count,
  bool_or(f.io_status = 'unknown') as has_unknown,
  bool_or(f.use_write) as writes
from {{ ref('stg_io_fields') }} f
join {{ ref('stg_entries') }} e using (entry_id)
group by e.entry_id, e.path, f.kind, f.resource_path, f.name
order by f.resource_path, f.name, e.path
