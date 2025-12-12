from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import re

app = FastAPI()

client = httpx.AsyncClient(http2=True, follow_redirects=True, timeout=30)

def fix_headers(headers):
    exclude = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    return {k: v for k, v in headers.items() if k.lower() not in exclude}

@app.get("/{path:path}")
@app.post("/{path:path}")
async def proxy(request: Request, path: str):
    url = str(request.query_params.get("url", "") or f"https://{path}")

    if url == "https://":
        return Response(content="<h1>Enter a URL</h1><input style='width:600px;padding:10px' placeholder='https://youtube.com'><button onclick=\"location.href='?url='+document.querySelector('input').value\">Go</button>", media_type="text/html")

    try:
        r = await client.request(
            method=request.method,
            url=url,
            headers={k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]},
            content=await request.body(),
            params=request.query_params if not request.query_params.get("url") else {}
        )

        # Let httpx auto-decompress (this is the key!)
        content = r.content

        # Simple link rewriting so clicks stay in proxy
        if "text/html" in r.headers.get("content-type", ""):
            content = re.sub(b'href="/', f'href="/?url={url.rstrip("/")}/'.encode(), r.content, flags=re.I)
            content = re.sub(b"src="/", f'src="/?url={url.rstrip("/")}/'.encode(), content, flags=re.I)
            content = re.sub(b"href=\"//", b'href="/?url=https://', content)
            content = re.sub(b"src=\"//", b'src="/?url=https://', content)

        return StreamingResponse(
            iter([content]),
            status_code=r.status_code,
            headers=fix_headers(r.headers),
            media_type=r.headers.get("content-type", "application/octet-stream")
        )
    except Exception as e:
        return Response(f"Proxy error: {str(e)}", status_code=502)
