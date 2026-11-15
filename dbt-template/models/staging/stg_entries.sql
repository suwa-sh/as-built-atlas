-- 入口一覧。階層パスを第 1〜5 段に分解する (深さは任意だが、行列やページの畳み込みに上位 5 段を使う)
with e as (
  select *, string_split(path, '/') as parts from {{ ref('entries') }}
)
select
  entry_id, path, name, layer, status, extractor, source_file, source_line, depth,
  nullif(parts[2], '') as level1,
  nullif(parts[3], '') as level2,
  nullif(parts[4], '') as level3,
  nullif(parts[5], '') as level4,
  nullif(parts[6], '') as level5,
  -- 親のパス (ページのドリルダウン用)
  case when depth > 1 then regexp_replace(path, '/[^/]+$', '') else null end as parent_path
from e
