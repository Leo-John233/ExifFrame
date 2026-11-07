# ExifFrame

ExifFrame 是一款 Windows 照片水印工具，支持批量为 JPEG、PNG 和 HEIC 照片添加拍摄信息水印，也可以组合自定义文字和编辑模板

项目基于 [leslievan 的 semi-utils](https://github.com/leslievan/semi-utils) 开发，在原有水印处理流程上增加了桌面窗口、可视化编辑、照片信息编辑和中英文切换

## 开始使用

### 使用单文件版

打开 `ExifFrame.exe` 即可使用，无需安装 Python，也不用另外准备 ExifTool

首次运行会在 EXE 旁创建 `config` 文件夹，用于保存设置和自建模板。更新程序时保留这个文件夹即可沿用配置，程序所在目录需要有写入权限

### 从源码运行

当前开发和打包使用 Windows x64 与 Python 3.13，先准备 ExifTool，再安装依赖并启动程序

从 [ExifTool 官网](https://exiftool.org/) 下载 Windows 版，将解压后的程序和支持文件放入项目的 `exiftool` 目录

```text
exiftool/
├── exiftool.exe
└── exiftool_files/
```

也可以保留下载包中的文件名 `exiftool(-k).exe`，但要同时保留旁边的 `exiftool_files` 文件夹

在项目目录执行

```powershell
python -m pip install -r requirements.txt
python main.py
```

缺少 ExifTool 时，源码启动会提示补全目录。水印编辑和导出仍可使用，拍摄信息会尝试从照片自带的 EXIF 读取；照片信息编辑、保存信息副本和迁移信息则需要完整的 ExifTool

原有浏览器界面仍可通过 `python web_server.py` 启动，两个入口共用图像处理和照片信息读取逻辑

## 添加水印

1. 添加照片或选择输入目录，也可以把照片拖入窗口
2. 勾选需要处理的照片，选择水印模板
3. 查看预览，调整文字、颜色、整体缩放和底部留白
4. 选择输出目录，设置 JPEG 质量和覆盖选项，然后导出照片

水印缩放默认为 100%，底部留白可以自动计算，也可以手动调整。保存设置会记录目录和导出选项，保存模板会保留水印的内容与版式

### 组合模板内容

打开组合底部信息，选择一个文字区域，再添加相机、镜头、焦距、光圈、快门、ISO、日期或自定义文字。字段可以拖动排序，也可以设置分隔符和前后缀

例如，可以将一行组合为 `ISO160 | Alice | 1/250s`，另一行放置日期与版权。缺失的字段可以隐藏，也可以显示为破折号

新建模板可以从内置样式、当前模板或空白边框开始。没有导入照片时，编辑器会使用项目自带的示例照片预览，示例不会加入导出队列

需要直接修改 JSON/Jinja 模板时，打开高级源码。修改后会自动更新预览，点击保存模板保留修改；在源码与可视化编辑之间切换时，未保存的草稿和已有表达式会保留

### 日期与位置的显示

- 日期默认显示为 `2026.11.04`，拍摄时间和日期与时间可以单独添加
- 地理位置将经纬度合为一项，以度分秒显示，例如 `26°9'12"N 119°17'8"E`，缺少任一坐标时隐藏整项
- 海拔显示为 `3555m`，海平面以下为 `-3555m`，有小数时保留有效数值
- 自定义文字支持 `ℤ`、`ℝ`、`ℂ`、`𝕫` 等符号，预览和导出保留原字符

这些格式只影响水印显示，不会更改照片中保存的 EXIF

## 编辑照片信息

照片信息编辑器提供相机、镜头、曝光、拍摄时间、版权和 GPS 等 27 项字段，也可以对勾选的照片批量应用修改

修改默认只用于本次预览和水印导出，原片保持不变。需要把信息写入文件时，可以保存修改副本，或从 RAW、JPEG 参考照片迁移信息到目标副本

在组合面板中也能编辑照片信息，修改会同步到当前预览

## 导出规则

- 输入目录内的照片可以保留相对目录结构，PNG 仍导出为 PNG，其他支持格式导出为 JPEG
- 单独添加且不在输入目录内的照片使用 `_watermarked` 后缀，同名时默认自动编号
- 已有输出文件默认跳过，启用覆盖后只替换允许覆盖的输出文件
- 已导入的原片始终受到保护，包括没有勾选的照片
- 取消导出会保留已完成的文件，并显示成功、失败和跳过数量

## 设置与快捷键

在查看菜单中可以切换简体中文与英文，也可以打开关于窗口查看作者信息和项目来源。切换语言会保留照片队列、勾选状态和未保存内容

各版本均使用程序目录下的 `config` 文件夹

| 文件 | 保存内容 |
| --- | --- |
| `config/config.ini` | 输入输出目录、模板和导出选项 |
| `config/desktop.json` | 桌面样式设置 |
| `config/ui.json` | 语言偏好 |

旧版用户首次启动新版单文件程序时，会尝试迁移 `%LOCALAPPDATA%\ExifFrame` 中的配置。程序旁已有的配置优先保留，旧目录中的文件不会被删除

| 操作 | 快捷键 |
| --- | --- |
| 编辑照片信息 | `Ctrl+I` |
| 组合底部信息 | `Ctrl+Shift+E` |
| 编辑高级源码 | `Ctrl+E` |

## 自行打包

准备好项目的 `exiftool` 目录后，在 Windows x64 的 Python 3.13 环境中执行

```powershell
python -m pip install -r build_support/requirements-windows.txt
python build_support/build_windows.py
```

生成的程序位于 `build/ExifFrame.exe`，ExifTool、模板、字体和标识均已包含在内，分发时只需要这个 EXE

构建直接使用本地 `exiftool` 文件，资源不完整时提示补全。NumPy 下载包保存在 `build/download`，存在时直接复用，不做额外的哈希校验或来源核验

临时依赖和分析文件放在项目外的系统临时目录，构建结束后自动清理。下载缓存、生成的程序和用户配置会保留；构建期间会限制处理器和内存占用，给其他程序留出资源

需要使用本地 NumPy 包时，可通过 `--numpy-wheel` 指定文件。添加 `--onedir` 可以生成目录版，分发目录版时需要保留整个输出文件夹

`exiftool` 是本地资源目录，不随 Git 提交

## GitHub 自动打包

在仓库的 Actions 页面选择 `Build ExifFrame for Windows`，可以手动运行工作流，也可以推送以 `v` 开头的标签触发构建，例如 `v2.1.5`

云端使用 Windows 2025 和 Python 3.13 x64，调用与本地相同的构建脚本。Python 依赖、NumPy 下载包和 ExifTool 分别缓存，缓存可用时直接复用

ExifTool 缓存缺失时，工作流从[官方 SourceForge 发布目录](https://sourceforge.net/projects/exiftool/files/)下载固定的 13.60 Windows 64 位包，补全云端的 `exiftool` 目录。这一步只在云端执行，本地打包仍直接使用已有文件

首次建议在默认分支上手动运行一次，方便后续标签构建复用缓存。GitHub 的缓存有分支和标签作用域，具体规则见[官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache)

构建完成后，在该次运行的 Artifacts 中下载产物，包内只有 `ExifFrame.exe`。标签构建按版本命名，手动构建使用提交编号区分

## 模板示例

| 模板 | 说明 | 效果 |
| --- | --- | --- |
| [经典相机边框](static/standard1.json) | 相机、镜头和拍摄参数 | ![经典相机边框](static/standard1.jpeg) |
| [留白与阴影](static/standard2.json) | 圆角照片、阴影和宽边框 | ![留白与阴影](static/standard2.jpeg) |
| [沉浸模糊背景](static/blur.json) | 延展画面色彩，居中显示拍摄信息 | ![沉浸模糊背景](static/blur.jpeg) |
| [尼康模糊背景](static/nikon_blur.json) | 适合尼康照片的专属版式 | ![尼康模糊背景](static/nikon_blur.jpeg) |
| [极简参数](static/normal1.json) | 在右下角显示拍摄参数 | ![极简参数](static/normal1.jpeg) |
| [旅途与时间](static/normal2.json) | 文件夹名称和拍摄时间 | ![旅途与时间](static/normal2.jpeg) |
| [品牌居中](static/center_logo.json) | 标识居中，两侧可自由组合文字 | ![品牌居中](static/center_logo.jpeg) |
| [仅品牌标识](static/center_logo_only.json) | 在底部居中显示品牌标识 | ![仅品牌标识](static/center_logo_only.jpeg) |

功能对照、兼容性说明和历史性能记录见[网页功能对照与性能验证](docs/compatibility-and-performance.md)。示例照片取自上游样图的照片区域，制作过程见[示例照片生成脚本](scripts/build_preview_sample.py)

## 作者与项目引用

ExifFrame 作者：[Leo-John233](https://github.com/Leo-John233)

| 项目 | 作者 | 与 ExifFrame 的关系 |
| --- | --- | --- |
| [semi-utils](https://github.com/leslievan/semi-utils) | leslievan | 本项目的开发基础，提供原始水印处理流程和示例素材 |
| [ExifEditor-GUI](https://github.com/Leo-John233/ExifEditor-GUI) | Leo-John233 | 照片信息编辑与迁移功能的参考，本项目使用独立的 Qt 实现 |
| [ExifTool](https://exiftool.org/) | Phil Harvey | 照片元数据的读取、写入和迁移工具 |

ExifFrame 采用 [Apache License 2.0](LICENSE)，相关项目与工具保留各自的许可条款。ExifTool 的许可说明见[官方网站](https://exiftool.org/#license)
