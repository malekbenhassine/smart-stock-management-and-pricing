from pathlib import Path
import pandas as pd


def read_csv_safe(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def summarize_csv(path: Path) -> dict:
    df = read_csv_safe(path)
    return {
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns.tolist()],
    }