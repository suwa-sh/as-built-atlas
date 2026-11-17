-- 入口ごとの権限のまとめ。認証の確認 (kind = authentication) が、自分か、自分を包む入口にあるか。この観点を分析した結果だけを出す
-- 確かめられなかった確認 (status が unknown) は、認証ありに数えず、求める役割と権限にも並べない (unknown_guard_count に出す)
-- authentication が false の行は、「認証の確認が見つからなかった入口」。包む入口がまだ分析されていないときは、そこにある確認を数えられない (enclosing_not_analyzed で分かる)
with g as (
  select entry_id,
    bool_or(kind = 'authentication' and status <> 'unknown') as authentication,
    count(*) filter (where status = 'unknown') as unknown_guard_count,
    count(*) as guard_count,
    coalesce(string_agg(distinct case when kind = 'role' and status <> 'unknown' then nullif(value, '') end, ', ' order by case when kind = 'role' and status <> 'unknown' then nullif(value, '') end), '') as roles,
    coalesce(string_agg(distinct case when kind = 'permission' and status <> 'unknown' then nullif(value, '') end, ', ' order by case when kind = 'permission' and status <> 'unknown' then nullif(value, '') end), '') as permissions
  from {{ ref('mart_entry_guards') }} group by entry_id
), pending as (
  select w.entry_id, count(*) as enclosing_not_analyzed
  from {{ ref('stg_entry_within') }} w
  left join {{ ref('stg_results') }} r on r.entry_id = w.within_entry_id and r.aspects_analyzed
  where r.entry_id is null
  group by w.entry_id
)
select
  e.entry_id, e.path, e.name, e.layer,
  coalesce(g.authentication, false) as authentication,
  coalesce(g.guard_count, 0) as guard_count,
  coalesce(g.unknown_guard_count, 0) as unknown_guard_count,
  coalesce(g.roles, '') as roles,
  coalesce(g.permissions, '') as permissions,
  coalesce(p.enclosing_not_analyzed, 0) as enclosing_not_analyzed
from {{ ref('stg_entries') }} e
join {{ ref('stg_results') }} r using (entry_id)
left join g using (entry_id)
left join pending p using (entry_id)
where r.aspects_analyzed
order by coalesce(g.authentication, false), e.path
