select
  e.entry_id, e.path, c.reason,
  count(*) as unknown_count,
  string_agg(c.claim_path, ', ' order by c.claim_path) as wheres
from {{ ref('stg_claims') }} c
join {{ ref('stg_entries') }} e using (entry_id)
where c.status = 'unknown'
group by e.entry_id, e.path, c.reason
order by e.path, c.reason
