# Myrient Community App Store for Umbrel

A community app store for [Umbrel](https://umbrel.com) containing the Myrient Search Engine.

## Apps

| App | Description | Port |
|-----|-------------|------|
| Myrient Search | Full-text search engine for the Myrient game archive | 8076 |

## How to Install

### Option 1: Via Umbrel UI

1. Open your Umbrel dashboard
2. Go to **App Store** > **Community App Stores** (or click the three dots menu)
3. Click **Add Community App Store**
4. Enter this repository URL: `https://github.com/tagius/umbrel-community-app-store`
5. Click **Add**
6. Find "Myrient Search" in the app store and click **Install**

### Option 2: Via CLI

SSH into your Umbrel and run:

```bash
sudo ~/umbrel/scripts/repo add https://github.com/tagius/umbrel-community-app-store.git
sudo ~/umbrel/scripts/repo update
```

Then install from the Umbrel UI, or:

```bash
sudo ~/umbrel/scripts/app install myrient-myrient-search
```

## Port Allocation

This app store uses port **8076**, which is not used by any official Umbrel app or common community app store. If you have a conflict, you can modify the `port` field in `myrient-myrient-search/umbrel-app.yml`.

## Pre-indexed Image

By default, the first launch will crawl and index the entire Myrient archive (takes ~30 minutes). If you want to skip this, you can deploy a pre-indexed image. See the [main repository README](https://github.com/tagius/myrient-search#pre-indexed-deployment) for instructions.
