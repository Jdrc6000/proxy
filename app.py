from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
import httpx
from urllib.parse import urlparse

app = FastAPI()

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade"
}

@app.api_route("/proxy", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(request: Request):
    # accept url, q, or u as the target URL
    qp = request.query_params
    target = qp.get("url") or qp.get("q") or qp.get("u")
    if not target:
        raise HTTPException(status_code=400, detail="Missing target URL. Provide ?url=... (or ?q=... / ?u=...)")

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https allowed.")

    try:
        body = await request.body()
        forward_headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            upstream = await client.request(
                method=request.method,
                url=target,
                content=body,
                headers=forward_headers,
                params=request.query_params  # optional: forward other query params if you want
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream fetch error: {exc}")

    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)
