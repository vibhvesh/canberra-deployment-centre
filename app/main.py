import os
import secrets
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

ROOT = Path(os.getenv("CANBERRA_ROOT", "/opt/canberra")).resolve()
UPLOADS = ROOT / "uploads"
SHARED = ROOT / "shared"
USERNAME = os.getenv("CANBERRA_USERNAME", "root")
PASSWORD = os.getenv("CANBERRA_PASSWORD", "")
MAX_UPLOAD_MB = int(os.getenv("CANBERRA_MAX_UPLOAD_MB", "2048"))
ALLOWED_IPS = {v.strip() for v in os.getenv("CANBERRA_ALLOWED_IPS", "").split(",") if v.strip()}
CATEGORIES = ("logs/system", "logs/application", "logs/docker", "logs/debug",
              "code", "zip-packages", "datasets", "audio", "models", "backups", "temporary")

app = FastAPI(title="Canberra Deployment Centre", docs_url=None, redoc_url=None)
basic = HTTPBasic()


def require_root(request: Request, credentials: HTTPBasicCredentials = Depends(basic)):
    peer = request.client.host if request.client else ""
    if ALLOWED_IPS and peer not in ALLOWED_IPS:
        raise HTTPException(403, "Source IP not allowed")
    valid = secrets.compare_digest(credentials.username, USERNAME)
    valid = valid and bool(PASSWORD) and secrets.compare_digest(credentials.password, PASSWORD)
    if not valid:
        raise HTTPException(HTTP_401_UNAUTHORIZED, "Invalid root console credentials",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(400, "Invalid path")
    return candidate


def audit(event: str, detail: str = ""):
    folder = ROOT / "audit"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "console.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now().astimezone().isoformat()} | {event} | {detail[:500]}\n")


@app.on_event("startup")
def startup():
    for folder in (UPLOADS, SHARED, ROOT / "audit", ROOT / "projects", ROOT / "tools"):
        folder.mkdir(parents=True, exist_ok=True)
    for category in CATEGORIES:
        (UPLOADS / category).mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
def home(user: str = Depends(require_root)):
    usage = shutil.disk_usage(ROOT)
    options = "".join(f'<option value="{c}">{c}</option>' for c in CATEGORIES)
    return f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canberra Deployment Centre</title><style>
body{{font:15px system-ui;background:#101827;color:#edf2f7;margin:0;padding:22px}}
main{{max-width:1000px;margin:auto}}.card{{background:#1b293b;border:1px solid #34445a;border-radius:12px;padding:16px;margin:12px 0}}
h1{{font-size:24px}}h2{{font-size:18px}}input,select,button{{padding:10px;border-radius:7px;border:1px solid #506078;margin:5px 0;max-width:100%}}
button{{background:#2563eb;color:white;border:0;cursor:pointer}}a{{color:#93c5fd}}small{{color:#aab8ca}}code{{color:#a7f3d0}}
</style></head><body><main><h1>Canberra Deployment Centre</h1>
<small>Root-controlled server console · HTTP port 1101</small>
<div class="card"><h2>Storage</h2><p>Total: {usage.total//(1024**3)} GB · Free: {usage.free//(1024**3)} GB</p>
<a href="/api/status">System status</a> · <a href="/files">Shared folders</a> · <a href="/uploads">Upload browser</a></div>
<div class="card"><h2>Upload files</h2><form action="/upload" method="post" enctype="multipart/form-data">
<select name="category">{options}</select><input type="file" name="file" required><button>Upload</button></form>
<small>Files go into /opt/canberra/uploads/ under the selected category.</small></div>
<div class="card"><h2>Create shared folder</h2><form action="/folder" method="post">
<input name="folder" placeholder="e.g. CAI/releases" required><button>Create folder</button></form>
<small>Root-console only: /opt/canberra/shared/</small></div>
<div class="card"><h2>Server diagnostics</h2><form action="/command" method="post"><select name="command">
<option value="status">System status</option><option value="disk">Disk usage</option>
<option value="memory">Memory usage</option><option value="docker">Docker containers</option>
<option value="services">Canberra services</option><option value="uptime">Uptime</option></select>
<button>Run</button></form><small>Only fixed diagnostic commands are enabled; no unrestricted web shell.</small></div>
<div class="card"><h2>Server paths</h2><code>/opt/canberra/uploads/</code><br><code>/opt/canberra/shared/</code><br>
<code>/opt/canberra/projects/</code><br><code>/opt/canberra/tools/</code></div></main></body></html>"""


@app.get("/api/status")
def status(user: str = Depends(require_root)):
    usage = shutil.disk_usage(ROOT)

    def output(args):
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=8)
            return (result.stdout + result.stderr)[-12000:]
        except Exception as exc:
            return str(exc)

    return {"hostname": socket.gethostname(), "root": str(ROOT),
            "disk_bytes": {"total": usage.total, "used": usage.used, "free": usage.free},
            "memory": output(["free", "-h"]), "uptime": output(["uptime"]),
            "docker": output(["docker", "ps", "--format", "{{.Names}}  {{.Status}}"])}


@app.post("/upload")
async def upload(category: str = Form(...), file: UploadFile = File(...),
                 user: str = Depends(require_root)):
    if category not in CATEGORIES:
        raise HTTPException(400, "Unknown upload category")
    directory = safe_path(UPLOADS, category)
    directory.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "upload.bin").name
    if filename in ("", ".", ".."):
        raise HTTPException(400, "Invalid filename")
    destination = directory / filename
    if destination.exists():
        destination = directory / f"{destination.stem}_{secrets.token_hex(4)}{destination.suffix}"
    size = 0
    try:
        with destination.open("xb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"Upload exceeds {MAX_UPLOAD_MB} MB limit")
                stream.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    audit("UPLOAD", f"{destination} bytes={size}")
    return RedirectResponse(url=f"/uploads?path={category}", status_code=303)


def listing(root: Path, path: str, title: str, route: str):
    folder = safe_path(root, path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(404, "Folder not found")
    rows = []
    for item in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        relative = item.relative_to(root).as_posix()
        if item.is_dir():
            rows.append(f'<li>📁 <a href="/{route}?path={relative}">{item.name}/</a></li>')
        else:
            area = "uploads" if route == "uploads" else "shared"
            rows.append(f'<li>📄 <a href="/download?area={area}&path={relative}">{item.name}</a> '
                        f'<small>({item.stat().st_size} bytes)</small></li>')
    parent = Path(path).parent.as_posix() if path else ""
    back = f'<a href="/{route}?path={parent}">⬅ Parent</a>' if path else ""
    return f'<html><body style="font:16px system-ui;max-width:900px;margin:30px auto"><h2>{title}: /{path}</h2>{back}<ul>{"".join(rows)}</ul><a href="/">Home</a></body></html>'


@app.get("/uploads", response_class=HTMLResponse)
def uploads(path: str = "", user: str = Depends(require_root)):
    return listing(UPLOADS, path, "Uploads", "uploads")


@app.get("/files", response_class=HTMLResponse)
def files(path: str = "", user: str = Depends(require_root)):
    return listing(SHARED, path, "Shared folders", "files")


@app.get("/download")
def download(area: str, path: str, user: str = Depends(require_root)):
    root = UPLOADS if area == "uploads" else SHARED if area == "shared" else None
    if root is None:
        raise HTTPException(400, "Invalid area")
    target = safe_path(root, path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    audit("DOWNLOAD", str(target))
    return FileResponse(target, filename=target.name)


@app.post("/folder")
def create_folder(folder: str = Form(...), user: str = Depends(require_root)):
    clean = folder.strip().strip("/")
    if not clean or any(part in ("", ".", "..") for part in clean.split("/")):
        raise HTTPException(400, "Invalid folder path")
    target = safe_path(SHARED, clean)
    target.mkdir(parents=True, exist_ok=False)
    audit("CREATE_FOLDER", str(target))
    return RedirectResponse(url="/files", status_code=303)


@app.post("/command", response_class=HTMLResponse)
def command(command: str = Form(...), user: str = Depends(require_root)):
    commands = {
        "status": ["bash", "-lc", "hostname; uptime; uname -a"],
        "disk": ["df", "-h"], "memory": ["free", "-h"], "docker": ["docker", "ps", "-a"],
        "services": ["systemctl", "list-units", "--type=service", "--state=running", "canberra*"],
        "uptime": ["uptime"],
    }
    if command not in commands:
        raise HTTPException(400, "Command not permitted")
    try:
        result = subprocess.run(commands[command], capture_output=True, text=True, timeout=15)
        result_text = (result.stdout + "\n" + result.stderr)[-20000:]
    except Exception as exc:
        result_text = str(exc)
    audit("DIAGNOSTIC_COMMAND", command)
    return f'<html><body style="font:14px monospace;white-space:pre-wrap;margin:24px"><a href="/">Home</a><hr>{result_text}</body></html>'
