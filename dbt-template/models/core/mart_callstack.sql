-- 呼び出しの構造 (入口ごとの処理と親子関係)。source は定義場所 (file:line)
select
  f.entry_id, e.path,
  f.frame_id, f.caller_id, f.layer, f.kind, f.name, f.source_file, f.source_line,
  f.source_file || ':' || cast(f.source_line as varchar) as source,
  f.call_status, f.summary_status, f.summary,
  (select count(*) from {{ ref('stg_io') }} i where i.entry_id = f.entry_id and i.frame_id = f.frame_id) as io_count
from {{ ref('stg_frames') }} f
join {{ ref('stg_entries') }} e using (entry_id)
order by e.path, f.seq
