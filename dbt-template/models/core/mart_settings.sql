-- 設定への依存。1 行 = 設定 × 入口 (同じ名前の設定に種類が 2 つ書かれていたら、kind に並べる)。effect は、その設定で動きがどう変わるか (処理ごとの説明を並べる)
select
  s.name as setting,
  string_agg(distinct s.kind, ', ' order by s.kind) as kind,
  e.entry_id, e.path,
  string_agg(distinct fr.name, ', ' order by fr.name) as frames,
  coalesce(string_agg(distinct nullif(s.effect, ''), ' / ' order by nullif(s.effect, '')), '') as effect,
  s.name || '|' || e.entry_id as setting_key,
  bool_or(s.status = 'unknown') as has_unknown
from {{ ref('stg_settings') }} s
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_frames') }} fr on fr.entry_id = s.entry_id and fr.frame_id = s.frame_id
group by s.name, e.entry_id, e.path
order by s.name, e.path
