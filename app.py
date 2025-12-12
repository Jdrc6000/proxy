from flask import Flask, request, Response
import requests
import re

app = Flask(__name__)

# List of headers to forward (important ones)
def get_headers():
    headers = {}
    for name, value in request.headers:
        if name.lower() in ["host", "content-length", "cf-connecting-ip"]:
            continue
        headers[name] = value
    return headers

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def proxy(path):
    target_url = request.args.get("url") or f"https://{path}"
    
    # If someone just visits your proxy root, show a simple form
    if not target_url or target_url == "https://":
        return """
        <title>Free Proxy</title>
        <h2>Enter URL:</h2>
        <form>
            <input name="url" placeholder="https://youtube.com" style="width:500px;padding:10px;font-size:18px">
            <button type="submit" style="padding:10px 20px;font-size:18px">Go</button>
        </form>
        <p>Or just type after / → yoursite.pythonanywhere.com/google.com</p>
        """

    try:
        resp = requests.get(
            target_url,
            headers=get_headers(),
            cookies=request.cookies,
            allow_redirects=True,
            stream=True,
            timeout=30
        )

        # Fix links in HTML so they stay inside the proxy
        content = resp.content.decode('utf-8', errors='ignore')
        content = content.replace('href="/', f'href="/{path}?url={target_url.rstrip("/")}"/'.replace('//', '/'))
        content = content.replace('src="/', f'src="/{path}?url={target_url.rstrip("/")}"/'.replace('//', '/'))
        content = re.sub(r'href="(?!http|//)', f'href="/?url={target_url}', content)
        content = re.sub(r'src="(?!http|//)', f'src="/?url={target_url}', content)

        return Response(content, status=resp.status_code, content_type=resp.headers.get('content-type', 'text/html'))

    except Exception as e:
        return f"<h1>Error</h1><p>{str(e)}</p><p>Try again or different site.</p>", 502

if __name__ == "__main__":
    app.run()
