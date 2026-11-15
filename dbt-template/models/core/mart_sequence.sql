-- シーケンス (入口ごと)。呼び出し (呼び出し元フレーム → フレーム) と I/O (フレーム → データ) を、callstack の並び順でメッセージ列にする
-- seq は入口ごとの連番 (フレームの並び順 → そのフレームへの呼び出し → そのフレームの I/O の順)。I/O の件数に上限は無い
-- frame_id は、そのメッセージを起こした処理 (呼び出しなら呼ばれた側、I/O なら読み書きした側)。呼び出しの構造 (mart_callstack) の節と対応する
-- evidence は、そのメッセージの根拠の場所 (file:line を ", " で連ねる。根拠が無ければ null)
with ev as (
  select entry_id, claim_path, string_agg(file || ':' || cast(line as varchar), ', ' order by file, line) as evidence
  from {{ ref('stg_evidence') }}
  group by entry_id, claim_path
), calls as (
  select
    f.entry_id, e.path, f.seq as frame_seq, 0 as sub, 0 as idx,
    c.name as from_node, f.name as to_node,
    coalesce(f.kind, 'call') as message, 'call' as message_kind,
    f.call_status as status, f.call_reason as reason, f.frame_id,
    'callstack/' || f.frame_id || '/call' as claim_path
  from {{ ref('stg_frames') }} f
  join {{ ref('stg_entries') }} e using (entry_id)
  join {{ ref('stg_frames') }} c on c.entry_id = f.entry_id and c.frame_id = f.caller_id
), ios as (
  select
    i.entry_id, e.path, f.seq as frame_seq, 1 as sub, i.idx,
    f.name as from_node, i.resource_path as to_node,
    i.op as message, 'io' as message_kind,
    i.status, i.reason, f.frame_id,
    'callstack/' || f.frame_id || '/io/' || cast(i.idx as varchar) as claim_path
  from {{ ref('stg_io') }} i
  join {{ ref('stg_frames') }} f on f.entry_id = i.entry_id and f.frame_id = i.frame_id
  join {{ ref('stg_entries') }} e on e.entry_id = i.entry_id
), msgs as (
  select * from calls union all select * from ios
)
select
  m.entry_id, m.path,
  row_number() over (partition by m.entry_id order by m.frame_seq, m.sub, m.idx) as seq,
  m.from_node, m.to_node, m.message, m.message_kind, m.status, m.reason, m.frame_id,
  ev.evidence
from msgs m
left join ev on ev.entry_id = m.entry_id and ev.claim_path = m.claim_path
order by m.path, seq
