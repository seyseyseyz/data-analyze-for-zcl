from pathlib import Path

import yaml


def load_overrides(path: Path) -> dict[str, dict[str, set[str]]]:
    """Parse mapping_overrides.yaml into ``{table_type: {canonical: {alias, ...}}}``.

    Absent or empty file → ``{}`` (the normal headless/first-run case). Malformed
    structure raises ``ValueError`` at build start (fail fast on a corrupt config).
    Overrides only ADD aliases; the merge happens in ``mapping._effective_aliases``.
    """
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"mapping_overrides.yaml 顶层必须是映射 (table_type -> ...)，实际是 {type(raw).__name__}"
        )
    result: dict[str, dict[str, set[str]]] = {}
    for table_type, columns in raw.items():
        if not isinstance(columns, dict):
            raise ValueError(
                f"mapping_overrides.yaml[{table_type}] 必须是 canonical -> 别名列表 的映射"
            )
        table_map: dict[str, set[str]] = {}
        for canonical, aliases in columns.items():
            if isinstance(aliases, str):
                aliases = [aliases]
            if not isinstance(aliases, list):
                raise ValueError(
                    f"mapping_overrides.yaml[{table_type}][{canonical}] 必须是别名列表或单个别名"
                )
            table_map[str(canonical)] = {str(alias) for alias in aliases}
        result[str(table_type)] = table_map
    return result
