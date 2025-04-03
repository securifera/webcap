import os
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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


@app.get("/")
async def read_root():
    # Directly serve the HTML file using FileResponse
    return FileResponse(Path(__file__).parent / "templates" / "index.html")
