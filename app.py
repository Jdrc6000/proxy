from flask import Flask, request, Response
import requests
import re
from urllib.parse import urlparse, urljoin

app = Flask(__name__)

def rewrite_content(content, target_url, proxy_base):
    """Rewrite links in HTML to stay within the proxy."""
    base_url = urlparse(target_url).scheme + '://' + urlparse(target_url).netloc
    # Rewrite absolute URLs
    content = re.sub(r'(href|src|action)=["\']([^"\']+)["\']', lambda m: rewrite_link(m, base_url, proxy_base), content)
    # Rewrite relative URLs
    content = re.sub(r'(href|src|action)=["\']/([^"\']*)["\']', lambda m: f'{m.group(1)}="{proxy_base}/{urlparse(target_url).netloc}/{m.group(2)}"', content)
    return content

def rewrite_link(match, base_url, proxy_base):
    attr = match.group(1)
    link = match.group(2)
    if link.startswith('http'):
        parsed = urlparse(link)
        return f'{attr}="{proxy_base}/{parsed.netloc}{parsed.path}{"?" + parsed.query if parsed.query else ""}"'
    elif link.startswith('//'):
        return f'{attr}="{proxy_base}/{link[2:]}"'
    else:
        full_link = urljoin(base_url, link)
        parsed = urlparse(full_link)
        return f'{attr}="{proxy_base}/{parsed.netloc}{parsed.path}{"?" + parsed.query if parsed.query else ""}"'

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def proxy(path):
    proxy_base = request.host_url.rstrip('/')  # e.g., https://jdrc6000.pythonanywhere.com
    target_url = request.args.get("url") or f"https://{path}"

    if not target_url or target_url == "https://":
        return """
        <title>Proxy</title>
        <h2>Enter URL to Proxy:</h2>
        <form method="GET">
            <input name="url" placeholder="https://www.google.com" style="width:500px;padding:10px;font-size:18px">
            <button type="submit" style="padding:10px 20px;font-size:18px">Proxy It</button>
        </form>
        <p>Or append after /: yourapp.pythonanywhere.com/www.google.com/search?q=whatever</p>
        """

    headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'content-length']}
    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,
            timeout=30
        )

        response_headers = dict(resp.headers)
        response_headers.pop('Content-Encoding', None)  # Let Flask handle
        response_headers.pop('Transfer-Encoding', None)

        if 'text/html' in resp.headers.get('content-type', ''):
            # Rewrite HTML content
            content = resp.content.decode('utf-8', errors='ignore')
            content = rewrite_content(content, target_url, request.script_root)
            return Response(content, status=resp.status_code, headers=response_headers)
        else:
            # Stream non-HTML (images, JS, etc.)
            def generate():
                for chunk in resp.iter_content(1024):
                    yield chunk
            return Response(generate(), status=resp.status_code, headers=response_headers)

    except Exception as e:
        return f"<h1>Proxy Error</h1><p>{str(e)}</p><p>Check URL format or try a different site. If free account, site must be whitelisted.</p>", 502

if __name__ == "__main__":
    app.run()
