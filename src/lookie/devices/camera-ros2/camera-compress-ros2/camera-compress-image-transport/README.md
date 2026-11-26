# camera_compress_transport

Humble `image_transport` 插件包。安装并 source 之后，使用 `image_transport::Publisher` 的节点会发现下面四个 transport。有订阅者时才编码。不支持的编码丢弃该帧并限速打日志。`32FC1` 不会被当成深度。

| transport | 8 位彩色 / mono / Bayer | `16UC1` / `mono16` |
| --- | --- | --- |
| `camera_compress` | JPEG（libjpeg） | PNG |
| `vaapi_compress` | JPEG（VA-API，失败则 libjpeg） | PNG |
| `depth_rvl_compress` | 跳过 | 无损 RVL |
| `depth_png_compress` | 跳过 | PNG，等级 1，RLE |

## 构建

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select camera_compress_transport
source install/setup.bash
ros2 run image_transport list_transports
```

列表中应出现：

```text
image_transport/camera_compress
image_transport/vaapi_compress
image_transport/depth_rvl_compress
image_transport/depth_png_compress
```

## 发布端如何选用

本机 `image_transport` 3.1 的白名单值是插件类名去掉 `_pub`。要保留原始图并打开某个插件：

```text
<基话题点分形式>.enable_pub_plugins:=['image_transport/raw', 'image_transport/<transport>']
```

命名空间 `/camera`、基话题 `/camera/color/image_raw` 时，参数名一般是 `color.image_raw.enable_pub_plugins`。RealSense 节点名是 `camera` 时，再加节点名前缀，例如 `camera.aligned_depth_to_color.image_raw.enable_pub_plugins`。节点启动后用 `ros2 param list` 核对。

不设白名单时，已安装的全部发布插件都会加载，包括上游的 `compressed`。每个插件只在自己的话题有订阅者时才编码。白名单里开多条并且都有订阅者时，CPU 会叠加。

RealSense 只有 `use_intra_process_comms:=false` 时才创建 `image_transport` 发布端。鱼眼当前的 `rclpy` 发布端不会加载插件；需要 `image_transport republish`，`in_transport:=raw`，`out_transport:=<transport>`。

质量参数挂在 `<基话题点分形式>.<transport>.<参数名>` 下。没有写出参数的插件不声明参数。

## 订阅端如何选用

直接订阅 `<基话题>/<transport>`，消息类型 `sensor_msgs/CompressedImage`。这条订阅会让发布端编码，本进程不会解码。

要拿回 `sensor_msgs/Image`，用 `image_transport` 订阅基话题，transport 设为上表里的短名。rqt 会去找类名 `image_transport/<transport>_sub`。启动 rqt 的终端必须先 `source install/setup.bash`，并且 `list_transports` 里能看到该 transport。未 source 时插件列表只有系统自带的 `compressed`、`compressedDepth`、`raw`、`theora`。

## camera_compress

8 位彩色、mono8、Bayer 用 libjpeg 编成 JPEG，彩色统一成 `bgr8` 再编码。`16UC1` 和 `mono16` 编成 PNG。

输出话题是 `<基话题>/camera_compress`。`format` 形如 `bgr8; jpeg compressed bgr8` 或 `16UC1; png compressed 16UC1`。

```text
color.image_raw.camera_compress.jpeg_quality:=90
color.image_raw.camera_compress.png_level:=1
```

`jpeg_quality` 范围 1–100，默认 90。`png_level` 范围 0–9，默认 1。Foxglove 可以显示这两种载荷。

## vaapi_compress

编码范围与 `camera_compress` 相同。彩色 BGR 优先走 VA-API JPEG，pipeline 是 `appsrc`、`videoconvert`（BGR 转 NV12）、`vaapijpegenc`。初始化或编码失败时，该帧退回 libjpeg。mono 不进 VA-API，直接 libjpeg。`16UC1` 和 `mono16` 仍是 CPU 上的 PNG。未设置 `LIBVA_DRIVER_NAME` 时使用 `iHD`。

输出话题是 `<基话题>/vaapi_compress`。`format` 与 `camera_compress` 相同。

```text
color.image_rect_raw.vaapi_compress.jpeg_quality:=90
aligned_depth_to_color.image_raw.vaapi_compress.png_level:=1
```

参数范围和默认值与 `camera_compress` 相同。硬件编码器就绪时日志为 `VA-API JPEG encoder initialized (宽x高, quality=质量)`。Foxglove 可以显示 JPEG 和 PNG。

## depth_rvl_compress

只编码 `16UC1` 和 `mono16`。RVL 按行把连续的 0 做行程编码，其余像素存成差分，无损，不量化，也不按距离截断。

输出话题是 `<基话题>/depth_rvl_compress`。`format` 形如 `16UC1; rvl compressed 16UC1`。`data` 开头是小端的宽、高两个 `uint32`，后面是 RVL 数据，长度总是 4 的倍数。没有质量参数。首帧成功后日志为 `depth_rvl_compress encoding 16UC1 (宽x高)`。

Foxglove 不认这个 `format`，不能把该话题显示成深度图。解码需要本包的订阅插件。

## depth_png_compress

只编码 `16UC1` 和 `mono16`。PNG 压缩等级固定为 1，zlib 策略为 `RLE`。策略写在等级后面，避免 OpenCV 把策略改回默认的 LZ77。不量化，载荷是裸 PNG，没有 `compressedDepth` 的 12 字节头。

输出话题是 `<基话题>/depth_png_compress`。`format` 形如 `16UC1; png compressed 16UC1`。没有质量参数。首帧成功后日志为 `depth_png_compress encoding 16UC1 (宽x高)`。Foxglove 可以把该话题显示成深度图。
