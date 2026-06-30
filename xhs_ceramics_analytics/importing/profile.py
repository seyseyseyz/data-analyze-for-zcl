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
    return FileProfile(
        path=path,
        table_name=path.stem,
        columns=list(frame.columns),
        row_count=len(frame),
        sample_rows=frame.head(5).where(pd.notna(frame), None).to_dict(orient="records"),
    )
