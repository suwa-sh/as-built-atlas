-- 設定の広がり。1 行 = 設定 × 入口の階層の最初の段。数は、その段の下で、その設定に動きを左右される入口の数
select
  setting,
  coalesce(nullif(string_split(path, '/')[2], ''), '/') as section,
  count(distinct entry_id) as entry_count,
  setting || '|' || coalesce(nullif(string_split(path, '/')[2], ''), '/') as cell_key
from {{ ref('mart_settings') }}
group by 1, 2
order by 1, 2
