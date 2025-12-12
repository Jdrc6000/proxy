from flask import Flask, request, Response, redirect, url_for, send_from_directory
import requests
import re
from urllib.parse import urlparse, urljoin
import os

app = Flask(__name__)

# Simple favicon so it stops 502 spamming your logs
@app.route('/favicon.ico')
def favicon():
    return "", 204

@app.route("/", methods=["GET", "POST"])
def index():
    url = request.args.get("q") or request.form.get("q", "").strip()
    if not url:
        return '''
        <title>Koyeb Proxy</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>body{font-family:Arial;background:#111;color:#fff;text-align:center;padding:50px}</style>
        <h1>Koyeb Proxy</h1>
        <form method="get">
            <input name="q" placeholder="https://youtube.com" autofocus style="width:90%;max-width:600px;padding:15px;font-size:18px">
            <button style="padding:15px 25px;font-size:18px">Go</button>
        </form>
        <p style="margin-top:30px">Or just append the site: your-app.koyeb.app/youtube.com</p>
        '''
    if not url.startswith("http"):
        url = "https://" + url
    return redirect("/proxy/" + url)

@app.route("/proxy/<path:url>", methods=["GET", "POST"])
def proxy(url):
    # Reconstruct full target URL
    target = url
    if "://" not in target:
        target = "https://" + target
    
    # Add back query string if present
    if request.query_string:
        target += ("?" + request.query_string.decode())

    headers = {}
    for k, v in request.headers:
        if k.lower() not in ["host", "content-length", "cf-connecting-ip"]:
            headers[k] = v

    # Good user agent (some sites block default Python UA)
    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    try:
        resp = requests.request(
            method=request.method,
            url=target,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,  # We handle redirects manually
            stream=True,
            timeout=30
        )
    except Exception as e:
        return f"<h1>Blocked or down</h1><p>{str(e)}</p>", 502

    # Handle redirects properly inside proxy
    if 300 <= resp.status_code < 400 and "location" in resp.headers:
        location = resp.headers["location"]
        if location.startswith("/"):
            location = urlparse(target).scheme + "://" + urlparse(target).netloc + location
        return redirect("/proxy/" + location)

    # Safely decompress
    content = b""
    try:
        for chunk in resp.iter_content(8192):
            content += chunk
    except:
        return "Stream failed", 502

    # Decompress if needed
    if resp.headers.get("content-encoding") == "br":
        try:
            import brotli
            content = brotli.decompress(content)
        except:
            pass  # ignore brotli errors
    elif resp.headers.get("content-encoding") == "gzip":
        import gzip
        try:
            content = gzip.decompress(content)
        except:
            pass

    headers_out = {}
    for k, v in resp.headers.items():
        if k.lower() not in ["content-encoding", "transfer-encoding", "content-length", "set-cookie"]:
            headers_out[k] = v

    # Only rewrite HTML/JS/CSS
    content_type = resp.headers.get("content-type", "")
    if any(x in content_type for x in ["text/html", "javascript", "css"]):
        try:
            text = content.decode("utf-8", errors="ignore")
            
            # Fix all relative URLs
            base = target.split("?")[0].rstrip("/") + "/"
            text = re.sub(r'(href|src|action)=["\']\/', rf'\1="/proxy/{base}', text)
            text = re.sub(r'(href|src|action)=["\']([^\/])', rf'\1="/proxy/{base}\2', text)
            
            # Prevent frames busting
            text = text.replace("window.top", "window.self")
            text = text.replace("window.parent", "window.self")
            
            content = text.encode("utf-8")
            headers_out["content-length"] = str(len(content))
        except:
            pass

    return Response(content, status=resp.status_code, headers=headers_out, content_type=resp.headers.get("content-type"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
