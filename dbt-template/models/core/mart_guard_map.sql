-- 入口 × 確認の種類。1 行 = 入口 1 件 × 種類 1 つ (確認が無い組も、0 で出す)。数は、その入口に効く確認の数 (自分の確認と、自分を包む入口の確認)
-- 確かめられなかった確認 (status が unknown) は数えない。認証の確認が 0 の組に no_authentication が付く。この観点を分析した結果だけを出す
with kinds as (
  select kind, min(kind_order) as kind_order from (
    select * from (values ('authentication', 1), ('role', 2), ('permission', 3), ('ownership', 4), ('other', 5)) as t(kind, kind_order)
    union all
    select distinct kind, 9 from {{ ref('stg_guards') }}
  ) group by kind
), effective as (
  select entry_id, kind, status from {{ ref('stg_guards') }}
  union all
  select w.entry_id, g.kind, g.status
  from {{ ref('stg_entry_within') }} w
  join {{ ref('stg_guards') }} g on g.entry_id = w.within_entry_id
), c as (
  select entry_id, kind, count(*) filter (where status <> 'unknown') as guard_count from effective group by entry_id, kind
)
select
  e.entry_id, e.path, k.kind, k.kind_order,
  coalesce(c.guard_count, 0) as guard_count,
  (k.kind = 'authentication' and coalesce(c.guard_count, 0) = 0) as no_authentication,
  e.entry_id || '|' || k.kind as cell_key
from {{ ref('stg_entries') }} e
join {{ ref('stg_results') }} r using (entry_id)
cross join kinds k
left join c on c.entry_id = e.entry_id and c.kind = k.kind
where r.aspects_analyzed
order by e.path, k.kind_order
