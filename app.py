from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from urllib.parse import urlparse, urljoin, quote
import httpx
import re
from bs4 import BeautifulSoup

app = FastAPI()
# Global client for efficiency
client = httpx.AsyncClient(
    follow_redirects=True, 
    timeout=30.0, 
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=20)
)

# Simple homepage
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <title>Koyeb Proxy</title>
    <style>body{font-family:system-ui;background:#111;color:#0f0;margin:40px;text-align:center}
    input,button{padding:15px;font-size:18px;margin:10px;width:90%;max-width:600px}</style>
    <h1>Koyeb Proxy (Full POST Support)</h1>
    <form action="/proxy" method="get">
      <input name="q" placeholder="https://www.google.com" required>
      <button>Go →</button>
    </form>
    <p><small>Now handles cookies, logins, & forms!</small></p>
    """

# Unified proxy endpoint – NOW HANDLES POST/PUT/OPTIONS TOO!
@app.route("/proxy", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "OPTIONS"])
async def proxy(request: Request):
    # Parse query params
    query_params = dict(request.query_params)
    q = query_params.pop("q", None)
    u = query_params.pop("u", None)

    if not q and not u:
        raise HTTPException(400, "Missing q= or u= parameter")

    target_url = u or q
    if not target_url.startswith(("http://", "https://")):
        target_url = "https://" + target_url

    parsed = urlparse(target_url)
    if not parsed.netloc:
        raise HTTPException(400, "Invalid URL")

    # Build proxy prefix for rewriting (use the ORIGINAL q as base)
    base_q = q or u
    proxy_prefix = f"{request.base_url}proxy?q={quote(base_q)}"

    # Forward ALL headers from browser (but clean up proxy-specific ones)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)  # We'll set this dynamically
    headers["User-Agent"] = headers.get("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    headers["Accept"] = headers.get("accept", "*/*")
    headers["Referer"] = target_url + "/" if "referer" not in headers else headers["referer"]
    headers["Origin"] = parsed.scheme + "://" + parsed.netloc

    # Forward body for POST/PUT/PATCH (forms, uploads, etc.)
    body = await request.body()

    try:
        # Use the SAME method as the incoming request
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body if body else None,
            params=query_params if query_params else None  # Forward extra params
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Target site error")
    except Exception as e:
        raise HTTPException(502, f"Proxy error: {str(e)}")

    content_type = resp.headers.get("content-type", "").split(";")[0].lower()
    raw_bytes = resp.content

    # Rewrite HTML (only for GET/HEAD, as POST responses are often JSON/redirects)
    if request.method in ("GET", "HEAD") and content_type in ("text/html", "application/xhtml+xml"):
        text = resp.text
        soup = BeautifulSoup(text, "html.parser")

        # Add <base> for relative URLs
        if soup.head:
            base_tag = soup.new_tag("base", href=target_url.rstrip('/') + "/")
            if soup.head.find("base") is None:
                soup.head.insert(0, base_tag)

        # Rewrite links, scripts, images, forms, etc.
        for attr in ("href", "src", "srcset", "data-src", "poster", "action", "formaction", "data"):
            for tag in soup.find_all(attrs={attr: True}):
                old = tag[attr]
                if old.startswith(("data:", "javascript:", "#", "mailto:", "tel:")) or old.startswith(proxy_prefix):
                    continue
                absolute = urljoin(target_url, old)
                tag[attr] = f"{proxy_prefix}&u={quote(absolute)}"

        # Rewrite inline styles (background:url(), etc.)
        for tag in soup.find_all(style=True):
            tag["style"] = re.sub(
                r'url\s*\(\s*["\']?(.*?)["\']?\s*\)',
                lambda m: f'url("{proxy_prefix}&u={quote(urljoin(target_url, m.group(1)))}")',
                tag["style"]
            )

        # Rewrite forms to POST to proxy
        for form in soup.find_all("form"):
            if form.get("action"):
                form["action"] = f"{proxy_prefix}&u={quote(urljoin(target_url, form['action']))}"

        raw_bytes = str(soup).encode("utf-8")

    # Rewrite CSS
    elif "text/css" in content_type:
        css = resp.text
        css = re.sub(
            r'url\s*\(\s*["\']?(.*?)["\']?\s*\)',
            lambda m: f'url("{proxy_prefix}&u={quote(urljoin(target_url, m.group(1)))}")',
            css
        )
        raw_bytes = css.encode("utf-8")

    # For JS, light rewrite (won't catch dynamic fetches, but helps static ones)
    elif "javascript" in content_type or "application/json" in content_type:
        js = resp.text
        # Basic URL replacement in strings
        js = re.sub(
            r'["\']((?:https?://[^"\']+))["\']',
            lambda m: f'"{proxy_prefix}&u={quote(m.group(1))}"',
            js
        )
        raw_bytes = js.encode("utf-8")

    # OPTIONS for CORS (handles preflight requests)
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, OPTIONS, HEAD",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
                "Access-Control-Max-Age": "86400",
            }
        )

    # Stream the response (works for large files/videos)
    async def stream_content():
        yield raw_bytes

    response_headers = dict(resp.headers)
    response_headers.pop("content-length", None)  # Avoid conflicts
    response_headers["Access-Control-Allow-Origin"] = "*"
    response_headers["X-Frame-Options"] = "ALLOWALL"  # Helps with embeds

    return StreamingResponse(
        stream_content(),
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
        headers=response_headers
    )

# Health check (add /health if needed)
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.on_event("shutdown")
async def shutdown():
    await client.aclose()
