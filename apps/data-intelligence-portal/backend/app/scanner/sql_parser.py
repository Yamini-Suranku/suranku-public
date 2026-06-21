"""SQL parsing for the repo scanner.

Uses sqlglot to extract, from a SQL string:
  - the unique real source tables (CTE names excluded),
  - the target table (from CREATE/INSERT, else a supplied default), and
  - column-level lineage with the transformation expression, resolved through
    CTEs and nested subqueries back to real source columns.

Everything is best-effort: a parse failure is reported as a warning, never raised.
"""
from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage

# --- dbt Jinja preprocessing -------------------------------------------------
# dbt models are the most common SQL repos; resolve their templating to plain SQL
# so tables/columns parse. ref('m')->m, source('s','t')->s.t, config/blocks stripped.
_DBT_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_DBT_BLOCK = re.compile(r"\{%.*?%\}", re.S)
_DBT_CONFIG = re.compile(r"\{\{\s*config\s*\(.*?\)\s*\}\}", re.S)
_DBT_REF = re.compile(r"\{\{\s*ref\s*\((.*?)\)\s*\}\}", re.S)
_DBT_SOURCE = re.compile(r"\{\{\s*source\s*\((.*?)\)\s*\}\}", re.S)
_DBT_OTHER = re.compile(r"\{\{.*?\}\}", re.S)
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")


def _render_dbt(sql: str) -> str:
    if "{{" not in sql and "{%" not in sql:
        return sql
    sql = _DBT_COMMENT.sub(" ", sql)
    sql = _DBT_BLOCK.sub(" ", sql)
    sql = _DBT_CONFIG.sub(" ", sql)
    sql = _DBT_REF.sub(lambda m: (_QUOTED.findall(m.group(1)) or ["ref"])[-1], sql)
    sql = _DBT_SOURCE.sub(
        lambda m: ".".join(_QUOTED.findall(m.group(1))[-2:]) or "source", sql
    )
    sql = _DBT_OTHER.sub("macro_value", sql)  # any remaining expression -> placeholder
    return sql


def _table_name(table: exp.Table) -> str:
    parts = [table.args.get("catalog"), table.args.get("db"), table.this]
    return ".".join(p.name for p in parts if p)


def _target_of(stmt: exp.Expression, default_target: str | None) -> tuple[str | None, exp.Expression]:
    """Return (target_table, select_expression) for a statement."""
    if isinstance(stmt, exp.Create) and isinstance(stmt.this, (exp.Table, exp.Schema)):
        tbl = stmt.this if isinstance(stmt.this, exp.Table) else stmt.this.this
        body = stmt.expression or stmt
        return (_table_name(tbl) if isinstance(tbl, exp.Table) else default_target, body)
    if isinstance(stmt, exp.Insert):
        tgt = stmt.this
        if isinstance(tgt, exp.Schema):
            tgt = tgt.this
        body = stmt.expression or stmt
        return (_table_name(tgt) if isinstance(tgt, exp.Table) else default_target, body)
    return default_target, stmt


def parse_sql(sql: str, dialect: str | None = None, default_target: str | None = None) -> dict[str, Any]:
    """Parse a SQL string (may contain multiple statements).

    Returns:
        {
          "source_tables": [str, ...],            # unique real source tables
          "targets": [str, ...],                  # target tables touched
          "table_edges": [{source, target, relation}],
          "column_edges": [{source_table, source_column, target_table,
                            target_column, transformation}],
          "warnings": [str, ...],
        }
    """
    out: dict[str, Any] = {
        "source_tables": [],
        "targets": [],
        "table_edges": [],
        "column_edges": [],
        "warnings": [],
    }
    src_tables: set[str] = set()
    targets: set[str] = set()
    table_edges: set[tuple[str, str, str]] = set()

    sql = _render_dbt(sql)
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect or None) if s is not None]
    except Exception as exc:  # noqa: BLE001 - best-effort parser
        out["warnings"].append(f"sql parse error: {exc}")
        return out

    for stmt in statements:
        try:
            cte_names = {c.alias_or_name for c in stmt.find_all(exp.CTE)}
            stmt_sources = sorted(
                {
                    _table_name(t)
                    for t in stmt.find_all(exp.Table)
                    if t.name not in cte_names and _table_name(t)
                }
            )
            target, body = _target_of(stmt, default_target)
            src_tables.update(stmt_sources)
            if target:
                targets.add(target)
                for s in stmt_sources:
                    if s != target:
                        table_edges.add((s, target, "derived_from"))

            select = body.find(exp.Select)
            if target and select is not None:
                for projection in select.selects:
                    col = projection.alias_or_name
                    if not col or col == "*":
                        continue  # SELECT * needs a schema; table-level edge already captured
                    try:
                        root = lineage(col, body, dialect=dialect or None)
                    except Exception:  # noqa: BLE001
                        continue
                    transform = root.expression.sql(dialect=dialect or None) if root.expression else None
                    for leaf in root.walk():
                        if leaf.downstream:
                            continue
                        src = leaf.source
                        if isinstance(src, exp.Table):
                            out["column_edges"].append(
                                {
                                    "source_table": _table_name(src),
                                    "source_column": leaf.name.split(".")[-1],
                                    "target_table": target,
                                    "target_column": col,
                                    "transformation": transform,
                                }
                            )
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"statement skipped: {exc}")

    out["source_tables"] = sorted(src_tables)
    out["targets"] = sorted(targets)
    out["table_edges"] = [{"source": s, "target": t, "relation": r} for (s, t, r) in sorted(table_edges)]
    return out
