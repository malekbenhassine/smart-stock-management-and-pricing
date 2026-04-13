import joblib
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from utils import load_and_clean_data, feature_engineering


def test_model(path="test_data.csv"):
    df = load_and_clean_data(path)
    df = feature_engineering(df, drop_leaky_columns=True)
    df = df.sort_values("date").reset_index(drop=True)

    if df.empty:
        raise ValueError("Le fichier de test est vide après préparation.")

    model = joblib.load("models/demand_model.pkl")
    trained_features = joblib.load("models/demand_features.pkl")

    y_test = df["sales"].copy()

    X_test = df.drop(columns=["sales"], errors="ignore")
    X_test = X_test.reindex(columns=trained_features, fill_value=0)

    y_pred = model.predict(X_test)

    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    r2 = r2_score(y_test, y_pred)

    return {
        "status": "model tested successfully",
        "rows_used": len(df),
        "test_results": {
            "MAE": round(mae, 2),
            "RMSE": round(rmse, 2),
            "R2": round(r2, 4)
        }
    }


if __name__ == "__main__":
    result = test_model("test_data.csv")
    print(result)