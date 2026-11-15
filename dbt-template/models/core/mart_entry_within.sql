-- 入口を包む入口。1 行 = 包まれる入口 × 包む入口 (包む入口が無い入口は行にならない)。ord は外側からの順 (1 が最も外側)。
-- 包む側と包まれる側は別々に分析するので、処理と読み書きは足し合わせない。
-- within_status が rejected の包む入口は分析されないので、その処理はどの入口の結果にも現れない
select
  w.entry_id, w.path, e.name, e.layer,
  w.ord,
  w.within_entry_id, w.within_path, we.name as within_name, we.status as within_status
from {{ ref('stg_entry_within') }} w
join {{ ref('stg_entries') }} e using (entry_id)
join {{ ref('stg_entries') }} we on we.entry_id = w.within_entry_id
order by w.path, w.ord
