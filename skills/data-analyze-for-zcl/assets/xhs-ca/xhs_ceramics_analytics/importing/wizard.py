from pathlib import Path

import yaml

from xhs_ceramics_analytics.importing.mapping import guess_field_mapping, guess_table_type
from xhs_ceramics_analytics.importing.profile import profile_file


def build_mapping_for_files(files: list[Path]) -> dict[str, object]:
    tables: list[dict[str, object]] = []
    for path in files:
        profile = profile_file(path)
        table_type = guess_table_type(profile)
        tables.append(
            {
                "path": str(path),
                "table_type": table_type,
                "source_name": profile.table_name,
                "field_mapping": guess_field_mapping(profile, table_type),
                "row_count": profile.row_count,
            }
        )
    return {"tables": tables}


def write_mapping(files: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(build_mapping_for_files(files), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
