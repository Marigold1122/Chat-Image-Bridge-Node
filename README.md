# ComfyUI Chat Image Bridge

ComfyUI custom nodes for image generation through OpenAI-compatible chat APIs,
with extra support for Gemini/Nano Banana Pro style image parameters.

The node does not ship with a built-in provider URL or API key. Users supply
their own OpenAI-compatible base URL and credentials at runtime. The default
model name is `gemini-3-pro-image-preview` as a convenience placeholder; change
it to any model supported by your provider.

## Features

- OpenAI-compatible `/v1/chat/completions` image generation
- `base_url`, API key, and model are user supplied
- `Fetch Models` button for OpenAI-compatible `/v1/models`
- Optional reference image inputs
- `1K`, `2K`, and `4K` resolution controls
- Common aspect ratio controls
- Gemini native `imageConfig` support for models such as `gemini-3-pro-image-preview`
- Decodes Markdown image data URLs, plain image URLs, `b64_json`, and Gemini `inlineData`

## Installation

Clone this repository into your ComfyUI `custom_nodes` directory:

```bash
cd ComfyUI/custom_nodes
git clone <this-repository-url> ComfyUI-ChatImageBridge
```

Install optional Python requirements if your environment does not already have
them:

```bash
pip install -r ComfyUI-ChatImageBridge/requirements.txt
```

Restart ComfyUI.

## Simple Node

Add:

```text
api -> Chat Image Bridge -> Chat Image Bridge
```

Fill:

- `api_key`: your provider API key
- `base_url`: your provider base URL, such as `https://example.com`, `https://example.com/v1`, or a full `/v1/chat/completions` URL
- `model`: the image-capable chat model name
- `prompt`: your image prompt
- `resolution`: `auto`, `1K`, `2K`, or `4K`
- `aspect_ratio`: `auto`, `1:1`, `16:9`, `9:16`, and common ratios

Click `Fetch Models` to query the provider's OpenAI-compatible `/v1/models`
endpoint. The node updates the existing `model` dropdown in place.

Connect `image` to `Save Image` or any downstream image node.

Optional `image_1` and `image_2` inputs send reference images as OpenAI-style
`image_url` data URLs.

## Gemini Image Parameters

For Gemini image models such as `gemini-3-pro-image-preview`, non-auto
resolution/aspect settings are sent through the native Gemini request shape:

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

If the provider does not support the native Gemini endpoint, the node falls back
to OpenAI-compatible `/v1/chat/completions` and keeps the settings as prompt
hints.

## Advanced Node

Use `Chat Image Bridge Advanced` if you need:

- raw response output
- extracted image reference output
- `system_prompt`
- `size`
- custom request fields through `extra_body_json`
- up to 14 reference images

## Notes

- `base_url` may be a provider root URL, a `/v1` URL, or a full `/v1/chat/completions` URL.
- API keys are entered in the node UI and are not hard-coded in this repository.
- Some providers may not support Gemini native endpoints. The node will fall back to OpenAI-compatible chat completions.
