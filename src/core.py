# Standard library imports
import datetime
import json
import os
import random
from pathlib import Path
from typing import List
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

# Third-party imports
import requests
import yfinance as yf
from dotenv import load_dotenv
from googlenewsdecoder import gnewsdecoder
from openai import OpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

# Local application imports
from mode_enum import Mode
from const import THINKING_MESSAGES, USER_AGENTS
from output_manager import init_output_manager, _print
from models import (
    TickerInfo,
    Article,
    ProcessSymbolResult,
    AgentOutput,
    FeedItem,
    Holding,
    Report,
)


def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
    }


# ---------------- CONFIG ----------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------- YAHOO ETF INFO ----------------
async def get_etf_holdings(etf: str) -> List[Holding]:
    try:
        t = yf.Ticker(etf)
        holdings = t.funds_data.top_holdings

        if holdings is None or holdings.empty:
            await _print(f"⚠️ No holdings for {etf}")
            return []

        # Limit to top 5 holdings
        holdings = holdings.head(5)

        results: List[Holding] = [
            Holding(
                etf=etf,
                symbol=symbol,
                name=holdings.loc[symbol, "Name"],
                percent=holdings.loc[symbol, "Holding Percent"],
            )
            for symbol in holdings.index
        ]

        await _print(
            f"✅ Extracted top 5 holdings for {etf}: {', '.join([holding['symbol'] for holding in results])}"
        )
        return results
    except Exception as e:
        await _print(f"❌ Error fetching ETF holdings: {e}")
        return []


# ---------------- YAHOO SYMBOL INFO ----------------
async def get_yahoo_ticker_info(symbol) -> TickerInfo:
    await _print(f"\n🔍 Looking for *{symbol}*...")

    info = yf.Ticker(symbol).info

    if not info:
        raise Exception(f"No results found for symbol: {symbol}")

    change_pct = info.get("regularMarketChangePercent")

    return TickerInfo(
        quoteType=info.get("quoteType"),
        shortname=info.get("shortName") or info.get("longName"),
        exchange=info.get("exchange"),
        symbol=info.get("symbol", symbol),
        change_1d_pct=round(float(change_pct), 2) if change_pct is not None else None,
    )


# ---------------- RSS PARSER ----------------
def parse_rss_items(content) -> List[FeedItem]:
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    root = ET.fromstring(content)

    items: List[FeedItem] = []
    for item in root.findall(".//item"):
        data: FeedItem = FeedItem(
            title=(item.findtext("title") or "").strip(),
            link=(item.findtext("link") or "").strip(),
            pubDate=(item.findtext("pubDate") or "").strip(),
            description=(item.findtext("description") or "").strip(),
            source=(item.findtext("source") or "").strip(),
        )
        items.append(data)

    return items


# ---------------- RSS FETCH ----------------
def get_valid_stock_articles(ticker) -> List[Article]:
    query = quote_plus(f"{ticker} stock when:2d")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    # print(f"[{rss_url}]")

    try:
        _session = requests.Session()
        response = _session.get(rss_url, headers=get_headers(), timeout=10)
        feeds: List[FeedItem] = parse_rss_items(response.content)

        articles = []
        for feed in feeds[:3]:
            decoded = gnewsdecoder(feed["link"]).get("decoded_url")

            print(f"🔗 Article: {decoded}")

            articles.append(
                Article(
                    title=feed["title"],
                    link=decoded,
                    source=feed["source"],
                )
            )

        return articles
    except Exception as e:
        print(f"❌ Error fetching RSS feed: {e}")
        return []


# ---------------- LOAD SYSTEM PROMPT ----------------
def load_system_prompt() -> str:
    prompt_path = Path() / "prompts" / "prompt_0_0_6.md"
    with open(prompt_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content


# ---------------- AI AGENT ----------------
async def call_agent(ticker: ProcessSymbolResult) -> AgentOutput | None:
    info: TickerInfo = ticker["info"]
    articles: List[Article] = ticker["articles"]

    await _print("\n" + random.choice(THINKING_MESSAGES))

    formatted_articles: str = "\n\n".join(
        [
            f"TITLE: {a['title']}\nSOURCE: {a['source']}\nLINK: {a['link']}"
            for a in articles
        ]
    )

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[
            ChatCompletionSystemMessageParam(
                role="system",
                content=(load_system_prompt()),
            ),
            ChatCompletionUserMessageParam(
                role="user",
                content=f"TICKER: {info}\n\nARTICLES:\n{formatted_articles}",
            ),
        ],
    )

    raw: str = response.choices[0].message.content.strip()

    return parse_agent_response(raw)


# ---------------- SAFE JSON ----------------
def parse_agent_response(text: str) -> AgentOutput | None:
    try:
        clean = text.replace("```json", "").replace("```", "").strip()
        summary = json.loads(clean)
        return AgentOutput(
            sentiment=summary.get("sentiment"),
            brief=summary.get("brief"),
            drivers=summary.get("drivers"),
            confidence=summary.get("confidence"),
            sources=summary.get("sources"),
        )
    except json.JSONDecodeError:
        return None


def write_final_report_file(report: Report) -> Path:
    s_datetime: str = report["datetime"].strftime("%Y-%m-%d")

    filename = Path() / "reports" / f"{s_datetime}_report.md"

    report["text"] = f"# 📊 Stock News Report - {s_datetime}\n\n" + report["text"]

    with open(filename, "w", encoding="utf-8") as f:
        f.write(report["text"])

    print(f"\n✨ Done! Report saved as {filename}")

    return filename


async def process_symbol(symbol: str, report: Report) -> ProcessSymbolResult | None:
    report["text"] += f"## {symbol}\n\n"

    try:
        info: TickerInfo = await get_yahoo_ticker_info(symbol)
        if info["quoteType"] is None:
            raise Exception()
    except Exception as e:
        await _print(f"❌ Error fetching ticker info: {e}")
        report["text"] += "\nError fetching ticker information.\n\n"
        return None

    articles: List[Article] = []

    print(f"✅ Ticker type: {info['quoteType']}")

    match info["quoteType"]:
        case "EQUITY":
            await _print(f"🗞️ Collecting articles...")
            articles: List[Article] = get_valid_stock_articles(info["shortname"])
        case "ETF":
            holdings: List[Holding] = await get_etf_holdings(symbol)
            if not holdings:
                await _print("⚠️ Failed to get ETF holdings → skipping")
                report["text"] += f"## {symbol}\nFailed to retrieve ETF holdings.\n\n"
                return None
            await _print(f"🗞️ Collecting articles...")
            for holding in holdings:
                articles.extend(get_valid_stock_articles(holding["name"]))
        case _:
            await _print(f"⚠️ Unsupported symbol type: {info['quoteType']} → skipping")
            return None

    return ProcessSymbolResult(info=info, articles=articles)


async def process_symbols(symbols: List[str], report: Report) -> Path:
    for symbol in symbols:
        result: ProcessSymbolResult | None = await process_symbol(symbol, report)

        if result is None:
            continue

        articles: List[Article] = result["articles"]

        if not articles:
            report["text"] += f"## {symbol}\nNo readable articles.\n\n"
            continue

        response: AgentOutput | None = await call_agent(result)

        if response is None:
            report += f"## {symbol}\nFailed to parse agent response.\n\n"
            continue

        # response: AgentOutput = AgentOutput(
        #     sentiment="neutral",
        #     brief="This is a placeholder summary. Replace with actual AI output.",
        #     drivers="N/A",
        #     confidence=0.0,
        #     sources=[
        #         "https://www.example.com/article1",
        #         "https://www.example.com/article2",
        #     ],
        # )

        report["text"] += f"**Sentiment:**\n{response['sentiment']}\n\n"
        report["text"] += f"**Brief:**\n{response['brief']}\n\n"
        report["text"] += f"**Key Drivers:**\n{response['drivers']}\n\n"
        report["text"] += f"**Confidence:**\n{response['confidence']}\n\n"
        report["text"] += (
            "**Sources:**\n"
            + "\n".join(f"  - {src}" for src in response["sources"])
            + "\n\n"
        )

    return write_final_report_file(report)


# ---------------- MAIN ----------------
async def build_report(mode: Mode, symbols: list[str]) -> Path:
    report: Report = Report(
        datetime=datetime.datetime.now(),
        text="",
    )

    init_output_manager(mode)

    return await process_symbols(symbols, report)
