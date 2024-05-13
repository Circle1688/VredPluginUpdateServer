# VredPluginUpdateServer
 Vred 2025 插件自动更新系统

## 使用

### 客户端

#### Vred 2025 插件目录默认是`C:\Users\-Your-User-Name-\Documents\Autodesk\VRED-17.0\ScriptPlugins`

- 将`plugin`目录下的`PluginClient`放到插件目录下

### 服务端
 
- 将要更新的vred插件放入到`src`目录下

- 运行`vred_server.bat`

- 客户端启动Vred 2025，插件将会自动检查更新

## 更新

- 替换或者新增`src`下的插件即可，无需重启服务

#### 局限：因Vred的限制，无法删除已有插件，需要手动删除
