import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


output_dir = Path(os.environ["OUTPUT_DIR"])
if not output_dir.is_dir():
    raise ValueError(f"Output directory {output_dir} does not exist")


app = FastAPI()
app.mount("/screenshots", StaticFiles(directory=output_dir), name="screenshots")


@app.get("/api/screenshot/{id}")
async def get_screenshot(id: int):
    file_path = f"screenshots/screenshot_{id}.png"
    return FileResponse(file_path)
