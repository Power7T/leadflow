# LeadFlow

LeadFlow is an autonomous, end-to-end outbound sales and lead generation system designed for web development agencies. It silently works in the background to scrape Google Maps, analyze business websites, build fully customized demo websites, draft AI-personalized outreach, and automatically send emails and follow-ups.

---

## Key Features

### 1. Automated Lead Generation & Deduplication
- **Intelligent Scraping:** Uses the Google Places API to find local businesses based on niche and location.
- **Smart Deduplication:** Performs domain-based extraction and name-similarity comparisons to avoid reaching out to the same business twice.
- **Contact Enrichment:** Scrapes emails, social profiles, and verifies if phone numbers are WhatsApp-ready.
- **Owner Name Extraction:** Scrapes the business "About" or "Team" pages to identify owner names, automatically formatting salutations (e.g. *Hey Mike,* instead of *Hey owner,*).

### 2. Website Performance Auditing & Grading
- **Automatic Grading:** Evaluates lead websites using the Google PageSpeed Insights API.
- **Visual CRM Badging:** Automatically marks leads with Hot (🔥), Warm (🌡️), or Cold (🧊) badges based on site performance scores, helping target low-performing sites.

### 3. Premium Demo Generation & Deployment
- **Niche Templates:** Contains pre-designed premium HTML templates for multiple niches:
  - **Fitness & Gyms** (Dark neon sports aesthetics)
  - **Restaurants & Cafes** (Warm amber food-photography aesthetics)
  - **Dentist & Clinics** (Clean teal medical layout)
  - **Barbershops & Salons** (Vintage burgundy grooming portfolio)
  - **Real Estate** (Navy and gold luxury properties)
- **Central Template Manager:** Enable/disable specific templates dynamically from the dashboard.
- **GitHub Pages Auto-Deployment:** Deploys generated prospect demo sites to GitHub Pages via the GitHub Contents API and logs the live URL.

### 4. Smart Multi-Model Copywriter & Routing Pool
- **5-Tier Fallback Chain:** Directs prompt requests through a self-healing chain of AI services (`agy` CLI -> REST API -> OpenAI -> Claude -> Offline templates).
- **REST API Key Rotation:** Distributes API requests across a pool of up to 8 Gemini API keys in `.env` to bypass free-tier rate limits.
- **Smart Task Routing:**
  - **Outreach & Sequences:** Runs REST API keys first with optimized models (`gemini-2.5-flash`, `gemini-3-flash-preview`, `gemini-2.5-pro`) to save local system resources.
  - **Audits & Complex Logic:** Reserves local `agy` CLI models like `Claude Sonnet 4.6 (Thinking)` or `Gemini 3.1 Pro (High)` for logical tasks.
- **Offline Template Fallback:** Provides preselected copy variants for all outreach contexts (initial, follow-ups, audits, no-website, live follow-ups) if all APIs are offline.

### 5. Interactive Kanban Pipeline & CRM
- **Pipeline Stages:** Manage leads through a visual drag-and-drop pipeline containing columns for: *New*, *Generated*, *Sent*, *Opened*, *Demo Viewed*, *Replied*, and *Converted*.
- **Interaction Logging:** Track real-time events like email opens, demo site visits, and replies.

### 6. Campaign Analytics & A/B Testing
- **Conversion Funnel:** Visualizes transition rates from initial discovery down to conversions.
- **A/B Subject Line Performance:** Logs subjects used and computes open rates to rank top-performing subjects.
- **Performance Matrices:** Breaks down outreach performance by city and business category.

---

## Technology Stack

- **Backend:** Python (FastAPI), SQLite (Database)
- **Frontend:** HTML5, Vanilla CSS, Javascript (ES6)
- **Automation:** APScheduler (Background task coordinator)
- **AI / LLM:** Google Antigravity SDK (`agy` CLI) & Google Gemini REST API

---

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
   # API Keys (Google Studio - comma-separated list of up to 8 keys for rotation)
   GEMINI_API_KEY=your_key_1,your_key_2,your_key_3

   # Places API Key
   GOOGLE_MAPS_API_KEY=your_maps_api_key
   GOOGLE_PAGESPEED_API_KEY=your_pagespeed_api_key

   # GitHub Deployment
   GITHUB_TOKEN=your_github_token
   GITHUB_DEMO_REPO=your_github_username/leadflow-demos

   # SMTP Outreach
   SENDER_EMAIL=your_email@gmail.com
   SENDER_APP_PASSWORD=your_app_password

   # Schedulers / Booking
   CALENDLY_URL=https://calendly.com/your-username
   BOOKING_URL=https://www.fiverr.com/sellers/your-username
   ```
5. Start LeadFlow and the Demo Server:
   ```bash
   chmod +x LeadFlow.command
   ./LeadFlow.command
   ```
6. Access the dashboard in your browser at `http://127.0.0.1:8765`.

---

## Disclaimer
This project is built for autonomous lead generation. Always ensure compliance with local anti-spam laws (CAN-SPAM, GDPR) when automating outreach.
