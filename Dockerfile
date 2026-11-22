# as-built-atlas の配布物 (コンテナイメージ)。分析リポジトリに必要な依存は Docker だけ。
#   docker build -t ghcr.io/suwa-sh/as-built-atlas:dev .
#   docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:dev init . --profile batch-kestra
FROM python:3.12-slim AS os-updates

# Update the base packages. uv manages Python dependencies, including in analysis repositories.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip \
    && rm -f /usr/local/lib/python3.12/ensurepip/_bundled/pip-*.whl \
    && git config --system safe.directory '*'
FROM os-updates
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

WORKDIR /opt/abatlas
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONDONTWRITEBYTECODE=1

# 依存だけ先に入れる (レイヤーキャッシュ)
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# 配布物 = リポジトリのうち、ツール・schema・プロファイル・dbt テンプレート・skill・見本・文書
COPY abatlas ./abatlas
COPY schema ./schema
COPY profiles ./profiles
COPY dbt-template ./dbt-template
COPY .agents ./.agents
COPY tests/fixtures ./tests/fixtures
COPY docs/architecture ./docs/architecture
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

ENV PATH="/opt/abatlas/.venv/bin:$PATH"
ENTRYPOINT ["abatlas"]
CMD ["--help"]