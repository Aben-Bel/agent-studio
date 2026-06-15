import pandas as pd
import os

DATA_PATH = os.path.join(os.path.dirname(__file__), "semiconductor_wafer_defect_dataset.csv")

def load_dataset(path=DATA_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset not found at {path}")
    
    df = pd.read_csv(path)
    return df

if __name__ == "__main__":
    df = load_dataset()
    print(df.head())
