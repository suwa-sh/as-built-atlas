-- 個人情報などの流れ。データの辞書で、人が確かめた (approved) 列のうち、気を付ける区分のものを触る入口。1 行 = 入口 × データ × 列
-- 列が * の読み書き (全部の列) は、そのデータの、辞書にある列すべてを触るものとして数える
-- externals は、同じ入口が呼ぶ外部の接続先。「この入口から外へ出うる」という粗い見方で、その列の値が実際に送られるかまでは追っていない
with d as (
  select resource_path, field, category, category_label from {{ ref('stg_data_dictionary') }} where status = 'approved' and sensitive
), hit as (
  select f.entry_id, d.resource_path, d.field, d.category, d.category_label,
    bool_or(f.use_read) as r, bool_or(f.use_write) as w, bool_or(f.use_filter) as fl
  from {{ ref('stg_io_fields') }} f
  join d on d.resource_path = f.resource_path and (f.name = d.field or f.name = '*')
  group by f.entry_id, d.resource_path, d.field, d.category, d.category_label
), ext as (
  select entry_id, count(distinct resource_path) as external_count,
    string_agg(distinct coalesce(nullif(lv_host, ''), '(unknown)'), ', ' order by coalesce(nullif(lv_host, ''), '(unknown)')) as externals
  from {{ ref('stg_io') }} where kind = 'external_api' group by entry_id
)
select
  e.entry_id, e.path, h.category, h.category_label, h.resource_path, h.field,
  h.resource_path || '#' || h.field as field_key,
  (case when h.r then 'R' else '' end) || (case when h.w then 'W' else '' end) || (case when h.fl then 'F' else '' end) as uses,
  coalesce(x.external_count, 0) as external_count,
  coalesce(x.externals, '') as externals
from hit h
join {{ ref('stg_entries') }} e using (entry_id)
left join ext x using (entry_id)
order by h.category, h.resource_path, h.field, e.path
