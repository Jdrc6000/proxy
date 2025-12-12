from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import Response
import httpx
from urllib.parse import urlparse

app = FastAPI()

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade"
}

@app.api_route("/proxy", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(request: Request,
                url: str | None = Query(None),
                q: str | None = Query(None),
                u: str | None = Query(None)):

    target = url or q or u
    if not target:
        raise HTTPException(status_code=400, detail="No URL provided.")

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS allowed.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS allowed.")

    try:
        # Read body
        body = await request.body()

        # Forward headers except dangerous ones
        forward_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            upstream = await client.request(
                method=request.method,
                url=url,
                content=body,
                headers=forward_headers
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream fetch error: {exc}")

    # Strip hop-by-hop headers on the way back
    response_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in HOP_BY_HOP
    }

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers
    )
