from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from urllib.parse import urlparse, urljoin, quote
import httpx
import re
from bs4 import BeautifulSoup

app = FastAPI()
client = httpx.AsyncClient(follow_redirects=True, timeout=30.0, limits=httpx.Limits(max_connections=200))

# Simple homepage
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <title>Koyeb Proxy</title>
    <style>body{font-family:system-ui;background:#111;color:#0f0;margin:40px;text-align:center}
    input,button{padding:15px;font-size:18px;margin:10px;width:90%;max-width:600px}</style>
    <h1>Koyeb Proxy (Works on YouTube)</h1>
    <form action="/proxy" method="get">
      <input name="q" placeholder="https://www.youtube.com" required>
      <button>Go →</button>
    </form>
    """

# Main proxy endpoint – FIXED URL HANDLING
@app.get("/proxy")
@app.head("/proxy")  # Needed for some pre-flight checks
async def proxy(request: Request, q: str = None):
    if not q:
        raise HTTPException(400, "Missing q= parameter")

    # Normalize URL
    if not q.startswith(("http://", "https://")):
        q = "https://" + q

    target_url = q.strip()
    parsed = urlparse(target_url)
    if not parsed.netloc:
        raise HTTPException(400, "Invalid URL")

    # Build the prefix the proxy will use for rewriting
    proxy_prefix = f"{request.base_url}proxy?q={quote(target_url)}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": target_url + "/",
    }

    try:
        resp = await client.get(target_url, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="Target site error")
    except Exception as e:
        raise HTTPException(502, f"Proxy error: {str(e)}")

    content_type = resp.headers.get("content-type", "").split(";")[0].lower()
    raw_bytes = resp.content

    # Rewrite HTML
    if content_type in ("text/html", "application/xhtml+xml"):
        text = resp.text

        soup = BeautifulSoup(text, "html.parser")

        # <base> tag to make relative URLs work perfectly
        if soup.head:
            base_tag = soup.new_tag("base", href=target_url + "/")
            soup.head.insert(0, base_tag)

        # Rewrite all common attributes
        for attr in ("href", "src", "srcset", "data-src", "poster", "action", "data"):
            for tag in soup.find_all(attrs={attr: True}):
                old = tag[attr]
                if old.startswith(("data:", "javascript:", "#")) or old.startswith(proxy_prefix):
                    continue
                absolute = urljoin(target_url + "/", old)
                tag[attr] = proxy_prefix + "&u=" + quote(absolute)

        # Handle inline style="background: url(...)"
        for tag in soup.find_all(style=True):
            tag["style"] = re.sub(
                r"url\(['\"]?(.*?)['\"]?\)",
                lambda m: f"url({proxy_prefix}&u={quote(urljoin(target_url + '/', m.group(1)))})",
                tag["style"]
            )

        raw_bytes = str(soup).encode("utf-8")

    # Rewrite CSS files
    elif "text/css" in content_type:
        css = resp.text
        css = re.sub(
            r"url\(['\"]?(.*?)['\"]?\)",
            lambda m: f"url({proxy_prefix}&u={quote(urljoin(target_url + '/', m.group(1)))})",
            css
        )
        raw_bytes = css.encode("utf-8")

    # Stream everything else (videos, images, JS, etc.)
    async def stream():
        yield raw_bytes

    return StreamingResponse(
        stream(),
        media_type=resp.headers.get("content-type", "application/octet-stream"),
        headers={
            "Content-Disposition": resp.headers.get("content-disposition", ""),
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
            "X-Frame-Options": "ALLOWALL",
        }
    )

# Sub-resource proxy (the real magic)
@app.get("/proxy")
@app.head("/proxy")
async def proxy_subresource(request: Request, u: str):
    # This handles all CSS/JS/images fetched after HTML rewrite
    return await proxy(request, q=u)

@app.on_event("shutdown")
async def shutdown():
    await client.aclose()
