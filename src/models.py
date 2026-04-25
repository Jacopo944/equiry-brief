from typing import TypedDict, List
from datetime import datetime


class Report(TypedDict):
    datetime: datetime
    text: str


class FeedItem(TypedDict):
    title: str
    link: str
    pubDate: str
    description: str
    source: str


class AgentOutput(TypedDict):
    sentiment: str
    brief: str
    drivers: str
    confidence: float
    sources: List[str]


class Article(TypedDict):
    title: str
    link: str
    source: str


class TickerInfo(TypedDict):
    symbol: str
    quoteType: str
    shortname: str
    exchange: str
    change_1d_pct: float


class Holding(TypedDict):
    etf: str
    symbol: str
    name: str
    percent: float


class ProcessSymbolResult(TypedDict):
    info: TickerInfo
    articles: List[Article]
