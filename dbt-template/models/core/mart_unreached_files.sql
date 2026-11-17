-- どの入口からも辿られないファイル。対象の範囲にあるファイルのうち、分析結果のどこにも出てこないもの
-- (処理の定義の場所、入口の定義の場所、主張の根拠のどれにも無い)。1 行 = ファイル 1 つ
-- 分析していない入口が残っている間は、その入口からだけ辿られるファイルも、ここに出る (analyzed / approved で分かる)
-- 対象の clone が読めない場所で集計したときは、空
with reached as (
  select source_file as file from {{ ref('stg_frames') }}
  union
  select file from {{ ref('stg_evidence') }}
  union
  select source_file from {{ ref('stg_entries') }}
), progress as (
  select
    (select count(*) from {{ ref('stg_results') }}) as analyzed,
    (select count(*) from {{ ref('stg_entries') }} where status = 'approved') as approved
)
select
  t.file, t.top, t.ext,
  p.analyzed, p.approved
from {{ ref('stg_target_files') }} t
cross join progress p
left join reached r on r.file = t.file
where r.file is null
order by t.file
