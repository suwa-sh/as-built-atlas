-- 読み書きが触る列。is_repeat は、その読み書きが、もう一度書いたフレームのものか (stg_io と同じ)
select
  f.*,
  coalesce(i.is_repeat, false) as is_repeat
from {{ ref('io_fields') }} f
left join {{ ref('stg_io') }} i on i.entry_id = f.entry_id and i.frame_id = f.frame_id and i.idx = f.io_idx
