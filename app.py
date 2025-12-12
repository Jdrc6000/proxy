# app.py (or main.py / index.py – whatever your platform expects)
from flask import Flask, Request, Response, request
import requests
import brotli
import gzip

app = Flask(__name__)

# List of sites that force brotli – we have to decompress manually
def decompress(body: bytes, encoding: str) -> bytes:
    if encoding == "br":
        return brotli.decompress(body)
    if encoding in ["gzip", "deflate"]:
        return gzip.decompress(body)
    return body

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def proxy(path):
    url = request.args.get("url") or f"https://{path}"

    if not url.startswith("http"):
        url = "https://" + url

    # Show a tiny index page if no URL
    if url == "https://":
        return '''
        <title>Proxy</title><h2>Working proxy (brotli fixed)</h2>
        <form><input name="url" placeholder="https://youtube.com" style="width:600px;padding:12px;font-size:20px">
        <button style="padding:12px 30px;font-size:20px">Go</button></form>
        <p>Or just visit yourapp.koyeb.app/youtube.com</p>
        '''

    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"},  # ← important: ask for no compression
            cookies=request.cookies,
            allow_redirects=True,
            stream=False,
            timeout=30
        )

        # Force no compression from upstream (best solution)
        content = r.content
        headers = dict(r.headers)

        # If they still sent compressed data, decompress it
        encoding = headers.get("content-encoding", "").lower()
        if "br" in encoding or "gzip" in encoding or "deflate" in encoding:
            content = decompress(content, encoding.split(",")[0].strip())

        # Remove encoding headers so browser doesn't try to decompress again
        headers.pop("content-encoding", None)
        headers.pop("transfer-encoding", None)
        headers["content-length"] = str(len(content))

        # Very simple link rewriting so the proxy stays working
        if "text/html" in headers.get("content-type", ""):
            content = content.decode("utf-8", errors="ignore")
            content = content.replace('href="//', 'href="https://')
            content = content.replace("href='/", f'href="/?url={url.rstrip("/")}/')
            content = content.replace('src="/', f'src="/?url={url.rstrip("/")}/')
            content = content.encode("utf-8")

        return Response(content, status=r.status_code, headers=headers)

    except Exception as e:
        return f"<h1>Error</h1>{str(e)}", 502

if __name__ == "__main__":
    app.run()
