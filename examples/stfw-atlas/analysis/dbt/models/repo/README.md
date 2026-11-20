# analysis/dbt/models/repo

この分析リポジトリ独自の mart を置く (保持される。upgrade で上書きされない)。
build のたびに、イメージの中の core / profile のテンプレートと合成して dbt を動かす (作業ディレクトリは `analysis/data/dbt/`)。
宣言は core と同じく `schema.yml` の `meta.abatlas` に書く (origin: repo)。`{{ ref('stg_entries') }}` など staging を参照できる。
