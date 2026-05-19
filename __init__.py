import asyncio

from aiohttp import web

from server import PromptServer

from .chat_image_bridge import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
    extract_model_ids,
    normalize_models_endpoint,
)


def _fetch_models(base_url, api_key, timeout_seconds):
    import requests

    endpoint = normalize_models_endpoint(base_url)
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
        "User-Agent": "ComfyUI-ChatImageBridge/1.0",
    }
    response = requests.get(endpoint, headers=headers, timeout=timeout_seconds)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")

    payload = response.json()
    return endpoint, extract_model_ids(payload)


@PromptServer.instance.routes.post("/chat_image_bridge/models")
async def fetch_chat_image_bridge_models(request):
    try:
        body = await request.json()
        base_url = (body.get("base_url") or body.get("endpoint_url") or "").strip()
        api_key = (body.get("api_key") or "").strip()
        timeout_seconds = int(body.get("timeout_seconds") or 30)

        if not base_url:
            return web.json_response({"error": "base_url is required"}, status=400)
        if not api_key:
            return web.json_response({"error": "api_key is required"}, status=400)

        endpoint, models = await asyncio.to_thread(_fetch_models, base_url, api_key, timeout_seconds)
        return web.json_response({"models": models, "models_endpoint": endpoint})
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
