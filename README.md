# LLM-Trading-Bot

> **A flexible framework for LLM-powered algorithmic trading bots using JSON prompts & indicator data injection.**

---

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-Experimental-orange)]()

---

## Overview

**LLM-Trading-Bot** demonstrates how to structure a trading bot powered by Large Language Models (LLMs).  
This repo is **not a plug-and-play trading solution**, but a reference implementation showing:

- Bot logic modularized via JSON-based prompts
- Data injection of indicators and signals
- Bot outputs structured JSON for downstream automation

---

## Features

- **LLM-driven trade decisions** (entry, exit, SL/TP, etc)
- **Flexible prompt system**: Easily swap or edit trading strategy logic with JSON files
- **Data injection**: Inject technical indicators, price data, or custom signals
- **Structured Output**: Bot emits a JSON array with actionable trading instructions

---

## Example Output

Each cycle, the bot emits a JSON object like this:


```json
{
  "action": "ENTER",
  "side": "LONG",
  "price": 186.25,
  "stop_loss": 185.75,
  "take_profit": 188.00,
  "status": "OPEN",
  "risk_reward": 2.5,
  "reason": "Price swept 1h S/R zone, then rejected with high volume. Multi-timeframe confluence (4h/1h), liquidity grab confirmed. Recent trades show bias long, news neutral.",
  "save_memory": "Session break chop—avoid re-entry during low liquidity next time.",
  "strategy": "Enter long after liquidity sweep and rejection at 1h S/R zone; exit if zone lost.",
  "confidence": 78,
  "request": null
}
