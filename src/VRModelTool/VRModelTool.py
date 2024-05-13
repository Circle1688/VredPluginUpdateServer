import uiTools
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6 import QtNetwork
from PySide6.QtNetwork import *
from vrKernelServices import vrdNode, vrdGeometryNode, vrScenegraphTypes, vrdVirtualTouchpadButton, vrdDecoreSettings, vrGeometryTypes, vrMaterialTypes, vrUVTypes
import vrController
import vrFileIO
import csv
import os
import random
import string
import vrScenegraph
import vrOptimize
import vrMaterialPtr
import re
import vrNodePtr
import vrNodeUtils
import vrFieldAccess
import vrGeometryEditor
import vrFileDialog
import vrOSGWidget
import vrCamera
import sys
import json
import hashlib
import math
import zipfile
import io
import time
import shutil

__version__ = 'V2405013 -- VRED-17.0'


def get_icon(icon_name):
    cur_dir = os.path.split(os.path.realpath(__file__))[0]
    return QIcon(os.path.join(cur_dir, f"icon/{icon_name}.png"))
    

class FBXExporter():
    def __init__(self):
        pass

    def export(self, out_path):

        # Preserve camera position before/after export as loading will
        # reset it
        cameraTransform = vrCamera.getActiveCameraNode().getWorldTransform()

        # disable rendering to speed up things
        vrOSGWidget.enableRender(False)
        # disable scenegraph update to speed up things
        vrScenegraph.enableScenegraph(False)

        # Clear undo stack to free deleted nodes that haven't been actually deleted yet
        vrUndoService.clear()

        # 重命名
        self.renameNode_recursive(vrdNode(vrScenegraph.getRootNode()))

        savedvpbPath = vrFileIOService.getFileName()

        # 保存重命名后的文件
        vrFileIOService.saveFile(savedvpbPath)


        # 清理环境
        self.clear_environments()

        vrMaterialService.removeUnusedMaterials()

        # 清理贴图
        self.clearTextures()

        # Removing invalid nodes
        vrOptimize.removeEmptyGeometries(vrScenegraph.getRootNode())
        vrOptimize.removeInvalidTexCoords(vrScenegraph.getRootNode())
        vrOptimize.removeEmptyShells(vrScenegraph.getRootNode())
        vrOptimize.cleanupGroupNodes(vrScenegraph.getRootNode(), True)

        # 三角化
        self.removeNURBS()

        vrFileIOService.saveFile(out_path)

        print('Loading back saved scene...')
        vrFileIO.load([savedvpbPath], vrScenegraph.getRootNode().getParent(), True, False)

        # Restore camera position to what it was before the export
        if cameraTransform is not None:
            vrCamera.getActiveCameraNode().setTransformMatrix(cameraTransform, False)

        vrScenegraph.enableScenegraph(True)  # reenable scenegraph updates
        vrOSGWidget.enableRender(True)  # reenable rendering


    def renameNode_recursive(self, node):
        pattern = r'\W+'
        rep_name = re.sub(pattern, "_", node.getName())
        node.setName(rep_name)
        others = []
        for child in node.getChildren():
            geo = vrdGeometryNode(child)
            if geo.isValid():

                trig_count = geo.getPrimitiveCount()
                vertex_count = geo.getVertexCount()
                center = child.getWorldBoundingBox().getCenter()

                idx = self.unique_idx(trig_count, vertex_count, center.x(), center.y(), center.z())
                geo.setName(rep_name + '_' + idx)
            else:
                others.append(child)

        for other in others:
            self.renameNode_recursive(other)

    def unique_idx(self, trig, vertex, x, y, z):
        serialized = f'{trig}{vertex}{x}{y}{z}'
        output = hashlib.sha256(serialized.encode()).hexdigest()
        return output[:8]



    def clear_environments(self):
        names = ['Studio', 'EnvironmentsTransform']
        nodes = []
        vrNodeService.initFindCache()
        for name in names:
            node = vrNodeService.findNode(name)
            nodes.append(node)
        vrNodeService.clearFindCache()

        for node in nodes:
            for childnode in node.getChildren():
                vrScenegraph.deleteNode(vrNodePtr.toNode(childnode.getObjectId()), True)

    def clearTextures(self):
        mats = vrMaterialPtr.getAllMaterials()
        data = ['diffuse', 'glossy', 'specular', 'incandescence', 'bump', 'transparency', 'scatter', 'roughness',
                'displacement', 'fresnel', 'rotation', 'indexOfRefraction', 'specularBump', 'metallic',
                'ambientOcclusion']
        for mat in mats:
            for fname in data:
                colorComponentData = vrFieldAccess.vrFieldAccess(mat.fields().getFieldContainer('colorComponentData'))
                Component = vrFieldAccess.vrFieldAccess(colorComponentData.getFieldContainer(fname + 'Component'))
                Component.setBool("useTexture", False)

    
    def removeNURBS(self):
        """
        Travels the entire hierarchy, finds NURBS nodes and converts them. Also temporarily stores
        the node's transform in a sibling node and restores it back after conversion, since VRED doesn't
        maintain it during the conversion for some reason
        """

        def removeNURBSRecursive(node, nurbsNodes):
            for index in range(node.getNChildren()):
                child = node.getChild(index)

                # Nodes with this attachment *may* be NURBs, but all NURBs have this attachment
                if self.isNURBS(child):
                    nurbsNodes.append(child)
                else:
                    removeNURBSRecursive(child, nurbsNodes)

        nodesToFix = []
        removeNURBSRecursive(vrScenegraph.getRootNode(), nodesToFix)

        # print('Removing NURBS from nodes ' + str([a.getName() for a in nodesToFix]))

        count = 0
        for node in nodesToFix:
            nodeOrigName = node.getName()
            parent = node.getParent()

            newNode = vrScenegraph.createNode('Transform3D', str(nodeOrigName) + "_Temp", parent)

            vrScenegraph.copyTransformation(node, newNode)

            v2node = vrNodeService.getNodeFromId(node.getID())
            # vrOptimize.removeNURBS(node)
            vrScenegraphService.convertToMesh([v2node])
            count += 1

            vrScenegraph.copyTransformation(newNode, node)

            newNode.sub()

        return count
    
    def isNURBS(self, node):
        if node is not None:
            nodeType = node.getType()
            if nodeType == 'Surface':
                return True
            elif nodeType == 'Geometry':
                nodeFields = node.fields()
                if nodeFields.hasField('geometryType'):
                    return nodeFields.getUInt32("geometryType") == 2
   

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

 
class HideDialog(QDialog):
    def __init__(self, parent=None):
        super(HideDialog, self).__init__(parent=parent)

    def closeEvent(self, event):
        event.ignore()
        self.hide()

class IconLabel(QLabel):
    def __init__(self, icon:str, size:int=26, parent=None):
        super(IconLabel, self).__init__(parent=parent)
        pixmap = get_icon(icon).pixmap(QSize(size, size))
        self.setPixmap(pixmap)

class FileInfoItem(QWidget):
    def __init__(self, title:str, value:str = "", parent=None):
        super(FileInfoItem, self).__init__(parent=parent)
        hbox = QHBoxLayout(self)

        _title = QLabel(title)
        self._value = QLabel(value)
        hbox.addWidget(_title)
        hbox.addStretch()
        hbox.addWidget(self._value)
    
    def setValue(self, value):
        self._value.setText(value)

    def setIcon(self, icon):
        pixmap = get_icon(icon).pixmap(QSize(26, 26))
        self._value.setPixmap(pixmap)

class FileInfo(QWidget):
    def __init__(self, parent=None):
        super(FileInfo, self).__init__(parent=parent)
        vbox = QVBoxLayout(self)
        hbox = QHBoxLayout()

        self.ic = QLabel()
        self.filename = QLabel()
        hbox.addSpacing(10)
        hbox.addWidget(self.ic)
        hbox.addWidget(self.filename)
        hbox.addStretch()

        self._data = FileInfoItem("修改日期")
        self._create = FileInfoItem("创建者")
        self._modifi = FileInfoItem("修改者")
        self._filesize = FileInfoItem("文件大小")
        vbox.addLayout(hbox)
        vbox.addWidget(self._data)
        vbox.addWidget(self._create)
        vbox.addWidget(self._modifi)
        vbox.addWidget(self._filesize)
        vbox.addStretch()


    def setInfo(self, name, data, create, modifi, filesize):
        if ".usd" in name:
            pixmap = get_icon("usd").pixmap(QSize(30, 30))
        else:
            pixmap = get_icon("folder").pixmap(QSize(32, 32))
        self.ic.setPixmap(pixmap)
        self.filename.setText(name)
        self._data.setValue(data)
        self._create.setValue(create)
        self._modifi.setValue(modifi)

        if filesize >= (1024 * 1024 * 1024):
            self._filesize.setValue(f"{round(filesize / (1024 * 1024 * 1024), 2)} GB")
        elif filesize >= (1024 * 1024):
            self._filesize.setValue(f"{round(filesize / (1024 * 1024), 2)} MB")
        else:
            self._filesize.setValue(f"{round(filesize / 1024, 2)} KB")

        # print(filestat)
        # if filestat == "OK":
        #     self._filestat.setIcon("normal")
        # elif filestat == "ERROR_LOCKED":
        #     self._filestat.setIcon("lock")
        # else:
        #     self._filestat.setIcon("unkown")

class ProgressDialog():
    def __init__(self, info):
        self.progress_dialog = QProgressDialog()
        self.progress_dialog.setWindowTitle("等待中...")
        self.progress_dialog.setLabelText(info)
        self.progress_dialog.setRange(0,0)
        self.progress_dialog.setWindowModality(Qt.ApplicationModal)
        self.progress_dialog.setWindowFlags(Qt.FramelessWindowHint)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.resize(320, 100)
        self.progress_dialog.show()

    def close(self):
        self.progress_dialog.close()

    def setValue(self, value):
        self.progress_dialog.setRange(0,1)
        self.progress_dialog.setValue(value)
        
class OmniBrowser(HideDialog):
    tree_isDouble = False
    list_isDouble = False
    def __init__(self, parent=None):
        super(OmniBrowser, self).__init__(parent=parent)
        
        
        self.progress_dialog = None

        self._fetch_module = FetchMaterial()

        self.setupUi()

        self.restore_to_default()

    def restore_to_default(self):
        self.current_expand_item = None
        self.info = {}  # 存储信息
        self.list_node = {}
        self.save_file_path = ""
        self.connected = False
        self.select_file_path = ""

        self.list_view.clear()
        self.tree_view.clear()
        self._dir.setText("")
        self.fileinfo.setVisible(False)
        self.save_btn.setEnabled(False)
        self.sync_material_btn.setVisible(False)
        self.progressbar.setVisible(False)

    def setupUi(self):

        self.tree_view = QTreeWidget()
        self.tree_view.setColumnCount(2)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.hideColumn(1)
        self.list_view = QListWidget()
        self.list_view.setFlow(QListView.LeftToRight)
        self.list_view.setResizeMode(QListView.Adjust)
        self.list_view.setGridSize(QSize(200, 200))
        self.list_view.setSpacing(300)
        self.list_view.setViewMode(QListView.IconMode)
        self.list_view.setIconSize(QSize(120, 120))
        # self.list_view.setWordWrap(True)
        # self.list_view.setTextElideMode(Qt.ElideNone)

        
        vbox_fileinfo = QVBoxLayout()
        self.fileinfo = FileInfo()

        self.sync_material_btn = QPushButton("同步Omniverse材质")
        self.sync_material_btn.setIcon(get_icon("icon_omniverse_panel"))
        vbox_fileinfo.addWidget(self.fileinfo)
        vbox_fileinfo.addWidget(self.sync_material_btn)
        vbox_fileinfo.addStretch()
        self.sync_material_btn.setVisible(False)

        vbox = QVBoxLayout(self)

        hbox = QHBoxLayout()
        hbox.addWidget(self.tree_view)
        hbox.addWidget(self.list_view)
        hbox.addLayout(vbox_fileinfo)

        hbox.setStretchFactor(self.tree_view, 1)
        hbox.setStretchFactor(self.list_view, 3)
        hbox.setStretchFactor(vbox_fileinfo, 1)

        name = QLabel("服务器")
        self._input = QLineEdit("10.192.127.37")

        hbox1 = QHBoxLayout()
        hbox1.addWidget(IconLabel("server", 22))
        hbox1.addWidget(name)
        hbox1.addWidget(self._input)

        connect_btn = QPushButton("连接")
        connect_btn.setIcon(get_icon("connect"))
        hbox1.addWidget(connect_btn)
        
        vbox.addLayout(hbox1)
        self._dir = QLabel("")
        hbox3 = QHBoxLayout()
        hbox3.addWidget(IconLabel("url"))
        hbox3.addWidget(self._dir)
        hbox3.addStretch()
        vbox.addLayout(hbox3)
        vbox.addLayout(hbox)

        self.progressbar = QProgressBar()
        self.progressbar.setFixedHeight(10)
        self.progressbar.setRange(0, 0)
        self.progressbar.setVisible(False)
        vbox.addWidget(self.progressbar)

        name1 = QLabel("文件名")
        self.filename_input = QLineEdit()
        name2 = QLabel(".usd")

        hbox2 = QHBoxLayout()
        hbox2.addWidget(IconLabel("file"))
        hbox2.addWidget(name1)
        hbox2.addWidget(self.filename_input)
        hbox2.addWidget(name2)

        self.save_btn = QPushButton("保存")
        self.save_btn.setIcon(get_icon("save"))
        self.save_btn.setEnabled(False)
        hbox2.addWidget(self.save_btn)
        vbox.addLayout(hbox2)

        connect_btn.clicked.connect(self.connect2server)
        self.tree_view.itemExpanded.connect(self.expand_item)
        self.tree_view.itemCollapsed.connect(self.collapse_item)
        self.tree_view.itemClicked.connect(self.tree_single_click)
        self.tree_view.itemDoubleClicked.connect(self.tree_double_click)
        self.list_view.itemClicked.connect(self.list_single_click)
        self.list_view.itemDoubleClicked.connect(self.list_double_click)
        self.filename_input.textChanged.connect(self.set_save_btn)
        self.save_btn.clicked.connect(self.save_file)
        self.sync_material_btn.clicked.connect(self.sync_material)

        self.setWindowTitle('Omniverse浏览器')
        self.setWindowIcon(get_icon('icon_omniverse_panel'))
        self.resize(1900, 1000)
    
    def set_save_btn(self, text):
        if self.connected:
            self.save_btn.setEnabled(text != "")
        else:
            self.save_btn.setEnabled(False)

    def save_file(self):
        savedvpbPath = vrFileIOService.getFileName()
        if savedvpbPath != "":
            path = self.save_file_path + self.filename_input.text() + '.usd'

            if self.select_file_path == path:
                reply = QMessageBox.question(self, "导出到Omniverse", "将覆盖该文件，是否继续？", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.StandardButton.No:
                    return
                
            # 尝试锁定
            self.lock_file(path)

        else:
            QMessageBox.warning(None, "导出到Omniverse","请先保存Vpb文件",QMessageBox.Ok)

    def lock_success(self, data):
        res = data["result"]
        # print(res)
        if res == "ERROR_NOT_FOUND" or res == "OK":
            url = data["url"]
            self.setEnabled(False)
            savedvpbPath = vrFileIOService.getFileName()
            filenameNoExt = os.path.splitext(savedvpbPath)[0]
            out_path = filenameNoExt + ".fbx"
            exporter = FBXExporter()
            exporter.export(out_path)

            QTimer.singleShot(100,lambda: self.convert_file(out_path, url))
        elif res == "ERROR_LOCKED":
            self.setEnabled(True)
            self.progressbar.setVisible(False)
            QMessageBox.warning(None, "导出","该文件已被其他用户锁定，请等待解锁后再试",QMessageBox.Ok)
        else:
            self.setEnabled(True)
            self.progressbar.setVisible(False)
            QMessageBox.warning(None, "锁定",f"锁定失败：{res}",QMessageBox.Ok)


    def lock_file(self, url):
        self.setEnabled(False)
        self.progressbar.setVisible(True)
        self.sync_material_btn.setVisible(False)

        # url = self.tree_view.currentItem().text(1) + item.text()
        target_url = "http://localhost:8111/lock"
        json_data = {"url": url}
        http = HttpReq()
    
        http.request(target_url, json_data, self.lock_success,self.onFail)

    def sync_material(self):
        self.progress_dialog = ProgressDialog("正在同步...")
        target_url = "http://localhost:8111/material"
        path = self.select_file_path
        json_data = {"url": path}
        http = HttpReq()

        http.request(target_url, json_data, self.onSyncSucc,self.onFail)

    def onSyncSucc(self, data):
        material_data = data["materials_data"]
        # print(material_data)
        self._fetch_module.sync(material_data)

        self.progress_dialog.close()

    def export_materials_data(self):
        materials_data = {}
        materials = vrMaterialService.getAllMaterials()
        for material in materials:
            bound_nodes = vrMaterialService.findNodesWithMaterial(material)

            bound_nodes_no_surface = []
            for bound_node in bound_nodes:
                if bound_node.getChildCount() != 0:
                    bound_nodes_no_surface.append(bound_node.getName())
            
            if len(bound_nodes_no_surface) != 0:
                materials_data[material.getName()] = bound_nodes_no_surface

        return materials_data
            

    def convert_file(self, out_path, url):
        self.progress_dialog = ProgressDialog("正在转换文件...")

        # materials_data = self.export_materials_data()

        target_url = "http://localhost:8111/convert"
        json_data = {"fbx_path": out_path, "url": url}
        http = HttpReq()

        http.request(target_url, json_data, self.onConvertSucc,self.onFail)

    def onConvertSucc(self, data):
        res = data["result"]
        if res == "OK":
            self.progress_dialog.close()
            self.progress_dialog = ProgressDialog("正在保存文件到服务器...")
            usd_path = data["usd_path"]
            url = data["url"]

            materials_data = self.export_materials_data()

            target_url = "http://localhost:8111/save"
            json_data = {"url": url, "usd_path": usd_path, "materials_data": materials_data}
            http = HttpReq()

            http.request(target_url, json_data, self.onSaveSucc,self.onFail)
        else:
            self.progress_dialog.close()
            QMessageBox.warning(None, "文件转换",f"转换失败：{res}",QMessageBox.Ok)

    def onSaveSucc(self, data):
        # print(self.save_file_path)
        url = data["url"]
        usd_path = data["usd_path"]
        src_path = usd_path.replace(".usd", ".fbx")

        target_url = "http://localhost:8111/unlock"
        json_data = {"url": url}
        http = HttpReq()
    
        http.request(target_url, json_data, lambda x: self.unlock_success(x, src_path, usd_path),self.onFail)
        

    def unlock_success(self, data, src_path, usd_path):
        res = data["result"]
        if res == "OK":
            QTimer.singleShot(100,lambda: self.save_refresh(src_path, usd_path))
        else:
            self.progress_dialog.close()
            QMessageBox.warning(None, "解锁",f"解锁失败：{res}",QMessageBox.Ok)


    def save_refresh(self, src_path, usd_path):
        os.remove(src_path)
        os.remove(usd_path)
        self.sync_material_btn.setVisible(False)
        self.progress_dialog.close()
        self.list_view.clear()
        self.request_list(self.save_file_path)

    def __judge_click_list(self,item):
        if self.list_isDouble == False:
            #单击

            self.click_file_item(item)
        else:
            #双击
            self.list_isDouble = False
            
            self.click_folder_item(item)

    def list_double_click(self, item):
        self.list_isDouble = True

    def list_single_click(self, item):
        QTimer.singleShot(300,lambda:self.__judge_click_list(item))

    def __judge_click_tree(self,item, column):
        if self.tree_isDouble == False:
            #单击

            self.click_item(item, column)
        else:
            #双击
            self.tree_isDouble = False
            # print('mouse double clicked'   )
            # if item.isExpanded():
            #     self.click_item(item, column)
            if item.childCount() == 0:
                self.click_item(item, column)

    def tree_double_click(self, item, column):
        self.tree_isDouble = True

    def tree_single_click(self, item, column):
        QTimer.singleShot(300,lambda:self.__judge_click_tree(item, column))
        

    def click_file_item(self, item):
        self.setEnabled(False)
        self.progressbar.setVisible(True)
        self.sync_material_btn.setVisible(False)

        url = self.tree_view.currentItem().text(1) + item.text()
        target_url = "http://localhost:8111/stat"
        json_data = {"url": url}
        http = HttpReq()
    
        http.request(target_url, json_data, self.onStatSucc,self.onFail)
    
    def click_folder_item(self, item):
        if item.text() in self.list_node:
            item_ = self.list_node[item.text()]
            # self.tree_view.setCurrentItem(item_)
            # print(item_.text(0))
            
            self.tree_view.setCurrentItem(item_)
            self.tree_view.expandItem(item_)
            # self.list_view.clear()

    def click_item(self, item, column):
        self.sync_material_btn.setVisible(False)
        self.list_view.clear()
        self.current_expand_item = item
        self.request_list(item.text(1))

    def expand_item(self, item):
        if self.tree_view.currentItem() != item:
            return
        # print(item.text(0))
        self.current_expand_item = item
        self.list_view.clear()
        item.setIcon(0,get_icon("folder_open"))
        # print(item.text(1))
        self.request_list(item.text(1))

    def collapse_item(self, item):
        item.setIcon(0,get_icon("folder"))

    def connect2server(self):
        self.tree_view.clear()
        self.list_view.clear()
        self.sync_material_btn.setVisible(False)
        #设置根节点
        self.root = QTreeWidgetItem(self.tree_view)
        self.root.setText(0,self._input.text())
        self.root.setText(1,self._input.text() + "/")
        self.root.setIcon(0,get_icon("folder"))
        self.tree_view.addTopLevelItem(self.root)
        self.current_expand_item = self.root

        # self.click_item(self.root, 0)
        self.tree_view.setCurrentItem(self.root)
        self.tree_view.expandItem(self.root)

        # self.request_list(self.root.text(1))

    def request_list(self, url):
        # print(url)
        self.setEnabled(False)

        self.progressbar.setVisible(True)
        target_url = "http://localhost:8111/list"
        json_data = {"url": url}
        http = HttpReq()
    
        http.request(target_url, json_data, self.onSucc,self.onFail)
    
    def onSucc(self, data):
        self.connected = True
        # print("succc",data)
        self.info = data["this_entry"]
        self.refresh(data["entries"])

    def onStatSucc(self, data):
        self.connected = True
        self.progressbar.setVisible(False)
        self.setEnabled(True)
        name = data['relative_path']
        self.fileinfo.setInfo(name, data['modified_time'], data['created_by'], data['modified_by'], data['size'])
        self.fileinfo.setVisible(True)
        if '.usd' in name:
            self.filename_input.setText(name.replace(".usd", ""))
            self.sync_material_btn.setVisible(True)
            self.select_file_path = data['url']

    def onFail(self, data, err):
        self.connected = False
        self.setEnabled(True)
        print("fail",data)
        if self.progress_dialog is not None:
            self.progress_dialog.close()

        self.restore_to_default()
        # error_info = f"未能连接上服务器，错误原因：{str(err)}"
        if data == "":
            error_info = "请检查是否已运行Omniverse USD Composer"
        elif data == '''{"detail":"Not Found"}''':
            error_info = "请检查是否已加载Omniverse连接器扩展"
        else:
            info = json.loads(data)["info"]
            if info == "ERROR_CONNECTION":
                error_info = "未能连接上Omniverse服务器，请检查目标IP地址是否正确"

        QTimer.singleShot(100,lambda: QMessageBox.warning(self, "连接错误",error_info,QMessageBox.Ok))
        

    def add_child_node(self, name, url, parent_node):
        child_node = QTreeWidgetItem()
        child_node.setText(0, name)
        child_node.setText(1, url.replace("//", "/"))
        child_node.setIcon(0,get_icon("folder"))
        parent_node.addChild(child_node)
        return child_node
    
    def refresh(self, entries):
        self.fileinfo.setInfo(self.info['relative_path'], self.info['modified_time'], self.info['created_by'], self.info['modified_by'], self.info['size'])
        self.fileinfo.setVisible(True)
        self.current_expand_item.takeChildren()
        self.list_node = {}
        self.save_file_path = self.info['url']
        self._dir.setText(f"omniverse://{self.save_file_path}")
        for entry in entries:
            name = entry["relative_path"]
            url = entry["url"]
            # print(name)
            # print(url)
            
            # 文件夹
            if '.' not in name:
                child_node = self.add_child_node(name, url, self.current_expand_item)
                # has_dir = False
                for _ in entry["child"]:
                    _name = _["relative_path"]
                    url = _["url"]
                    if '.' not in _name:
                        # has_dir = True
                        self.add_child_node(_name, url, child_node)
                        # break
                # if has_dir:
                #     self.add_child_node(name, url, child_node)
                item = QtWidgets.QListWidgetItem(get_icon("folder_icon"),name)
                item.setTextAlignment(Qt.AlignHCenter)
                self.list_view.addItem(item)

                self.list_node[name] = child_node
            # 文件
            else:
                if '.usd' in name:
                    item = QtWidgets.QListWidgetItem(get_icon("usd"),name)
                    item.setTextAlignment(Qt.AlignHCenter)
                    self.list_view.addItem(item)
        
        self.progressbar.setVisible(False)
        self.setEnabled(True)

class MergeNode():
    def __init__(self):
        pass

    def merge(self):

        # 用于处理所有合并节点的函数，保留次级结构
        def mergeALLNodes(node, CurrentNodeCount, AllCount):

            # 清除变换信息
            vrOptimize.flushTransformations(node)

            nodes = []
            nodes = vrdNode(node).getChildren()

            # 初始化进度
            nodeprocess = 0

            for child in nodes:
                if vrNodePtr.toNode(child.getObjectId()).getType() != "Geometry":
                    # 合并几何体
                    mergeGeos(child)

                    # 移动合并后的几何体到根组节点
                    for eachgeo in child.getChildren():
                        vrScenegraph.moveNode(eachgeo, child, node)

                    # 清除无用节点
                    # deleteNoneNode(child)

                # 计算当前进度
                nodeprocess += 1

                if AllCount == 1:
                    currentpersent = nodeprocess / len(nodes)
                else:
                    currentpersent = (CurrentNodeCount / AllCount) + (nodeprocess / len(nodes)) * (1 / AllCount)

                self.progress_dialog.setValue(currentpersent)
                QApplication.processEvents()

            # 清除无用节点
            deleteNoneNode(node)

        # 用于清除无用节点的函数
        def deleteNoneNode(node):
            allnodes = vrdNode(node).getChildren()

            for child in allnodes:
                if vrNodePtr.toNode(child.getObjectId()).getType() != "Geometry":
                    vrScenegraph.deleteNode(child, True)


        # 用于合并几何体的函数
        def mergeGeos(node):

            # 清除变换信息
            vrOptimize.flushTransformations(node)

            # 合并几何体
            vrOptimize.mergeGeometry(node)

            # 移动所有几何体到次级节点
            MoveNodes(node)

            # 合并几何体
            vrOptimize.mergeGeometry(node)

        # 遍历所有几何体并移动
        def MoveNodes(node):

            # 遍历所有几何体
            geoNodes = []
            self.findGeosRecursive(vrdNode(node), geoNodes, None)

            # 移动合并后的几何体到根节点
            for eachgeo in geoNodes:
                vrScenegraph.moveNode(eachgeo, eachgeo.getParent(), node)


        nodes = vrScenegraph.getSelectedNodes()

        # 处理单选或多选对象
        if len(nodes) != 0:
            self.progress_dialog = ProgressDialog("正在合并...")
            nodeprocess = 0

            for node in nodes:
                # 清除共享关系
                vrNodeUtils.unshareCores(node)

                nodeprocess += 1

                # 合并几何体
                mergeALLNodes(node, nodeprocess, len(nodes))

            print("done merge")
            self.progress_dialog.close()

        else:
            QMessageBox.warning(None, "合并","请选择对象！",QMessageBox.Ok)

    # 用于遍历几何体的函数
    def findGeosRecursive(self, node, geos, predicate):
        """ Recursively traverses the scenegraph starting at node
            and collects geometry nodes which can be filtered
            with a predicate.
            Args:
                node (vrdNode): Currently traversed node
                geos (list of vrdGeometryNode): List of collected geometry nodes
                predicate (function): None or predicate(vrdGeometryNode)->bool
        """
        geo = vrdGeometryNode(node)
        if geo.isValid():
            if predicate is None or predicate(geo):
                geos.append(geo)
            # stop traversing the tree
        else:
            # traverse the children
            for child in node.getChildren():
                self.findGeosRecursive(child, geos, predicate)

class OptimizaModule():
    def __init__(self):
        pass


    def removeFace(self):
        """
        删除几何体下的重复面
        """
        def remove_face(node):
            """
            删除几何体的重复面
            """
            selnodes = vrdNode(node).getChildren()
            center_item = []
            for node in selnodes:
                BBC = vrNodeUtils.getBoundingBoxCenter(node, True)

                center_item.append((BBC.x(), BBC.y(), BBC.z()))

            set_item = set(center_item)

            for center in set_item:
                index = [i for i, val in enumerate(center_item) if val == center]
                if len(index) > 1:
                    PCounts = []
                    for i in index:
                        PCounts.append(vrdGeometryNode(vrdNode(node)).getPrimitiveCount())
                    if len(set(PCounts)) == 1:
                        index.pop()
                        for idx in index:
                            vrScenegraph.deleteNode(selnodes[idx], True)

        node = vrScenegraph.getSelectedNode()
        if node.getType() == 'Geometry':
            remove_face(node)
        else:
            QMessageBox.warning(None, "移除重复面","请选择几何体！",QMessageBox.Ok)

    def unified_Normals(self):
        settings = vrdDecoreSettings()
        settings.setResolution(1024)
        settings.setQualitySteps(8)
        settings.setCorrectFaceNormals(True)
        settings.setDecoreEnabled(False)
        settings.setSubObjectMode(vrGeometryTypes.DecoreSubObjectMode.Components)
        settings.setTransparentObjectMode(vrGeometryTypes.DecoreTransparentObjectMode.Ignore)
        treatAsCombinedObject = True

        nodesToDecore = vrNodeService.getSelectedNodes()

        if nodesToDecore != []:
            vrDecoreService.decore(nodesToDecore, treatAsCombinedObject, settings)
        else:
            QMessageBox.warning(None, "统一法线","请选择对象！",QMessageBox.Ok)

class MaterialBrushDialog(HideDialog):

    def __init__(self, parent=None):
        super(MaterialBrushDialog, self).__init__(parent=parent)
        
        self.mat=None

        self.setupUi()

    def setupUi(self):
        mat_label = QtWidgets.QLabel('当前记录的材质:')
        self.mat_img = QtWidgets.QLabel()
        self.mat_lineedit = QtWidgets.QLabel()

        alabel = QtWidgets.QLabel()

        record_Btn = QtWidgets.QPushButton('记录材质')
        record_Btn.setIcon(get_icon('icon_material_record'))
        record_Btn.setIconSize(QtCore.QSize(32, 32))
        record_Btn.clicked.connect(self.click_record)

        selectBtn = QtWidgets.QPushButton('选择材质相同项')
        selectBtn.setIcon(get_icon('icon_material_select'))
        selectBtn.setIconSize(QtCore.QSize(32, 32))
        selectBtn.clicked.connect(self.click_select_all)

        apply_Btn = QtWidgets.QPushButton('赋予已记录材质')
        apply_Btn.setIcon(get_icon('icon_material_apply'))
        apply_Btn.setIconSize(QtCore.QSize(32, 32))
        apply_Btn.clicked.connect(self.click_apply)

        vbox = QtWidgets.QVBoxLayout(self)

        vbox.addWidget(mat_label)
        vbox.addWidget(self.mat_img)
        vbox.addWidget(self.mat_lineedit)
        vbox.addWidget(alabel)
        vbox.addWidget(record_Btn)
        vbox.addWidget(selectBtn)
        vbox.addWidget(apply_Btn)

        self.setWindowTitle('材质刷')
        self.setWindowIcon(get_icon('icon_material_panel'))
        self.resize(300, 100)

    def click_record(self):
        node = vrScenegraph.getSelectedNode()
        self.mat = vrdNode(node).getMaterial()
        self.mat_img.setPixmap(QtGui.QPixmap.fromImage(self.mat.getPreview()).scaled(60, 60, QtCore.Qt.KeepAspectRatio))
        self.mat_lineedit.setText(self.mat.getName())

    def click_select_all(self):
        node = vrScenegraph.getSelectedNode()
        allnodes = node.getMaterial().getNodes()
        selnodes = []
        for node in allnodes:
            if vrdNode(node).isVisible() == True:
                selnodes.append(node)

        vrScenegraph.selectNodes(selnodes)


    def click_apply(self):
        nodes = vrScenegraph.getSelectedNodes()
        if len(nodes) != 0:
            vrUndoService.beginUndo()
            vrUndoService.beginMultiCommand("applyMaterial")
            try:
                for node in nodes:
                    vrdNode(node).applyMaterial(self.mat)
                self.preview_label.setPixmap(QtGui.QPixmap.fromImage(self.mat.getPreview()).scaled(60, 60, QtCore.Qt.KeepAspectRatio))
                self.preview_name.setText(self.mat.getName())
            except:
                pass
            finally:
                vrUndoService.endMultiCommand()
                vrUndoService.endUndo()

class UVDialog(HideDialog):

    def __init__(self, parent=None):
        super(UVDialog, self).__init__(parent=parent)

        self.ProjectionSettings = None
        self.project_mode = None

        self.setupUi()

    def setupUi(self):
        mat_label = QtWidgets.QLabel('当前记录材质UV的节点:')
        self.mat_lineedit = QtWidgets.QLabel()

        alabel = QtWidgets.QLabel()

        record_Btn = QtWidgets.QPushButton('记录UV')
        record_Btn.setIcon(get_icon('icon_material_record'))
        record_Btn.setIconSize(QtCore.QSize(32, 32))
        record_Btn.clicked.connect(self.click_record)

        apply_Btn = QtWidgets.QPushButton('赋予已记录UV')
        apply_Btn.setIcon(get_icon('icon_material_apply'))
        apply_Btn.setIconSize(QtCore.QSize(32, 32))
        apply_Btn.clicked.connect(self.click_apply)

        vbox = QtWidgets.QVBoxLayout(self)

        vbox.addWidget(mat_label)
        vbox.addWidget(self.mat_lineedit)
        vbox.addWidget(alabel)
        vbox.addWidget(record_Btn)
        vbox.addWidget(apply_Btn)

        self.setWindowTitle('UV刷')
        self.setWindowIcon(get_icon('icon_material_panel'))
        self.resize(400, 100)

    def click_record(self):
        node = vrScenegraph.getSelectedNode()
        self.mat_lineedit.setText(vrdNode(node).getName())
        self.project_mode = vrUVService.getProjectionMode(vrdGeometryNode(vrdNode(node)), uvSet=vrUVTypes.MaterialUVSet)
        if self.project_mode == vrUVTypes.UVProjectionMode.PlanarMapping:
            self.ProjectionSettings = vrUVService.readPlanarProjectionSettings(vrdGeometryNode(vrdNode(node)), uvSet=vrUVTypes.MaterialUVSet)
        elif self.project_mode == vrUVTypes.UVProjectionMode.TriplanarMapping:
            self.ProjectionSettings = vrUVService.readTriplanarProjectionSettings(vrdGeometryNode(vrdNode(node)), uvSet=vrUVTypes.MaterialUVSet)
        elif self.project_mode == vrUVTypes.UVProjectionMode.CylindricalMapping:
            self.ProjectionSettings = vrUVService.readCylindricalProjectionSettings(vrdGeometryNode(vrdNode(node)), uvSet=vrUVTypes.MaterialUVSet)
        else:
            pass



    def click_apply(self):
        if self.ProjectionSettings:
            nodes = vrScenegraph.getSelectedNodes()
            if len(nodes) != 0:
                vrUndoService.beginUndo()
                vrUndoService.beginMultiCommand("applyUV")
                try:
                    nodes = [vrdGeometryNode(vrdNode(node)) for node in nodes]
                    if self.project_mode == vrUVTypes.UVProjectionMode.PlanarMapping:
                        vrUVService.applyPlanarProjection(nodes, self.ProjectionSettings, uvSet=vrUVTypes.MaterialUVSet)
                    elif self.project_mode == vrUVTypes.UVProjectionMode.TriplanarMapping:
                        vrUVService.applyTriplanarProjection(nodes, self.ProjectionSettings, uvSet=vrUVTypes.MaterialUVSet)
                    elif self.project_mode == vrUVTypes.UVProjectionMode.CylindricalMapping:
                        vrUVService.applyCylindricalProjection(nodes, self.ProjectionSettings, uvSet=vrUVTypes.MaterialUVSet)
                    else:
                        pass
                    # du
                    # vrUVService.translateUV(nodes, du, 0.0, uvSet=vrUVTypes.MaterialUVSet)
                except Exception as e:
                    print(e)
                finally:
                    vrUndoService.endMultiCommand()
                    vrUndoService.endUndo()

class FetchMaterial():

    def __init__(self):
        pass
    
    def sync(self, material_data):

        vrUndoService.beginUndo()
        vrUndoService.beginMultiCommand("syncMaterial")
        
        materials = material_data.keys()

        missing_materials = []
        for material in materials:
            material_vrd = vrMaterialService.findMaterials(material)
            if len(material_vrd) == 0:
                missing_materials.append(material)
            
            QApplication.processEvents()

        self.create_random_materials(missing_materials)  # 创建缺失材质

        vrNodeService.initFindCache()
        for material, objs in material_data.items():
            found_nodes = []
            for obj in objs:
                found_node = vrNodeService.findNode(obj)
                found_nodes.append(found_node)

            material_vrd = vrMaterialService.findMaterial(material)
            vrMaterialService.applyMaterialToNodes(material_vrd, found_nodes)

        vrNodeService.clearFindCache()

        vrUndoService.endMultiCommand()
        vrUndoService.endUndo()

        # vrUndoService.beginUndo()
        # vrUndoService.beginMultiCommand("clearUnusedMaterial")

        # vrMaterialService.removeUnusedMaterials()

        # vrUndoService.endMultiCommand()
        # vrUndoService.endUndo()
    
    def generate_random_color(self, min_distance=0.2, previous_colors=None, max_attempts=100):
        """生成一个带有足够颜色通道差异的随机RGB颜色，确保与之前生成的颜色不相邻。"""

        def color_distance(color1, color2):
            """计算两个颜色之间的欧氏距离。"""
            return math.sqrt(sum((c1 - c2) ** 2 for c1, c2 in zip(color1, color2)))

        if previous_colors is None:
            previous_colors = []

        if not previous_colors:
            return (random.random(), random.random(), random.random())

        for _ in range(max_attempts):
            r = random.random()
            g = random.random()
            b = random.random()

            min_distance_to_previous = min(
                color_distance(new_color, prev_color) for new_color in ((r, g, b),) for prev_color in previous_colors)

            if min_distance_to_previous >= min_distance:
                return (r, g, b)

        # return None
        return (random.random(), random.random(), random.random())

    def create_random_materials(self, material_names):
        previous_colors = []
        for name in material_names:
            mat = vrMaterialService.createMaterial(name, vrMaterialTypes.Plastic)
            color = self.generate_random_color(min_distance=0.3, previous_colors=previous_colors)
            previous_colors.append(color)
            r, g, b = color
            mat.setDiffuseColor(QVector3D(r, g, b))
            mat.setRoughness(0.2)
            QApplication.processEvents()


# Load the .ui files. We derive widget classes from these types.
_form, _base = uiTools.loadUiType('VRModelTool.ui')

class VRModelTool(_form, _base):
    def __init__(self, parent=None):
        super(VRModelTool, self).__init__(parent)
        parent.layout().addWidget(self)
        self.parent = parent

        self.setupUi(self)
        self.setupUIicon()

        self.brush_dialog = None
        self.uv_tool_dialog = None
        self.omni_explorer = None

        self.merge_ = MergeNode()
        self.optim_ = OptimizaModule()

    def setButtonStyle(self, button, icon):
        button.setIcon(get_icon(icon))
        button.setIconSize(QtCore.QSize(32, 32))
        button.setStyleSheet("QPushButton{text-align : left;min-width: 250px;}")

    def setupUIicon(self):
        cur_dir = os.path.split(os.path.realpath(__file__))[0]
        self._label.setPixmap(QtGui.QPixmap(os.path.join(cur_dir, "icon\icon_xp_vr.png")).scaled(100, 50, QtCore.Qt.KeepAspectRatio))
        self._label.setAlignment(QtCore.Qt.AlignCenter)
        self._versionlabel.setText(__version__)
        self._versionlabel.setAlignment(QtCore.Qt.AlignCenter)

        self._merge.clicked.connect(self.merge)
        self.setButtonStyle(self._merge, "icon_merge")

        self._normal.clicked.connect(self.normal)
        self.setButtonStyle(self._normal, "icon_normal")

        self._delete_surface.clicked.connect(self.delete_surface)
        self.setButtonStyle(self._delete_surface, "icon_clear")

        self._materialBrush.clicked.connect(self.materialbrush)
        self.setButtonStyle(self._materialBrush, "icon_material")

        self._uvTools.clicked.connect(self.uv_tools)
        self.setButtonStyle(self._uvTools, "icon_material_record")

        self._export2Omniverse.clicked.connect(self.export2omniverse)
        self.setButtonStyle(self._export2Omniverse, "icon_omniverse")

        self._vrTools.clicked.connect(self.vrlock)
        self.setButtonStyle(self._vrTools, "icon_vrtool")

        # self._pbar.setRange(0, 100)
        # self._pbar.reset()
        # utils._pbar = self._pbar
    
    def get_center(self, widget):
        # 获取窗口在屏幕中心的位置
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        size = widget.geometry()
        return QtCore.QPoint((screen.width() - size.width()) / 2, (screen.height() - size.height()) / 2)

    def merge(self):
        self.merge_.merge()

    def normal(self):
        self.optim_.unified_Normals()

    def delete_surface(self):
        self.optim_.removeFace()

    def materialbrush(self):

        if not self.brush_dialog:
            self.brush_dialog = MaterialBrushDialog(self)
            self.brush_dialog.move(self.get_center(self.brush_dialog))
            self.brush_dialog.show()
        else:
            self.brush_dialog.show()


    def uv_tools(self):
        
        if not self.uv_tool_dialog:
            self.uv_tool_dialog = UVDialog(self)
            self.uv_tool_dialog.move(self.get_center(self.uv_tool_dialog))
            self.uv_tool_dialog.show()
        else:
            self.uv_tool_dialog.show()



    def export2omniverse(self):

        if not self.omni_explorer:

            self.omni_explorer = OmniBrowser(self)
            
            self.omni_explorer.move(self.get_center(self.omni_explorer))
            self.omni_explorer.show()
        else:
            self.omni_explorer.show()

    def vrlock(self):
        vrImmersiveInteractionService.setViewpointMode(True, True, True)
        # Get the left controller
        leftController = vrDeviceService.getVRDevice("left-controller")
        # Get the right controller
        rightController = vrDeviceService.getVRDevice("right-controller")

        # Define the description of the virtual buttons on the touchpad.
        # These description consist of a name, a radius 0 - 1 and an angle 0 - 360,
        # where on the circular touchpad the button is located
        padCenter = vrdVirtualTouchpadButton("padcenter", 0.0, 0.0, 0.0, 0.0)
        padLeft = vrdVirtualTouchpadButton("padleft", 0.0, 0.0, 0.0, 0.0)
        padUp = vrdVirtualTouchpadButton("padup", 0.0, 0.0, 0.0, 0.0)
        padRight = vrdVirtualTouchpadButton("padright", 0.0, 0.0, 0.0, 0.0)
        padDown = vrdVirtualTouchpadButton("paddown", 0.0, 0.0, 0.0, 0.0)


        # Add the descirptions for the virtual buttons to the left controller
        leftController.addVirtualButton(padCenter, "touchpad")
        leftController.addVirtualButton(padLeft, "touchpad")
        leftController.addVirtualButton(padUp, "touchpad")
        leftController.addVirtualButton(padRight, "touchpad")
        leftController.addVirtualButton(padDown, "touchpad")

        # Also add the descriptions to the right controller
        # Note that each controller can have different tochpad layouts, if
        # it is needed.
        rightController.addVirtualButton(padLeft, "touchpad")
        rightController.addVirtualButton(padUp, "touchpad")
        rightController.addVirtualButton(padRight, "touchpad")
        rightController.addVirtualButton(padDown, "touchpad")
        rightController.addVirtualButton(padCenter, "touchpad")

        # Get the interaction which actions should be remapped to the virtual buttons
        teleport = vrDeviceService.getInteraction("Teleport")
        # Set the mapping of the actions to the new virtual buttons
        teleport.setControllerActionMapping("prepare", "any-paddown-touched")
        teleport.setControllerActionMapping("abort", "any-paddown-untouched")
        teleport.setControllerActionMapping("execute", "any-paddown-pressed")

        QMessageBox.warning(None, "vr锁定","已锁定触摸板！",QMessageBox.Ok)


vrmodeltool_plugin = VRModelTool(VREDPluginWidget)