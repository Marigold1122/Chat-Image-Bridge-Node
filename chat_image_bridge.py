import base64
import json
import re
import time
from io import BytesIO
from urllib.parse import quote

import numpy as np
import requests
import torch
from PIL import Image, ImageOps


DATA_IMAGE_RE = re.compile(
    r"data:image/(?P<mime>[A-Za-z0-9.+-]+);base64,(?P<b64>(?:[A-Za-z0-9+/=]|\r|\n)+)",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+", re.I)
GRSAI_PROXY_RE = re.compile(
    r"^https?://grsai-file\d+\.dakka\.com\.cn/cnzfile/(?P<encoded>[^?#]+)(?P<suffix>[?#].*)?$",
    re.I,
)
RESOLUTION_OPTIONS = ["auto", "1K", "2K", "4K"]
ASPECT_RATIO_OPTIONS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9"]
DEFAULT_MODEL = "gemini-3-pro-image-preview"
GPT_IMAGE_DEFAULT_BASE_URL = ""
GPT_IMAGE_MODELS = ["gpt-image-2-vip", "gpt-image-2", "nano-banana", "nano-banana-2", "nano-banana-pro"]
GPT_IMAGE_RESOLUTION_OPTIONS = ["auto", "1K", "2K", "4K"]
GPT_IMAGE_ASPECT_RATIO_OPTIONS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9"]
GPT_IMAGE_MODEL_RESOLUTIONS = {
    "gpt-image-2-vip": {"1K", "2K", "4K"},
    "gpt-image-2": {"1K"},
    "nano-banana": {"1K"},
    "nano-banana-2": {"1K", "2K", "4K"},
    "nano-banana-pro": {"1K", "2K", "4K"},
}
GPT_IMAGE_SIZE_TABLE = {
    "1K": {
        "1:1": "1280x1280",
        "2:3": "848x1280",
        "3:2": "1280x848",
        "3:4": "960x1280",
        "4:3": "1280x960",
        "4:5": "1024x1280",
        "5:4": "1280x1024",
        "9:16": "720x1280",
        "16:9": "1280x720",
        "21:9": "1280x544",
    },
    "2K": {
        "1:1": "2048x2048",
        "2:3": "1360x2048",
        "3:2": "2048x1360",
        "3:4": "1536x2048",
        "4:3": "2048x1536",
        "4:5": "1632x2048",
        "5:4": "2048x1632",
        "9:16": "1152x2048",
        "16:9": "2048x1152",
        "21:9": "2048x864",
    },
    "4K": {
        "1:1": "2880x2880",
        "2:3": "2336x3520",
        "3:2": "3520x2336",
        "3:4": "2480x3312",
        "4:3": "3312x2480",
        "4:5": "2560x3216",
        "5:4": "3216x2560",
        "9:16": "2160x3840",
        "16:9": "3840x2160",
        "21:9": "3840x1632",
    },
}


class RetryableImageGenerationError(RuntimeError):
    def __init__(self, status_code, message, retry_after=None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def normalize_endpoint(base_url):
    value = (base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("base_url is required")
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/images/generations"):
        return value[: -len("/images/generations")] + "/chat/completions"
    if value.endswith("/v1"):
        return f"{value}/chat/completions"
    return f"{value}/v1/chat/completions"


def normalize_images_endpoint(base_url):
    value = (base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("base_url is required")
    if value.endswith("/images/generations"):
        return value
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")] + "/images/generations"
    if value.endswith("/v1"):
        return f"{value}/images/generations"
    return f"{value}/v1/images/generations"


def normalize_models_endpoint(base_url):
    value = (base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("base_url is required")
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")] + "/models"
    if value.endswith("/images/generations"):
        return value[: -len("/images/generations")] + "/models"
    if value.endswith("/v1"):
        return f"{value}/models"
    return f"{value}/v1/models"


def normalize_gemini_base(base_url):
    value = (base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("base_url is required")
    if value.endswith("/chat/completions"):
        value = value[: -len("/chat/completions")]
    if value.endswith("/v1"):
        value = value[: -len("/v1")]
    return value.rstrip("/")


def normalize_gemini_endpoint(base_url, model):
    root = normalize_gemini_base(base_url)
    return f"{root}/v1beta/models/{quote(model, safe='')}:generateContent"


def extract_model_ids(payload):
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or payload.get("model") or []
    else:
        items = []

    models = []
    if isinstance(items, str):
        models.append(items)
    elif isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                models.append(item)
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model")
                if model_id:
                    models.append(str(model_id))

    unique = []
    seen = set()
    for model in models:
        if model not in seen:
            seen.add(model)
            unique.append(model)
    return unique


def compose_prompt(prompt, resolution="auto", aspect_ratio="auto"):
    hints = []
    resolution = (resolution or "auto").strip()
    aspect_ratio = (aspect_ratio or "auto").strip()

    if resolution and resolution.lower() != "auto":
        hints.append(f"Resolution: {resolution}.")
    if aspect_ratio and aspect_ratio.lower() != "auto":
        hints.append(f"Aspect ratio: {aspect_ratio}.")

    if not hints:
        return prompt
    return "\n".join(hints + [prompt])


def normalize_generation_option(value):
    value = (value or "").strip()
    if not value or value.lower() == "auto":
        return ""
    return value


def gpt_image_size_for(model, resolution, aspect_ratio):
    model = (model or "").strip()
    resolution = (resolution or "auto").strip()
    aspect_ratio = (aspect_ratio or "auto").strip()

    if resolution.lower() == "auto" and aspect_ratio.lower() == "auto":
        return ""
    if resolution.lower() == "auto" or aspect_ratio.lower() == "auto":
        raise ValueError("GPT Image requires both resolution and aspect_ratio to be set together, or both set to auto")

    supported = GPT_IMAGE_MODEL_RESOLUTIONS.get(model)
    if not supported:
        raise ValueError(f"Unsupported GPT Image model: {model}")
    if resolution not in supported:
        allowed = ", ".join(sorted(supported))
        raise ValueError(f"{model} supports resolution {allowed}, but got {resolution}")

    try:
        return GPT_IMAGE_SIZE_TABLE[resolution][aspect_ratio]
    except KeyError as exc:
        raise ValueError(f"Unsupported GPT Image size option: {resolution} {aspect_ratio}") from exc


def retry_after_seconds_from_response(response):
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0, int(float(retry_after)))
        except (TypeError, ValueError):
            pass

    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        for key in ("retry_after", "retryAfter", "retry_after_seconds", "retryAfterSeconds"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return max(0, int(value))
            if isinstance(value, str):
                try:
                    return max(0, int(float(value)))
                except ValueError:
                    continue

    return None


def tensor_to_png_data_url(tensor):
    image = tensor.detach().cpu() if isinstance(tensor, torch.Tensor) else torch.as_tensor(tensor)
    if image.ndim == 4:
        image = image[0]
    if image.ndim != 3:
        raise ValueError(f"Expected IMAGE tensor with 3 or 4 dimensions, got shape {tuple(image.shape)}")

    # ComfyUI images are usually HWC, but accept CHW tensors defensively.
    if image.shape[0] in (1, 3, 4) and image.shape[-1] not in (1, 3, 4):
        image = image.permute(1, 2, 0)

    arr = image.clamp(0, 1).numpy()
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    arr = (arr * 255.0).round().astype(np.uint8)

    pil = Image.fromarray(arr)
    if pil.mode not in ("RGB", "RGBA"):
        pil = pil.convert("RGB")

    buffer = BytesIO()
    pil.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def tensor_to_png_inline_data(tensor):
    data_url = tensor_to_png_data_url(tensor)
    return {"mimeType": "image/png", "data": data_url.split(",", 1)[1]}


def image_bytes_to_tensor(image_bytes):
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    arr = np.array(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0).float()


def data_url_to_bytes(value):
    match = DATA_IMAGE_RE.search(value or "")
    if not match:
        raise ValueError("Invalid data:image base64 value")
    b64 = re.sub(r"\s+", "", match.group("b64"))
    return base64.b64decode(b64)


def extract_image_references(text):
    if not text:
        return []

    refs = []
    refs.extend(match.group(0) for match in DATA_IMAGE_RE.finditer(text))
    refs.extend(match.group(0).rstrip(".,") for match in URL_RE.finditer(text))

    unique = []
    seen = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def collect_image_references(value):
    refs = []
    if isinstance(value, str):
        refs.extend(extract_image_references(value))
    elif isinstance(value, list):
        for item in value:
            refs.extend(collect_image_references(item))
    elif isinstance(value, dict):
        inline_data = value.get("inlineData") or value.get("inline_data")
        if isinstance(inline_data, dict) and isinstance(inline_data.get("data"), str):
            mime = inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png"
            refs.append(f"data:{mime};base64,{inline_data['data']}")

        for key, item in value.items():
            if key == "b64_json" and isinstance(item, str):
                if item.strip().lower().startswith("data:image/"):
                    refs.append(item.strip())
                else:
                    refs.append("data:image/png;base64," + item)
            else:
                refs.extend(collect_image_references(item))

    unique = []
    seen = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def redact_data_urls(text):
    def repl(match):
        mime = match.group("mime")
        b64_len = len(re.sub(r"\s+", "", match.group("b64")))
        return f"data:image/{mime};base64,<redacted {b64_len} chars>"

    return DATA_IMAGE_RE.sub(repl, text)


def redact_object(value):
    if isinstance(value, str):
        return redact_data_urls(value)
    if isinstance(value, list):
        return [redact_object(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_object(item) for key, item in value.items()}
    return value


def summarize_ref(ref):
    match = DATA_IMAGE_RE.search(ref or "")
    if match:
        b64_len = len(re.sub(r"\s+", "", match.group("b64")))
        return f"data:image/{match.group('mime')};base64,<redacted {b64_len} chars>"
    return ref


def image_url_candidates(url):
    candidates = [url]
    match = GRSAI_PROXY_RE.match(url or "")
    if match:
        decoded = match.group("encoded").replace("_d_", ".").replace("_x_", "/")
        if "/" in decoded:
            host, path = decoded.split("/", 1)
            if "." in host and path:
                candidates.append(f"https://{host}/{path}{match.group('suffix') or ''}")

    unique = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


class ChatImageBridgeBase:
    def _image_config(self, resolution="", aspect_ratio=""):
        image_config = {}
        resolution = normalize_generation_option(resolution)
        aspect_ratio = normalize_generation_option(aspect_ratio)

        if resolution:
            image_config["imageSize"] = resolution
        if aspect_ratio:
            image_config["aspectRatio"] = aspect_ratio
        return image_config

    def _build_payload(
        self,
        model,
        prompt,
        system_prompt,
        size,
        extra_body_json,
        image_inputs,
        resolution="",
        aspect_ratio="",
    ):
        image_data_urls = [tensor_to_png_data_url(image) for image in image_inputs if image is not None]
        if image_data_urls:
            content = [{"type": "text", "text": prompt}]
            content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_data_urls)
        else:
            content = prompt

        messages = []
        if (system_prompt or "").strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        if (size or "").strip():
            payload["size"] = size.strip()

        image_config = self._image_config(resolution, aspect_ratio)
        if image_config:
            payload["generationConfig"] = {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": image_config,
            }

        if (extra_body_json or "").strip():
            extra = json.loads(extra_body_json)
            if not isinstance(extra, dict):
                raise ValueError("extra_body_json must be a JSON object")
            payload.update(extra)

        return payload

    def _build_gemini_payload(self, prompt, system_prompt, extra_body_json, image_inputs, resolution="", aspect_ratio=""):
        parts = []
        for image in image_inputs:
            if image is not None:
                parts.append({"inlineData": tensor_to_png_inline_data(image)})
        parts.append({"text": prompt})

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
            },
        }

        image_config = self._image_config(resolution, aspect_ratio)
        if image_config:
            payload["generationConfig"]["imageConfig"] = image_config

        if (system_prompt or "").strip():
            payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}

        if (extra_body_json or "").strip():
            extra = json.loads(extra_body_json)
            if not isinstance(extra, dict):
                raise ValueError("extra_body_json must be a JSON object")
            payload.update(extra)

        return payload

    def _should_use_native_gemini(self, model, resolution="", aspect_ratio=""):
        model_name = (model or "").lower()
        has_image_config = bool(self._image_config(resolution, aspect_ratio))
        return has_image_config and "gemini" in model_name

    def _post_with_retries(self, endpoint, api_key, payload, timeout_seconds, retry_times):
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "User-Agent": "ComfyUI-ChatImageBridge/1.0",
        }

        last_error = None
        for attempt in range(1, retry_times + 1):
            try:
                response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_seconds)
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
                return response.json()
            except Exception as exc:
                last_error = exc
                if attempt < retry_times:
                    time.sleep(min(2 * attempt, 8))
        raise RuntimeError(f"Chat image request failed after {retry_times} attempt(s): {last_error}")

    def _decode_refs_to_image(self, refs, timeout_seconds):
        tensors = []
        decoded_refs = []

        for ref in refs:
            try:
                if ref.lower().startswith("data:image/"):
                    image_bytes = data_url_to_bytes(ref)
                else:
                    last_error = None
                    image_bytes = None
                    for url in image_url_candidates(ref):
                        try:
                            response = requests.get(
                                url,
                                timeout=timeout_seconds,
                                headers={
                                    "User-Agent": "Mozilla/5.0",
                                    "Accept": "image/*,*/*;q=0.8",
                                },
                            )
                            response.raise_for_status()
                            image_bytes = response.content
                            break
                        except Exception as exc:
                            last_error = exc
                    if image_bytes is None:
                        raise last_error or RuntimeError("image download failed")

                tensor = image_bytes_to_tensor(image_bytes)
                tensors.append(tensor)
                decoded_refs.append(ref)
            except Exception as exc:
                print(f"[Chat Image Bridge] Skipped image reference: {summarize_ref(ref)} ({exc})")

        if not tensors:
            raise RuntimeError("No decodable image was found in the chat completion response")

        base_shape = tensors[0].shape[1:]
        same_shape = [tensor for tensor in tensors if tensor.shape[1:] == base_shape]
        if len(same_shape) != len(tensors):
            print("[Chat Image Bridge] Returned images have different sizes; outputting images matching the first size.")

        return torch.cat(same_shape, dim=0), decoded_refs

    def _generate(
        self,
        api_key,
        base_url,
        model,
        prompt,
        system_prompt,
        size,
        extra_body_json,
        timeout_seconds,
        retry_times,
        redact_response,
        resolution="",
        aspect_ratio="",
        **kwargs,
    ):
        if not (api_key or "").strip():
            raise ValueError("api_key is required")
        if not (model or "").strip():
            raise ValueError("model is required")
        if not (prompt or "").strip():
            raise ValueError("prompt is required")

        image_inputs = [kwargs.get(f"image_{i:02d}") for i in range(1, 15)]

        if self._should_use_native_gemini(model, resolution, aspect_ratio):
            try:
                endpoint = normalize_gemini_endpoint(base_url, model.strip())
                payload = self._build_gemini_payload(
                    prompt,
                    system_prompt,
                    extra_body_json,
                    image_inputs,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                )
                data = self._post_with_retries(endpoint, api_key, payload, int(timeout_seconds), int(retry_times))
            except Exception as exc:
                print(f"[Chat Image Bridge] Native Gemini request failed; falling back to chat/completions: {exc}")
                endpoint = normalize_endpoint(base_url)
                payload = self._build_payload(
                    model.strip(),
                    compose_prompt(prompt, resolution, aspect_ratio),
                    system_prompt,
                    size,
                    extra_body_json,
                    image_inputs,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                )
                data = self._post_with_retries(endpoint, api_key, payload, int(timeout_seconds), int(retry_times))
        else:
            endpoint = normalize_endpoint(base_url)
            payload = self._build_payload(
                model.strip(),
                compose_prompt(prompt, resolution, aspect_ratio),
                system_prompt,
                size,
                extra_body_json,
                image_inputs,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
            )
            data = self._post_with_retries(endpoint, api_key, payload, int(timeout_seconds), int(retry_times))

        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            refs = collect_image_references(message)
        else:
            refs = []

        if not refs:
            refs = collect_image_references(data)
        if not refs:
            preview = json.dumps(redact_object(data), ensure_ascii=False)[:2000]
            raise RuntimeError(f"Chat completion response did not contain image data or image URLs: {preview}")

        image, decoded_refs = self._decode_refs_to_image(refs, int(timeout_seconds))
        response_obj = redact_object(data) if redact_response else data
        response_text = json.dumps(response_obj, ensure_ascii=False, indent=2)
        refs_text = "\n".join(summarize_ref(ref) for ref in decoded_refs)
        return image, response_text, refs_text


class ChatImageBridge(ChatImageBridgeBase):
    """Clean image generator node for OpenAI-compatible chat/completions endpoints."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "base_url": ("STRING", {"default": "", "multiline": False}),
                "model": ("STRING", {"default": DEFAULT_MODEL, "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "resolution": (RESOLUTION_OPTIONS, {"default": "auto"}),
                "aspect_ratio": (ASPECT_RATIO_OPTIONS, {"default": "auto"}),
                "timeout_seconds": ("INT", {"default": 300, "min": 30, "max": 1800}),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "generate"
    CATEGORY = "api/Chat Image Bridge"

    def generate(
        self,
        api_key,
        base_url,
        model,
        prompt,
        resolution,
        aspect_ratio,
        timeout_seconds,
        image_1=None,
        image_2=None,
    ):
        image, _, _ = self._generate(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prompt=prompt,
            system_prompt="",
            size="",
            extra_body_json="",
            timeout_seconds=timeout_seconds,
            retry_times=1,
            redact_response=True,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            image_01=image_1,
            image_02=image_2,
        )
        return (image,)


class ChatImageBridgeAdvanced(ChatImageBridgeBase):
    """Advanced image generator node with raw response outputs and request overrides."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "base_url": ("STRING", {"default": "", "multiline": False}),
                "model": ("STRING", {"default": DEFAULT_MODEL, "multiline": False}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "system_prompt": ("STRING", {"default": "", "multiline": True}),
                "size": ("STRING", {"default": "", "multiline": False}),
                "extra_body_json": ("STRING", {"default": "", "multiline": True}),
                "timeout_seconds": ("INT", {"default": 300, "min": 30, "max": 1800}),
                "retry_times": ("INT", {"default": 1, "min": 1, "max": 10}),
                "redact_response": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                **{f"image_{i:02d}": ("IMAGE",) for i in range(1, 15)},
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "response", "image_refs")
    FUNCTION = "generate"
    CATEGORY = "api/Chat Image Bridge"

    def generate(
        self,
        api_key,
        base_url,
        model,
        prompt,
        system_prompt,
        size,
        extra_body_json,
        timeout_seconds,
        retry_times,
        redact_response,
        **kwargs,
    ):
        return self._generate(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            size=size,
            extra_body_json=extra_body_json,
            timeout_seconds=timeout_seconds,
            retry_times=retry_times,
            redact_response=redact_response,
            **kwargs,
        )


class GPTImage(ChatImageBridgeBase):
    """GPT image node using the image generations endpoint."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "base_url": ("STRING", {"default": GPT_IMAGE_DEFAULT_BASE_URL, "multiline": False}),
                "model": (GPT_IMAGE_MODELS, {"default": "gpt-image-2-vip"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "resolution": (GPT_IMAGE_RESOLUTION_OPTIONS, {"default": "1K"}),
                "aspect_ratio": (GPT_IMAGE_ASPECT_RATIO_OPTIONS, {"default": "1:1"}),
                "timeout_seconds": ("INT", {"default": 600, "min": 60, "max": 3600}),
            },
            "optional": {
                "image_1": ("IMAGE",),
                "image_2": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "generate"
    CATEGORY = "api/Chat Image Bridge"

    def _build_payload(self, model, prompt, size, image_inputs):
        image_refs = [
            tensor_to_png_inline_data(image)["data"]
            for image in image_inputs
            if image is not None
        ]
        payload = {
            "model": model,
            "prompt": prompt,
            "image": image_refs,
            "response_format": "url",
        }
        if (size or "").strip():
            payload["size"] = size
        return payload

    def _post_image_generation(self, endpoint, api_key, payload, timeout_seconds):
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ComfyUI-ChatImageBridge/1.0",
            "Connection": "close",
        }

        last_error = None
        trust_env = True
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                return self._post_image_generation_once(
                    endpoint,
                    headers,
                    payload,
                    timeout_seconds,
                    trust_env=trust_env,
                )
            except requests.exceptions.SSLError as exc:
                last_error = exc
                if trust_env:
                    print("[Chat Image Bridge] GPT Image request failed with SSL error; retrying without environment proxy settings.")
                    time.sleep(1)
                    trust_env = False
                    continue
                break
            except RetryableImageGenerationError as exc:
                last_error = exc
                if attempt < max_attempts:
                    wait_seconds = exc.retry_after if exc.retry_after is not None else 120
                    print(f"[Chat Image Bridge] GPT Image request returned HTTP {exc.status_code}; retrying in {wait_seconds} seconds.")
                    time.sleep(wait_seconds)
                    continue
                break

        raise last_error or RuntimeError("GPT Image request failed")

    def _post_image_generation_once(self, endpoint, headers, payload, timeout_seconds, trust_env=True):
        session = requests.Session()
        session.trust_env = trust_env

        with session.post(endpoint, headers=headers, json=payload, timeout=timeout_seconds) as response:
            if response.status_code >= 400:
                if response.status_code == 524:
                    retry_after = retry_after_seconds_from_response(response) or 120
                    raise RetryableImageGenerationError(
                        response.status_code,
                        f"HTTP {response.status_code}: {response.text[:1000]}",
                        retry_after=retry_after,
                    )
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")

            data = response.json()
            refs = collect_image_references(data)
            if not refs:
                preview = json.dumps(redact_object(data), ensure_ascii=False)[:2000]
                raise RuntimeError(f"GPT Image response did not contain image data or image URLs: {preview}")

            return data, refs

    def generate(self, api_key, base_url, model, prompt, resolution, aspect_ratio, timeout_seconds, image_1=None, image_2=None):
        if not (api_key or "").strip():
            raise ValueError("api_key is required")
        if not (base_url or "").strip():
            raise ValueError("base_url is required")
        if not (prompt or "").strip():
            raise ValueError("prompt is required")

        model = (model or "").strip()
        size = gpt_image_size_for(model, resolution, aspect_ratio)
        endpoint = normalize_images_endpoint(base_url)
        payload = self._build_payload(model, prompt, size, [image_1, image_2])
        _, refs = self._post_image_generation(endpoint, api_key, payload, int(timeout_seconds))
        image, _ = self._decode_refs_to_image(refs, int(timeout_seconds))
        return (image,)


RightCodesGPTImage = GPTImage

NODE_CLASS_MAPPINGS = {
    "ChatImageBridge": ChatImageBridge,
    "ChatImageBridgeAdvanced": ChatImageBridgeAdvanced,
    "GPTImage": GPTImage,
    "RightCodesGPTImage": GPTImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ChatImageBridge": "Chat Image Bridge",
    "ChatImageBridgeAdvanced": "Chat Image Bridge Advanced",
    "GPTImage": "GPT Image",
    "RightCodesGPTImage": "GPT Image",
}
