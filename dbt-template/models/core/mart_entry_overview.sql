with io_counts as (
  select entry_id,
    count(*) as io_count,
    count(*) filter (where status = 'unknown') as io_unknown
  from {{ ref('stg_io') }} group by entry_id
), claim_counts as (
  select entry_id,
    count(*) as claim_count,
    count(*) filter (where status = 'fact') as fact_count,
    count(*) filter (where status = 'interpretation') as interpretation_count,
    count(*) filter (where status = 'unknown') as unknown_count
  from {{ ref('stg_claims') }} group by entry_id
)
select
  e.entry_id, e.path, e.name, e.layer, e.status, e.level1, e.level2, e.depth,
  r.entry_id is not null as analyzed,
  r.analyzed_at, r.target_commit, r.profile_version,
  -- 今のプロファイルの版と違う版で分析した結果 (分析の決まりが変わっていれば、範囲が今と違う)。未分析は false
  coalesce(r.profile_stale, false) as profile_stale,
  r.skill_version, r.reviewed_findings_open,
  r.run_cost_usd, r.run_duration_s,
  r.summary,
  coalesce(r.frame_count, 0) as frame_count,
  coalesce(i.io_count, 0) as io_count,
  coalesce(c.claim_count, 0) as claim_count,
  coalesce(c.fact_count, 0) as fact_count,
  coalesce(c.interpretation_count, 0) as interpretation_count,
  coalesce(c.unknown_count, 0) as unknown_count,
  -- 複雑度の仮の指標: フレーム数 + I/O 数 (段階 2 では置き場だけ用意する)
  coalesce(r.frame_count, 0) + coalesce(i.io_count, 0) as complexity
from {{ ref('stg_entries') }} e
left join {{ ref('stg_results') }} r using (entry_id)
left join io_counts i using (entry_id)
left join claim_counts c using (entry_id)
