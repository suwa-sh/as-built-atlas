{#-
  seed の CSV の読み込み。dbt-duckdb の既定 (duckdb__load_csv_rows) を、引用符とエスケープを明示する形に置き換える。

  既定は、引用符とエスケープを DuckDB の自動判定に任せる。自動判定は、ファイルの先頭のほうの行だけを見て決めるので、
  二重引用符を含む値 (ETL は、CSV の決まりどおり "" と書く) が先頭のほうに無いと、「エスケープ無し」と判定し、
  後ろの行で「引用符が閉じていない」と失敗する (分析結果が数千行になった実物で起きた)。
  ETL (abatlas/etl.py の write_seeds) は、Python の csv の既定 (引用符 "、エスケープは "" ) で書くので、同じ値を明示する。
-#}
{% macro duckdb__load_csv_rows(model, agate_table) %}
    {% set seed_file_path = adapter.get_seed_file_path(model) %}
    {% set delimiter = config.get('delimiter', ',') %}
    {% set sql %}
      COPY {{ this.render() }} FROM '{{ seed_file_path }}' (FORMAT CSV, HEADER TRUE, DELIMITER '{{ delimiter }}', QUOTE '"', ESCAPE '"')
    {% endset %}
    {% do adapter.add_query(sql, abridge_sql_log=True) %}
    {{ return(sql) }}
{% endmacro %}
