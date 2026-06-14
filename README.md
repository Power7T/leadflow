# LeadFlow

LeadFlow is an autonomous, end-to-end outbound sales and lead generation system designed for web development agencies. It silently works in the background to scrape Google Maps, analyze business websites, build fully customized demo websites, draft AI-personalized outreach, and automatically send emails and follow-ups.

## Features

- **Automated Lead Generation:** Uses the Google Places API to find local businesses based on niche and location.
- **Intelligent Website Scoring:** Automatically fetches and analyzes the business's existing website (or lack thereof), scoring it based on mobile responsiveness, load times, and missing revenue opportunities. Drops poor leads (e.g. scores >= 70 or landline numbers).
- **Contact Extraction & Enrichment:** Scrapes emails, Instagram handles, LinkedIn profiles, and verifies if phone numbers are active mobile numbers (WhatsApp ready) using telecommunication carrier logic.
- **Demo Site Generation:** Automatically generates a beautiful, fast, and mobile-friendly static demo site tailored to the business's niche (e.g., Gym, Airbnb) and deploys it live to GitHub Pages.
- **Autonomous AI Outreach:** Uses an integrated AI model (Gemini 3.5 Flash) to draft highly-personalized, high-converting outreach emails and DMs. Follows strict copywriting rules, including "Pattern Interrupts" and confident statements, while dynamically injecting the custom demo link.
- **Hands-Free Automation (The "Night Shift"):** 
  - **Auto-Find:** Scrapes new leads daily at 6 AM UTC based on predefined locations.
  - **Auto-Send:** Every 60 minutes, the system autonomously builds demo sites for high-scoring leads (>80) and fires off the AI-generated email.
  - **Auto-Followup:** Drip campaigns automatically run every 15 minutes to follow up with leads who haven't responded within 4 days.
- **Integrated CRM & Kanban:** Manage leads, track email opens/clicks via pixel tracking, and move closed deals through a visual pipeline.

## Technology Stack

- **Backend:** Python (FastAPI), SQLite (Database)
- **Frontend:** HTML, Vanilla CSS, JS
- **Automation:** APScheduler (Background Jobs), Subprocess Git integrations
- **AI / LLM:** Google Antigravity SDK (`agy`) for hyper-personalized messaging
- **Integrations:** Google Maps API, Google PageSpeed API, Gmail SMTP

## Setup & Installation

**Note: Do NOT commit your `.env` file to version control. Keep all API keys secret.**

1. Clone the repository.
2. Ensure you have Python 3.10+ installed.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install phonenumbers --break-system-packages
   ```
4. Create a `.env` file in the root directory and add your credentials:
   ```env
   GOOGLE_MAPS_API_KEY=your_maps_api_key
   GOOGLE_PAGESPEED_API_KEY=your_pagespeed_api_key
   SENDER_EMAIL=your_email@gmail.com
   SENDER_APP_PASSWORD=your_app_password
   # Optional: HUNTER_API_KEY, APOLLO_API_KEY
   ```
5. Run the server:
   ```bash
   uvicorn server:app --host 127.0.0.1 --port 8765
   ```
6. Access the dashboard via your browser.

## Disclaimer
This project is built for autonomous lead generation. Always ensure compliance with local anti-spam laws (CAN-SPAM, GDPR) when automating outreach.
