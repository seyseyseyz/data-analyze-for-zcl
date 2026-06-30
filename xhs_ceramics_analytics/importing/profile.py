from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class FileProfile:
    path: Path
    table_name: str
    columns: list[str]
    row_count: int
    sample_rows: list[dict[str, object]]


def profile_csv(path: Path) -> FileProfile:
    frame = pd.read_csv(path)
    sample = frame.head(5)
    sample_rows = sample.astype(object).where(pd.notna(sample), None).to_dict(orient="records")
    return FileProfile(
        path=path,
        table_name=path.stem,
        columns=list(frame.columns),
        row_count=len(frame),
        sample_rows=sample_rows,
    )
