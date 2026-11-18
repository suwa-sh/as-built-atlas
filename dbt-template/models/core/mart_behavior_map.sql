-- 入口ごとの、動きを変える物の数。1 行 = 入口 1 件 × 種類 1 つ (数が 0 の組は出さない)
-- 種類: conditional_call = いつも起きるとは限らない呼び出し、decision / validation / calculation = 業務のルール、setting = 動きを変える設定 (名前の数)
with c as (
  select path, 'conditional_call' as kind, 1 as kind_order, count(*) as item_count from {{ ref('mart_call_conditions') }} group by path
  union all
  select path, kind, case kind when 'decision' then 2 when 'validation' then 3 when 'calculation' then 4 else 5 end, count(*) from {{ ref('mart_rules') }} group by path, kind
  union all
  select path, 'setting', 6, count(distinct setting) from {{ ref('mart_settings') }} group by path
)
select path, kind, kind_order, item_count, path || '|' || kind as cell_key
from c
order by path, kind_order
