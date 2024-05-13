import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from typing import List
import uvicorn
import zipfile
import io
from pydantic import BaseModel


class UpdateRequest(BaseModel):
    download_list: List


class PluginItem(BaseModel):
    name: str
    modify_timestamp: float

class ListResponse(BaseModel):
    plugins: List[PluginItem]

app = FastAPI()

@app.post("/update")
async def update(item: UpdateRequest):
    download_list = item.download_list

    current_dir = os.path.split(os.path.realpath(__file__))[0]

    zip_file_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_file_bytes, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:

        for plugin_name in download_list:
            dir_path = os.path.join(current_dir, f"src/{plugin_name}")
            for path, dir_names, filenames in os.walk(dir_path):
                # 去掉目标跟路径，只对目标文件夹下边的文件及文件夹进行压缩
                fpath = path.replace(dir_path, plugin_name)

                for filename in filenames:
                    zip_file.write(os.path.join(path, filename), os.path.join(fpath, filename))

    zip_file_bytes.seek(0)
    return StreamingResponse(zip_file_bytes, media_type="application/zip", headers={
        "Content-Disposition": "attachment;filename=vred-plugin-server.zip"
    })

@app.get("/list")
async def list_plugins():
    current_dir = os.path.split(os.path.realpath(__file__))[0]
    plugin_dir = os.path.join(current_dir, "src")

    plugins = []
    plugin_names = os.listdir(plugin_dir)

    for plugin_name in plugin_names:
        modify_timestamp = os.path.getmtime(os.path.join(plugin_dir, plugin_name))
        plugins.append(PluginItem(name=plugin_name, modify_timestamp=modify_timestamp))

    return ListResponse(plugins=plugins)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8800)
