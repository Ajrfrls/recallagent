
#!/usr/bin/env python3
import os, sys, json, time, requests, select
from dotenv import load_dotenv
from colorama import init as colorama_init, Fore, Style
from tabulate import tabulate

# ===== init =====
colorama_init(autoreset=True)
load_dotenv(os.path.expanduser("~/.env"))

BASE_URL         = os.getenv("RECALL_API_URL", "https://api.competitions.recall.network").rstrip("/")
AGENT_NAME       = os.getenv("AGENT1_NAME", "agent")
AGENT_KEY        = os.getenv("AGENT1_KEY")
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "20"))
# slippage dari .env (string), validasi sederhana agar tetap string untuk payload
SLIPPAGE_ENV = os.getenv("SLIPPAGE", "0.3").strip()
try:
    _ = float(SLIPPAGE_ENV)  # pastikan numerik
except:
    SLIPPAGE_ENV = "0.3"

if not AGENT_KEY:
    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} Tidak ada AGENT1_KEY di .env")
    sys.exit(1)

# ===== chains =====
CHAINS = {
    "ethereum":  {"family":"evm","specific":"eth","usdc":"0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"},
    "arbitrum":  {"family":"evm","specific":"arbitrum","usdc":"0xaf88d065e77c8cC2239327C5EDb3A432268e5831"},
    "polygon":   {"family":"evm","specific":"polygon","usdc":"0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"},
    "base":      {"family":"evm","specific":"base","usdc":"0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA"},
    "avalanche": {"family":"evm","specific":"avax","usdc":"0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E"},
    "optimism":  {"family":"evm","specific":"optimism","usdc":"0x7f5c764cbc14f9669b88837ca1490cca17c31607"},
    "solana":    {"family":"svm","specific":"mainnet","usdc":"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"},
}
CHAIN_ORDER = list(CHAINS.keys())

# ===== utils =====
def print_title(t):
    print(f"\n{Style.BRIGHT}{Fore.CYAN}{t}{Style.RESET_ALL}")

def headers():
    return {"Authorization": f"Bearer {AGENT_KEY}"}

def safe_request(method, url, **kwargs):
    try:
        resp = requests.request(method, url, timeout=30, **kwargs)
        return resp
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {e}")
        class _Stub:
            ok = False
            text = str(e)
            def json(self): return {"error": str(e)}
        return _Stub()

def get(ep, **kw):
    return safe_request("get", BASE_URL + ep, headers=headers(), **kw)

def post(ep, p, **kw):
    return safe_request("post", BASE_URL + ep, headers=headers(), json=p, **kw)

# ===== chain picker =====
def pick_chain(prompt="Pilih Chain"):
    print_title(prompt)
    for i, ch in enumerate(CHAIN_ORDER, 1):
        print(f"{i}) {ch}")
    try:
        sel = int(input("Nomor: ").strip())
        if 1 <= sel <= len(CHAIN_ORDER):
            return CHAIN_ORDER[sel-1]
    except:
        pass
    print(f"{Fore.RED}Pilihan tidak valid")
    return None

# ===== balances =====
def balance_raw():
    r = get("/api/agent/balances")
    if not r.ok:
        return []
    body = r.json()
    return body.get("balances", []) if isinstance(body, dict) else (body or [])

def show_balance():
    bals = balance_raw()
    print_title(f"Balance — Agent: {AGENT_NAME}")
    if bals:
        rows = [[b.get("symbol","?"),
                 round(float(b.get("amount",0)),6),
                 round(float(b.get("value",0)),2),
                 b.get("specificChain","?")]
                for b in bals]
        print(tabulate(rows, headers=["Token","Amount","USD Value","Chain"], tablefmt="pretty"))
        total = sum(float(b.get("value",0)) for b in bals)
        print(f"\nTotal Portfolio Value: {Style.BRIGHT}{total:.2f} USD{Style.RESET_ALL}")
    else:
        print("Tidak ada saldo.")
    return bals

# ===== history =====
def fetch_trades_all():
    r = get("/api/agent/trades")
    if not r.ok:
        return []
    body = r.json()
    trades = body.get("trades", []) if isinstance(body, dict) else (body or [])
    try:
        trades.sort(key=lambda x: x.get("timestamp",""))
    except:
        pass
    return trades

def history():
    trades = fetch_trades_all()
    print_title(f"History — Agent: {AGENT_NAME}")
    if trades:
        rows = [[t.get("fromTokenSymbol","?"),
                 t.get("toTokenSymbol","?"),
                 round(float(t.get("fromAmount",0)),6),
                 round(float(t.get("toAmount",0)),6),
                 t.get("reason","-"),
                 (t.get("timestamp","-")[:19])]
                for t in trades]
        print(tabulate(rows, headers=["From","To","FromAmt","ToAmt","Reason","Time"], tablefmt="pretty"))
    else:
        print("Belum ada history.")

# ===== trade core =====
def execute(from_chain, to_chain, from_t, to_t, amt, reason):
    meta_from = CHAINS[from_chain]
    meta_to   = CHAINS[to_chain]
    payload = {
        "fromToken": str(from_t),
        "toToken":   str(to_t),
        "amount":    str(amt),
        "slippageTolerance": SLIPPAGE_ENV,
        "fromChain": meta_from["family"],      "toChain": meta_to["family"],
        "fromSpecificChain": meta_from["specific"], "toSpecificChain": meta_to["specific"],
        "reason": reason
    }
    r = post("/api/trade/execute", payload)
    print_title("Trade Result")
    try:
        if r.ok:
            res = r.json()
            tx = res.get("transaction", {}) if isinstance(res, dict) else {}
            rows = [
                ["From",     tx.get("fromTokenSymbol","?"), tx.get("fromAmount")],
                ["To",       tx.get("toTokenSymbol","?"),   tx.get("toAmount")],
                ["Price",    "-",                           tx.get("price")],
                ["USD Value","-",                           tx.get("tradeAmountUsd")],
                ["Reason",   "-",                           tx.get("reason")],
                ["Status",   "-",                           "Success" if tx.get("success") else "Fail"],
                ["Time",     "-",                           tx.get("timestamp")]
            ]
            print(tabulate(rows, headers=["Field","Token","Value"], tablefmt="pretty"))
        else:
            print(r.text)
    except Exception as e:
        print(r.text, e)

# ===== helpers extra =====
def get_balance_amount(specific_chain, token_symbol_or_addr):
    """cek saldo token di chain tertentu (by symbol/addr)"""
    bals = balance_raw()
    token_upper = (token_symbol_or_addr or "").upper()
    token_lower = (token_symbol_or_addr or "").lower()
    for b in bals:
        if b.get("specificChain") != specific_chain:
            continue
        sym = (b.get("symbol") or "").upper()
        addr = (b.get("address") or "").lower()
        if sym == token_upper or (token_lower and addr == token_lower):
            try:
                return float(b.get("amount",0))
            except:
                return 0.0
    return 0.0

# ===== PNL unrealized (improved; all swaps; addr-aware) =====
def pnl_unrealized():
    STABLES = {"USDC","USDBC","USDT"}

    def addr(x):  return (x or "").lower()
    def symu(x):  return (x or "").upper()

    trades = fetch_trades_all()

    # posisi akumulatif per (tokenAddrOrSym, chain)
    pos = {}  # key -> {"amt": float, "cost": float}

    def add_pos(key, amount, usd_cost):
        if key not in pos:
            pos[key] = {"amt":0.0, "cost":0.0}
        if amount > 0:  # buy
            pos[key]["amt"]  += amount
            pos[key]["cost"] += usd_cost
        elif amount < 0:  # sell
            if pos[key]["amt"] <= 0:
                return
            avg = pos[key]["cost"]/pos[key]["amt"] if pos[key]["amt"] else 0.0
            take_amt = min(-amount, pos[key]["amt"])
            pos[key]["amt"]  -= take_amt
            pos[key]["cost"] -= avg * take_amt

    # bangun posisi dari semua trade
    for t in trades:
        to_chain   = (t.get("toSpecificChain")   or t.get("toChain")   or "?")
        from_chain = (t.get("fromSpecificChain") or t.get("fromChain") or "?")

        to_addr   = addr(t.get("toTokenAddress"))
        from_addr = addr(t.get("fromTokenAddress"))

        to_sym   = symu(t.get("toTokenSymbol"))
        from_sym = symu(t.get("fromTokenSymbol"))

        to_amt   = float(t.get("toAmount") or 0.0)
        from_amt = float(t.get("fromAmount") or 0.0)
        usd      = float(t.get("tradeAmountUsd") or 0.0)

        to_key   = (to_addr or to_sym, to_chain)
        from_key = (from_addr or from_sym, from_chain)

        # skip jika keduanya stable
        if to_sym in STABLES and from_sym in STABLES:
            continue

        if to_amt > 0 and to_sym not in STABLES:
            add_pos(to_key, to_amt, usd)
        if from_amt > 0 and from_sym not in STABLES:
            add_pos(from_key, -from_amt, 0.0)

    # baca balance sekarang, hitung PNL unrealized
    bals = balance_raw()
    rows, total_pnl = [], 0.0
    for b in bals:
        sym_raw = b.get("symbol") or "?"
        if symu(sym_raw) in STABLES:
            continue
        chain = b.get("specificChain") or "?"
        b_addr = addr(b.get("address"))
        key = (b_addr or symu(sym_raw), chain)

        amt_now = float(b.get("amount") or 0.0)
        val_now = float(b.get("value")  or 0.0)
        p = pos.get(key)
        if not p or amt_now <= 0:
            continue

        if p["amt"] > 0:
            avg_cost = p["cost"]/p["amt"]
            cost_now = avg_cost * amt_now
        else:
            continue

        pnl_val = val_now - cost_now
        pnl_str = f"{Fore.GREEN}{pnl_val:.2f}{Style.RESET_ALL}" if pnl_val>=0 else f"{Fore.RED}{pnl_val:.2f}{Style.RESET_ALL}"
        rows.append([sym_raw, chain, round(amt_now,6), round(avg_cost,4), round(val_now,2), pnl_str])
        total_pnl += pnl_val

    print_title("Unrealized PNL")
    if rows:
        print(tabulate(rows, headers=["Token","Chain","Amount","Avg Buy $","Cur Val $","Unreal PNL $"], tablefmt="pretty"))
        total_str = f"{Fore.GREEN}{total_pnl:.2f}{Style.RESET_ALL}" if total_pnl>=0 else f"{Fore.RED}{total_pnl:.2f}{Style.RESET_ALL}"
        print(f"\nTotal Unrealized PNL: {Style.BRIGHT}{total_str}{Style.RESET_ALL} USD")
    else:
        print("Belum ada posisi non-stable yang terhitung PNL.")

# ===== batch buy/sell =====
def batch_buy():
    from_chain = pick_chain("Dari Chain (USDC sumber)")
    to_chain   = pick_chain("Ke Chain (Token tujuan)")
    if not from_chain or not to_chain: return
    to     = input("toToken (alamat/simbol): ").strip()
    total  = float(input("Total USDC: ").strip())
    step   = float(input("Per trade USDC: ").strip())
    reason = input("Reason (opsional): ").strip() or "BATCH BUY"
    spent = 0.0
    while spent < total:
        amt = min(step, total-spent)
        print(f"\n[Batch Buy] Eksekusi {amt} USDC...")
        execute(from_chain, to_chain, CHAINS[from_chain]["usdc"], to, amt, reason)
        spent += amt
        time.sleep(2)

def batch_sell():
    from_chain = pick_chain("Dari Chain (Token sumber)")
    to_chain   = pick_chain("Ke Chain (USDC tujuan)")
    if not from_chain or not to_chain: return
    frm    = input("fromToken (alamat/simbol): ").strip()
    total  = float(input("Total Token: ").strip())
    step   = float(input("Per trade Token: ").strip())
    reason = input("Reason (opsional): ").strip() or "BATCH SELL"
    sold = 0.0
    while sold < total:
        amt = min(step, total-sold)
        print(f"\n[Batch Sell] Eksekusi {amt} token...")
        execute(from_chain, to_chain, frm, CHAINS[to_chain]["usdc"], amt, reason)
        sold += amt
        time.sleep(2)

# ===== token↔token (single) same/cross-chain =====
def token_to_token_single():
    from_chain = pick_chain("Dari Chain (Token sumber)")
    to_chain   = pick_chain("Ke Chain (Token tujuan)")
    if not from_chain or not to_chain:
        input("\n[Enter untuk lanjut]")
        return

    frm    = input("fromToken (alamat/simbol/addr): ").strip()
    to     = input("toToken (alamat/simbol/addr): ").strip()
    amt_in = input("Jumlah token sumber: ").strip()
    reason = input("Reason (opsional): ").strip() or f"T2T {from_chain}->{to_chain}"

    # sanity saldo (opsional)
    try:
        have = get_balance_amount(CHAINS[from_chain]["specific"], frm)
        if have and float(amt_in) > have + 1e-9:
            print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} Saldo {frm} {have} < {amt_in}")
    except:
        pass

    execute(from_chain, to_chain, frm, to, amt_in, reason)
    input("\n[Enter untuk lanjut]")

# ===== contoh preset cross-chain (WETH arb -> WMATIC polygon) =====
def token_to_token_cross_example():
    from_chain = "arbitrum"
    to_chain   = "polygon"
    WETH_ARB   = "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"
    WMATIC_POL = "0x0d500B1d8E8Ef31E21C99d1Db9A6444d3ADf1270"
    amt_in     = "0.05"
    reason     = f"T2T_XCHAIN {from_chain}->{to_chain}"
    try:
        have = get_balance_amount(CHAINS[from_chain]["specific"], WETH_ARB)
        if have and float(amt_in) > have + 1e-9:
            print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} Saldo WETH Arbitrum {have} < {amt_in}")
    except:
        pass
    execute(from_chain, to_chain, WETH_ARB, WMATIC_POL, amt_in, reason)
    input("\n[Enter untuk lanjut]")

# ===== menu (dashboard auto-refresh) =====
def menu():
    while True:
        os.system("clear")
        print_title(f"Dashboard — Agent: {AGENT_NAME}")
        show_balance()
        pnl_unrealized()

        print("\nMenu:")
        print("1) HISTORY")
        print("2) BUY (single)")
        print("3) SELL (single)")
        print("4) BATCH BUY")
        print("5) BATCH SELL")
        print("6) TOKEN to TOKEN (singke)")
        print("0) KELUAR")
        print(f"(Dashboard auto-refresh tiap {REFRESH_INTERVAL} detik jika tidak ada input)")

        # tunggu input max REFRESH_INTERVAL detik
        print("\nPilih menu (Enter untuk refresh): ", end="", flush=True)
        i, _, _ = select.select([sys.stdin], [], [], REFRESH_INTERVAL)

        if i:
            c = sys.stdin.readline().strip()
            if c=="1":
                history(); input("\n[Enter untuk lanjut]")
            elif c=="2":
                from_chain = pick_chain("Dari Chain (USDC sumber)")
                to_chain   = pick_chain("Ke Chain (Token tujuan)")
                if not from_chain or not to_chain:
                    input("\n[Enter untuk lanjut]"); 
                    continue
                to     = input("toToken (alamat/simbol): ").strip()
                amt    = input("Jumlah USDC: ").strip()
                reason = input("Reason (opsional): ").strip() or "BUY"
                execute(from_chain, to_chain, CHAINS[from_chain]["usdc"], to, amt, reason)
                input("\n[Enter untuk lanjut]")
            elif c=="3":
                from_chain = pick_chain("Dari Chain (Token sumber)")
                to_chain   = pick_chain("Ke Chain (USDC tujuan)")
                if not from_chain or not to_chain:
                    input("\n[Enter untuk lanjut]"); 
                    continue
                frm    = input("fromToken (alamat/simbol): ").strip()
                amt    = input("Jumlah token: ").strip()
                reason = input("Reason (opsional): ").strip() or "SELL"
                execute(from_chain, to_chain, frm, CHAINS[to_chain]["usdc"], amt, reason)
                input("\n[Enter untuk lanjut]")
            elif c=="4":
                batch_buy();  input("\n[Enter untuk lanjut]")
            elif c=="5":
                batch_sell(); input("\n[Enter untuk lanjut]")
            elif c=="6":
                token_to_token_single()
            elif c=="7":
                token_to_token_cross_example()
            elif c=="0":
                print("bye 👋"); sys.exit(0)
            else:
                print("Menu tidak dikenal."); time.sleep(2)
        else:
            # tidak ada input -> refresh dashboard
            continue

# ===== entry =====
if __name__ == "__main__":
    menu()

