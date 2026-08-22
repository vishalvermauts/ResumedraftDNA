# Deployment Documentation: ResumeDraftDNA Backend

This document outlines the infrastructure requirements, setup procedures, and deployment logic for the **ResumedraftDNA** backend, a Python/FastAPI service designed to orchestrate job intelligence for the ResumeDraft application.

---

## 1. AWS EC2 Requirements
To support the Docker Compose stack (FastAPI, Redis, Celery, MongoDB), your instance must have sufficient memory and compute resources.

*   **Instance Type**: `t4g.medium` (Recommended)
    *   **vCPU**: 2
    *   **RAM**: 4 GB
    *   **Architecture**: ARM64 (Graviton2 - efficient & cost-effective)
*   **AMI**: Ubuntu 24.04 LTS (or 22.04)
*   **Networking**:
    *   **Inbound Rules**: 
        *   Port 22 (SSH) - Restrict to your IP for security.
        *   Port 80/443 (HTTP/HTTPS) - Required for the Caddy reverse proxy.
        *   Port 8000 (API) - Optional, only if accessing directly without Caddy.
*   **Storage**: 50GB gp3 SSD.

---

## 2. Infrastructure Setup (One-Time)

### Step 1: Prepare the EC2 Instance
Log into your AWS console and ensure the instance `draftresume` (`t4g.medium`) is running with the Security Group allowing ports 22, 80, and 443.

### Step 2: Install Docker & Environment
SSH into your instance and run the following commands:

```bash
# Update and install Docker
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### Step 3: Clone & Configure
```bash
mkdir -p ~/app
cd ~/app
git clone https://github.com/vishalvermauts/ResumedraftDNA.git .

# Create the .env file with mandatory secrets
cat <<EOF > .env
GEMINI_API_KEY=your_gemini_api_key_here
FIREBASE_PROJECT_ID=your_project_id
MONGODB_URI=mongodb://mongo:27017/resumedraft
REDIS_URL=redis://redis:6379
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
EOF
```
*Note: Make sure to populate these values with your actual API keys and IDs.*

### Step 4: Launch
```bash
sudo docker compose up -d
```

---

## 3. Connecting Next.js Frontend to DNA Backend

The frontend (Next.js app) needs to know where the backend lives to make API requests.

### Configuration
Update the `.env.local` file in your main `Resumedraft` frontend repository:

```bash
NEXT_PUBLIC_DNA_API_URL=http://98.80.105.34:8000/v1
```

### Authentication Contract
1. **Frontend**: When the frontend makes an API call to the DNA backend, it must extract the Firebase ID token:
   ```javascript
   const token = await auth.currentUser.getIdToken();
   const response = await fetch(`${process.env.NEXT_PUBLIC_DNA_API_URL}/some-endpoint`, {
     headers: { 'Authorization': `Bearer ${token}` }
   });
   ```
2. **Backend**: The FastAPI app uses `app/auth.py` to verify this token using the `firebase-admin` SDK. This ensures no session management is required on the backend.

---

## 4. Background Task Management
The DNA backend uses **Celery + Redis** to handle asynchronous tasks (e.g., ATS parsing, job scraping). 

- **View Celery Logs**: `sudo docker compose logs -f worker`
- **Inspect Queue**: If tasks are stuck, use `sudo docker compose exec redis redis-cli llen celery` to check queue length.
- **Monitoring**: Celery workers auto-restart. If they crash repeatedly, check the `logs` for memory errors or missing dependencies.

---

## 5. Updates & Maintenance

When you push new code to the `ResumedraftDNA` repository, follow these steps on your server to update the backend:

### Step 1: Update Code
```bash
cd ~/app
git pull origin master
```

### Step 2: Restart Services
```bash
# Rebuild and restart containers
sudo docker compose up -d --build
```
*Note: You do not need to delete the `.env` file during this update; it will persist.*

---

## 5. Operational Monitoring
- **View Logs**: `sudo docker compose logs -f api`
- **Restart Backend**: `sudo docker compose restart api`
- **Health Check**: `curl http://98.80.105.34:8000/v1/health`

---

## 6. Security Precautions
- **Database**: We are using local Docker MongoDB for simplicity initially, but for production-level durability, **we strongly recommend moving to MongoDB Atlas**.
- **Keys**: Never commit `.env` or `serviceAccountKey.json` to version control.
- **Firewall**: Ensure `ufw` or AWS Security Groups restrict access to ports 80/443/22 to only known, authorized traffic.

---

## 7. Gemini API Safeguards

Google Search Grounding is permanently disabled in this codebase. Do not re-enable the `ai_search` connector or the grounded Gemini code path.

### Required controls
* Keep `ENABLE_GEMINI_GROUNDING=false` in every environment, even though the current code no longer depends on it.
* Do not add live or paid grounding tests to CI.
* If you need job discovery expansion, use the ATS connectors and JSON-LD paths only.
* Any AI cost spikes must be investigated through standard Gemini usage, not search grounding.
