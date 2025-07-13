# LLM-Trading-Bot

> **A flexible framework for LLM-powered algorithmic trading bots using JSON prompts & indicator data injection.**

---

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
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

The bot produces output like:
```json
{
  "side": "BUY",
  "decision": "ENTER",
  "stop_loss": 185.10,
  "take_profit": 187.90,
  "confidence": 0.92,
  "reason": "Price swept liquidity at S/R zone, strong volume confirmation."
}
