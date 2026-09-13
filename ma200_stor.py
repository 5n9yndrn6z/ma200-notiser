"""
MA200-bevakning - stor version (svenska + amerikanska aktier)
-----------------------------------------------------------------
Korsar close MA200 uppat -> KOP. Nedat -> SALJ (med affarsresultat).
Skickar EN samlad digest-notis per korning om nagra nya signaler hittas -
inte en push per aktie (annars blir det for many notiser pa en stor lista).

TICKERLISTOR:
  USA   - S&P 500 + S&P 400 hamtas LIVE fran Wikipedia vid varje korning
          (~900 bolag, uppdateras automatiskt - inga tickers hardkodade).
  SVERIGE - ingen ren, gratis, komplett, skrapbar kalla for *alla* ~800-900
          Nasdaq Stockholm-bolag hittades (den uppenbara kallan visade sig
          vara en JS-sida utan data i ren HTML). SE_TICKERS nedan ar darfor
          en handplockad lista med kanda Nasdaq Stockholm-bolag (storre
          Large/Mid Cap-tyngdpunkt). Ga garna igenom och komplettera den.
          Nagra enstaka tickers kan vara inaktuella (avnoterade/omdopta) -
          skriptet hoppar da bara over dem (loggar och fortsatter).

Miljovariabel NTFY_TOPIC maste vara satt (GitHub Secret).
"""

import os
import time

import pandas as pd
import requests
import yfinance as yf

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

MA_LENGTH = 200
HISTORY_PERIOD = "3y"
BATCH_SIZE = 100          # antal tickers per yfinance-anrop
BATCH_PAUSE_SEC = 2       # kort paus mellan batchar - schysst mot Yahoo

# ----------------------------------------------------------------------
# Svenska bolag - handplockad startlista (Nasdaq Stockholm, .ST)
# ----------------------------------------------------------------------
SE_TICKERS = [
    # Large cap / valkanda
    "ABB.ST", "ALFA.ST", "ASSA-B.ST", "ATCO-A.ST", "ATCO-B.ST", "AZN.ST", "BOL.ST",
    "ELUX-A.ST", "ELUX-B.ST", "EQT.ST", "ERIC-B.ST", "ESSITY-B.ST", "EVO.ST",
    "GETI-B.ST", "HEXA-B.ST", "HM-B.ST", "HOLM-B.ST", "HUSQ-B.ST", "INDU-C.ST",
    "INVE-B.ST", "KINV-B.ST", "LATO-B.ST", "LIFCO-B.ST", "LUND-B.ST", "NDA-SE.ST",
    "NIBE-B.ST", "SAAB-B.ST", "SAND.ST", "SCA-B.ST", "SEB-A.ST", "SHB-A.ST",
    "SINCH.ST", "SKA-B.ST", "SKF-B.ST", "SSAB-A.ST", "SSAB-B.ST", "SWED-A.ST",
    "TEL2-B.ST", "TELIA.ST", "VOLV-A.ST", "VOLV-B.ST", "WALL-B.ST",
    # Fastigheter
    "CAST.ST", "FABG.ST", "BALD-B.ST", "SAGA-B.ST", "SBB-B.ST", "WIHL.ST",
    "NP3.ST", "CATE.ST", "KLOV-B.ST", "DIOS.ST", "HUFV-A.ST",
    # Dagligvaror / detaljhandel
    "AXFO.ST", "ICA.ST", "CLAS-B.ST", "BILI-A.ST", "BYGG.ST", "MIPS.ST",
    "THULE.ST", "NEWA-B.ST", "BOOZT.ST", "RVRC.ST",
    # Industri
    "TREL-B.ST", "HEXP.ST", "NOLA-B.ST", "LAGR-B.ST", "ADDT-B.ST", "BEIA-B.ST",
    "BEIJ-B.ST", "BERG-B.ST", "MTRS.ST", "NOTE.ST", "OEM-B.ST", "TROAX.ST",
    "INSTAL.ST", "BRAV.ST", "LINDAB.ST", "SYSR.ST", "DUNI.ST", "CLOE-B.ST",
    "INDT.ST",
    # Bygg
    "NCC-A.ST", "NCC-B.ST", "PEAB-B.ST", "JM.ST", "BONAV-B.ST",
    # Halsovard / bioteknik
    "ELEKTA-B.ST", "MYCR.ST", "SOBI.ST", "CAMX.ST", "BIOA-B.ST", "BIOG-B.ST",
    "VITR.ST", "SECARE.ST",
    # Gaming / tech
    "PDX.ST", "G5EN.ST", "STAR-B.ST", "MTG-B.ST", "FING-B.ST", "EMBRAC-B.ST",
    "SECT-B.ST",
    # Tjanster
    "SECU-B.ST", "LOOM-B.ST", "COOR.ST", "AMBEA.ST",
    # Investmentbolag
    "CREA.ST", "VNV.ST", "BURE.ST", "SVOL-B.ST",
]


def get_sp500_tickers() -> list:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = pd.read_html(url)
    df = tables[0]
    return [s.replace(".", "-") for s in df["Symbol"].astype(str)]


def get_sp400_tickers() -> list:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
    tables = pd.read_html(url)
    df = tables[0]
    col = "Ticker symbol" if "Ticker symbol" in df.columns else "Symbol"
    return [s.replace(".", "-") for s in df[col].astype(str)]


def build_ticker_list() -> list:
    us_tickers = []
    for name, fn in [("S&P 500", get_sp500_tickers), ("S&P 400", get_sp400_tickers)]:
        try:
            t = fn()
            us_tickers += t
            print(f"{name}: {len(t)} tickers hamtade fran Wikipedia")
        except Exception as e:
            print(f"VARNING: kunde inte hamta {name} fran Wikipedia ({e}) - hoppar over.")

    all_tickers = sorted(set(SE_TICKERS) | set(us_tickers))
    print(f"Totalt {len(all_tickers)} unika tickers ({len(SE_TICKERS)} SE handplockade + {len(set(us_tickers))} US fran Wikipedia)")
    return all_tickers


def chunks(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def load_batch(tickers: list) -> dict:
    """Hamtar historik for en lista tickers i EN batch-request.
    Returnerar {ticker: DataFrame} for de som gick att hamta."""
    result = {}
    try:
        raw = yf.download(
            tickers, period=HISTORY_PERIOD, interval="1d",
            group_by="ticker", threads=True, progress=False, auto_adjust=True,
        )
    except Exception as e:
        print(f"  Batch misslyckades helt ({len(tickers)} tickers): {e}")
        return result

    if len(tickers) == 1:
        df = raw.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)
        if "Close" in df.columns:
            result[tickers[0]] = df
        return result

    for t in tickers:
        try:
            sub = raw[t].dropna(how="all")
            if not sub.empty and "Close" in sub.columns:
                result[t] = sub
        except Exception:
            continue
    return result


def compute_signal(df: pd.DataFrame):
    """Returnerar en dict med signalinfo, eller None om ingen ny signal."""
    df = df.dropna(subset=["Close"]).copy()
    df["MA200"] = df["Close"].rolling(MA_LENGTH).mean()
    df = df.dropna(subset=["MA200"])
    if df.empty:
        return None

    df["above"] = df["Close"] > df["MA200"]
    df["cross"] = df["above"].astype(int).diff()

    last = df.iloc[-1]
    if last["cross"] == 0:
        return None

    price = float(last["Close"])
    date = str(df.index[-1].date())

    if last["cross"] == 1:
        return {"direction": "KOP", "date": date, "price": price, "pct": None}

    crosses = df[df["cross"] != 0]
    pct = None
    if len(crosses) >= 2:
        prev_buy = crosses.iloc[-2]
        pct = (price / float(prev_buy["Close"]) - 1) * 100
    return {"direction": "SALJ", "date": date, "price": price, "pct": pct}


def send_digest(signals: list) -> None:
    if not signals:
        print("Inga nya signaler idag.")
        return
    if not NTFY_TOPIC:
        print(f"VARNING: NTFY_TOPIC ar inte satt - {len(signals)} signal(er) hittades men ingen notis skickades.")
        return

    lines = []
    for s in signals:
        if s["direction"] == "KOP":
            lines.append(f"KOP {s['ticker']} @ {s['price']:.2f} ({s['date']})")
        else:
            pct_txt = f", {s['pct']:+.2f}%" if s["pct"] is not None else ""
            lines.append(f"SALJ {s['ticker']} @ {s['price']:.2f} ({s['date']}{pct_txt})")

    title = f"{len(signals)} ny(a) MA200-signal(er)"
    message = "\n".join(lines)

    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
            timeout=15,
        )
        print(f"Digest-notis skickad med {len(signals)} signal(er).")
    except Exception as e:
        print(f"Kunde inte skicka notis: {e}")


def main() -> None:
    if os.environ.get("TEST_NOTIFICATION", "false").lower() == "true":
        send_digest([{"ticker": "TEST", "direction": "KOP", "date": "-", "price": 0.0, "pct": None}])
        return

    tickers = build_ticker_list()
    signals = []

    for i, batch in enumerate(chunks(tickers, BATCH_SIZE), start=1):
        print(f"Batch {i}/{-(-len(tickers) // BATCH_SIZE)} ({len(batch)} tickers)...")
        data = load_batch(batch)
        for ticker, df in data.items():
            sig = compute_signal(df)
            if sig:
                sig["ticker"] = ticker
                signals.append(sig)
        if i * BATCH_SIZE < len(tickers):
            time.sleep(BATCH_PAUSE_SEC)

    send_digest(signals)


if __name__ == "__main__":
    main()
