from flask import Flask, request, Response, redirect, url_for
import requests
import re
from urllib.parse import urlparse, urljoin

app = Flask(__name__)

# Domains you want to allow (add more if you want)
ALLOWED_DOMAINS = ["youtube.com", "youtu.be", "google.com", "discord.com", "spotify.com", "netflix.com"]

def fix_url(url, base):
    if not url:
        return url
    if url.startswith("http"):
        return url
    return urljoin(base, url)

@app.route("/", methods=["GET", "POST"])
def index():
    url = request.args.get("q") or request.form.get("q")
    if not url:
        return '''
        <title>Proxy</title><center><h1>Koyeb Proxy</h1>
        <form><input name="q" placeholder="https://youtube.com" style="width:80%;padding:15px;font-size:20px">
        <button style="padding:15px">Go</button></form>
        <p>Or visit https://your-app.koyeb.app/https://youtube.com</p>
        '''
    return redirect(url_for("proxy", path=url.lstrip("https://").lstrip("http://")))

@app.route("/<path:path>")
def proxy(path):
    target = request.args.get("q")
    if not target:
        target = "https://" + path.split("?")[0]
        if not any(domain in target.lower() for domain in ["."]):  # fallback
            target = "https://" + path

    # Force https
    if not target.startswith("http"):
        target = "https://" + target

    headers = {k: v for k, v in request.headers if k.lower() not in ["host", "cf-connecting-ip"]}
    headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    try:
        r = requests.get(target, headers=headers, stream=True, timeout=30, allow_redirects=True)
    except:
        return "<h1>Request failed – bad URL or site blocked your IP</h1>", 502

    # Properly handle compressed content
    content = r.content
    if r.headers.get("Content-Encoding") == "gzip":
        import gzip
        content = gzip.decompress(content)
    elif r.headers.get("Content-Encoding") == "br":
        import brotli
        content = brotli.decompress(content)

    content_type = r.headers.get("Content-Type", "")
    if "text/html" in content_type or "application/javascript" in content_type or "text/css" in content_type:
        text = content.decode("utf-8", errors="ignore")

        # Rewrite all URLs so they stay inside the proxy
        base_url = target.rstrip("/") + "/"
        text = re.sub(r'(href|src|action)=["\']/(?!/)', lambda m: f'{m.group(1)}="/{base_url.split("/",3)[2] if base_url.split("/",3)[2:] else ""}', text)
        text = re.sub(r'(href|src|action)=["\'](?!https?:|//)', lambda m: m.group(1) + '="https://' + path.split("?")[0] + m.group(2), text)
        text = text.replace('http://', 'https://').replace("window.location", "parent.location")

        content = text.encode("utf-8")

    resp_headers = {}
    for k, v in r.headers.items():
        if k.lower() not in ["content-encoding", "transfer-encoding", "content-length"]:
            resp_headers[k] = v

    return Response(content, status=r.status_code, headers=resp_headers, content_type=r.headers.get("Content-Type"))

if __name__ == "__main__":
    app.run()
