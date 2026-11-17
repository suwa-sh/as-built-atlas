-- データを介したつながり。同じデータを、書く入口と、読む入口が別にあるもの。1 行 = データ 1 つ
-- キューやテーブルやファイルを介して動く入口のつながり (ある入口が書いたものを、別の入口が読む) を出す。呼び出しや遷移では結ばれない
-- 向きは、操作の語彙の direction (out = 書く側、in = 読む側)。外部の接続先は含めない。書く入口と読む入口が同じ 1 件だけのデータは出さない
with io as (
  -- resource_path は、分かっている段の値だけをつないだもの。欠けた段があると、別のデータが同じパスになりうる (database が x のものと、table が x のもの)。
  -- そこで、段ごとの値をすべて並べた levels_key も合わせて、同じデータかを決める
  select distinct i.kind, i.resource_path, i.op_direction, e.entry_id, e.path,
    -- 空の段も位置を保つ (値の無い段を飛ばすと、別の段の同じ値と区別できない)
    coalesce(i.lv_host, '') || '|' || coalesce(i.lv_dbms, '') || '|' || coalesce(i.lv_database, '') || '|' || coalesce(i.lv_schema, '') || '|' || coalesce(i.lv_table, '') || '|' || coalesce(i.lv_instance, '') || '|' || coalesce(i.lv_namespace, '') || '|' || coalesce(i.lv_key_pattern, '') || '|' || coalesce(i.lv_broker, '') || '|' || coalesce(i.lv_topic, '') || '|' || coalesce(i.lv_directory, '') || '|' || coalesce(i.lv_file, '') || '|' || coalesce(i.lv_account, '') || '|' || coalesce(i.lv_bucket, '') || '|' || coalesce(i.lv_prefix, '') || '|' || coalesce(i.lv_object, '') as levels_key
  from {{ ref('stg_io') }} i
  join {{ ref('stg_entries') }} e using (entry_id)
  where i.kind <> 'external_api'
), w as (
  select kind, resource_path, levels_key, count(*) as writer_count, string_agg(path, ', ' order by path) as writers
  from io where op_direction = 'out' group by kind, resource_path, levels_key
), r as (
  select kind, resource_path, levels_key, count(*) as reader_count, string_agg(path, ', ' order by path) as readers
  from io where op_direction = 'in' group by kind, resource_path, levels_key
), pairs as (
  -- 書く入口と読む入口が違う組が、1 つでもあるデータ
  select distinct a.kind, a.resource_path, a.levels_key
  from io a join io b on a.kind = b.kind and a.resource_path = b.resource_path and a.levels_key = b.levels_key
  where a.op_direction = 'out' and b.op_direction = 'in' and a.entry_id <> b.entry_id
)
select
  p.kind, p.resource_path,
  w.writer_count, w.writers,
  r.reader_count, r.readers
from pairs p
join w using (kind, resource_path, levels_key)
join r using (kind, resource_path, levels_key)
order by p.kind, p.resource_path
