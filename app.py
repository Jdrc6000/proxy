from flask import Flask, request, Response
import requests
import re
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

# Headers to forward (skip junk)
def get_headers():
    headers = {}
    for name, value in request.headers:
        if name.lower() in ["host", "content-length", "cf-connecting-ip"]:
            continue
        headers[name] = value
    headers['User-Agent'] = request.headers.get('User-Agent', 'Mozilla/5.0')
    return headers

def follow_redirects(initial_url, headers, max_redirects=5):
    current_url = initial_url
    for _ in range(max_redirects):
        resp = requests.get(current_url, headers=headers, allow_redirects=False, timeout=30)
        if resp.status_code != 302 and resp.status_code != 301 and resp.status_code != 307:
            return resp, current_url
        location = resp.headers.get('Location')
        if not location:
            return resp, current_url
        # Make relative redirects absolute
        current_url = urljoin(current_url, location)
    return requests.get(current_url, headers=headers, allow_redirects=True, timeout=30), current_url

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def proxy(path):
    # Parse target from query or path
    target_url = request.args.get("url")
    if not target_url:
        if path:
            target_url = f"https://{path}"
        else:
            # Root: simple form
            return """
            <title>Koyeb Proxy</title>
            <h2>Enter URL to Proxy:</h2>
            <form method="GET">
                <input name="url" placeholder="https://google.com" style="width:500px;padding:10px;font-size:18px">
                <button type="submit" style="padding:10px 20px;font-size:18px">Load</button>
            </form>
            <p>Or append to URL: yourapp.koyeb.app/google.com</p>
            """

    if not target_url.startswith(('http://', 'https://')):
        target_url = 'https://' + target_url

    try:
        headers = get_headers()
        resp, final_url = follow_redirects(target_url, headers)

        # For non-HTML, just stream it back (images/CSS/JS)
        content_type = resp.headers.get('content-type', '')
        if not content_type.startswith('text/html'):
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            return Response(
                resp.iter_content(chunk_size=8192),
                status=resp.status_code,
                headers={k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
            )

        # For HTML: fetch, rewrite links to stay in proxy
        content = resp.content.decode('utf-8', errors='ignore')
        base_url = urlparse(final_url).netloc  # e.g., 'www.google.com'

        # Rewrite relative/absolute links
        content = re.sub(r'((?:src|href|action)=["\'])/', r'\1/?url=' + final_url.rstrip('/') + '/?', content)
        content = re.sub(r'((?:src|href|action)=["\'])(?!https?://|/)', r'\1/?url=' + final_url + '/', content)
        # Fix JS fetches too (basic)
        content = re.sub(r'url:\s*["\']/', r'url: "/?url=' + final_url.rstrip('/') + '/?"', content)

        # Set proxy as base for relative stuff
        content = content.replace('<head>', f'<head><base href="/?url={final_url}">')

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        return Response(
            content.encode('utf-8'),
            status=resp.status_code,
            headers={k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
        )

    except Exception as e:
        return f"<h1>Proxy Error</h1><p>{str(e)}</p><p>Target: {target_url}</p><p>Try a different URL.</p>", 502

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
