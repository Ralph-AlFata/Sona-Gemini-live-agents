import { toPng } from "html-to-image";
import katex from "katex";
import "katex/dist/katex.min.css";

export type CanvasTextFormat = "plain" | "latex";

export interface ResolvedCanvasText {
  displayMode: boolean;
  format: CanvasTextFormat;
  rawText: string;
  renderText: string;
}

interface LatexRenderResult {
  height: number;
  image: HTMLImageElement;
  width: number;
}

const LATEX_FONT_SCALE = 0.72;
const renderCache = new Map<string, Promise<LatexRenderResult>>();

function isWrapped(text: string, start: string, end: string): boolean {
  return text.startsWith(start) && text.endsWith(end) && text.length > start.length + end.length;
}

function inferLatexFromText(rawText: string): { displayMode: boolean; format: CanvasTextFormat; renderText: string } {
  const trimmed = rawText.trim();
  if (isWrapped(trimmed, "$$", "$$")) {
    return { displayMode: true, format: "latex", renderText: trimmed.slice(2, -2).trim() };
  }
  if (isWrapped(trimmed, "\\[", "\\]")) {
    return { displayMode: true, format: "latex", renderText: trimmed.slice(2, -2).trim() };
  }
  if (isWrapped(trimmed, "$", "$")) {
    return { displayMode: false, format: "latex", renderText: trimmed.slice(1, -1).trim() };
  }
  if (isWrapped(trimmed, "\\(", "\\)")) {
    return { displayMode: false, format: "latex", renderText: trimmed.slice(2, -2).trim() };
  }
  return { displayMode: false, format: "plain", renderText: rawText };
}

function loadImageFromUrl(src: string, width: number, height: number): Promise<LatexRenderResult> {
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve({ image, width, height });
    image.onerror = () => reject(new Error("Failed to load rendered LaTeX image"));
    image.src = src;
  });
}

function createRenderRoot(): HTMLDivElement {
  const root = document.createElement("div");
  root.style.position = "fixed";
  root.style.left = "-10000px";
  root.style.top = "0";
  root.style.pointerEvents = "none";
  root.style.opacity = "0";
  root.style.background = "transparent";
  root.style.padding = "0";
  root.style.margin = "0";
  root.style.zIndex = "-1";
  document.body.appendChild(root);
  return root;
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

export function resolveCanvasText(
  rawText: string,
  options?: { displayMode?: unknown; textFormat?: unknown },
): ResolvedCanvasText {
  const inferred = inferLatexFromText(rawText);
  const format = options?.textFormat === "latex" || options?.textFormat === "plain"
    ? options.textFormat
    : inferred.format;
  const displayMode = typeof options?.displayMode === "boolean"
    ? options.displayMode
    : inferred.displayMode;
  return {
    rawText,
    format,
    displayMode,
    renderText: format === "latex" ? (inferred.format === "latex" ? inferred.renderText : rawText) : rawText,
  };
}

export function estimateLatexSize(text: string, fontSize: number, displayMode: boolean): { height: number; width: number } {
  const effectiveFontSize = fontSize * LATEX_FONT_SCALE;
  const charWidth = displayMode ? 0.7 : 0.58;
  return {
    width: Math.max(effectiveFontSize, text.trim().length * effectiveFontSize * charWidth),
    height: Math.max(
      effectiveFontSize * 1.1,
      displayMode ? effectiveFontSize * 1.35 : effectiveFontSize * 1.05,
    ),
  };
}

export function getLatexRender(
  latex: string,
  options: { color: string; displayMode: boolean; fontSize: number },
): Promise<LatexRenderResult> {
  const { color, displayMode, fontSize } = options;
  const effectiveFontSize = fontSize * LATEX_FONT_SCALE;
  const cacheKey = JSON.stringify({ latex, color, displayMode, effectiveFontSize });
  const cached = renderCache.get(cacheKey);
  if (cached) return cached;

  const renderPromise = (async () => {
    const root = createRenderRoot();
    try {
      const wrapper = document.createElement("div");
      wrapper.style.display = "inline-block";
      wrapper.style.background = "transparent";
      wrapper.style.color = color;
      wrapper.style.padding = "0";
      wrapper.style.margin = "0";
      wrapper.style.lineHeight = "1";
      wrapper.style.width = "fit-content";
      wrapper.style.fontSize = `${effectiveFontSize}px`;

      wrapper.innerHTML = katex.renderToString(latex, {
        displayMode,
        output: "html",
        strict: "ignore",
        throwOnError: false,
      });

      const renderedElement = wrapper.firstElementChild as HTMLElement | null;
      if (renderedElement) {
        renderedElement.style.margin = "0";
        renderedElement.style.padding = "0";
        renderedElement.style.lineHeight = "1";
        renderedElement.style.textAlign = "left";
      }

      const displayElement = wrapper.querySelector(".katex-display") as HTMLElement | null;
      if (displayElement) {
        displayElement.style.display = "inline-block";
        displayElement.style.margin = "0";
      }

      const katexElement = wrapper.querySelector(".katex") as HTMLElement | null;
      if (katexElement) {
        katexElement.style.lineHeight = "1";
      }

      root.appendChild(wrapper);

      if ("fonts" in document && document.fonts?.ready) {
        await document.fonts.ready;
      }
      await nextFrame();

      const target = displayElement ?? renderedElement ?? wrapper;
      const rect = target.getBoundingClientRect();
      const fallback = estimateLatexSize(latex, fontSize, displayMode);
      const width = Math.max(1, Math.ceil(rect.width || fallback.width));
      const height = Math.max(1, Math.ceil(rect.height || fallback.height));
      const dataUrl = await toPng(target, {
        backgroundColor: "rgba(0,0,0,0)",
        cacheBust: true,
        canvasWidth: width,
        canvasHeight: height,
        pixelRatio: 1,
      });
      return await loadImageFromUrl(dataUrl, width, height);
    } finally {
      root.remove();
    }
  })().catch((error) => {
    renderCache.delete(cacheKey);
    throw error;
  });

  renderCache.set(cacheKey, renderPromise);
  return renderPromise;
}
