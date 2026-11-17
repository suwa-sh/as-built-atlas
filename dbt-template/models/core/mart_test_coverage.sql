-- テストとの対応。1 行 = 処理 1 つ (テストとの対応を分析した結果だけ)。test_count が 0 の行は、その処理を直接呼ぶテストが見つからなかった
-- 確かめられなかった対応 (status が unknown) は、数と名前に入れない (unknown_test_count に出す)
-- 外との境の層の処理 (リポジトリに定義が無いライブラリなど。プロファイルの role: boundary) は、テストの対象ではないので出さない
select
  e.entry_id, e.path, f.name as frame_name, f.layer,
  f.source_file || ':' || cast(f.source_line as varchar) as source,
  count(t.idx) filter (where t.status <> 'unknown') as test_count,
  count(t.idx) filter (where t.status = 'unknown') as unknown_test_count,
  coalesce(string_agg(t.name, ', ' order by t.name) filter (where t.status <> 'unknown'), '') as tests,
  coalesce(string_agg(distinct t.kind, ', ' order by t.kind) filter (where t.status <> 'unknown'), '') as test_kinds,
  f.entry_id || '|' || f.frame_id as frame_key
from {{ ref('stg_frames') }} f
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_results') }} r using (entry_id)
left join {{ ref('stg_tests') }} t on t.entry_id = f.entry_id and t.frame_id = f.frame_id
where r.tests_analyzed and not coalesce(f.boundary, false)
group by e.entry_id, e.path, f.name, f.layer, f.source_file, f.source_line, f.entry_id, f.frame_id
order by count(t.idx) filter (where t.status <> 'unknown'), e.path, f.name
