from utils import load_and_clean_data


def split_train_test_csv(
    input_path="data.csv",
    train_output="train_data.csv",
    test_output="test_data.csv",
    train_ratio=0.8
):
    df = load_and_clean_data(input_path)
    df = df.sort_values("date").reset_index(drop=True)

    unique_dates = sorted(df["date"].dropna().unique())
    if len(unique_dates) < 2:
        raise ValueError("Pas assez de dates différentes pour faire un split temporel.")

    split_idx = int(len(unique_dates) * train_ratio)
    split_idx = max(1, min(split_idx, len(unique_dates) - 1))

    split_date = unique_dates[split_idx]

    train_df = df[df["date"] < split_date].copy()
    test_df = df[df["date"] >= split_date].copy()

    if train_df.empty or test_df.empty:
        raise ValueError("Le split a produit un train ou un test vide.")

    train_df.to_csv(train_output, index=False)
    test_df.to_csv(test_output, index=False)

    print("✅ Fichiers générés avec succès")
    print(f"Train: {train_output} -> {len(train_df)} lignes")
    print(f"Test : {test_output} -> {len(test_df)} lignes")
    print(f"Date de séparation : {split_date}")


if __name__ == "__main__":
    split_train_test_csv()