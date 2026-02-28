import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Rect, Text, Line } from "react-konva";
import type { Stage as KonvaStage } from "konva/lib/Stage";
import type { DSLMessageRaw } from "../services/drawingSocket";

interface PointNorm {
  x: number;
  y: number;
}

interface TextItem {
  id: string;
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
}

interface StrokeItem {
  id: string;
  points: PointNorm[];
  color: string;
  strokeWidth: number;
  owner: "user" | "agent";
}

interface HighlightItem {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
}

interface WhiteboardProps {
  messages: DSLMessageRaw[];
}

const HANDWRITING_FONT = '"Patrick Hand", "Comic Sans MS", cursive';
const SHAPE_STEP_DELAY_MS = 14;
const FREEHAND_STEP_DELAY_MS = 12;
const ELLIPSE_SEGMENTS = 48;
const POLYGON_SIDES = 5;
const SEGMENT_SAMPLES_PER_UNIT = 90;

function asNumber(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
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

function toPointNorm(value: unknown): PointNorm | null {
  if (!value || typeof value !== "object") return null;
  const maybeX = asNumber((value as Record<string, unknown>)["x"], NaN);
  const maybeY = asNumber((value as Record<string, unknown>)["y"], NaN);
  if (!Number.isFinite(maybeX) || !Number.isFinite(maybeY)) return null;
  return {
    x: Math.max(0, Math.min(1, maybeX)),
    y: Math.max(0, Math.min(1, maybeY)),
  };
}

function shapeToPoints(payload: Record<string, unknown>): PointNorm[] {
  const shape = asString(payload["shape"], "line");
  const x = asNumber(payload["x"], 0);
  const y = asNumber(payload["y"], 0);
  const width = asNumber(payload["width"], 0.2);
  const height = asNumber(payload["height"], 0.2);

  if (shape === "line") {
    return [{ x, y }, { x: x + width, y: y + height }];
  }

  if (shape === "rectangle") {
    return [
      { x, y },
      { x: x + width, y },
      { x: x + width, y: y + height },
      { x, y: y + height },
      { x, y },
    ];
  }

  if (shape === "triangle") {
    return [
      { x, y: y + height },
      { x: x + width / 2, y },
      { x: x + width, y: y + height },
      { x, y: y + height },
    ];
  }

  if (shape === "ellipse") {
    const cx = x + width / 2;
    const cy = y + height / 2;
    const rx = width / 2;
    const ry = height / 2;
    const points: PointNorm[] = [];
    for (let i = 0; i <= ELLIPSE_SEGMENTS; i++) {
      const t = (Math.PI * 2 * i) / ELLIPSE_SEGMENTS;
      points.push({ x: cx + rx * Math.cos(t), y: cy + ry * Math.sin(t) });
    }
    return points;
  }

  if (shape === "polygon") {
    const cx = x + width / 2;
    const cy = y + height / 2;
    const rx = width / 2;
    const ry = height / 2;
    const points: PointNorm[] = [];
    for (let i = 0; i <= POLYGON_SIDES; i++) {
      const t = (Math.PI * 2 * i) / POLYGON_SIDES - Math.PI / 2;
      points.push({ x: cx + rx * Math.cos(t), y: cy + ry * Math.sin(t) });
    }
    return points;
  }

  return [];
}

export function Whiteboard({ messages }: WhiteboardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<KonvaStage | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [textItems, setTextItems] = useState<TextItem[]>([]);
  const [strokes, setStrokes] = useState<StrokeItem[]>([]);
  const [highlights, setHighlights] = useState<HighlightItem[]>([]);
  const [localStroke, setLocalStroke] = useState<PointNorm[]>([]);
  const [toolMode, setToolMode] = useState<"draw" | "delete">("draw");
  const queueRef = useRef<DSLMessageRaw[]>([]);
  const processedCountRef = useRef(0);
  const processingRef = useRef(false);
  const unmountedRef = useRef(false);
  const isDrawingRef = useRef(false);
  const localPointsRef = useRef<PointNorm[]>([]);

  function getNormalizedPointer(): PointNorm | null {
    const stage = stageRef.current;
    if (!stage || dimensions.width <= 0 || dimensions.height <= 0) return null;
    const pointer = stage.getPointerPosition();
    if (!pointer) return null;
    return {
      x: Math.max(0, Math.min(1, pointer.x / dimensions.width)),
      y: Math.max(0, Math.min(1, pointer.y / dimensions.height)),
    };
  }

  function isFarEnough(nextPoint: PointNorm): boolean {
    const previous = localPointsRef.current[localPointsRef.current.length - 1];
    if (!previous) return true;
    const dx = nextPoint.x - previous.x;
    const dy = nextPoint.y - previous.y;
    return Math.sqrt(dx * dx + dy * dy) >= 0.0015;
  }

  function handleDrawStart(): void {
    if (toolMode !== "draw") return;
    const point = getNormalizedPointer();
    if (!point) return;
    isDrawingRef.current = true;
    localPointsRef.current = [point];
    setLocalStroke([point]);
  }

  function handleDrawMove(): void {
    if (toolMode !== "draw") return;
    if (!isDrawingRef.current) return;
    const point = getNormalizedPointer();
    if (!point || !isFarEnough(point)) return;
    const next = [...localPointsRef.current, point];
    localPointsRef.current = next;
    setLocalStroke(next);
  }

  function handleDrawEnd(): void {
    if (toolMode !== "draw") return;
    if (!isDrawingRef.current) return;
    isDrawingRef.current = false;
    const points = localPointsRef.current;
    localPointsRef.current = [];
    setLocalStroke([]);
    if (points.length < 2) return;
    setStrokes((prev) => [
      ...prev,
      {
        id: `user-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
        points,
        color: "#111",
        strokeWidth: 2,
        owner: "user",
      },
    ]);
  }

  function handleDeleteStroke(strokeId: string): void {
    if (toolMode !== "delete") return;
    setStrokes((prev) =>
      prev.filter((stroke) => !(stroke.id === strokeId && stroke.owner === "user")),
    );
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

  useEffect(() => {
    function updateSize() {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight,
        });
      }
    }

    updateSize();
    window.addEventListener("resize", updateSize);
    return () => window.removeEventListener("resize", updateSize);
  }, []);

  useEffect(() => {
    return () => {
      unmountedRef.current = true;
      queueRef.current = [];
    };
  }, []);

  useEffect(() => {
    if (messages.length <= processedCountRef.current) return;
    queueRef.current.push(...messages.slice(processedCountRef.current));
    processedCountRef.current = messages.length;

    async function processQueue() {
      if (processingRef.current) return;
      processingRef.current = true;
      while (!unmountedRef.current && queueRef.current.length > 0) {
        const message = queueRef.current.shift();
        if (!message) continue;
        const payload = message.payload;

        if (message.type === "clear") {
          setTextItems([]);
          setStrokes([]);
          setHighlights([]);
          setLocalStroke([]);
          localPointsRef.current = [];
          continue;
        }

        if (message.type === "text") {
          setTextItems((prev) => [
            ...prev,
            {
              id: message.id,
              text: asString(payload["text"], ""),
              x: asNumber(payload["x"], 0),
              y: asNumber(payload["y"], 0),
              fontSize: asNumber(payload["font_size"], 18),
              color: asString(payload["color"], "#000"),
            },
          ]);
          continue;
        }

        if (message.type === "highlight") {
          setHighlights((prev) => [
            ...prev,
            {
              id: message.id,
              x: asNumber(payload["x"], 0),
              y: asNumber(payload["y"], 0),
              width: asNumber(payload["width"], 0),
              height: asNumber(payload["height"], 0),
              color: asString(payload["color"], "rgba(255,255,0,0.3)"),
            },
          ]);
          continue;
        }

        if (message.type === "freehand") {
          const pointsRaw = payload["points"];
          if (!Array.isArray(pointsRaw)) continue;
          const points = pointsRaw
            .map((point) => toPointNorm(point))
            .filter((point): point is PointNorm => point !== null);
          if (points.length < 2) continue;

          await sleep(asNumber(payload["delay_ms"], 0));
          if (unmountedRef.current) break;
          const firstPoint = points[0];
          if (!firstPoint) continue;

          const strokeId = `freehand-${message.id}`;
          setStrokes((prev) => [
            ...prev,
            {
              id: strokeId,
              points: [firstPoint],
              color: asString(payload["color"], "#111"),
              strokeWidth: asNumber(payload["stroke_width"], 2),
              owner: "agent",
            },
          ]);
          const stepDelay = Math.max(
            6,
            Math.min(FREEHAND_STEP_DELAY_MS, Math.round(asNumber(payload["delay_ms"], 35) / 2)),
          );
          await animateStroke(strokeId, points, stepDelay);
          continue;
        }

        if (message.type === "shape") {
          const points = shapeToPoints(payload)
            .map((point) => toPointNorm(point))
            .filter((point): point is PointNorm => point !== null);
          if (points.length < 2) continue;
          const firstPoint = points[0];
          if (!firstPoint) continue;

          const shapeStrokeId = `shape-${message.id}`;
          setStrokes((prev) => [
            ...prev,
            {
              id: shapeStrokeId,
              points: [firstPoint],
              color: asString(payload["color"], "#111"),
              strokeWidth: 2,
              owner: "agent",
            },
          ]);

          await animateStroke(shapeStrokeId, points, SHAPE_STEP_DELAY_MS);
        }
      }
      processingRef.current = false;
    }

    void processQueue();
  }, [messages]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", background: "#f5f5f5", position: "relative" }}
    >
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
        <button
          onClick={() => setToolMode("draw")}
          style={{
            padding: "6px 10px",
            borderRadius: 6,
            border: "1px solid #ccc",
            background: toolMode === "draw" ? "#111" : "#fff",
            color: toolMode === "draw" ? "#fff" : "#111",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          Draw
        </button>
        <button
          onClick={() => setToolMode("delete")}
          style={{
            padding: "6px 10px",
            borderRadius: 6,
            border: "1px solid #ccc",
            background: toolMode === "delete" ? "#111" : "#fff",
            color: toolMode === "delete" ? "#fff" : "#111",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          Delete
        </button>
      </div>
      {dimensions.width > 0 && dimensions.height > 0 && (
        <Stage
          ref={stageRef}
          width={dimensions.width}
          height={dimensions.height}
          onMouseDown={handleDrawStart}
          onMouseMove={handleDrawMove}
          onMouseUp={handleDrawEnd}
          onMouseLeave={handleDrawEnd}
          onTouchStart={handleDrawStart}
          onTouchMove={handleDrawMove}
          onTouchEnd={handleDrawEnd}
          style={{ touchAction: "none", cursor: toolMode === "draw" ? "crosshair" : "pointer" }}
        >
          <Layer>
            <Rect
              x={0}
              y={0}
              width={dimensions.width}
              height={dimensions.height}
              fill="#ffffff"
            />
          </Layer>
          <Layer>
            {highlights.map((highlight) => (
              <Rect
                key={highlight.id}
                x={highlight.x * dimensions.width}
                y={highlight.y * dimensions.height}
                width={highlight.width * dimensions.width}
                height={highlight.height * dimensions.height}
                fill={highlight.color}
              />
            ))}
          </Layer>
          <Layer>
            {strokes.map((stroke) => (
              <Line
                key={stroke.id}
                points={stroke.points.flatMap((point) => [
                  point.x * dimensions.width,
                  point.y * dimensions.height,
                ])}
                stroke={stroke.color}
                strokeWidth={stroke.strokeWidth}
                lineCap="round"
                lineJoin="round"
                onClick={() => handleDeleteStroke(stroke.id)}
                onTap={() => handleDeleteStroke(stroke.id)}
                opacity={
                  toolMode === "delete" && stroke.owner === "user"
                    ? 0.8
                    : 1
                }
              />
            ))}
            {localStroke.length > 1 && (
              <Line
                points={localStroke.flatMap((point) => [
                  point.x * dimensions.width,
                  point.y * dimensions.height,
                ])}
                stroke="#111"
                strokeWidth={2}
                lineCap="round"
                lineJoin="round"
              />
            )}
          </Layer>
          <Layer>
            {textItems.map((item) => (
              <Text
                key={item.id}
                x={item.x * dimensions.width}
                y={item.y * dimensions.height}
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
