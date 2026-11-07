# ExifFrame

ExifFrame 是一款 Windows 照片水印工具，支持批量为 JPEG、PNG 和 HEIC 照片添加拍摄信息水印，也可以组合自定义文字和编辑模板。项目基于 [leslievan 的 semi-utils](https://github.com/leslievan/semi-utils) 开发，增加了桌面窗口、可视化编辑、照片信息编辑和中英文切换

## 开始使用

### 发布版

下载 Release 中的 `ExifFrame.exe` 后直接运行，无需安装 Python 或另行准备 ExifTool。首次运行会在 EXE 旁创建 `config` 文件夹，保存设置和自建模板；更新程序时保留这个文件夹即可沿用配置，程序目录需要有写入权限

### 源码运行

开发和打包使用 Windows x64 与 Python 3.13。从 [ExifTool 官网](https://exiftool.org/) 下载 Windows 版，将程序和支持文件一起放入项目目录

```text
exiftool/
├── exiftool.exe
└── exiftool_files/
```

程序名也可以保留为 `exiftool(-k).exe`，但旁边的 `exiftool_files` 文件夹不能省略。准备好后，在项目目录安装依赖并启动

```powershell
python -m pip install -r requirements.txt
python main.py
```

缺少 ExifTool 时，启动会提示补全目录，水印编辑和导出仍可使用，拍摄信息会尝试从照片自带的 EXIF 读取；照片信息编辑、保存信息副本和迁移信息需要完整的 ExifTool。旧版浏览器界面可通过 `python web_server.py` 启动

## 添加水印

1. 添加照片或选择输入目录，也可以将照片拖入窗口
2. 勾选要处理的照片，选择模板
3. 查看预览，调整文字、颜色、整体缩放和底部留白
4. 选择输出目录，设置 JPEG 质量和覆盖选项，然后导出

水印缩放默认为 100%，底部留白可自动计算或手动调整。保存设置会记录目录与导出选项，保存模板会保留水印内容和版式

### 编辑模板

在组合底部信息中选择文字区域，添加相机、镜头、曝光、日期或自定义文字，再调整字段顺序、分隔符和前后缀。例如，一行可以组合为 `ISO160 | Alice | 1/250s`，另一行放日期与版权；缺失字段可隐藏或显示为破折号

新模板可以从内置样式、当前模板或空白边框开始，没有导入照片时使用项目示例预览，示例不会加入导出队列。需要修改 JSON/Jinja 时打开高级源码，修改会自动更新预览，保存模板后保留；切换编辑方式时，未保存的草稿和已有表达式会保留

- 日期默认显示为 `2026.11.04`，拍摄时间和日期与时间可以单独添加
- 地理位置合并经纬度，以度分秒显示，例如 `26°9'12"N 119°17'8"E`，缺少任一坐标时隐藏整项
- 海拔显示为 `3555m`，海平面以下为 `-3555m`，有小数时保留有效数值
- 自定义文字支持 `ℤ`、`ℝ`、`ℂ`、`𝕫` 等符号，预览和导出保留原字符

以上格式只影响水印显示，不会改写照片中保存的 EXIF

## 照片信息与导出

照片信息编辑器提供相机、镜头、曝光、拍摄时间、版权和 GPS 等 27 项字段，可对勾选照片批量应用修改，也可在组合面板中编辑。修改默认只用于本次预览和水印导出，原片保持不变；需要写入文件时，可以保存修改副本，或从 RAW、JPEG 参考照片迁移信息到目标副本

- 输入目录内的照片可保留相对目录结构，PNG 仍导出为 PNG，其他支持格式导出为 JPEG；目录外单独添加的照片使用 `_watermarked` 后缀，同名时默认自动编号
- 已有输出默认跳过，启用覆盖后只替换允许覆盖的文件；已导入原片始终受到保护，包括没有勾选的照片
- 取消导出会保留已完成文件，并显示成功、失败和跳过数量

## 设置与快捷键

查看菜单可以切换中英文，也可以打开关于窗口查看作者和项目来源。切换语言会保留照片队列、勾选状态和未保存内容；各版本默认使用程序目录下的 `config` 文件夹

| 文件 | 保存内容 |
| --- | --- |
| `config/config.ini` | 输入输出目录、模板和导出选项 |
| `config/desktop.json` | 桌面样式设置 |
| `config/ui.json` | 语言偏好 |

旧版用户首次启动新版单文件程序时，会尝试迁移 `%LOCALAPPDATA%\ExifFrame` 中的配置，程序旁已有配置优先保留，旧目录文件不会被删除

| 操作 | 快捷键 |
| --- | --- |
| 编辑照片信息 | `Ctrl+I` |
| 组合底部信息 | `Ctrl+Shift+E` |
| 编辑高级源码 | `Ctrl+E` |

## 构建与发布

### 本地打包

补全项目的 `exiftool` 目录后，在 Windows x64 的 Python 3.13 环境中执行

```powershell
python -m pip install -r build_support/requirements-windows.txt
python build_support/build_windows.py
```

生成的程序位于 `build/ExifFrame.exe`，已包含 ExifTool、模板、字体和标识，分发时只需要这个 EXE。构建直接使用本地 ExifTool，NumPy 下载包保存在 `build/download`，存在时复用，不做额外的哈希校验或来源核验

临时依赖和分析文件位于项目外的系统临时目录，结束后自动清理，下载缓存、程序和用户配置保留。构建会限制处理器与内存占用；`--numpy-wheel` 可指定本地 NumPy 包，`--onedir` 可生成需要整目录分发的目录版

### GitHub Release

在 Actions 中手动运行 Windows 发布工作流并填写版本标签，例如 `v2.1.5`，发布新版本时建议选择默认分支，也可以推送 `v` 开头的标签触发。已有标签会构建对应版本，新标签在构建成功后创建；随后自动发布 Release，程序附件为 `ExifFrame.exe`

云端使用 Windows 2025 和 Python 3.13 x64，分别缓存 Python 依赖、NumPy 和 ExifTool。ExifTool 缓存缺失时，从[官方发布目录](https://sourceforge.net/projects/exiftool/files/)下载固定的 13.60 Windows 64 位包；这一步只在云端执行，本地打包仍使用已有文件

重复运行同一版本时，会保留已有发布说明和程序附件，只补全缺失内容。默认分支运行也方便后续标签构建复用缓存，缓存作用域见[GitHub 说明](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#restrictions-for-accessing-a-cache)；其他分支的工作流文件与默认分支不同时，自动发布可能受 [GitHub 权限规则](https://docs.github.com/en/rest/releases/releases#create-a-release)限制

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

## 作者与项目引用

ExifFrame 作者：[Leo-John233](https://github.com/Leo-John233)

| 项目 | 作者 | 与 ExifFrame 的关系 |
| --- | --- | --- |
| [semi-utils](https://github.com/leslievan/semi-utils) | leslievan | 开发基础，提供原始水印处理流程和示例素材 |
| [ExifEditor-GUI](https://github.com/Leo-John233/ExifEditor-GUI) | Leo-John233 | 照片信息编辑与迁移功能的参考，本项目使用独立的 Qt 实现 |
| [ExifTool](https://exiftool.org/) | Phil Harvey | 照片元数据的读取、写入和迁移工具 |

本项目采用 [Apache License 2.0](LICENSE)，相关项目与工具保留各自许可条款，ExifTool 许可见[官方网站](https://exiftool.org/#license)。开发资料见[功能对照与历史性能记录](docs/compatibility-and-performance.md)和[示例照片生成脚本](scripts/build_preview_sample.py)
