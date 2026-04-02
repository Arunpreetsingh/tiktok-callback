#!/usr/bin/env python3
"""
web_demo/app.py — ShopReel web UI demo for TikTok app review.

Demonstrates all 3 API scopes via a browser UI:
  1. user.info.basic  — OAuth login, display connected account
  2. video.upload     — upload video as inbox draft (pull_by_url)
  3. video.publish    — publish video directly to profile (pull_by_url)

Deploy to Vercel. Set env vars:
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI, SECRET_KEY
"""

import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import requests
from flask import (Flask, redirect, render_template, request,
                   session, url_for, jsonify)
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
# Set TIKTOK_REDIRECT_URI to your Vercel URL + /callback after deploying
REDIRECT_URI  = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8080/callback")
SCOPES        = "user.info.basic,video.publish,video.upload"
API_BASE      = "https://open.tiktokapis.com"

# Video hosted on GitHub Pages (pull_by_url — no file upload from server)
DEMO_VIDEO_URL = "https://arunpreetsingh.github.io/tiktok-callback/demo.mp4"
DEMO_CAPTION   = (
    "Want to wake up to smoother skin? 🌟 This retinol serum reduces fine lines and hydrates 🌿 "
    "It's only $19.99! #KoreanSkincare #RetinolForSensitiveSkin #SkincareLovers "
    "#GlowUp #NightSerum #HaruharuWonders #SkincareOnABudget #BeautyEssentials"
)


def api_headers():
    return {
        "Authorization": f"Bearer {session.get('access_token', '')}",
        "Content-Type": "application/json; charset=UTF-8",
    }


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", user=session.get("user"))


@app.route("/login")
def login():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    # PKCE
    code_verifier = secrets.token_urlsafe(64)
    session["code_verifier"] = code_verifier
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key":            CLIENT_KEY,
        "scope":                 SCOPES,
        "response_type":         "code",
        "redirect_uri":          REDIRECT_URI,
        "state":                 state,
        "code_challenge":        code_challenge,
        "code_challenge_method": "S256",
    })
    return redirect(auth_url)


@app.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return render_template("error.html", message=f"TikTok OAuth error: {error}")

    code  = request.args.get("code")
    state = request.args.get("state")

    if state != session.get("oauth_state"):
        return render_template("error.html", message="State mismatch — possible CSRF.")

    # Exchange code for access token
    resp = requests.post(
        f"{API_BASE}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key":    CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code":          code,
            "grant_type":    "authorization_code",
            "redirect_uri":  REDIRECT_URI,
            "code_verifier": session.get("code_verifier", ""),
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("error"):
        return render_template("error.html", message=f"Token exchange failed: {data}")

    session["access_token"] = data["access_token"]

    # Fetch user info — scope: user.info.basic
    user_resp = requests.get(
        f"{API_BASE}/v2/user/info/",
        headers=api_headers(),
        params={"fields": "open_id,display_name,username,avatar_url"},
        timeout=10,
    )
    user_data = user_resp.json().get("data", {}).get("user", {})
    session["user"] = {
        "username":     user_data.get("username") or user_data.get("display_name", ""),
        "display_name": user_data.get("display_name", ""),
        "avatar_url":   user_data.get("avatar_url", ""),
    }

    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if not session.get("user"):
        return redirect(url_for("index"))
    return render_template("dashboard.html",
                           user=session["user"],
                           caption=DEMO_CAPTION,
                           video_url=DEMO_VIDEO_URL)


@app.route("/api/upload-draft", methods=["POST"])
def upload_draft():
    """Scope: video.upload — upload as inbox draft via pull_by_url."""
    init_resp = requests.post(
        f"{API_BASE}/v2/post/publish/inbox/video/init/",
        headers=api_headers(),
        json={"source_info": {
            "source":    "PULL_FROM_URL",
            "video_url": DEMO_VIDEO_URL,
        }},
        timeout=15,
    )
    data = init_resp.json()
    if init_resp.status_code != 200 or data.get("error", {}).get("code", "ok") != "ok":
        return jsonify({"success": False, "error": data.get("error", data)}), 400

    publish_id = data["data"]["publish_id"]
    return jsonify({
        "success":    True,
        "publish_id": publish_id,
        "message":    "Video uploaded to your TikTok inbox as a draft. Check your TikTok app for the review notification.",
        "scope_used": "video.upload",
    })


@app.route("/api/publish", methods=["POST"])
def publish():
    """Scope: video.publish — direct post via pull_by_url."""
    init_resp = requests.post(
        f"{API_BASE}/v2/post/publish/video/init/",
        headers=api_headers(),
        json={
            "post_info": {
                "title":                   DEMO_CAPTION[:2200],
                "privacy_level":           "SELF_ONLY",
                "disable_duet":            False,
                "disable_stitch":          False,
                "disable_comment":         False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source":    "PULL_FROM_URL",
                "video_url": DEMO_VIDEO_URL,
            },
        },
        timeout=15,
    )
    data = init_resp.json()
    if init_resp.status_code != 200 or data.get("error", {}).get("code", "ok") != "ok":
        return jsonify({"success": False, "error": data.get("error", data)}), 400

    publish_id = data["data"]["publish_id"]

    # Poll status
    for _ in range(15):
        time.sleep(4)
        s_resp = requests.post(
            f"{API_BASE}/v2/post/publish/status/fetch/",
            headers=api_headers(),
            json={"publish_id": publish_id},
            timeout=10,
        )
        status = s_resp.json().get("data", {}).get("status", "PROCESSING")
        if status == "PUBLISH_COMPLETE":
            return jsonify({
                "success":    True,
                "publish_id": publish_id,
                "status":     status,
                "message":    "Video published to your TikTok profile (SELF_ONLY — change visibility in TikTok Studio).",
                "scope_used": "video.publish",
            })
        if status == "FAILED":
            return jsonify({"success": False, "error": "Publish failed on TikTok side"}), 500

    return jsonify({
        "success":    True,
        "publish_id": publish_id,
        "status":     "PROCESSING",
        "message":    "Video submitted — it will appear on your TikTok profile shortly.",
        "scope_used": "video.publish",
    })


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    print("\n  ShopReel Demo Server")
    print("  Open: http://localhost:8080\n")
    app.run(debug=False, port=8080)
