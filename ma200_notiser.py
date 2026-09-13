import os
import pandas as pd
import requests
import yfinance as yf

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

TICKERS = {
    "Volvo B":    "VOLV-B.ST",
    "Investor B": "INVE-B.ST",
    "Ericsson B": "ERIC-B.ST",
    "H&M B":      "HM-B.ST",
    "Swedbank A": "SWED-A.ST",
}

MA_LENGTH = 200
HISTORY_PERIOD = "3y"


def load_data(ticker):
    df = yf.download(ticker, period=HISTORY_PERIOD, interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df["MA200"] = df["Close"].rolling(MA_LENGTH).mean()
    df = df.dropna(subset=["MA200"]).copy()
    df["above"] = df["Close"] > df["MA200"]
    df["cross"] = df["above"].astype(int).diff()
    return df


def send_notification(title, message):
    if not NTFY_TOPIC:
        print("VARNING: NTFY_TOPIC saknas.")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
            timeout=10,
        )
    except Exception as e:
        print(f"Kunde inte skicka notis: {e}")


def check_ticker(name, ticker):
    try:
        df = load_data(ticker)
    except Exception as e:
        print(f"{name}: kunde inte hämta data ({e})")
        return

    last = df.iloc[-1]
    last_date = str(df.index[-1].date())
    if last["cross"] == 0:
        print(f"{name}: ingen ny signal ({last_date})")
        return

    price = float(last["Close"])
    if last["cross"] == 1:
        title = f"BUY signal: {name}"
        message = f"{name} korsade MA200 uppåt {last_date} vid kurs {price:.2f}."
    else:
        crosses = df[df["cross"] != 0]
        result_txt = ""
        if len(crosses) >= 2:
            prev_buy = crosses.iloc[-2]
            pct = (price / float(prev_buy["Close"]) - 1) * 100
            result_txt = f" Affären blev {pct:+.2f}% (köpt {prev_buy.name.date()})."
        title = f"SELL signal: {name}"
        message = f"{name} korsade MA200 nedåt {last_date} vid kurs {price:.2f}.{result_txt}"

    send_notification(title, message)
    print(f"Notis skickad: {message}")


def main():
    for name, ticker in TICKERS.items():
        check_ticker(name, ticker)


if __name__ == "__main__":
    main()
