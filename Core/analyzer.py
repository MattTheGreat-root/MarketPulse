import pandas as pd
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression

class Analyzer:
    def __init__(self, path):
        self.path = path

    def run(self):
        # Prepare data
        df = pd.read_csv(self.path)
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df.dropna(subset=['price'], inplace=True)
        
        df['bazkhord'] = df['likes'] + df['comments']
        df.sort_values('price', inplace=True)

        X, y = df[['price']], df['bazkhord']
        
        # Train model
        model = LinearRegression().fit(X, y)
        coef = model.coef_[0]
        
        print(f"Slope: {coef:.4f} | R2: {model.score(X, y):.4f}")
        
        if coef != 0:
            rel = "+" if coef > 0 else "-"
            print(f"Result: + price -> {rel} bazkhord.")

        # Plot
        plt.scatter(df['price'], y, label="Data")
        plt.plot(df['price'], model.predict(X), color="red", label="Fit")
        plt.title("Price vs Bazkhord")
        plt.legend()
        plt.show()