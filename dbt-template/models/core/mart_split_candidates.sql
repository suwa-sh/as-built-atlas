-- 別の入口に分ける候補。3 件以上の入口が通り、その下に 10 以上の処理の段を持つ処理 (定義の場所 (ファイルと行)・名前・層が同じフレーム)。1 行 = 処理 1 つ
-- 多くの入口が描く部品は、入口の数だけ、同じ木が分析結果に繰り返される。その部品を別の入口にすれば、分析は 1 回で済む (決めるのは人。プロファイルの決まりを見る)
--   frames_each    = その処理の下の段の数 (自分を含む。入口ごとの数の最大)
--   repeated_frames = 繰り返されている段の数 (入口ごとの数の合計から、1 回分を引いたもの)。分けると、おおよそこの数の段が、分析結果から減る
-- 段の数は、処理の数 (定義の場所・名前・層の組) で数える。終端の決まりを満たすために、もう一度書いたフレームは、同じ処理なので、2 回数えない。
-- 同じ入口の中に、同じ処理のフレームが 2 つ以上あるときは、下の段がいちばん多いものを採る (結果のファイルの中の並び順には、頼らない)
-- 外との境の層 (boundary) の処理は、出さない。大きな処理の中の処理も、条件を満たせば別の行として出る (外側を分ければ、内側は分けなくてよい)
with recursive frames as (
  select entry_id, frame_id, layer, name, source_file, source_line, coalesce(caller_id, '') as caller_id, boundary,
    source_file || ':' || source_line || '|' || name || '|' || layer as def_key
  from {{ ref('stg_frames') }}
), walk as (
  -- フレームごとに、その下の段 (自分を含む) を辿る
  select entry_id, frame_id as root_id, frame_id from frames where caller_id <> ''
  union all
  select f.entry_id, w.root_id, f.frame_id
  from frames f join walk w on f.entry_id = w.entry_id and f.caller_id = w.frame_id
), size as (
  select w.entry_id, w.root_id as frame_id, count(distinct f.def_key) as subtree
  from walk w join frames f on f.entry_id = w.entry_id and f.frame_id = w.frame_id
  group by w.entry_id, w.root_id
), per_entry as (
  select f.entry_id, f.source_file, f.source_line, f.name, f.layer, max(s.subtree) as subtree
  from frames f join size s using (entry_id, frame_id)
  where f.caller_id <> '' and coalesce(f.boundary, '') <> 'true'
  group by f.entry_id, f.source_file, f.source_line, f.name, f.layer
)
select
  x.layer, x.name, x.source_file,
  count(*) as entry_count,
  max(x.subtree) as frames_each,
  sum(x.subtree) - max(x.subtree) as repeated_frames,
  string_agg(e.path, ', ' order by e.path) as entries,
  x.source_file || ':' || x.source_line || '|' || x.name || '|' || x.layer as candidate_key
from per_entry x
join {{ ref('stg_entries') }} e using (entry_id)
group by x.layer, x.name, x.source_file, x.source_line
having count(*) >= 3 and max(x.subtree) >= 10
order by repeated_frames desc, x.source_file, x.source_line, x.name, x.layer
