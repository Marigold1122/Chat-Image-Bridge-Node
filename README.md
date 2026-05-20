# ComfyUI Chat Image Bridge

一个用于 ComfyUI 的第三方 API 生图节点集合，主要面向 OpenAI-compatible 聊天接口，也包含 GPT Image 专用请求节点。

仓库不会内置任何 API Key 或服务商地址。用户需要在节点里填写自己的 `base_url`、`api_key` 和模型名。

## 功能

- 支持 OpenAI-compatible `/v1/chat/completions` 生图接口
- 支持自定义 `base_url`、API Key 和模型名
- 支持点击 `Fetch Models` 从 `/v1/models` 获取模型列表
- 支持 Gemini / Nano Banana Pro 这类图片模型的原生 `imageConfig`
- 支持 1K、2K、4K 分辨率和常见长宽比
- 支持 1-2 张参考图输入
- 支持解析 Markdown 图片、图片 URL、`b64_json`、Gemini `inlineData`
- 提供 GPT Image 专用节点，使用流式 `/v1/chat/completions`
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

## 通用节点

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

## GPT Image 生图节点

添加节点：

```text
api -> Chat Image Bridge -> GPT Image Generate
```

这个节点面向 GPT Image / Nano Banana 这类绘图接口，使用流式 `/v1/chat/completions`。`base_url` 可以填写服务商根地址、`/v1` 地址，或完整 `/v1/chat/completions` 地址。

生图节点适合纯文生图，或者把输入图当作参考图。你只需要填写 `api_key`、`prompt`，选择模型、分辨率和比例即可。当分辨率和比例都明确选择时，节点内部会自动把 `1K / 2K / 4K` 和比例转换为接口需要的 `size`，例如：

```text
4K + 16:9 -> 3840x2160
2K + 1:1 -> 2048x2048
1K + 9:16 -> 720x1280
```

如果 `resolution` 或 `aspect_ratio` 选择 `auto`，节点不会强制报错；能换算出像素尺寸时会传 `size`，不能换算时会把你的分辨率或比例意图写入流式聊天消息，让服务商按语义处理。

## GPT Image 编辑节点

添加节点：

```text
api -> Chat Image Bridge -> GPT Image Edit
```

编辑节点适合“改这张图”的任务。它只接收一张待编辑图片，不提供 `aspect_ratio`，因为比例直接来自原图。

如果 `resolution=auto`，节点不会传 `size`。如果选择 `1K / 2K / 4K`，节点会读取输入图宽高，保持原图比例，并把最长边换算到对应档位：

```text
1K -> 最长边约 1280
2K -> 最长边约 2048
4K -> 最长边约 3840
```

例如输入图是 `2560x2560`，选择 `4K` 时会传 `3840x3840`；输入图是 `3000x2000`，选择 `4K` 时会传 `3840x2560`。节点不会改写你的 prompt，用户写什么就传什么。

支持的模型：

| 模型 | 分辨率 |
| --- | --- |
| `gpt-image-2-vip` | 1K、2K、4K |
| `gpt-image-2` | 1K |
| `nano-banana` | 1K |
| `nano-banana-2` | 1K、2K、4K |
| `nano-banana-pro` | 1K、2K、4K |

节点使用流式 `/v1/chat/completions` 请求，适合生成时间较长的图片任务，减少 Cloudflare 超时概率。如果服务商在流式响应中返回图片直链，节点会自动下载并转成 ComfyUI 的 `IMAGE`。

## base_url 填法

下面几种都可以：

```text
https://example.com
https://example.com/v1
https://example.com/v1/chat/completions
```

节点会自动整理为请求需要的接口地址。

## 获取模型列表

通用节点填好 `api_key` 和 `base_url` 后，可以点击节点里的：

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

当 `resolution` 或 `aspect_ratio` 不是 `auto` 时，通用节点会优先使用 Gemini 原生请求格式，并传入：

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

GPT Image 节点则会按接口文档传入 `size`，例如 `3840x2160`。

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
- `gpt-image-2` 和 `nano-banana` 在 GPT Image 节点里只开放 1K，选择更高分辨率会直接报错，避免请求失败或产生无效消耗。
- 旧版工作流如果使用过 `endpoint_url`，建议改成新版的 `base_url`。
