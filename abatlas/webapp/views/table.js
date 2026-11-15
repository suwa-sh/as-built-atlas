// 表示の種類: 表 (view: table)

import { showCols } from "../model/catalog.js";
import { emptyMsg } from "../ui/card.js";
import { gridTable } from "../ui/table.js";

export function table(m, data) {
  if (!data.rows.length) return emptyMsg("行が無い");
  return gridTable(m, data.rows, showCols(m, data.columns), {});
}
