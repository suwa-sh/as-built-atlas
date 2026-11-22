// 画面: 分析の状態 (#/status)

import { el } from "../lib/dom.js";
import { hEntry } from "../lib/hash.js";
import { model } from "../model/catalog.js";
import { cardFor } from "../ui/card.js";
import { toast } from "../ui/toast.js";
import { panelBody, byView } from "../views/index.js";
import { term } from "../model/vocab.js";

const $main = document.getElementById("main");

export function pageStatus() {
  const marts = [
    ...new Set([
      ...(model.subj.analysis || []),
      ...model.catalog.filter((m) => m.tags.includes("monitor")),
    ]),
  ].sort(byView);
  const parts = [
    el(
      "div",
      { class: "head" },
      el(
        "div",
        null,
        el("h1", null, term("analysis_status")),
        el(
          "p",
          { class: "sub" },
          `どこまで分析が進み、どこが ${term("unknown")} か。${term("mart")} の ${term("rebuild")} もここから`,
        ),
      ),
    ),
  ];
  for (const m of marts)
    parts.push(
      cardFor(
        m,
        panelBody(m, {}, { link: m.keys.path ? (r) => hEntry(r[m.keys.path]) : null }),
        {},
      ),
    );
  const btn = el("button", { class: "primary" }, `${term("mart")} を ${term("rebuild")}`);
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = `${term("rebuild")} 中…`;
    try {
      const r = await fetch("recompute", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(`${r.status} ${j.detail || r.statusText}`);
      toast(
        `${term("rebuild")} した: dbt ${j.dbt_ok}/${j.dbt_nodes} ノード、${term("entry")} ${j.entries} 件、結果 ${j.results} 件`,
      );
      document.dispatchEvent(new CustomEvent("abatlas:reload")); // 画面の層は起動 (app.js) を読めないので、イベントで知らせる。app.js が受けてカタログ・ナビ・画面を読み直す
    } catch (e) {
      toast(`${term("rebuild")} できない: ${e.message}`, 10000);
    } finally {
      btn.disabled = false;
      btn.textContent = `${term("mart")} を ${term("rebuild")}`;
    }
  });
  parts.push(
    el(
      "section",
      { class: "card" },
      el("h2", null, `${term("mart")} を ${term("rebuild")}`),
      el(
        "p",
        { class: "note" },
        `分析結果 YAML (analysis/results) と ${term("entry")} 一覧から、すべての ${term("mart")} を ${term("rebuild")} する (ETL → dbt build)。数分かかることがある。閲覧者には不要な操作`,
      ),
      btn,
    ),
  );
  $main.replaceChildren(...parts);
}
