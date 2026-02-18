# Myrient Search — Deployment Guide (Beginner-Friendly)

This guide walks you through publishing your Docker image to GitHub and installing it on Umbrel. No prior GitHub or Docker publishing experience needed.

---

## Prerequisites

On your local computer, you need:

- **Git** installed (check: `git --version`)
- **Docker Desktop** installed and running
- A **GitHub account** (yours is `tagius`)

---

## Part 1: Install Git & Authenticate with GitHub

### 1.1 — Configure Git (one-time setup)

Open a terminal and run:

```bash
git config --global user.name "tagius"
git config --global user.email "thom.suig@gmail.com"
```

### 1.2 — Create a GitHub Personal Access Token

You need a token so Git and Docker can talk to GitHub on your behalf.

1. Go to https://github.com/settings/tokens?type=beta
2. Click **"Generate new token"**
3. Name it something like `myrient-deploy`
4. Under **Repository permissions**, set:
   - Contents: **Read and Write**
   - Packages: **Read and Write**
5. Under **Account permissions**, set:
   - (defaults are fine)
6. Click **Generate token**
7. **Copy the token immediately** — you won't see it again. It looks like `github_pat_xxxxxxx...`

Save it somewhere safe temporarily (a text file on your desktop is fine for now).

---

## Part 2: Create the Main Repo (`myrient-search`)

### 2.1 — Create the repo on GitHub

1. Go to https://github.com/new
2. Repository name: `myrient-search`
3. Description: `Self-hosted search engine for the Myrient game archive`
4. Set it to **Public** (required for free GHCR packages)
5. **Don't** check "Add a README" (we already have files)
6. Click **Create repository**

### 2.2 — Push your code

In your terminal, navigate to your myrient-search folder and run these commands one by one:

```bash
cd /path/to/your/myrient-search

# Remove any old git state and start fresh
rm -rf .git
git init

# Add all files (.gitignore will exclude __pycache__, .db files, etc.)
git add .

# Verify: check that nothing unwanted is staged
git status
```

Review the `git status` output. You should NOT see `__pycache__/`, any `.db` files, or `Myrient-Search-Engine/`. The `.env` file SHOULD be included — it contains no secrets, just configuration defaults.

If everything looks clean:

```bash
# Create your first commit
git commit -m "Initial release: Myrient Search Engine v1.0.0"

# Tell git where your GitHub repo is
git remote add origin https://github.com/tagius/myrient-search.git

# Push (it will ask for your username and password)
# Username: tagius
# Password: paste your Personal Access Token (NOT your GitHub password)
git branch -M main
git push -u origin main
```

> **Tip**: If it asks for a password, always use your **Personal Access Token**, not your GitHub login password. GitHub stopped accepting passwords in 2021.

### 2.3 — Tag a version (this triggers the Docker image build)

```bash
git tag v1.0.0
git push origin v1.0.0
```

This triggers the GitHub Action that builds your Docker image for both AMD64 (regular PCs) and ARM64 (Raspberry Pi, Umbrel Home) and pushes it to `ghcr.io/tagius/myrient-search:v1.0.0`.

### 2.4 — Wait for the build & make the package public

1. Go to https://github.com/tagius/myrient-search/actions
2. You should see a workflow running called "Build and Push to GHCR"
3. Wait for it to finish (green checkmark) — takes 5-10 minutes
4. Go to https://github.com/tagius?tab=packages
5. Click on `myrient-search`
6. Click **Package settings** (right sidebar)
7. Scroll down to **Danger Zone** > **Change visibility** > set to **Public**

> **Why public?** Umbrel needs to pull the image without authentication. Free GitHub accounts can host unlimited public packages.

---

## Part 3: Create the App Store Repo (`umbrel-community-app-store`)

This is a separate repo that tells Umbrel about your app.

### 3.1 — Create the repo on GitHub

1. Go to https://github.com/new
2. Repository name: `umbrel-community-app-store`
3. Description: `Myrient apps for Umbrel`
4. Set it to **Public**
5. **Don't** check "Add a README"
6. Click **Create repository**

### 3.2 — Push the app store files

```bash
# Navigate to the app store folder inside your project
cd /path/to/your/myrient-search/umbrel-app-store

# Initialize a NEW git repo here (this is a separate repo from myrient-search)
git init
git add .
git commit -m "Add Myrient Search app for Umbrel"

git remote add origin https://github.com/tagius/umbrel-community-app-store.git
git branch -M main
git push -u origin main
```

---

## Part 4: Add Gallery Screenshots (Optional but Recommended)

Take 3 screenshots of your Myrient Search UI and save them as:
- `1.jpg` — the main search page
- `2.jpg` — search results
- `3.jpg` — filters or sort in action

Place them in `umbrel-app-store/myrient-myrient-search/gallery/` then push:

```bash
cd /path/to/your/myrient-search/umbrel-app-store
git add gallery/
git commit -m "Add gallery screenshots"
git push
```

---

## Part 5: Install on Your Umbrel

### 5.1 — Add the community app store

1. Open your Umbrel dashboard in a browser (usually `http://umbrel.local`)
2. Go to the **App Store**
3. Click the **three dots** (⋯) in the top right
4. Click **Community App Stores**
5. Paste this URL: `https://github.com/tagius/umbrel-community-app-store`
6. Click **Add**

### 5.2 — Install Myrient Search

1. You should now see "Myrient Apps" as a store
2. Find **Myrient Search** and click **Install**
3. Wait for it to download and start

### 5.3 — Access it

Open `http://umbrel.local:8076` in your browser. That's it!

The first launch will automatically start crawling and indexing Myrient. This takes about 30 minutes. You can watch the progress in the UI footer.

---

## Configuration

All settings are in the `.env` file at the root of the project. The defaults work out of the box, but you can customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `MYRIENT_BASE_URL` | `https://myrient.erista.me/files/` | Myrient archive URL to crawl |
| `CRAWL_CONCURRENCY` | `10` | Number of simultaneous crawler connections |
| `CRAWL_DELAY_MS` | `50` | Delay between requests (ms) — be polite to the server |
| `CRAWL_TIMEOUT` | `30` | Request timeout (seconds) |
| `SYNC_SCHEDULE` | `0 3 1 * *` | Auto-sync cron schedule (3 AM, 1st of month) |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server port inside the container |
| `DATA_DIR` | `/data` | Where the database is stored inside the container |
| `RESULTS_PER_PAGE` | `50` | Search results per page |
| `MAX_RESULTS` | `10000` | Maximum search results |

After editing `.env`, restart the container:

```bash
docker compose down && docker compose up -d
```

---

## Part 6: Updating the App in the Future

When you make changes to your code:

```bash
# In your myrient-search folder:
cd /path/to/your/myrient-search

git add .
git commit -m "Description of what changed"
git push

# Tag a new version to rebuild the Docker image
git tag v1.1.0
git push origin v1.1.0
```

Then update the app store:

1. Edit `umbrel-app-store/myrient-myrient-search/umbrel-app.yml`
2. Change `version: "1.0.0"` to `version: "1.1.0"`
3. Update the image tag in `docker-compose.yml` to `v1.1.0`
4. Add release notes
5. Commit and push:

```bash
cd /path/to/your/myrient-search/umbrel-app-store
git add .
git commit -m "Update to v1.1.0"
git push
```

On Umbrel, the update will appear automatically (Umbrel checks for updates periodically).

---

## Troubleshooting

**"Permission denied" when pushing:**
Make sure you're using your Personal Access Token as the password, not your GitHub password.

**GitHub Action fails:**
Go to Actions tab > click the failed run > read the error. Most common: the Dockerfile has a syntax error or a file is missing.

**Package not visible / 403 when Umbrel pulls:**
Make sure the package is set to **Public** (Part 2, step 2.4).

**Port conflict on Umbrel:**
If another app already uses port 8076, edit the `port:` in `umbrel-app.yml` and pick another (e.g., 8077). Then push the change.

**App won't start on Umbrel:**
SSH into Umbrel and check logs:
```bash
docker logs myrient-myrient-search_web_1 --tail 50
```

---

## Quick Reference — What Goes Where

| What | Repo | Purpose |
|------|------|---------|
| App code, Dockerfile, `.env`, GitHub Action | `tagius/myrient-search` | Builds the Docker image → `ghcr.io/tagius/myrient-search` |
| umbrel-app.yml, docker-compose.yml | `tagius/umbrel-community-app-store` | Tells Umbrel how to install & run the app |
