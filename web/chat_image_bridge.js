import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_CLASS = "ChatImageBridge";
const FETCH_BUTTON = "Fetch Models";

function findWidget(node, name) {
	return node.widgets?.find((widget) => widget.name === name);
}

function markCanvasDirty() {
	app.graph?.setDirtyCanvas?.(true, true);
	app.canvas?.setDirty?.(true, true);
}

function setWidgetValue(widget, value) {
	if (!widget) {
		return;
	}
	widget.value = value;
	widget.callback?.(value);
}

function prepareModelWidget(node) {
	const modelWidget = findWidget(node, "model");
	if (!modelWidget) {
		return;
	}

	const currentModel = `${modelWidget.value || ""}`.trim();
	const existingValues = Array.isArray(modelWidget.options?.values) ? modelWidget.options.values : [];
	const values = ["", currentModel, ...existingValues]
		.map((value) => `${value || ""}`.trim())
		.filter((value, index, array) => index === array.indexOf(value));

	modelWidget.options = modelWidget.options || {};
	modelWidget.options.values = values;
	modelWidget.type = "combo";
}

function updateModelDropdown(node, models) {
	const modelWidget = findWidget(node, "model");
	if (!modelWidget) {
		throw new Error("model widget was not found");
	}

	const currentModel = `${modelWidget?.value || ""}`.trim();
	const selected = currentModel && models.includes(currentModel) ? currentModel : models[0];

	modelWidget.options = modelWidget.options || {};
	modelWidget.options.values = models.includes("") ? models : ["", ...models];
	modelWidget.type = "combo";
	setWidgetValue(modelWidget, selected);

	markCanvasDirty();
	return selected;
}

async function fetchModels(node) {
	const apiKey = `${findWidget(node, "api_key")?.value || ""}`.trim();
	const baseUrl = `${findWidget(node, "base_url")?.value || findWidget(node, "endpoint_url")?.value || ""}`.trim();
	const timeoutSeconds = Number(findWidget(node, "timeout_seconds")?.value || 30);

	if (!baseUrl) {
		window.alert("base_url is required");
		return;
	}
	if (!apiKey) {
		window.alert("api_key is required");
		return;
	}

	try {
		const response = await api.fetchApi("/chat_image_bridge/models", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				base_url: baseUrl,
				api_key: apiKey,
				timeout_seconds: Math.max(5, Math.min(timeoutSeconds, 120)),
			}),
		});
		const data = await response.json();

		if (!response.ok || data.error) {
			throw new Error(data.error || `HTTP ${response.status}`);
		}

		const models = Array.isArray(data.models) ? data.models.filter(Boolean) : [];
		if (!models.length) {
			throw new Error("No models were returned by the provider");
		}

		updateModelDropdown(node, models);
	} catch (error) {
		console.error("[Chat Image Bridge] Failed to fetch models:", error);
		window.alert(`Failed to fetch models: ${error.message || error}`);
	}
}

app.registerExtension({
	name: "Comfy.ChatImageBridge.Models",
	async beforeRegisterNodeDef(nodeType, nodeData) {
		if (nodeData.name !== NODE_CLASS) {
			return;
		}

		const onNodeCreated = nodeType.prototype.onNodeCreated;
		nodeType.prototype.onNodeCreated = function () {
			const result = onNodeCreated?.apply(this, arguments);
			prepareModelWidget(this);

			if (!findWidget(this, FETCH_BUTTON)) {
				const fetchButton = this.addWidget("button", FETCH_BUTTON, null, () => fetchModels(this));
				fetchButton.serialize = false;
			}

			return result;
		};
	},
});
