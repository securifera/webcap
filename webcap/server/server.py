import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from webcap.errors import ScreenshotDirError


output_dir = Path(os.environ["OUTPUT_DIR"])
if not output_dir.is_dir():
    raise ScreenshotDirError(f"Output directory {output_dir} does not exist")

json_dir = output_dir / "json"
if not json_dir.is_dir():
    raise ScreenshotDirError(f"JSON directory {json_dir} does not exist")


# serve screenshot files
app = FastAPI()
app.mount("/screenshots", StaticFiles(directory=output_dir), name="screenshots")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


templates_dir = Path(__file__).parent / "templates"
print(f"Resolved templates directory: {templates_dir}")

# serve root page
templates = Jinja2Templates(directory=templates_dir)


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
