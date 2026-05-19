# ComfyUI Chat Image Bridge

一个用于 ComfyUI 的第三方 API 生图节点，面向 OpenAI-compatible 聊天接口，同时对 Gemini / Nano Banana Pro 这类图片模型做了额外适配。

这个节点不内置任何服务商地址或 API Key。用户需要在节点里填写自己的 `base_url`、`api_key` 和模型名。为了方便上手，默认模型名预填为：

```text
gemini-3-pro-image-preview
```

## 功能

- 支持 OpenAI-compatible `/v1/chat/completions` 生图接口
- 支持自定义 `base_url`、API Key 和模型名
- 支持点击 `Fetch Models` 从 `/v1/models` 获取模型列表
- 支持 1K、2K、4K 分辨率选择
- 支持常见长宽比选择
- 支持 1-2 张参考图输入
- 支持解析 Markdown 图片、图片 URL、`b64_json`、Gemini `inlineData`
- 对 `gemini-3-pro-image-preview` 等 Gemini 图片模型支持原生 `imageConfig`
- 提供高级节点，可输出原始响应和图片引用，方便调试

## 安装

### 启动器安装

如果你的 ComfyUI 启动器支持从 GitHub 仓库安装自定义节点，可以直接填入本仓库地址：

```text
https://github.com/Marigold1122/Chat-Image-Bridge-Node
```

安装后重启 ComfyUI。

### 手动安装

进入 ComfyUI 的 `custom_nodes` 目录：

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Marigold1122/Chat-Image-Bridge-Node.git ComfyUI-ChatImageBridge
```

如果你的环境缺少依赖，可以安装：

```bash
pip install -r ComfyUI-ChatImageBridge/requirements.txt
```

然后重启 ComfyUI。

## 基础节点

添加节点：

```text
api -> Chat Image Bridge -> Chat Image Bridge
```

主要参数：

- `api_key`：你的第三方中转站或模型服务商 API Key
- `base_url`：接口地址，可以填服务商根地址、`/v1` 地址，或完整 `/v1/chat/completions` 地址
- `model`：模型名，默认是 `gemini-3-pro-image-preview`
- `prompt`：提示词
- `resolution`：分辨率，支持 `auto`、`1K`、`2K`、`4K`
- `aspect_ratio`：长宽比，支持 `auto`、`1:1`、`16:9`、`9:16` 等
- `timeout_seconds`：请求超时时间

可选输入：

- `image_1`
- `image_2`

输出：

- `image`

可以直接接到 `Save Image` 或其他 ComfyUI 图像节点。

## base_url 填法

下面几种都可以：

```text
https://example.com
https://example.com/v1
https://example.com/v1/chat/completions
```

节点会自动整理为请求需要的接口地址。

## 获取模型列表

填好 `api_key` 和 `base_url` 后，点击节点里的：

```text
Fetch Models
```

节点会请求：

```text
/v1/models
```

然后把返回的模型列表填入 `model` 下拉框。

如果你的服务商不支持 `/v1/models`，也可以直接手动填写模型名。

## 4K 和长宽比

对于 Gemini 图片模型，例如：

```text
gemini-3-pro-image-preview
```

当 `resolution` 或 `aspect_ratio` 不是 `auto` 时，节点会优先使用 Gemini 原生请求格式，并传入：

```json
{
  "generationConfig": {
    "responseModalities": ["TEXT", "IMAGE"],
    "imageConfig": {
      "imageSize": "4K",
      "aspectRatio": "16:9"
    }
  }
}
```

这样 `4K` 和长宽比会作为真正的图片参数发送，而不是只写进 prompt。

如果服务商不支持 Gemini 原生接口，节点会自动回退到 OpenAI-compatible `/v1/chat/completions`，并把分辨率和比例作为提示词前缀兜底。

## 高级节点

添加节点：

```text
api -> Chat Image Bridge -> Chat Image Bridge Advanced
```

高级节点适合调试或特殊接口，额外提供：

- 原始响应 `response`
- 图片引用 `image_refs`
- `system_prompt`
- `size`
- `extra_body_json`
- 最多 14 张参考图输入

## 注意事项

- API Key 只在节点 UI 里填写，本仓库不会硬编码任何 Key。
- 不同中转站对 OpenAI-compatible 的兼容程度不同，字段支持可能不完全一致。
- 如果 4K 或比例没有生效，请优先确认服务商是否支持 Gemini 原生 `imageConfig`。
- 旧版工作流如果使用过 `endpoint_url`，建议改成新版的 `base_url`。
