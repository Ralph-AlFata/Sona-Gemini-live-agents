import { useEffect, useRef, useState } from "react";

export interface PointNorm {
  x: number;
  y: number;
}

export type DrawingTool =
  | "select"
  | "rectangle"
  | "square"
  | "triangle"
  | "right_triangle"
  | "circle"
  | "line"
  | "rhombus"
  | "parallelogram"
  | "trapezoid"
  | "pentagon"
  | "hexagon"
  | "octagon"
  | "number_line"
  | "freehand"
  | "text"
  | "eraser";

export interface DraftShape {
  tool: Exclude<DrawingTool, "select" | "text" | "eraser">;
  points: PointNorm[];
}

interface UseDrawingToolOptions {
  getPointer: () => PointNorm | null;
  onCreateShape: (tool: DraftShape["tool"], points: PointNorm[]) => void | Promise<void>;
  onCreateText: (point: PointNorm) => void | Promise<void>;
  onDeleteElement: (elementId: string) => void | Promise<void>;
  onMoveElement: (elementId: string, dx: number, dy: number) => void | Promise<void>;
  resolveElementAt: (point: PointNorm) => string | null;
  onSelectionChange: (elementId: string | null) => void;
  selectedElementId: string | null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  const node = target;
  if (!(node instanceof HTMLElement)) return false;
  const tag = node.tagName.toLowerCase();
  return node.isContentEditable || tag === "input" || tag === "textarea" || tag === "select";
}

export function useDrawingTool({
  getPointer,
  onCreateShape,
  onCreateText,
  onDeleteElement,
  onMoveElement,
  resolveElementAt,
  onSelectionChange,
  selectedElementId,
}: UseDrawingToolOptions) {
  const [activeTool, setActiveTool] = useState<DrawingTool>("select");
  const [draftShape, setDraftShape] = useState<DraftShape | null>(null);
  const dragStartRef = useRef<PointNorm | null>(null);
  const isDraggingSelectionRef = useRef(false);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (isEditableTarget(event.target)) return;
      const map: Record<string, DrawingTool> = {
        "1": "select",
        "2": "rectangle",
        "3": "triangle",
        "4": "circle",
        "5": "line",
        "6": "line",
        "7": "freehand",
        "8": "text",
        "0": "eraser",
        q: "square",
        w: "right_triangle",
        e: "rhombus",
        r: "parallelogram",
        t: "trapezoid",
        y: "pentagon",
        u: "hexagon",
        i: "octagon",
        o: "number_line",
      };
      const next = map[event.key];
      if (!next) return;
      event.preventDefault();
      setActiveTool(next);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function handlePointerDown(): void {
    const point = getPointer();
    if (!point) return;

    if (activeTool === "select") {
      const hitElementId = resolveElementAt(point);
      onSelectionChange(hitElementId);
      if (hitElementId) {
        dragStartRef.current = point;
        isDraggingSelectionRef.current = true;
      }
      return;
    }

    if (activeTool === "eraser") {
      const hitElementId = resolveElementAt(point);
      if (hitElementId) {
        void onDeleteElement(hitElementId);
      }
      return;
    }

    if (activeTool === "text") {
      void onCreateText(point);
      return;
    }

    setDraftShape({
      tool: activeTool,
      points: [point],
    });
  }

  function handlePointerMove(): void {
    if (!draftShape) return;
    const point = getPointer();
    if (!point) return;
    if (draftShape.tool === "freehand") {
      setDraftShape((current) => {
        if (!current) return current;
        const previous = current.points[current.points.length - 1];
        if (!previous) return current;
        const dx = point.x - previous.x;
        const dy = point.y - previous.y;
        if (Math.sqrt(dx * dx + dy * dy) < 0.0015) {
          return current;
        }
        return {
          ...current,
          points: [...current.points, point],
        };
      });
      return;
    }
    setDraftShape((current) => {
      if (!current) return current;
      return {
        ...current,
        points: [current.points[0]!, point],
      };
    });
  }

  function handlePointerUp(): void {
    if (activeTool === "select" && isDraggingSelectionRef.current && selectedElementId) {
      const start = dragStartRef.current;
      const end = getPointer();
      dragStartRef.current = null;
      isDraggingSelectionRef.current = false;
      if (start && end) {
        const dx = end.x - start.x;
        const dy = end.y - start.y;
        if (Math.abs(dx) > 0.002 || Math.abs(dy) > 0.002) {
          void onMoveElement(selectedElementId, dx, dy);
        }
      }
      return;
    }

    if (!draftShape) return;
    const currentDraft = draftShape;
    setDraftShape(null);
    if (currentDraft.tool === "freehand") {
      if (currentDraft.points.length >= 2) {
        void onCreateShape(currentDraft.tool, currentDraft.points);
      }
      return;
    }
    if (currentDraft.points.length < 2) return;
    void onCreateShape(currentDraft.tool, currentDraft.points);
  }

  return {
    activeTool,
    setActiveTool,
    draftShape,
    handlePointerDown,
    handlePointerMove,
    handlePointerUp,
  };
}
