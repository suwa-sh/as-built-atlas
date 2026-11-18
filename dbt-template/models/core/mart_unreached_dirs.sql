-- どの入口からも辿られないファイルを、フォルダごとに数える。1 行 = フォルダ 1 つ。数は、その下 (さらに下のフォルダも含む) のファイルの数
-- 範囲の直下に置かれたファイルは、(top) にまとめる
with f as (
  select file, string_split(file, '/') as parts from {{ ref('mart_unreached_files') }}
), d as (
  select array_to_string(parts[1:i], '/') as dir, i as depth from f, unnest(range(1, len(parts))) as t(i)
  union all
  select '(top)' as dir, 1 as depth from f where len(parts) = 1
)
select
  dir,
  case when depth > 1 then regexp_replace(dir, '/[^/]+$', '') else '' end as parent,
  regexp_extract(dir, '[^/]+$') as name,
  count(*) as file_count,
  depth
from d
group by dir, depth
order by dir
