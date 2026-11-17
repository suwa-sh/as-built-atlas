-- データを介したつながり。同じデータを、書く入口と、読む入口が別にあるもの。1 行 = データ 1 つ
-- キューやテーブルやファイルを介して動く入口のつながり (ある入口が書いたものを、別の入口が読む) を出す。呼び出しや遷移では結ばれない
-- 向きは、操作の語彙の direction (out = 書く側、in = 読む側)。外部の接続先は含めない。書く入口と読む入口が同じ 1 件だけのデータは出さない
with io as (
  select distinct i.kind, i.resource_path, i.op_direction, e.entry_id, e.path
  from {{ ref('stg_io') }} i
  join {{ ref('stg_entries') }} e using (entry_id)
  where i.kind <> 'external_api'
), w as (
  select kind, resource_path, count(*) as writer_count, string_agg(path, ', ' order by path) as writers
  from io where op_direction = 'out' group by kind, resource_path
), r as (
  select kind, resource_path, count(*) as reader_count, string_agg(path, ', ' order by path) as readers
  from io where op_direction = 'in' group by kind, resource_path
), pairs as (
  -- 書く入口と読む入口が違う組が、1 つでもあるデータ
  select distinct a.kind, a.resource_path
  from io a join io b on a.kind = b.kind and a.resource_path = b.resource_path
  where a.op_direction = 'out' and b.op_direction = 'in' and a.entry_id <> b.entry_id
)
select
  p.kind, p.resource_path,
  w.writer_count, w.writers,
  r.reader_count, r.readers
from pairs p
join w using (kind, resource_path)
join r using (kind, resource_path)
order by p.kind, p.resource_path
