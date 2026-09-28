# Rebooy Panel — Creator Studio & Social Media Automation

![Python](https://img.shields.io/badge/Python-3.13-blue.svg?style=flat-square&logo=python)
![Django](https://img.shields.io/badge/Django-5.1-green.svg?style=flat-square&logo=django)
![DaisyUI](https://img.shields.io/badge/DaisyUI-4.12.23-orange.svg?style=flat-square&logo=daisyui)
![TailwindCSS](https://img.shields.io/badge/TailwindCSS-3.x-38bdf8.svg?style=flat-square&logo=tailwindcss)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ed.svg?style=flat-square&logo=docker)
![License](https://img.shields.io/badge/License-Proprietary-red.svg?style=flat-square)

**Rebooy Panel** is a centralized content creation, audience analytics, and automated WordPress publishing platform designed for digital creators, social media agencies, and media managers. Built with **Django 5** and **DaisyUI** (supporting dynamic **Coffee** and **Latte** themes), it integrates generative AI models (**Google Gemini**, **OpenRouter**) with scraping engines and WordPress REST API multi-domain pools.

---

## 🌟 Key Modules & Capabilities

### 1. 🎬 Video to Prompt Studio (`/video-prompt/`)
- **Reverse-Engineering with AI:** Analyzes local video uploads (`.mp4`, `.mov`, `.avi`) or social media URLs using Google Gemini to deconstruct scenes, camera movements, lighting, and visual styles.
- **Scene-by-Scene Breakdown:** Generates timestamps, character actions, emotional dialogue, and background soundscapes.
- **Dual Markdown Viewer:** Provides both an interactive HTML preview rendered with `marked.js` (`.md-prose`) and a raw formatted multiline code editor with instant copy actions.
- **Video Metadata & Statistics:** Audits views, likes, comments count, uploader details, and duration.

### 2. 📥 Instagram Downloader & Auto-Publisher (`/ig-downloader/`)
- **Watermark-Free Reel Downloads:** Extracts high-definition video streams and native thumbnails via `yt-dlp` and resilient direct streams.
- **Automated 16:9 Cinematic Covers:** Vertical (9:16) thumbnails are automatically converted into 1280×720 landscape covers using Gaussian-blurred ambient backgrounds, foreground centering, and soft depth shadows (eliminating feed distortion).
- **AI Facebook Copywriting:** Generates hook-driven social captions, engagement CTAs, and optimized hashtags.
- **Automated WordPress Publishing & Classification:** Posts articles directly to active WordPress sites, automatically categorizing them into **Dramas**, **Comedia**, or **Entretenimiento** via REST API.
- **Duplicate Prevention:** Rejects duplicate Reel URLs with HTTP 409 and displays an alert modal with direct history navigation.

### 3. 🪄 Fanpage Creator Studio (`/fanpages/`)
- **Brand Identity Generation:** Creates fanpage concepts, catchy names, descriptions, and visual guidelines.
- **Prompt Engineering:** Generates exact 1:1 profile image prompts and 16:5 cover prompts tuned for Midjourney, Stable Diffusion, and Flux.

### 4. 📈 Facebook Fan Extractor & Monitoring (`/extractor/`)
- **Live Audience Scraping:** Tracks follower counts, engagement status, and growth deltas across Facebook fanpages.
- **Auto-Refresh Scheduler:** Configurable automated background worker with countdown timers (15m to 24h).
- **Interactive Growth Curves:** Historical snapshots visualized with `Chart.js` area graphs.
- **Real-Time Live Progress Banner:** Displays instant visual progress (`processed / total`, percentage, and current page title) with Server-Sent Events (SSE) and polling fallback.
- **Anti-Duplicate Filter:** Detects and alerts if submitted fanpages are already being monitored.

### 5. 🌐 WordPress Domain Manager (`/panel/wordpress/`)
- **Centralized Multi-Site Pool:** Connects multiple WordPress installations using Application Passwords.
- **Multi-Domain Failover & Rotation:** Distributes published articles across active sites with automatic retry logic.
- **Featured Media & Categories:** Automatically uploads covers and manages category taxonomies via WP REST API.

### 6. 🛡️ User Administration & Security (`/panel/usuarios/` & `/seguridad/`)
- **Role-Based Access Control (RBAC):** Super Admin, Admin, and Standard User tiers.
- **Daily Generation Quotas:** Granular daily prompt limits with interactive steppers and quick-allocation chips.
- **Active Session Audit:** Live tracking of connected devices (mobile, tablet, desktop), IP addresses, and browsers with heartbeat verification.
- **Remote Revocation:** One-click remote session termination and mass logout capabilities.
- **Netscape Cookie Vault:** Live diagnostics, upload, and direct editing of `cookies.txt` for Instagram and Facebook scrapers.

---

## 🛠️ Tech Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3.13, Django 5.1, Gunicorn, Celery / Redis ready |
| **Frontend** | DaisyUI 4.12.23 (Coffee & Latte themes), Tailwind CSS, Lucide Icons, Chart.js, Marked.js |
| **Database** | SQLite (Default / Development) & PostgreSQL (Production via `psycopg2`) |
| **Media & Static** | WhiteNoise with Manifest Storage, Pillow (PIL), OpenCV, FFmpeg, yt-dlp |
| **AI Integration** | Google GenAI SDK (Gemini 2.5/3.7 Flash via CLI Proxy), OpenRouter API |
| **DevOps** | Docker, Docker Compose, Dokploy ready |

---

## 🚀 Getting Started (Local Development)

### 1. Clone the repository
```bash
git clone https://github.com/estebcast0003/rebooypanel.git
cd rebooypanel
```

### 2. Create and activate a virtual environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the root directory:
```env
DEBUG=True
SECRET_KEY=your-secure-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# AI Proxy & Services
CLI_PROXY_URL=https://cli.serverdok.site
CLI_SECRET_KEY=your-cli-secret-key
CLI_PROXY_MODEL=gemini-3.7-flash-high
OPENROUTER_API_KEY=your-openrouter-api-key

# Optional Celery & Redis
USE_CELERY=False
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
```

### 5. Run Migrations & Collect Static Files
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

### 6. Create a Superuser
```bash
python manage.py createsuperuser
```

### 7. Start the Development Server
```bash
python manage.py runserver 8000
```
Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

---

## 🐳 Docker Deployment

The application includes a production-ready `Dockerfile` and a container entrypoint script located at `scripts/entrypoint.sh`.

### Running with Docker Compose
```bash
docker compose up -d --build
```

### Building and Running the Docker Image manually
```bash
# Build image
docker build -t rebooypanel .

# Run container
docker run -d \
  -p 8000:8000 \
  -e DEBUG=False \
  -e ALLOWED_HOSTS="*" \
  -e SECRET_KEY="your-production-secret-key" \
  -v rebooy_media:/app/media \
  -v rebooy_data:/app/data \
  --name rebooypanel-app \
  rebooypanel
```

The container automatically executes `scripts/entrypoint.sh` on startup:
1. Verifies database connectivity with exponential retries.
2. Applies pending database migrations (`python manage.py migrate`).
3. Compiles and post-processes static assets (`python manage.py collectstatic`).
4. Boots Gunicorn with configured workers, threads, and timeout settings.

---

## 🧪 Testing

The test suite validates data isolation, authentication, AI scrapers, anti-duplicate controls, and WordPress REST API integrations:

```bash
# Run the complete test suite (118+ tests)
python manage.py test

# Run tests for a specific application
python manage.py test igdownloader
python manage.py test wordpress_manager
python manage.py test panel_admin
```

---

## 📁 Project Structure

```text
rebooypanel/
├── apps/
│   ├── accounts/             # CustomUser model, RBAC, and active session audit
│   ├── core/                 # Shared utilities, CLI Proxy client, home & login
│   ├── dashboard/            # Executive overview metrics & KPI cards
│   ├── extractor/            # Facebook Fan Extractor, scheduler & scraper
│   ├── fanpages/             # Fanpage Creator Studio & prompt generator
│   ├── igdownloader/         # Instagram Reel downloader & Facebook copywriter
│   ├── panel_admin/          # User administration, statistics & cookie vault
│   ├── videoprompt/          # Video to Prompt Studio & reverse-engineering
│   └── wordpress_manager/    # WordPress multi-domain REST API publishing pool
├── config/                   # Django settings, WSGI, ASGI, and URL routing
├── scripts/
│   └── entrypoint.sh         # Production container startup and migration script
├── static/                   # Global static assets (CSS, JS, images, icons)
├── staticfiles/              # WhiteNoise compiled static distribution files
├── templates/                # Base layout templates (panel_base_daisy.html)
├── Dockerfile                # Multi-stage production container definition
├── docker-compose.yml        # Docker Compose configuration
├── manage.py                 # Django command-line execution entry point
├── requirements.txt          # Python package dependencies
└── README.md                 # Project documentation
```

---

## 🔒 Security & Privacy

- CSRF protection enabled on all API and AJAX endpoints.
- Application Passwords sanitized for WordPress REST calls.
- Automated Netscape cookie hygiene and session log cleanup.
- Passwords hashed using Django's PBKDF2 implementation.

---

## 📄 License
This project is proprietary and confidential. Unauthorized copying, distribution, or modification is strictly prohibited.
