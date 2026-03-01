import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Rect, Text, Line } from "react-konva";
import type { Stage as KonvaStage } from "konva/lib/Stage";
import type { DSLMessageRaw } from "../services/drawingSocket";
import { postDraw } from "../services/drawingService";

interface PointNorm {
  x: number;
  y: number;
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
}

interface HighlightItem {
  id: string;
  elementId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
}

interface WhiteboardProps {
  messages: DSLMessageRaw[];
  sessionId: string;
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

export function Whiteboard({ messages, sessionId }: WhiteboardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<KonvaStage | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [textItems, setTextItems] = useState<TextItem[]>([]);
  const [strokes, setStrokes] = useState<StrokeItem[]>([]);
  const [highlights, setHighlights] = useState<HighlightItem[]>([]);
  const [localStroke, setLocalStroke] = useState<PointNorm[]>([]);
  const [toolMode, setToolMode] = useState<"draw" | "delete" | "select">("draw");
  const [selectedElementId, setSelectedElementId] = useState<string | null>(null);
  const queueRef = useRef<DSLMessageRaw[]>([]);
  const processedCountRef = useRef(0);
  const processingRef = useRef(false);
  const unmountedRef = useRef(false);
  const isDrawingRef = useRef(false);
  const localPointsRef = useRef<PointNorm[]>([]);
  // Select/drag state
  const dragStartRef = useRef<PointNorm | null>(null);
  const isDraggingRef = useRef(false);

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
      setStrokes((prev) => [
        ...prev,
        {
          id: `user-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
          elementId: `user-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
          points,
          color: "#111",
          strokeWidth: 2,
          owner: "user",
          elementType: "freehand",
        },
      ]);
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
          });
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
    const next: HighlightItem = {
      id: `highlight-${elementId}`,
      elementId,
      x: asNumber(payload["x"], 0),
      y: asNumber(payload["y"], 0),
      width: asNumber(payload["width"], 0),
      height: asNumber(payload["height"], 0),
      color: asString(payload["fill_color"], asString(payload["color"], "rgba(255,255,0,0.3)")),
    };
    setHighlights((prev) => {
      const without = prev.filter((item) => item.elementId !== elementId);
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
    const pointsRaw = payload["points"];
    if (!Array.isArray(pointsRaw)) return;

    const points = pointsRaw
      .map((point) => toPointNorm(point))
      .filter((point): point is PointNorm => point !== null);
    if (points.length < 2) return;

    const color = asString(payload["color"], "#111");
    const strokeWidth = asNumber(payload["stroke_width"], 2);
    const strokeId = `${elementType}-${elementId}`;

    if (!animate) {
      setStrokes((prev) => {
        const without = prev.filter((stroke) => stroke.elementId !== elementId);
        return [
          ...without,
          { id: strokeId, elementId, points, color, strokeWidth, owner: "agent", elementType },
        ];
      });
      return;
    }

    const firstPoint = points[0];
    if (!firstPoint) return;

    if (elementType === "freehand") {
      await sleep(asNumber(payload["delay_ms"], 0));
    }

    setStrokes((prev) => {
      const without = prev.filter((stroke) => stroke.elementId !== elementId);
      return [
        ...without,
        { id: strokeId, elementId, points: [firstPoint], color, strokeWidth, owner: "agent", elementType },
      ];
    });

    const stepDelay =
      elementType === "freehand"
        ? Math.max(6, Math.min(FREEHAND_STEP_DELAY_MS, Math.round(asNumber(payload["delay_ms"], 35) / 2)))
        : SHAPE_STEP_DELAY_MS;

    await animateStroke(strokeId, points, stepDelay);
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
          setSelectedElementId(null);
          localPointsRef.current = [];
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
            await upsertStroke(elementId, typedPayload, "freehand", true);
          } else if (elementType === "shape") {
            await upsertStroke(elementId, typedPayload, "shape", true);
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
      }

      processingRef.current = false;
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
            <Rect x={0} y={0} width={dimensions.width} height={dimensions.height} fill="#ffffff" />
          </Layer>

          {/* Highlights */}
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

          {/* Strokes (shapes + freehand) */}
          <Layer>
            {strokes.map((stroke) => {
              const isSelected = stroke.elementId === selectedElementId;
              return (
                <Line
                  key={stroke.id}
                  points={stroke.points.flatMap((point) => [
                    point.x * dimensions.width,
                    point.y * dimensions.height,
                  ])}
                  stroke={isSelected ? "#2563eb" : stroke.color}
                  strokeWidth={isSelected ? stroke.strokeWidth + 1 : stroke.strokeWidth}
                  lineCap="round"
                  lineJoin="round"
                  dash={isSelected ? [6, 3] : undefined}
                  onClick={() => {
                    if (toolMode === "delete" && stroke.owner === "user") {
                      handleDeleteStroke(stroke.id);
                    } else if (toolMode === "select") {
                      handleSelectStroke(stroke.elementId);
                    }
                  }}
                  onTap={() => {
                    if (toolMode === "delete" && stroke.owner === "user") {
                      handleDeleteStroke(stroke.id);
                    } else if (toolMode === "select") {
                      handleSelectStroke(stroke.elementId);
                    }
                  }}
                  opacity={toolMode === "delete" && stroke.owner === "user" ? 0.8 : 1}
                />
              );
            })}
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

          {/* Text */}
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
