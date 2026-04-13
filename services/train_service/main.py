from fastapi import FastAPI
from train import train_all_models

app = FastAPI()

@app.get("/")
def home():
    return {"message": "ML Service Running"}

@app.post("/train")
def train():
    result = train_all_models("data.csv")
    return {"status": "trained", "details": result}