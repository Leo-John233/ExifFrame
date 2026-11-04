# semi-utils

> [![hugo-papermod](https://img.shields.io/badge/Semi--Utils-@LeslieVan-red)](https://github.com/leslievan/semi-utils)
> [![download](https://img.shields.io/github/downloads/leslievan/semi-utils/total.svg)](https://github.com/leslievan/semit-utils/releases)
> [![release](https://img.shields.io/github/v/release/leslievan/semi-utils)](https://github.com/leslievan/semi-utils/releases)
> [![license](https://img.shields.io/github/license/leslievan/semi-utils)](https://github.com/leslievan/semi-utils/blob/master/LICENSE)
> ![language](https://img.shields.io/github/languages/top/leslievan/semi-utils?color=orange)
>
> **这是一个用于给照片批量添加水印、处理照片像素比、图像色彩和质量的工具。**

当前仅支持 Windows，运行源码需 Python 3.13 或更高版本。照片元数据读取使用项目内的 ExifTool，支持 `exiftool/exiftool.exe` 和官网下载包中的 `exiftool/exiftool(-k).exe`，请将 `exiftool_files` 与程序保留在同一目录。

## 桌面窗口

ExifFrame 提供独立桌面操作窗口，无需启动浏览器，也不依赖在线界面资源。

1. 设置输入、输出目录，在文件树中浏览并勾选照片，也可以添加或拖入照片
2. 选择模板，按需新建、另存副本或编辑 JSON/Jinja 源码
3. 预览水印并切换原图对照，选择按模板原样处理或使用快捷样式参数
4. 设置质量和覆盖选项，批量导出后在输出文件树中查看结果

输入目录内的照片按相对目录结构导出，PNG 保留为 PNG，其他支持格式导出为 JPEG。同名输出默认跳过，启用覆盖后仅替换独立输出目录中的文件。单独添加的照片使用 `_watermarked` 后缀，默认自动编号。程序始终保护原照片。“按模板原样处理”的预览从完整渲染结果缩略，快捷调整模式使用快速预览。没有 ExifTool 时会读取照片自带的 EXIF 信息。

在项目目录安装依赖后启动：

```powershell
python -m pip install -r requirements.txt
python main.py
```

使用本机已配置的 Conda 环境：

```powershell
& 'D:\miniconda3\envs\Python3.13\python.exe' -m pip install -r requirements.txt
& 'D:\miniconda3\envs\Python3.13\python.exe' main.py
```

`main.py` 仅负责启动桌面窗口；需要原版浏览器界面时运行 `python web_server.py`。两个入口共用水印处理器和 ExifTool 读取逻辑。

输入输出目录、模板、JPEG 质量、色度采样和覆盖开关以 `config/config.ini` 为准，桌面旧缓存不会覆盖这些共用配置。桌面独有的样式参数保存在 `config/desktop.json`。选择“按模板原样处理”后，导出沿用原版处理与保存方式。

### 验证与打包

```powershell
python main.py --smoke-test
python -m PyInstaller build_win_pkg.spec
```

桌面发布目录应包含 `ExifFrame.exe`、`config`、`static`、`pyproject.toml`，完整 EXIF 支持还需 `exiftool` 目录。GitHub Windows 发布流程会组装这些资源。

`test/` 和 `tests/` 作为本地验证目录忽略，不随仓库提交。保留本地测试文件时可运行 `python -m unittest discover -s tests -v`。

如果您觉得程序对您有所帮助的话，可以点击 [Sponsor](https:/su/cdn.lsvm.xyz/wechat.jpg) 按钮请作者喝杯咖啡，谢谢！


## 开发文档

**[Wiki](../../wiki)**

## 效果展示

| 模板                                     | 描述                                      | 效果                                      |
|----------------------------------------|-----------------------------------------|-----------------------------------------|
| [standard1](./static/standard1.json)   | 经典 EXIF 水印，包含相机型号、镜头、焦距、光圈、快门、ISO、拍摄时间和相机品牌 Logo | ![standard1](./static/standard1.jpeg)   |
| [standard2](./static/standard2.json)   | 在 standard1 基础上添加圆角、阴影效果和留白，适合社交媒体分享 | ![standard2](./static/standard2.jpeg)   |
| [nikon_blur](./static/nikon_blur.json) | 尼康风格水印，相机型号中的红色「Z」字高亮，配合模糊背景效果 | ![nikon_blur](./static/nikon_blur.jpeg) |
| [blur](./static/blur.json)             | 简洁风格，相机型号+参数垂直居中展示，配合模糊背景效果 | ![blur](./static/blur.jpeg)             |
| [normal1](./static/normal1.json)       | 极简风格，右下角显示拍摄参数，低调不抢眼 | ![normal1](./static/normal1.jpeg)       |
| [normal2](./static/normal2.json)       | 文件夹名称+拍摄时间，橙色文字，简洁实用 | ![normal2](./static/normal2.jpeg)       |
| [center_logo](./static/center_logo.json) | 中心 Logo 水印，可自定义四周文字内容 | ![center_logo](./static/center_logo.jpeg)       |


## 许可证

Semi-Utils 的发布基于 [Apache License 2.0](LICENSE).

### exiftool

Semi-Utils 引用了 [exiftool](https://exiftool.org/)，其发布基于 [GPL v1 + Artistic License 2.0](https://exiftool.org/#license)。


## 关于

[![Stargazers over time](https://starchart.cc/leslievan/semi-utils.svg)](https://starchart.cc/leslievan/semi-utils)
