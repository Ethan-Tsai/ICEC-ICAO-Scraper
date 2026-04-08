# ICEC-ICAO-Scraper

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Playwright](https://img.shields.io/badge/Playwright-Automated-green.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688.svg)

An automated flight carbon emission data collection technical demo. This tool encapsulates automated scraping, anti-WAF evasion mechanics, and a headless browser into a single executable, featuring an intuitive web dashboard powered by FastAPI.

> **Disclaimer: This project and its architecture are strictly for personal technical demonstration, testing, and educational purposes.**
> When running this project, you must comply with the target website's Terms of Service and strictly follow the safety delays defined in `site.config.json` to prevent server abuse. Users bear full responsibility for their actions.
> 
> **中文聲明：嚴禁惡意使用。本專案僅為單純的 Idea 測試與技術驗證，請勿用於任何攻擊或高頻率掃描，使用者須對自身行為全權負責。**

## Key Features

* **Anti-Blocking & Rate Limiting (Playwright Stealth)**: Automatically bypasses conventional bot detection mechanisms with smart backpressure retries and resource blocking.
* **Native-feeling Modern Dashboard**: Built-in lightweight WebSocket communication connects the frontend directly to the underlying Python engine, providing real-time visual updates and dynamic log streaming.
* **State Memory & Auto-Resume**: Disconnections or manual stops won't result in data loss. The system seamlessly resumes unfinished tasks on the next startup.
* **One-Click Build**: A tailored PyInstaller script bundles the web framework and Chromium browser engine into a lightweight portable executable for non-technical users.

## Development & Build Environment

If you wish to develop or build the executable from source:

### 1. Environment Setup
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Start Dev Server
```powershell
python main_dashboard.py
```
This will start the background engine and open a local server at `localhost:8000`.

### 3. Build for Production
To package the project into a standalone portable executable:
```powershell
.\build.ps1
```
The final build will be located in the `dist/ICEC_Smart_Assistant` directory.

## Usage Guide

1. Open `configs/List.csv` and input your target routes (using the 3-letter IATA airport codes for departure and destination).
2. Run `ICEC_Smart_Assistant.exe`.
3. Click **Start Automated Collection** on the dashboard, and the headless bot will begin background processing.
4. Click **Export Report** at any time to retrieve the latest JSON or CSV results.

## Safety Rules

This tool integrates evasion mechanics that simulate genuine human traffic. Please strictly adhere to the following safety rules:
1. **Do not arbitrarily lower delays**: Maintain the default `min_delay` and `max_delay` values provided in `configs/site.config.json` (recommended 6-12 seconds minimum).
2. Malicious scanning with aggressive concurrency or ultra-low latency may result in IP permanent bans and naturally violates the target website's Terms of Service.
