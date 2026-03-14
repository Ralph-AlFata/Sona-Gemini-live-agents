import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Rect, Text, Line, Shape, Group } from "react-konva";
import type { Stage as KonvaStage } from "konva/lib/Stage";
import type { DSLMessageRaw } from "../services/drawingSocket";
import { sendCanvasMetrics } from "../services/orchestratorLive";
import { postDraw, type SessionElementSnapshot } from "../services/drawingService";
import getStroke from "perfect-freehand";

interface PointNorm {
  x: number;
  y: number;
}

interface NormalizedBBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface ClipRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface GraphViewport {
  x: number;
  y: number;
  width: number;
  height: number;
  domainMin: number;
  domainMax: number;
  yMin: number;
  yMax: number;
  gridLines: number;
  showBorder: boolean;
  borderColor: string;
  borderOpacity: number;
  axisColor: string;
  axisWidth: number;
  gridColor: string;
  gridOpacity: number;
}

interface TextItem {
  id: string;
  elementId: string;
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
}

interface StrokeItem {
  id: string;
  elementId: string;
  points: PointNorm[];
  color: string;
  strokeWidth: number;
  owner: "user" | "agent";
  elementType: "freehand" | "shape";
  renderMode?: "freehand" | "polyline";
  clipRect?: ClipRect;
  highlightKind?: "circle" | "pointer";
  highlightPart?: "ellipse" | "arrow";
  targetElementIds?: string[];
  padding?: number;
  svgPath?: string;
}

interface HighlightItem {
  id: string;
  elementId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  targetElementIds?: string[];
  padding?: number;
}

interface WhiteboardProps {
  messages: DSLMessageRaw[];
  initialElements: SessionElementSnapshot[];
  sessionId: string;
  authToken: string;
}

const HANDWRITING_FONT = '"Patrick Hand", "Comic Sans MS", cursive';
const SHAPE_STEP_DELAY_MS = 20;
const FREEHAND_STEP_DELAY_MS = 12;
const SEGMENT_SAMPLES_PER_UNIT = 90;

function asNumber(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter((item) => item.length > 0);
}

function asHighlightKind(value: unknown): "circle" | "pointer" | null {
  if (value === "circle" || value === "pointer") return value;
  return null;
}

function asHighlightPart(value: unknown): "ellipse" | "arrow" | null {
  if (value === "ellipse" || value === "arrow") return value;
  return null;
}

function formatTickValue(value: number): string {
  if (!Number.isFinite(value)) return "";
  if (Math.abs(value) < 1e-9) return "0";
  const roundedInt = Math.round(value);
  if (Math.abs(value - roundedInt) < 1e-9) {
    return String(roundedInt);
  }
  return Number(value.toFixed(2)).toString();
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

function interpolateSegment(from: PointNorm, to: PointNorm): PointNorm[] {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.sqrt(dx * dx + dy * dy);
  const steps = Math.max(1, Math.ceil(distance * SEGMENT_SAMPLES_PER_UNIT));

  const points: PointNorm[] = [];
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    points.push({
      x: from.x + dx * t,
      y: from.y + dy * t,
    });
  }
  return points;
}

/**
 * Centripetal Catmull-Rom spline (α=0.5).
 * Guarantees no cusps or self-intersections at tight corners.
 */
function catmullRomSpline(controlPoints: PointNorm[]): PointNorm[] {
  if (controlPoints.length < 2) return [...controlPoints];
  if (controlPoints.length === 2) {
    return interpolateSegment(controlPoints[0]!, controlPoints[1]!);
  }

  const result: PointNorm[] = [controlPoints[0]!];

  for (let i = 0; i < controlPoints.length - 1; i++) {
    const p0 = controlPoints[Math.max(i - 1, 0)]!;
    const p1 = controlPoints[i]!;
    const p2 = controlPoints[i + 1]!;
    const p3 = controlPoints[Math.min(i + 2, controlPoints.length - 1)]!;

    // Centripetal knot intervals: t_i = |P_i - P_{i-1}|^0.5
    const d01 = Math.sqrt(Math.hypot(p1.x - p0.x, p1.y - p0.y)) || 1e-6;
    const d12 = Math.sqrt(Math.hypot(p2.x - p1.x, p2.y - p1.y)) || 1e-6;
    const d23 = Math.sqrt(Math.hypot(p3.x - p2.x, p3.y - p2.y)) || 1e-6;

    const segLen = d12 * d12;
    const steps = Math.max(2, Math.ceil(Math.sqrt(segLen) * SEGMENT_SAMPLES_PER_UNIT));

    // Centripetal tangents scaled by segment length (Hermite form)
    const s1x = ((p2.x - p0.x) / (d01 + d12)) * d12;
    const s1y = ((p2.y - p0.y) / (d01 + d12)) * d12;
    const s2x = ((p3.x - p1.x) / (d12 + d23)) * d12;
    const s2y = ((p3.y - p1.y) / (d12 + d23)) * d12;

    for (let s = 1; s <= steps; s++) {
      const t = s / steps;
      const t2 = t * t;
      const t3 = t2 * t;

      const h00 = 2 * t3 - 3 * t2 + 1;
      const h10 = t3 - 2 * t2 + t;
      const h01 = -2 * t3 + 3 * t2;
      const h11 = t3 - t2;

      const x = h00 * p1.x + h10 * s1x + h01 * p2.x + h11 * s2x;
      const y = h00 * p1.y + h10 * s1y + h01 * p2.y + h11 * s2y;

      result.push({ x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) });
    }
  }

  return result;
}

/**
 * Convert perfect-freehand outline points to an SVG path string.
 * Uses quadratic Bezier curves between midpoints for smooth rendering.
 */
function getSvgPathFromStroke(points: number[][]): string {
  if (points.length < 2) return "";
  const first = points[0]!;
  let d = `M ${first[0]} ${first[1]} Q`;
  for (let i = 0; i < points.length; i++) {
    const p0 = points[i]!;
    const p1 = points[(i + 1) % points.length]!;
    d += ` ${p0[0]} ${p0[1]} ${(p0[0]! + p1[0]!) / 2} ${(p0[1]! + p1[1]!) / 2}`;
  }
  d += " Z";
  return d;
}

/**
 * Compute the perfect-freehand SVG path for a set of pixel-space points.
 * Simulates pressure from point spacing for natural variable-width strokes.
 */
function computeFreehandPath(
  points: PointNorm[],
  unitPx: number,
  baseSize: number,
): string {
  if (points.length < 2) return "";

  // Convert to pixel space — both axes use width as the unit (width-uniform coords)
  const pixelPoints: [number, number][] = points.map((p) => [
    p.x * unitPx,
    p.y * unitPx,
  ]);

  const outlinePoints = getStroke(pixelPoints, {
    size: baseSize,
    thinning: 0.5,
    smoothing: 0.5,
    streamline: 0.3,
    simulatePressure: true,
    start: { taper: baseSize * 2, cap: true },
    end: { taper: baseSize * 1.5, cap: true },
  });

  return getSvgPathFromStroke(outlinePoints);
}

function toPointNorm(value: unknown): PointNorm | null {
  if (!value || typeof value !== "object") return null;
  const maybeX = asNumber((value as Record<string, unknown>)["x"], NaN);
  const maybeY = asNumber((value as Record<string, unknown>)["y"], NaN);
  if (!Number.isFinite(maybeX) || !Number.isFinite(maybeY)) return null;
  return {
    x: Math.max(0, Math.min(1, maybeX)),
    y: Math.max(0, maybeY),
  };
}

function toClipRect(value: unknown): ClipRect | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const width = asNumber(raw["width"], 0);
  const height = asNumber(raw["height"], 0);
  if (width <= 0 || height <= 0) {
    return null;
  }
  return {
    x: Math.max(0, Math.min(1, asNumber(raw["x"], 0))),
    y: Math.max(0, Math.min(2, asNumber(raw["y"], 0))),
    width: Math.max(0.001, Math.min(1, width)),
    height: Math.max(0.001, Math.min(2, height)),
  };
}

function toGraphViewport(value: unknown): GraphViewport | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const width = asNumber(raw["width"], 0);
  const height = asNumber(raw["height"], 0);
  const domainMin = asNumber(raw["domain_min"], -10);
  const domainMax = asNumber(raw["domain_max"], 10);
  const yMin = asNumber(raw["y_min"], -10);
  const yMax = asNumber(raw["y_max"], 10);

  if (width <= 0 || height <= 0 || domainMax <= domainMin || yMax <= yMin) {
    return null;
  }

  return {
    x: Math.max(0, Math.min(1, asNumber(raw["x"], 0.1))),
    y: Math.max(0, Math.min(1, asNumber(raw["y"], 0.1))),
    width: Math.max(0.001, Math.min(1, width)),
    height: Math.max(0.001, Math.min(1, height)),
    domainMin,
    domainMax,
    yMin,
    yMax,
    gridLines: Math.max(2, Math.min(30, Math.round(asNumber(raw["grid_lines"], 10)))),
    showBorder: asBoolean(raw["show_border"], true),
    borderColor: asString(raw["border_color"], "#444444"),
    borderOpacity: Math.max(0, Math.min(1, asNumber(raw["border_opacity"], 0.5))),
    axisColor: asString(raw["axis_color"], "#111111"),
    axisWidth: Math.max(0.5, asNumber(raw["axis_width"], 2)),
    gridColor: asString(raw["grid_color"], "#bbbbbb"),
    gridOpacity: Math.max(0, Math.min(1, asNumber(raw["grid_opacity"], 0.5))),
  };
}

export function Whiteboard({ messages, initialElements, sessionId, authToken }: WhiteboardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<KonvaStage | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [textItems, setTextItems] = useState<TextItem[]>([]);
  const [strokes, setStrokes] = useState<StrokeItem[]>([]);
  const [highlights, setHighlights] = useState<HighlightItem[]>([]);
  const [graphViewport, setGraphViewport] = useState<GraphViewport | null>(null);
  const [localStroke, setLocalStroke] = useState<PointNorm[]>([]);
  const [toolMode, setToolMode] = useState<"draw" | "delete" | "select">("draw");
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  const queueRef = useRef<DSLMessageRaw[]>([]);
  const processedCountRef = useRef(0);
  const processingRef = useRef(false);
  const unmountedRef = useRef(false);
  const isDrawingRef = useRef(false);
  const localPointsRef = useRef<PointNorm[]>([]);
  const measurementCanvasRef = useRef<HTMLCanvasElement | null>(null);
  // Select/drag state
  const dragStartRef = useRef<PointNorm | null>(null);
  const isDraggingRef = useRef(false);

  function clamp01(value: number): number {
    return Math.max(0, Math.min(1, value));
  }

  function getStrokeBBox(stroke: StrokeItem): NormalizedBBox | null {
    if (!stroke.points.length) return null;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (const point of stroke.points) {
      minX = Math.min(minX, point.x);
      minY = Math.min(minY, point.y);
      maxX = Math.max(maxX, point.x);
      maxY = Math.max(maxY, point.y);
    }
    return {
      x: clamp01(minX),
      y: clamp01(minY),
      width: Math.max(0.001, clamp01(maxX) - clamp01(minX)),
      height: Math.max(0.001, clamp01(maxY) - clamp01(minY)),
    };
  }

  function getTextBBox(text: TextItem): NormalizedBBox | null {
    if (dimensions.width <= 0 || dimensions.height <= 0) return null;
    const canvas = measurementCanvasRef.current ?? document.createElement("canvas");
    measurementCanvasRef.current = canvas;
    const context = canvas.getContext("2d");
    if (!context) return null;

    context.font = `${Math.max(1, text.fontSize)}px ${HANDWRITING_FONT}`;
    const metrics = context.measureText(text.text);
    const widthPx = Math.max(1, metrics.width);
    const ascent = metrics.actualBoundingBoxAscent || text.fontSize * 0.8;
    const descent = metrics.actualBoundingBoxDescent || text.fontSize * 0.2;
    const heightPx = Math.max(1, ascent + descent);

    return {
      x: clamp01(text.x),
      y: clamp01(text.y),
      width: Math.max(0.001, widthPx / dimensions.width),
      height: Math.max(0.001, heightPx / dimensions.width),
    };
  }

  function getHighlightBBox(highlight: HighlightItem): NormalizedBBox {
    return {
      x: clamp01(highlight.x),
      y: clamp01(highlight.y),
      width: Math.max(0.001, highlight.width),
      height: Math.max(0.001, highlight.height),
    };
  }

  function getElementBBox(
    elementId: string,
    currentHighlights: HighlightItem[],
  ): NormalizedBBox | null {
    const text = textItems.find((item) => item.elementId === elementId);
    if (text) return getTextBBox(text);

    const stroke = strokes.find((item) => item.elementId === elementId);
    if (stroke) return getStrokeBBox(stroke);

    const highlight = currentHighlights.find((item) => item.elementId === elementId);
    if (highlight) return getHighlightBBox(highlight);

    return null;
  }

  function computeUnionBBox(
    elementIds: string[],
    padding: number,
    currentHighlights: HighlightItem[],
  ): NormalizedBBox | null {
    const boxes = elementIds
      .map((elementId) => getElementBBox(elementId, currentHighlights))
      .filter((box): box is NormalizedBBox => box !== null);
    if (!boxes.length) return null;

    const x1 = Math.min(...boxes.map((box) => box.x));
    const y1 = Math.min(...boxes.map((box) => box.y));
    const x2 = Math.max(...boxes.map((box) => box.x + box.width));
    const y2 = Math.max(...boxes.map((box) => box.y + box.height));
    const pad = Math.max(0, Math.min(0.1, padding));

    const nx1 = clamp01(x1 - pad);
    const ny1 = clamp01(y1 - pad);
    const nx2 = clamp01(x2 + pad);
    const ny2 = clamp01(y2 + pad);

    return {
      x: nx1,
      y: ny1,
      width: Math.max(0.001, nx2 - nx1),
      height: Math.max(0.001, ny2 - ny1),
    };
  }

  function pointsApproximatelyEqual(a: PointNorm[], b: PointNorm[]): boolean {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      const p1 = a[i];
      const p2 = b[i];
      if (!p1 || !p2) return false;
      if (Math.abs(p1.x - p2.x) > 0.0001 || Math.abs(p1.y - p2.y) > 0.0001) {
        return false;
      }
    }
    return true;
  }

  function buildEllipsePoints(region: NormalizedBBox, segments = 40): PointNorm[] {
    const cx = region.x + region.width / 2;
    const cy = region.y + region.height / 2;
    const rx = region.width / 2;
    const ry = region.height / 2;
    const points: PointNorm[] = [];
    for (let i = 0; i <= segments; i++) {
      const theta = (2 * Math.PI * i) / segments;
      points.push({
        x: clamp01(cx + rx * Math.cos(theta)),
        y: clamp01(cy + ry * Math.sin(theta)),
      });
    }
    return points;
  }

  function buildPointerArrowPoints(region: NormalizedBBox): PointNorm[] {
    const cx = region.x + region.width / 2;
    const tipY = clamp01(region.y + region.height);
    const startY = clamp01(region.y + region.height + 0.07);
    if (startY < 1.0 && startY > tipY) {
      return [{ x: cx, y: startY }, { x: cx, y: tipY }];
    }
    return [];
  }

  function resolveDynamicHighlightPoints(
    highlightKind: "circle" | "pointer",
    highlightPart: "ellipse" | "arrow" | null,
    targetElementIds: string[],
    padding: number,
    currentHighlights: HighlightItem[],
  ): PointNorm[] | null {
    const union = computeUnionBBox(targetElementIds, padding, currentHighlights);
    if (!union) return null;
    if (highlightKind === "circle") {
      return buildEllipsePoints(union);
    }
    if (highlightPart === "arrow") {
      return buildPointerArrowPoints(union);
    }
    return buildEllipsePoints(union);
  }

  function getNormalizedPointer(): PointNorm | null {
    const stage = stageRef.current;
    if (!stage || dimensions.width <= 0 || dimensions.height <= 0) return null;
    const pointer = stage.getPointerPosition();
    if (!pointer) return null;
    return {
      x: Math.max(0, Math.min(1, pointer.x / dimensions.width)),
      y: Math.max(0, pointer.y / dimensions.width),
    };
  }

  function isFarEnough(nextPoint: PointNorm): boolean {
    const previous = localPointsRef.current[localPointsRef.current.length - 1];
    if (!previous) return true;
    const dx = nextPoint.x - previous.x;
    const dy = nextPoint.y - previous.y;
    return Math.sqrt(dx * dx + dy * dy) >= 0.0015;
  }

  function handleMouseDown(): void {
    const point = getNormalizedPointer();
    if (!point) return;

    if (toolMode === "draw") {
      isDrawingRef.current = true;
      localPointsRef.current = [point];
      setLocalStroke([point]);
    } else if (toolMode === "select" && selectedElementId) {
      // Begin drag
      dragStartRef.current = point;
      isDraggingRef.current = true;
    }
  }

  function handleMouseMove(): void {
    if (toolMode === "draw" && isDrawingRef.current) {
      const point = getNormalizedPointer();
      if (!point || !isFarEnough(point)) return;
      const next = [...localPointsRef.current, point];
      localPointsRef.current = next;
      setLocalStroke(next);
    }
  }

  function handleMouseUp(): void {
    if (toolMode === "draw") {
      if (!isDrawingRef.current) return;
      isDrawingRef.current = false;
      const points = localPointsRef.current;
      localPointsRef.current = [];
      setLocalStroke([]);
      if (points.length < 2) return;
      const elementId = `user-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
      const svgPath = computeFreehandPath(points, dimensions.width, 3);
      setStrokes((prev) => [
        ...prev,
        {
          id: `user-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
          elementId,
          points,
          color: "#111",
          strokeWidth: 2,
          owner: "user",
          elementType: "freehand",
          svgPath,
        },
      ]);
      void postDraw(
        sessionId,
        "draw_freehand",
        {
          points,
          style: {
            stroke_color: "#111111",
            stroke_width: 2,
            delay_ms: 0,
            animate: false,
          },
        },
        authToken,
        { elementId },
      ).catch(() => {
        // Keep optimistic local stroke even if persistence fails.
      });
    } else if (toolMode === "select" && isDraggingRef.current && selectedElementId) {
      const end = getNormalizedPointer();
      const start = dragStartRef.current;
      if (end && start) {
        const dx = end.x - start.x;
        const dy = end.y - start.y;
        if (Math.abs(dx) > 0.002 || Math.abs(dy) > 0.002) {
          void postDraw(sessionId, "move_elements", {
            element_ids: [selectedElementId],
            dx,
            dy,
          }, authToken);
        }
      }
      isDraggingRef.current = false;
      dragStartRef.current = null;
    }
  }

  function handleDeleteStroke(strokeId: string): void {
    if (toolMode !== "delete") return;
    setStrokes((prev) =>
      prev.filter((stroke) => !(stroke.id === strokeId && stroke.owner === "user")),
    );
  }

  function handleSelectStroke(elementId: string): void {
    if (toolMode !== "select") return;
    setSelectedElementId((prev) => (prev === elementId ? null : elementId));
  }

  async function animateStroke(
    strokeId: string,
    points: PointNorm[],
    stepDelayMs: number,
  ): Promise<void> {
    if (points.length < 2) return;

    for (let i = 1; i < points.length; i++) {
      const from = points[i - 1];
      const to = points[i];
      if (!from || !to) continue;

      const segmentPoints = interpolateSegment(from, to);
      for (const p of segmentPoints) {
        if (unmountedRef.current) return;
        setStrokes((prev) =>
          prev.map((stroke) =>
            stroke.id === strokeId
              ? { ...stroke, points: [...stroke.points, p] }
              : stroke,
          ),
        );
        await sleep(stepDelayMs);
      }
    }
  }

  function upsertText(elementId: string, payload: Record<string, unknown>): void {
    const next: TextItem = {
      id: `text-${elementId}`,
      elementId,
      text: asString(payload["text"], ""),
      x: asNumber(payload["x"], 0),
      y: asNumber(payload["y"], 0),
      fontSize: asNumber(payload["font_size"], 18),
      color: asString(payload["color"], "#000"),
    };
    setTextItems((prev) => {
      const without = prev.filter((item) => item.elementId !== elementId);
      return [...without, next];
    });
  }

  function upsertHighlight(elementId: string, payload: Record<string, unknown>): void {
    const targetElementIds = asStringArray(payload["target_element_ids"]);
    const padding = asNumber(payload["padding"], 0.02);
    const next: HighlightItem = {
      id: `highlight-${elementId}`,
      elementId,
      x: asNumber(payload["x"], 0),
      y: asNumber(payload["y"], 0),
      width: asNumber(payload["width"], 0),
      height: asNumber(payload["height"], 0),
      color: asString(payload["fill_color"], asString(payload["color"], "rgba(255,255,0,0.3)")),
      targetElementIds: targetElementIds.length ? targetElementIds : undefined,
      padding: targetElementIds.length ? padding : undefined,
    };
    setHighlights((prev) => {
      const without = prev.filter((item) => item.elementId !== elementId);
      if (next.targetElementIds && next.targetElementIds.length > 0) {
        const union = computeUnionBBox(next.targetElementIds, next.padding ?? 0.02, without);
        if (union) {
          return [...without, { ...next, ...union }];
        }
      }
      return [...without, next];
    });
  }

  /**
   * Upsert a stroke element (shape or freehand) from a points-based payload.
   * Both shapes and freehand strokes now carry an explicit `points` array,
   * so the rendering path is unified — no conversion needed.
   */
  async function upsertStroke(
    elementId: string,
    payload: Record<string, unknown>,
    elementType: "freehand" | "shape",
    animate: boolean,
  ): Promise<void> {
    const targetElementIds = asStringArray(payload["target_element_ids"]);
    const highlightKind = asHighlightKind(payload["highlight_kind"]);
    const highlightPart = asHighlightPart(payload["highlight_part"]);
    const padding = asNumber(payload["padding"], 0.02);
    const strokeHighlightMeta =
      elementType === "freehand" && highlightKind && targetElementIds.length > 0
        ? {
          highlightKind,
          highlightPart: (highlightPart ?? "ellipse") as "ellipse" | "arrow",
          targetElementIds,
          padding,
        }
        : {};

    const pointsRaw = payload["points"];
    if (!Array.isArray(pointsRaw)) return;

    let points = pointsRaw
      .map((point) => toPointNorm(point))
      .filter((point): point is PointNorm => point !== null);
    if (highlightKind && targetElementIds.length > 0) {
      const dynamicPoints = resolveDynamicHighlightPoints(
        highlightKind,
        highlightPart,
        targetElementIds,
        padding,
        highlights,
      );
      if (dynamicPoints && dynamicPoints.length >= 2) {
        points = dynamicPoints;
      }
    }
    if (points.length < 2) return;

    const color = asString(payload["color"], "#111");
    const strokeWidth = asNumber(payload["stroke_width"], 2);
    const strokeId = `${elementType}-${elementId}`;
    const renderMode =
      elementType === "freehand" && payload["render_mode"] === "polyline"
        ? "polyline"
        : "freehand";
    const clipRect = toClipRect(payload["graph_clip"]);
    const smoothedPoints =
      elementType === "freehand" && renderMode !== "polyline" ? catmullRomSpline(points) : points;

    if (!animate) {
      setStrokes((prev) => {
        const without = prev.filter((stroke) => stroke.elementId !== elementId);
        const svgPath = elementType === "freehand" && renderMode !== "polyline"
          ? computeFreehandPath(smoothedPoints, dimensions.width, strokeWidth * 1.5)
          : undefined;
        return [
          ...without,
          {
            id: strokeId,
            elementId,
            points: smoothedPoints,
            color,
            strokeWidth,
            owner: "agent",
            elementType,
            renderMode,
            clipRect: clipRect ?? undefined,
            svgPath,
            ...strokeHighlightMeta,
          },
        ];
      });
      return;
    }

    const firstPoint = smoothedPoints[0];
    if (!firstPoint) return;

    if (elementType === "freehand" && renderMode !== "polyline") {
      await sleep(asNumber(payload["delay_ms"], 0));
    }

    setStrokes((prev) => {
      const without = prev.filter((stroke) => stroke.elementId !== elementId);
      return [
        ...without,
        {
          id: strokeId,
          elementId,
          points: [firstPoint],
          color,
          strokeWidth,
          owner: "agent",
          elementType,
          renderMode,
          clipRect: clipRect ?? undefined,
          ...strokeHighlightMeta,
        },
      ];
    });

    if (elementType === "freehand" && renderMode !== "polyline") {
      // Freehand: animate by appending points and recomputing the
      // perfect-freehand outline on each frame for natural variable-width strokes.
      const stepDelay = Math.max(6, Math.min(FREEHAND_STEP_DELAY_MS, Math.round(asNumber(payload["delay_ms"], 35) / 2)));
      const baseSize = strokeWidth * 1.5;
      for (let i = 1; i < smoothedPoints.length; i++) {
        if (unmountedRef.current) return;
        const p = smoothedPoints[i]!;
        setStrokes((prev) =>
          prev.map((stroke) => {
            if (stroke.id !== strokeId) return stroke;
            const newPoints: PointNorm[] = [...stroke.points, p];
            return {
              ...stroke,
              points: newPoints,
              svgPath: computeFreehandPath(newPoints, dimensions.width, baseSize),
            };
          }),
        );
        await sleep(stepDelay);
      }
    } else {
      // Shapes and deterministic polylines use linear segment interpolation.
      await animateStroke(strokeId, smoothedPoints, SHAPE_STEP_DELAY_MS);
    }
  }

  useEffect(() => {
    function updateSize() {
      if (containerRef.current) {
        const width = containerRef.current.offsetWidth;
        const height = containerRef.current.offsetHeight;
        setDimensions((prev) => {
          if (prev.width === width && prev.height === height) {
            return prev;
          }
          return { width, height };
        });
      }
    }

    updateSize();
    const observer = new ResizeObserver(updateSize);
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }
    window.addEventListener("resize", updateSize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateSize);
    };
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    if (dimensions.width <= 0 || dimensions.height <= 0) return;
    sendCanvasMetrics(dimensions.width, dimensions.height);
  }, [dimensions.height, dimensions.width, sessionId]);

  useEffect(() => {
    unmountedRef.current = false;
    processingRef.current = false;
    return () => {
      unmountedRef.current = true;
      processingRef.current = false;
      queueRef.current = [];
    };
  }, []);

  useEffect(() => {
    processedCountRef.current = 0;
    queueRef.current = [];
    setGraphViewport(null);
    setLocalStroke([]);
    setSelectedElementId(null);
    localPointsRef.current = [];

    const nextText: TextItem[] = [];
    const nextStrokes: StrokeItem[] = [];
    const nextHighlights: HighlightItem[] = [];

    for (const element of initialElements) {
      const payload = element.payload;
      if (!payload || typeof payload !== "object") continue;

      if (element.element_type === "text") {
        nextText.push({
          id: `text-${element.element_id}`,
          elementId: element.element_id,
          text: asString(payload["text"], ""),
          x: asNumber(payload["x"], 0),
          y: asNumber(payload["y"], 0),
          fontSize: asNumber(payload["font_size"], 18),
          color: asString(payload["color"], "#000"),
        });
        continue;
      }

      if (element.element_type === "highlight") {
        const targetElementIds = asStringArray(payload["target_element_ids"]);
        nextHighlights.push({
          id: `highlight-${element.element_id}`,
          elementId: element.element_id,
          x: asNumber(payload["x"], 0),
          y: asNumber(payload["y"], 0),
          width: asNumber(payload["width"], 0),
          height: asNumber(payload["height"], 0),
          color: asString(payload["fill_color"], asString(payload["color"], "rgba(255,255,0,0.3)")),
          targetElementIds: targetElementIds.length ? targetElementIds : undefined,
          padding: targetElementIds.length ? asNumber(payload["padding"], 0.02) : undefined,
        });
        continue;
      }

      if (element.element_type === "freehand" || element.element_type === "shape") {
        const pointsRaw = payload["points"];
        if (!Array.isArray(pointsRaw)) continue;
        const points = pointsRaw
          .map((point) => toPointNorm(point))
          .filter((point): point is PointNorm => point !== null);
        if (points.length < 2) continue;
        const strokeWidth = asNumber(payload["stroke_width"], 2);
        nextStrokes.push({
          id: `${element.element_type}-${element.element_id}`,
          elementId: element.element_id,
          points,
          color: asString(payload["color"], "#111"),
          strokeWidth,
          owner: "agent",
          elementType: element.element_type,
          renderMode:
            element.element_type === "freehand" && payload["render_mode"] === "polyline"
              ? "polyline"
              : "freehand",
          clipRect: toClipRect(payload["graph_clip"]) ?? undefined,
          svgPath: element.element_type === "freehand" && payload["render_mode"] !== "polyline" && dimensions.width > 0
            ? computeFreehandPath(points, dimensions.width, strokeWidth * 1.5)
            : undefined,
          highlightKind: asHighlightKind(payload["highlight_kind"]) ?? undefined,
          highlightPart: asHighlightPart(payload["highlight_part"]) ?? undefined,
          targetElementIds: asStringArray(payload["target_element_ids"]),
          padding: asNumber(payload["padding"], 0.02),
        });
      }
    }

    setTextItems(nextText);
    setStrokes(nextStrokes);
    setHighlights(nextHighlights);
  }, [dimensions.width, initialElements]);

  useEffect(() => {
    setHighlights((prev) => {
      let changed = false;
      const next = prev.map((highlight) => {
        if (!highlight.targetElementIds || highlight.targetElementIds.length === 0) {
          return highlight;
        }
        const union = computeUnionBBox(
          highlight.targetElementIds,
          highlight.padding ?? 0.02,
          prev,
        );
        if (!union) {
          return highlight;
        }
        const isSame =
          Math.abs(union.x - highlight.x) < 0.0001 &&
          Math.abs(union.y - highlight.y) < 0.0001 &&
          Math.abs(union.width - highlight.width) < 0.0001 &&
          Math.abs(union.height - highlight.height) < 0.0001;
        if (isSame) {
          return highlight;
        }
        changed = true;
        return { ...highlight, ...union };
      });
      return changed ? next : prev;
    });
  }, [textItems, strokes, dimensions.width, dimensions.height]);

  useEffect(() => {
    setStrokes((prev) => {
      let changed = false;
      const next = prev.map((stroke) => {
        if (
          !stroke.highlightKind ||
          !stroke.targetElementIds ||
          stroke.targetElementIds.length === 0
        ) {
          return stroke;
        }
        const dynamicPoints = resolveDynamicHighlightPoints(
          stroke.highlightKind,
          stroke.highlightPart ?? "ellipse",
          stroke.targetElementIds,
          stroke.padding ?? 0.02,
          highlights,
        );
        if (!dynamicPoints || dynamicPoints.length < 2) {
          return stroke;
        }
        if (pointsApproximatelyEqual(dynamicPoints, stroke.points)) {
          return stroke;
        }
        changed = true;
        return { ...stroke, points: dynamicPoints };
      });
      return changed ? next : prev;
    });
  }, [textItems, strokes, highlights, dimensions.width, dimensions.height]);

  useEffect(() => {
    if (messages.length < processedCountRef.current) {
      processedCountRef.current = 0;
      queueRef.current = [];
      return;
    }
    if (messages.length <= processedCountRef.current) return;
    queueRef.current.push(...messages.slice(processedCountRef.current));
    processedCountRef.current = messages.length;

    async function processQueue() {
      if (processingRef.current) return;
      processingRef.current = true;

      try {
        while (!unmountedRef.current && queueRef.current.length > 0) {
          const message = queueRef.current.shift();
          if (!message) continue;
          const payload = message.payload;

          try {
            if (message.type === "clear") {
              setTextItems([]);
              setStrokes([]);
              setHighlights([]);
              setGraphViewport(null);
              setLocalStroke([]);
              setSelectedElementId(null);
              localPointsRef.current = [];
              continue;
            }

            if (message.type === "graph_viewport_set") {
              const viewport = toGraphViewport(payload["viewport"] ?? payload);
              if (viewport) {
                setGraphViewport(viewport);
              }
              continue;
            }

            if (message.type === "element_created") {
              const elementId = asString(payload["element_id"], "");
              const elementType = asString(payload["element_type"], "");
              const elementPayload = payload["payload"];
              if (!elementId || !elementPayload || typeof elementPayload !== "object") continue;

              const typedPayload = elementPayload as Record<string, unknown>;
              if (elementType === "text") {
                upsertText(elementId, typedPayload);
              } else if (elementType === "highlight") {
                upsertHighlight(elementId, typedPayload);
              } else if (elementType === "freehand") {
                await upsertStroke(elementId, typedPayload, "freehand", asBoolean(typedPayload["animate"], true));
              } else if (elementType === "shape") {
                await upsertStroke(elementId, typedPayload, "shape", asBoolean(typedPayload["animate"], true));
              }
              continue;
            }

            if (message.type === "elements_deleted") {
              const elementIds = Array.isArray(payload["element_ids"])
                ? payload["element_ids"].map((v) => String(v))
                : [];
              const idSet = new Set(elementIds);
              setStrokes((prev) => prev.filter((stroke) => !idSet.has(stroke.elementId)));
              setTextItems((prev) => prev.filter((item) => !idSet.has(item.elementId)));
              setHighlights((prev) => prev.filter((item) => !idSet.has(item.elementId)));
              // Deselect if the selected element was deleted
              setSelectedElementId((prev) => (prev && idSet.has(prev) ? null : prev));
              continue;
            }

            if (message.type === "elements_transformed") {
              const elements = Array.isArray(payload["elements"]) ? payload["elements"] : [];
              for (const item of elements) {
                if (!item || typeof item !== "object") continue;
                const elementId = asString((item as Record<string, unknown>)["element_id"], "");
                const elementType = asString((item as Record<string, unknown>)["element_type"], "");
                const elementPayload = (item as Record<string, unknown>)["payload"];
                if (!elementId || !elementPayload || typeof elementPayload !== "object") continue;
                const typedPayload = elementPayload as Record<string, unknown>;

                if (elementType === "text") {
                  const stylePayload = typedPayload["style"] as Record<string, unknown> | undefined;
                  upsertText(elementId, {
                    ...typedPayload,
                    color: asString(stylePayload?.stroke_color, "#000"),
                  });
                } else if (elementType === "highlight") {
                  const stylePayload = typedPayload["style"] as Record<string, unknown> | undefined;
                  upsertHighlight(elementId, {
                    ...typedPayload,
                    color: asString(stylePayload?.fill_color, "rgba(255,255,0,0.3)"),
                  });
                } else if (elementType === "freehand" || elementType === "shape") {
                  const stylePayload = typedPayload["style"] as Record<string, unknown> | undefined;
                  await upsertStroke(
                    elementId,
                    {
                      ...typedPayload,
                      color: asString(stylePayload?.stroke_color, "#111"),
                      stroke_width: asNumber(stylePayload?.stroke_width, 2),
                      delay_ms: 0,
                    },
                    elementType as "freehand" | "shape",
                    false,
                  );
                }
              }
              continue;
            }

            if (message.type === "elements_restyled") {
              const elements = Array.isArray(payload["elements"]) ? payload["elements"] : [];
              for (const item of elements) {
                if (!item || typeof item !== "object") continue;
                const elementId = asString((item as Record<string, unknown>)["element_id"], "");
                const style = (item as Record<string, unknown>)["style"];
                if (!elementId || !style || typeof style !== "object") continue;
                const styleObj = style as Record<string, unknown>;
                setStrokes((prev) =>
                  prev.map((stroke) =>
                    stroke.elementId === elementId
                      ? {
                        ...stroke,
                        color: asString(styleObj["color"], stroke.color),
                        strokeWidth: asNumber(styleObj["stroke_width"], stroke.strokeWidth),
                      }
                      : stroke,
                  ),
                );
                setTextItems((prev) =>
                  prev.map((text) =>
                    text.elementId === elementId
                      ? { ...text, color: asString(styleObj["color"], text.color) }
                      : text,
                  ),
                );
                setHighlights((prev) =>
                  prev.map((highlight) =>
                    highlight.elementId === elementId
                      ? { ...highlight, color: asString(styleObj["fill_color"], highlight.color) }
                      : highlight,
                  ),
                );
              }
            }
          } catch (messageError) {
            console.error("Failed to process drawing message", message.type, messageError);
          }
        }
      } finally {
        processingRef.current = false;
      }
    }

    void processQueue();
  }, [messages]);

  const cursor =
    toolMode === "draw" ? "crosshair" : toolMode === "select" ? "default" : "pointer";

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", background: "#f5f5f5", position: "relative" }}
    >
      {/* Toolbar */}
      <div
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          zIndex: 5,
          display: "flex",
          gap: 8,
          padding: 6,
          borderRadius: 8,
          background: "rgba(255,255,255,0.9)",
          border: "1px solid #ddd",
        }}
      >
        {(["draw", "select", "delete"] as const).map((mode) => (
          <button
            key={mode}
            onClick={() => {
              setToolMode(mode);
              if (mode !== "select") setSelectedElementId(null);
            }}
            style={{
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid #ccc",
              background: toolMode === mode ? "#111" : "#fff",
              color: toolMode === mode ? "#fff" : "#111",
              fontSize: 12,
              cursor: "pointer",
              textTransform: "capitalize",
            }}
          >
            {mode}
          </button>
        ))}
      </div>

      {dimensions.width > 0 && dimensions.height > 0 && (
        <Stage
          ref={stageRef}
          width={dimensions.width}
          height={dimensions.height}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onTouchStart={handleMouseDown}
          onTouchMove={handleMouseMove}
          onTouchEnd={handleMouseUp}
          style={{ touchAction: "none", cursor }}
        >
          {/* Background */}
          <Layer>
              <Rect
                x={0}
                y={0}
                width={dimensions.width}
                height={dimensions.height}
                fill="#ffffff"
                listening={false}
              />
              {graphViewport && (() => {
                const graphX = graphViewport.x * dimensions.width;
                const graphY = graphViewport.y * dimensions.width;
                const graphW = graphViewport.width * dimensions.width;
                const graphH = graphViewport.height * dimensions.width;
                const stepX = graphW / graphViewport.gridLines;
                const stepY = graphH / graphViewport.gridLines;

                const hasXAxis = graphViewport.yMin <= 0 && graphViewport.yMax >= 0;
                const hasYAxis = graphViewport.domainMin <= 0 && graphViewport.domainMax >= 0;
                const xAxisY = hasXAxis
                  ? graphY + ((graphViewport.yMax - 0) / (graphViewport.yMax - graphViewport.yMin)) * graphH
                  : graphY + graphH;
                const yAxisX = hasYAxis
                  ? graphX + ((0 - graphViewport.domainMin) / (graphViewport.domainMax - graphViewport.domainMin)) * graphW
                  : graphX;

                const xStepValue = (graphViewport.domainMax - graphViewport.domainMin) / graphViewport.gridLines;
                const yStepValue = (graphViewport.yMax - graphViewport.yMin) / graphViewport.gridLines;
                const showEvery = graphViewport.gridLines > 14 ? 2 : 1;

                const xTickLabelY =
                  xAxisY + 18 < graphY + graphH ? xAxisY + 6 : xAxisY - 18;
                const yLabelsOnLeft = yAxisX - 38 >= graphX - 2;
                const yTickLabelX = yLabelsOnLeft ? yAxisX - 36 : yAxisX + 6;
                const yTickAlign = yLabelsOnLeft ? "right" : "left";

                return (
                  <>
                    {Array.from({ length: graphViewport.gridLines - 1 }).map((_, idx) => {
                      const vx = graphX + (idx + 1) * stepX;
                      return (
                        <Line
                          key={`grid-v-${idx}`}
                          points={[vx, graphY, vx, graphY + graphH]}
                          stroke={graphViewport.gridColor}
                          strokeWidth={1}
                          opacity={graphViewport.gridOpacity}
                          listening={false}
                        />
                      );
                    })}
                    {Array.from({ length: graphViewport.gridLines - 1 }).map((_, idx) => {
                      const hy = graphY + (idx + 1) * stepY;
                      return (
                        <Line
                          key={`grid-h-${idx}`}
                          points={[graphX, hy, graphX + graphW, hy]}
                          stroke={graphViewport.gridColor}
                          strokeWidth={1}
                          opacity={graphViewport.gridOpacity}
                          listening={false}
                        />
                      );
                    })}

                    <Line
                      points={[graphX, xAxisY, graphX + graphW, xAxisY]}
                      stroke={graphViewport.axisColor}
                      strokeWidth={graphViewport.axisWidth}
                      listening={false}
                    />
                    <Line
                      points={[yAxisX, graphY, yAxisX, graphY + graphH]}
                      stroke={graphViewport.axisColor}
                      strokeWidth={graphViewport.axisWidth}
                      listening={false}
                    />

                    {Array.from({ length: graphViewport.gridLines + 1 }).map((_, idx) => {
                      if (idx % showEvery !== 0) return null;
                      const xPx = graphX + idx * stepX;
                      const xValue = graphViewport.domainMin + idx * xStepValue;
                      return (
                        <Text
                          key={`x-tick-${idx}`}
                          x={xPx - 18}
                          y={xTickLabelY}
                          width={36}
                          align="center"
                          text={formatTickValue(xValue)}
                          fontSize={11}
                          fill="#444"
                          listening={false}
                        />
                      );
                    })}
                    {Array.from({ length: graphViewport.gridLines + 1 }).map((_, idx) => {
                      if (idx % showEvery !== 0) return null;
                      const yPx = graphY + idx * stepY;
                      const yValue = graphViewport.yMax - idx * yStepValue;
                      return (
                        <Text
                          key={`y-tick-${idx}`}
                          x={yTickLabelX}
                          y={yPx - 7}
                          width={34}
                          align={yTickAlign}
                          text={formatTickValue(yValue)}
                          fontSize={11}
                          fill="#444"
                          listening={false}
                        />
                      );
                    })}

                    <Text
                      x={graphX + graphW - 12}
                      y={Math.max(graphY + 2, xAxisY - 16)}
                      text="x"
                      fontSize={13}
                      fontStyle="bold"
                      fill={graphViewport.axisColor}
                      listening={false}
                    />
                    <Text
                      x={Math.min(graphX + graphW - 12, yAxisX + 6)}
                      y={graphY + 2}
                      text="y"
                      fontSize={13}
                      fontStyle="bold"
                      fill={graphViewport.axisColor}
                      listening={false}
                    />

                    {graphViewport.showBorder && (
                      <Rect
                        x={graphX}
                        y={graphY}
                        width={graphW}
                        height={graphH}
                        stroke={graphViewport.borderColor}
                        strokeWidth={1}
                        opacity={graphViewport.borderOpacity}
                        listening={false}
                      />
                    )}
                  </>
                );
              })()}
            </Layer>

          {/* Highlights */}
          <Layer>
            {highlights.map((highlight) => (
              <Rect
                key={highlight.id}
                x={highlight.x * dimensions.width}
                y={highlight.y * dimensions.width}
                width={highlight.width * dimensions.width}
                height={highlight.height * dimensions.width}
                fill={highlight.color}
              />
            ))}
          </Layer>

          {/* Strokes (shapes + freehand) */}
          <Layer>
            {strokes.map((stroke) => {
              const isSelected = stroke.elementId === selectedElementId;
              const handleClick = () => {
                if (toolMode === "delete" && stroke.owner === "user") {
                  handleDeleteStroke(stroke.id);
                } else if (toolMode === "select") {
                  handleSelectStroke(stroke.elementId);
                }
              };
              const strokeOpacity = toolMode === "delete" && stroke.owner === "user" ? 0.8 : 1;
              const lineNode = (
                <Line
                  key={stroke.id}
                  points={stroke.points.flatMap((point) => [
                    point.x * dimensions.width,
                    point.y * dimensions.width,
                  ])}
                  stroke={isSelected ? "#2563eb" : stroke.color}
                  strokeWidth={isSelected ? stroke.strokeWidth + 1 : stroke.strokeWidth}
                  lineCap="round"
                  lineJoin="round"
                  dash={isSelected ? [6, 3] : undefined}
                  hitStrokeWidth={toolMode === "delete" ? 24 : 12}
                  onClick={handleClick}
                  onTap={handleClick}
                  opacity={strokeOpacity}
                />
              );

              // Freehand strokes with svgPath use perfect-freehand filled polygon
              if (stroke.svgPath && stroke.elementType === "freehand") {
                const shapeNode = (
                  <Shape
                    key={stroke.id}
                    sceneFunc={(ctx, shape) => {
                      const path = new Path2D(stroke.svgPath!);
                      ctx._context.fillStyle = isSelected ? "#2563eb" : stroke.color;
                      ctx._context.fill(path);
                      ctx.fillStrokeShape(shape);
                    }}
                    hitFunc={(ctx, shape) => {
                      const path = new Path2D(stroke.svgPath!);
                      ctx._context.fill(path);
                      ctx.fillStrokeShape(shape);
                    }}
                    onClick={handleClick}
                    onTap={handleClick}
                    opacity={strokeOpacity}
                  />
                );
                if (!stroke.clipRect) {
                  return shapeNode;
                }
                return (
                  <Group
                    key={`clip-${stroke.id}`}
                    clipX={stroke.clipRect.x * dimensions.width}
                    clipY={stroke.clipRect.y * dimensions.width}
                    clipWidth={stroke.clipRect.width * dimensions.width}
                    clipHeight={stroke.clipRect.height * dimensions.width}
                  >
                    {shapeNode}
                  </Group>
                );
              }

              if (!stroke.clipRect) {
                return lineNode;
              }
              return (
                <Group
                  key={`clip-${stroke.id}`}
                  clipX={stroke.clipRect.x * dimensions.width}
                  clipY={stroke.clipRect.y * dimensions.width}
                  clipWidth={stroke.clipRect.width * dimensions.width}
                  clipHeight={stroke.clipRect.height * dimensions.width}
                >
                  {lineNode}
                </Group>
              );
            })}
            {localStroke.length > 1 && (() => {
              const ghostPath = computeFreehandPath(localStroke, dimensions.width, 3);
              if (!ghostPath) return null;
              return (
                <Shape
                  sceneFunc={(ctx, shape) => {
                    const path = new Path2D(ghostPath);
                    ctx._context.fillStyle = "#111";
                    ctx._context.fill(path);
                    ctx.fillStrokeShape(shape);
                  }}
                />
              );
            })()}
          </Layer>

          {/* Text */}
          <Layer>
            {textItems.map((item) => (
              <Text
                key={item.id}
                x={item.x * dimensions.width}
                y={item.y * dimensions.width}
                text={item.text}
                fontSize={item.fontSize}
                fill={item.color}
                fontFamily={HANDWRITING_FONT}
              />
            ))}
          </Layer>
        </Stage>
      )}
    </div>
  );
}
