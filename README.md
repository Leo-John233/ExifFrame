# ExifFrame

ExifFrame 是一款 Windows 照片水印工具，支持批量处理照片、编辑拍摄信息和自定义水印模板

本项目基于 [leslievan](https://github.com/leslievan) 的开源项目 [semi-utils](https://github.com/leslievan/semi-utils) 开发，感谢原作者的开源工作

在原有处理流程上，ExifFrame 增加了独立桌面窗口、可视化模板编辑、照片信息编辑和中英文切换，日常操作都在桌面窗口中完成

## 主要功能

- 批量添加水印，支持 JPEG、PNG 和 HEIC 等常见照片格式
- 浏览照片并对照原图，实时查看模板和文字修改后的效果
- 自由组合相机、镜头、曝光、日期、地理位置等信息，也可加入自定义文字
- 编辑照片信息，默认只用于水印，按需保存修改副本或迁移其他照片的信息
- 新建和保存模板，保留 JSON/Jinja 源码编辑方式
- 在简体中文和英文之间切换，保留照片队列和未保存内容

## 运行

### 安装依赖并启动

当前开发和打包环境使用 Python 3.13，建议先激活自己的虚拟环境，再在项目目录执行

```powershell
python -m pip install -r requirements.txt
python main.py
```

`main.py` 启动桌面窗口，原有浏览器界面可通过 `python web_server.py` 启动，两个入口共用图像处理和照片信息读取逻辑

### 准备 ExifTool

从 [ExifTool 官网](https://exiftool.org/) 下载 Windows 版本，解压后放入项目的 `exiftool` 目录，并保留以下结构

```text
exiftool/
├── exiftool.exe
└── exiftool_files/
```

程序也支持官网下载包中的 `exiftool(-k).exe`，可以直接使用原文件名

没有 ExifTool 时，程序会尝试读取照片自带的 EXIF 信息，保存修改副本和迁移照片信息则需要完整的 ExifTool 文件

## 使用方式

1. 设置输入和输出目录，添加照片或将照片拖入窗口
2. 在文件列表中勾选需要处理的照片，选择合适的水印模板
3. 预览水印效果，按需调整文字、颜色、缩放和底部留白
4. 设置 JPEG 质量和覆盖选项，导出后在输出列表中查看结果

水印缩放默认为 100%，文字和标识沿用模板比例，底部留白可以自动计算，也可以手动调整

保存设置用于记录目录、导出选项和快捷样式，保存模板用于保留水印内容与组合

## 编辑水印模板

新建模板时，可以从内置样式、当前模板或空白边框开始，页面默认使用项目自带的示例照片，没有导入照片也能预览

点击模板区的“组合底部信息”，选择文字区域，再添加需要的字段

1. 选择左上、左下、右上或右下，无边框模板会列出自身的文字区域
2. 添加相机、镜头、焦距、光圈、快门、ISO 等字段，也可输入自定义文字
3. 拖动字段或使用上移、下移调整顺序，设置分隔符和字段前后的文字
4. 查看实时预览，完成后保存模板或另存为新模板

例如，左上可以组合成 `ISO160 | Alice | 1/250s`，右下可以放置日期和版权，缺失的信息可以隐藏，也可以显示为破折号

编辑窗口支持最小化和最大化，也可以收起编辑窗口回到主窗口查看，未保存的组合会保留

需要自定义处理流程时，可以通过高级源码编辑 JSON/Jinja 模板

切换编辑方式时，草稿和已有的高级表达式会保留

### 日期、位置和特殊字符

- 水印日期默认显示为 `2026.11.04`，需要具体时间时可添加拍摄时间或日期与时间字段
- 地理位置将经纬度合为一项，以度分秒显示，例如 `26°9'12"N 119°17'8"E`，缺少任一坐标时会隐藏整项
- 海拔显示为 `3555m`，海平面以下显示为 `-3555m`，有小数时会保留有效数值
- 自定义文字支持 `ℤ`、`ℝ`、`ℂ`、`𝕫` 等符号，预览和导出保留输入的字符

这些格式只影响水印显示，照片中的原始 EXIF 信息保持不变

### 常用快捷键

| 操作 | 快捷键 |
| --- | --- |
| 编辑照片信息 | `Ctrl+I` |
| 组合底部信息 | `Ctrl+Shift+E` |
| 编辑高级源码 | `Ctrl+E` |

## 编辑照片信息

照片信息编辑器支持相机、镜头、曝光、拍摄时间、版权和 GPS 等 27 项信息

修改默认只用于当前会话的预览和水印导出，原照片保持不变

需要把信息写入文件时，可以保存修改副本，也可以从 RAW 或 JPEG 参考照片迁移信息到目标副本

在组合面板中也可以打开“修改照片信息”，调整后的数值会同步用于当前预览

## 导出与原片保护

- 输入目录中的照片可以按原目录结构导出，PNG 保持为 PNG，其他支持格式导出为 JPEG
- 同名输出默认跳过，启用覆盖后只替换输出文件，已导入的原照片始终受到保护
- 单独添加的照片使用 `_watermarked` 后缀，遇到同名文件时默认自动编号
- 导出范围以当前勾选的照片为准，未勾选的原照片也会受到保护
- 取消导出后，已经完成的文件会保留，并显示成功、失败和跳过数量

## 语言与设置

在菜单中选择简体中文或英文，切换语言时会保留照片队列、勾选状态和未保存内容

源码和目录版使用程序目录下的 `config` 文件夹

| 文件 | 用途 |
| --- | --- |
| `config/config.ini` | 输入输出目录、模板和导出选项 |
| `config/desktop.json` | 桌面样式设置 |
| `config/ui.json` | 语言偏好 |

单文件版首次运行后，会在 `%LOCALAPPDATA%\ExifFrame` 中保存配置和自建模板，更新 EXE 后仍可继续使用

## 打包

Windows x64 打包使用 Python 3.13，先准备好 ExifTool，再在项目目录执行

```powershell
python -m pip install -r build_support/requirements-windows.txt
python build_support/build_windows.py
```

生成的单文件位于 `build/ExifFrame.exe`，分发时只需要这个 EXE

脚本会自动准备所需的 NumPy 依赖，并在构建结束后清理临时文件

使用已有依赖文件时，可通过 `--numpy-wheel` 指定路径，目录版可通过 `--onedir` 构建

## 模板示例

| 模板 | 说明 | 效果 |
| --- | --- | --- |
| [经典相机边框](static/standard1.json) | 展示相机、镜头和拍摄参数 | ![经典相机边框](static/standard1.jpeg) |
| [留白与阴影](static/standard2.json) | 圆角照片搭配阴影和宽边框 | ![留白与阴影](static/standard2.jpeg) |
| [沉浸模糊背景](static/blur.json) | 延展画面色彩，居中显示拍摄信息 | ![沉浸模糊背景](static/blur.jpeg) |
| [尼康模糊背景](static/nikon_blur.json) | 适合尼康照片的专属版式 | ![尼康模糊背景](static/nikon_blur.jpeg) |
| [极简参数](static/normal1.json) | 在右下角显示拍摄参数 | ![极简参数](static/normal1.jpeg) |
| [旅途与时间](static/normal2.json) | 显示文件夹名称和拍摄时间 | ![旅途与时间](static/normal2.jpeg) |
| [品牌居中](static/center_logo.json) | 标识居中，两侧可自由组合文字 | ![品牌居中](static/center_logo.jpeg) |
| [仅品牌标识](static/center_logo_only.json) | 在底部居中显示品牌标识 | ![仅品牌标识](static/center_logo_only.jpeg) |

## 开发说明

功能对照、兼容性说明和性能记录见 [网页功能对照与性能验证](docs/compatibility-and-performance.md)

示例照片来自上游项目样图中的照片区域，制作过程见 [示例照片生成脚本](scripts/build_preview_sample.py)

## 许可证

本项目采用 [Apache License 2.0](LICENSE)，原始许可证文件保留在仓库中

ExifTool 的许可条款见 [官方说明](https://exiftool.org/#license)
