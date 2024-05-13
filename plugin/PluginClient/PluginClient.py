from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6 import QtNetwork
from PySide6.QtNetwork import *
import zipfile
import io
import time
import shutil
import os
import json

class HttpReq(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.onSuccess = None
        self.onFailed = None
        self.m_netAccessManager = QNetworkAccessManager(self)
        # self.m_netReply = None
 
 
    def request(self,httpUrl,sendData,on_success,on_fail):
        # if self.m_netReply is not None:
        #     self.m_netReply.disconnect()
 
        self.onSuccess = on_success
        self.onFailed = on_fail
        # self.onJsonParams = jsonParams
 
        req = QNetworkRequest(QUrl(httpUrl))
        req.setHeader(QNetworkRequest.ContentTypeHeader,"application/json")
 
        senda = QJsonDocument(sendData).toJson()

        reply = self.m_netAccessManager.post(req,senda)
        # self.m_netReply = reply
        
        reply.finished.connect(lambda: self.readData(reply))

    def get(self,httpUrl,on_success,on_fail):
        self.onSuccess = on_success
        self.onFailed = on_fail
        # self.onJsonParams = jsonParams
 
        req = QNetworkRequest(QUrl(httpUrl))

        reply = self.m_netAccessManager.get(req)
        # self.m_netReply = reply
        
        reply.finished.connect(lambda: self.readData(reply))
 
    def readData(self, reply):
        recvData = reply.readAll()

        if reply.error() == QtNetwork.QNetworkReply.NoError:
            data = str(bytes(recvData.data()), encoding="utf-8")
            try:
                result = json.loads(data)
                self.onSuccess(result)
            except Exception as err:
                self.onFailed(data, err)
        else:
            self.onFailed(recvData, "")

    def download(self, httpUrl, sendData, on_success, on_fail):
        self.onSuccess = on_success
        self.onFailed = on_fail

        req = QNetworkRequest(QUrl(httpUrl))
        req.setHeader(QNetworkRequest.ContentTypeHeader,"application/json")
 
        senda = QJsonDocument(sendData).toJson()

        reply = self.m_netAccessManager.post(req,senda)
        # self.m_netReply = reply
        
        reply.finished.connect(lambda: self.__download(reply))

    def __download(self,reply):
        recvData = reply.readAll()
        data = bytes(recvData.data())
        if reply.error() == QtNetwork.QNetworkReply.NoError:
            # data = bytes(recvData.data())
            # self.unzip(data)
            self.onSuccess(data)
        else:
            self.onFailed(data, "")


script_folder_path = os.path.dirname(os.path.split(os.path.realpath(__file__))[0])


def onFail(data, err):
    QMessageBox.warning(None, "更新", f"无法连接到服务器，更新已取消：{err}",QMessageBox.Ok)


def onGetSucc(data):

    # 获取插件目录下所有的插件的名字，除了自己
    local_plugins = os.listdir(script_folder_path)
    local_plugins.remove("PluginClient")

    # 下载列表为数组，插件名
    download_list = []

    plugin_infos = data["plugins"]

    for plugin_info in plugin_infos:
        plugin_name = plugin_info["name"]
        # 如果存在，获取修改时间，如果修改时间小于服务器的（表示服务器是最新的），则加入下载列表
        if plugin_name in local_plugins:
            server_modify_timestamp = plugin_info["modify_timestamp"]
            modify_timestamp = os.path.getmtime(os.path.join(script_folder_path, plugin_name))

            if modify_timestamp < server_modify_timestamp:
                download_list.append(plugin_name)

        # 如果不存在该插件，则加入下载列表，并创建目录
        else:
            download_list.append(plugin_name)
            os.mkdir(os.path.join(script_folder_path, plugin_name))

    if len(download_list) == 0:
        return # 无需更新
    
    # 返回包含对应插件的压缩包
    url = "http://10.192.127.37:8800/update"
    http = HttpReq()
    http.download(url, {"download_list": download_list}, lambda x: onDownloadSucc(x, download_list), onFail)


def onDownloadSucc(data, download_list):
    
    for plugin_name in download_list:
        # 移除插件目录下的内容
        plugin_path = os.path.join(script_folder_path, plugin_name)

        contents = os.listdir(plugin_path)

        for item in contents:
            item_path = os.path.join(plugin_path, item)
            
            # 检查是否为文件，若是则删除
            if os.path.isfile(item_path):
                os.remove(item_path)
            # 若为目录，则递归删除
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)


    # 解压，将压缩包内对应的插件内容放入对应位置
    out_dir = script_folder_path
    zip_file_bytes = io.BytesIO(data)
    with zipfile.ZipFile(zip_file_bytes, "r") as zip_file:
        for fileM in zip_file.namelist():
            zip_file.extract(fileM, out_dir)
            
    # 提示更新完成，重启插件
    QMessageBox.warning(None, "更新",f"插件已更新，请点击菜单 编辑 -> 重新加载脚本插件",QMessageBox.Ok)


def get_plugin_list():

    # 请求插件列表 返回插件名和修改时间

    url = "http://10.192.127.37:8800/list"
    http = HttpReq()
    http.get(url, onGetSucc, onFail)


# get_plugin_list()