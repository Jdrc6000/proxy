from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlparse, urljoin
import httpx
import re
from bs4 import BeautifulSoup

app = FastAPI(title="Koyeb URL Proxy")
templates = Jinja2Templates(directory="templates")

# Optional: serve a small static index page
app.mount("/static", StaticFiles(directory="static"), name="static")

# Simple home page
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Koyeb Proxy</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {font-family: system-ui; text-align: center; padding: 50px; background: #0f0f23; color: #fff;}
            input {width: 80%; padding: 15px; font-size: 18px; margin: 20px;}
            button {padding: 15px 30px; font-size: 18px; background:#00ff9d; border:none; cursor:pointer;}
        </style>
    </head>
    <body>
        <h1>Koyeb Proxy</h1>
        <form action="/proxy" method="get">
            <input type="url" name="url" placeholder="https://example.com" required>
            <br>
            <button type="submit">Go</button>
        </form>
    </body>
    </html>
    """
    return HTMLResponse(html)

# Main proxy endpoint
@app.get("/proxy")
async def proxy(url: str, request: Request):
    if not url.startswith("http"):
        url = "https://" + url

    parsed_target = urlparse(url)
    if not parsed_target.scheme or not parsed_target.netloc:
        raise HTTPException(400, "Invalid URL")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        try:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; KoyebProxy/1.0)"})
            r.raise_for_status()
        except httpx.RequestError as e:
            raise HTTPException(502, f"Failed to reach target: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, f"Target returned {e.response.status_code}")

    content_type = r.headers.get("content-type", "")
    proxy_base = str(request.base_url) + "proxy?url=" + httpx.URL(url).encode()

    # If it's HTML, rewrite links so the proxy stays active
    if "text/html" in content_type or "application/xhtml+xml" in content_type:
        soup = BeautifulSoup(r.text, "html.parser")

        # Rewrite common attributes
        for tag in soup.find_all(href=True):
            tag["href"] = urljoin(url, tag["href"])
            if not tag["href"].startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            tag["href"] = proxy_base + tag["href"]

        for tag in soup.find_all(src=True):
            tag["src"] = urljoin(url, tag["src"])
            tag["src"] = proxy_base + tag["src"]

        for tag in soup.find_all(srcset=True):
            sources = [s.strip() for s in tag["srcset"].split(",")]
            new_sources = []
            for s in sources:
                if " " in s:
                    src, desc = s.split(" ", 1)
                    new_sources.append(proxy_base + urljoin(url, src) + " " + desc)
                else:
                    new_sources.append(proxy_base + urljoin(url, s))
            tag["srcset"] = ", ".join(new_sources)

        # Handle CSS @import and url()
        if soup.style:
            soup.style.string = rewrite_css_urls(soup.style.string, url, proxy_base)
        for style_tag in soup.find_all(style=True):
            style_tag["style"] = rewrite_css_urls(style_tag["style"], url, proxy_base)

        content = str(soup)
    else:
        content = r.content

    # Stream non-HTML content (videos, images, downloads)
    if not ("text/html" in content_type or "text/css" in content_type or "javascript" in content_type):
        def iter_content():
            yield from r.iter_bytes(chunk_size=1024*64)
        return StreamingResponse(iter_content(), media_type=content_type, headers={"Content-Disposition": r.headers.get("content-disposition", "")})

    # For CSS/JS that might contain absolute URLs
    if "text/css" in content_type:
        content = rewrite_css_urls(r.text, url, proxy_base)
    if "javascript" in content_type or "application/json" in content_type:
        content = rewrite_js_urls(r.text, url, proxy_base)

    return Response(content=content, media_type=content_type or "text/plain")

def rewrite_css_urls(css: str, base_url: str, proxy_base: str):
    if not css:
        return css
    def replace_url(match):
        u = match.group(1).strip("'\"")
        abs_url = urljoin(base_url, u)
        return f"url('{proxy_base}{abs_url}')"
    return re.sub(r"url\(['\"]?(.*?)['\"]?\)", replace_url, css)

def rewrite_js_urls(js: str, base_url: str, proxy_base: str):
    # Very light JS URL rewriting (won't catch everything, but helps)
    def repl(m):
        return m.group(1) + proxy_base + urljoin(base_url, m.group(2))
    js = re.sub(r"([=,\s\('\"])(\s*['\"]?(https?:\/\/[^'\"]+?)['\"]?)", repl, js)
    return js

# Optional: health check for Koyeb
@app.get("/health")
async def health():
    return {"status": "ok"}
