-- 状態の変化。決まった値を書く列 (set_to を持つ列) ごとに、その値を書く入口と処理。1 行 = データ × 列 × 書く値 × 入口 × 処理 (処理は frame_id で見分ける。同じ名前の処理が 2 つあれば 2 行)
select
  f.resource_path, f.name as field, f.set_to,
  f.resource_path || '#' || f.name as field_key,
  f.entry_id || '|' || f.frame_id || '|' || f.resource_path || '#' || f.name || '=' || f.set_to as change_key,
  count(*) as io_count,
  e.entry_id, e.path, f.frame_id, fr.name as frame_name, fr.layer,
  coalesce(nullif(fr.call_when, ''), '') as call_when
from {{ ref('stg_io_fields') }} f
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_frames') }} fr on fr.entry_id = f.entry_id and fr.frame_id = f.frame_id
where f.set_to <> ''
  -- もう一度書いたフレームは、同じ書き込みの写しなので出さない。ただし、その値が、写しにだけ書いてあるときは、出す (落とさない)
  and (not f.is_repeat or not exists (
    select 1 from {{ ref('stg_io_fields') }} o
    where o.entry_id = f.entry_id and o.resource_path = f.resource_path and o.name = f.name and o.set_to = f.set_to and not o.is_repeat))
group by f.resource_path, f.name, f.set_to, f.entry_id, e.entry_id, e.path, f.frame_id, fr.name, fr.layer, fr.call_when
order by f.resource_path, f.name, f.set_to, e.path, fr.name
