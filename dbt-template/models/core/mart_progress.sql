-- 進行状況。階層の第 1 段ごとの入口数・承認・分析済み。run の記録 (任意) があれば実績コストと残りの見積もりも出す
-- stg_results は entry_id で一意 (ETL が検査する) なので 1 回だけ結合する
select
  e.level1,
  count(*) as entries,
  count(*) filter (where e.status = 'approved') as approved,
  count(*) filter (where e.status = 'approved' and r.entry_id is not null) as analyzed,
  count(*) filter (where e.status = 'candidate') as candidate,
  count(*) filter (where e.status = 'rejected') as rejected,
  count(r.run_cost_usd) as runs_with_cost,
  sum(r.run_cost_usd) as cost_usd,
  sum(r.run_duration_s) as duration_s,
  -- 残り (承認済みで未分析) × 平均コスト。run の記録が無ければ null
  (count(*) filter (where e.status = 'approved' and r.entry_id is null)) * avg(r.run_cost_usd) as estimated_remaining_cost_usd,
  (count(*) filter (where e.status = 'approved' and r.entry_id is null)) * avg(r.run_duration_s) as estimated_remaining_duration_s
from {{ ref('stg_entries') }} e
left join {{ ref('stg_results') }} r using (entry_id)
group by e.level1
order by e.level1
