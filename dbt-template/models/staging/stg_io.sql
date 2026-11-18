-- 読み書き。分析結果の io を、そのまま 1 行ずつ持つ。足すのは is_repeat だけ
-- is_repeat: 同じ入口の中で、同じ処理を、もう一度書いたフレームの読み書き (数えるときに、2 回数えない)。
--   分析の決まりでは、同じ処理は 1 回だけ書く。ただし、呼び出し元が終端になって検査に落ちるときは、読み書きを持つ最初のフレームまで、もう一度書く。
--   その写しの読み書きは、最初に書いたフレームの読み書きと同じものなので、箇所の数に足すと、同じ読み書きを 2 回数えることになる。
--   判定: 定義の場所 (ファイルと行)・名前・層が同じフレームのうち、入口の中で最初のもの (seq が最小) でないフレームの読み書きで、
--   最初のフレームに、同じ相手 (種類とパス) への同じ操作があるもの。引数で届く先が変わる処理を、届く先ごとに書いたとき (相手が違う) は、当たらない
with f as (
  select entry_id, frame_id, source_file, source_line, name, layer, seq,
    min(seq) over (partition by entry_id, source_file, source_line, name, layer) as first_seq
  from {{ ref('frames') }}
), first_io as (
  select distinct f.entry_id, f.source_file, f.source_line, f.name, f.layer, i.kind, coalesce(i.resource_path, '') as resource_path, i.op
  from {{ ref('io') }} i
  join f using (entry_id, frame_id)
  where f.seq = f.first_seq
)
select
  i.*,
  (f.seq <> f.first_seq and fi.entry_id is not null) as is_repeat
from {{ ref('io') }} i
join f using (entry_id, frame_id)
left join first_io fi
  on fi.entry_id = i.entry_id and fi.source_file = f.source_file and fi.source_line = f.source_line and fi.name = f.name and fi.layer = f.layer
  and fi.kind = i.kind and fi.resource_path = coalesce(i.resource_path, '') and fi.op = i.op
