import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { DrawingTool } from "../hooks/useDrawingTool";

interface DrawingToolbarProps {
  activeTool: DrawingTool;
  onToolChange: (tool: DrawingTool) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  position: { x: number; y: number };
  bounds: { width: number; height: number };
  onPositionChange: (position: { x: number; y: number }) => void;
}

const TOOLS: Array<{
  tool: DrawingTool;
  label: string;
  icon: string;
  shortcut: string;
}> = [
  { tool: "select", label: "Pointer", icon: "↖", shortcut: "1" },
  { tool: "rectangle", label: "Rectangle", icon: "▭", shortcut: "2" },
  { tool: "triangle", label: "Triangle", icon: "△", shortcut: "3" },
  { tool: "circle", label: "Circle", icon: "◯", shortcut: "4" },
  { tool: "line", label: "Line", icon: "／", shortcut: "5" },
  { tool: "square", label: "Square", icon: "□", shortcut: "Q" },
  { tool: "right_triangle", label: "Right Tri", icon: "◺", shortcut: "W" },
  { tool: "rhombus", label: "Rhombus", icon: "◇", shortcut: "E" },
  { tool: "parallelogram", label: "Parallel", icon: "▱", shortcut: "R" },
  { tool: "trapezoid", label: "Trapezoid", icon: "⏢", shortcut: "T" },
  { tool: "pentagon", label: "Pentagon", icon: "⬟", shortcut: "Y" },
  { tool: "hexagon", label: "Hexagon", icon: "⬢", shortcut: "U" },
  { tool: "octagon", label: "Octagon", icon: "🛑", shortcut: "I" },
  { tool: "number_line", label: "Number Line", icon: "↔", shortcut: "O" },
  { tool: "freehand", label: "Pen", icon: "✎", shortcut: "7" },
  { tool: "text", label: "Text", icon: "T", shortcut: "8" },
  { tool: "eraser", label: "Eraser", icon: "⌫", shortcut: "0" },
];

export function DrawingToolbar({
  activeTool,
  onToolChange,
  collapsed,
  onCollapsedChange,
  position,
  bounds,
  onPositionChange,
}: DrawingToolbarProps) {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!dragging) return;

    function clampPosition(nextX: number, nextY: number) {
      const rect = toolbarRef.current?.getBoundingClientRect();
      const maxX = Math.max(0, bounds.width - (rect?.width ?? 0));
      const maxY = Math.max(0, bounds.height - (rect?.height ?? 0));
      return {
        x: Math.min(Math.max(0, nextX), maxX),
        y: Math.min(Math.max(0, nextY), maxY),
      };
    }

    function handlePointerMove(event: PointerEvent) {
      const parentRect = (toolbarRef.current?.offsetParent as HTMLElement | null)?.getBoundingClientRect();
      const next = clampPosition(
        event.clientX - (parentRect?.left ?? 0) - dragOffsetRef.current.x,
        event.clientY - (parentRect?.top ?? 0) - dragOffsetRef.current.y,
      );
      onPositionChange(next);
    }

    function handlePointerUp() {
      setDragging(false);
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, [bounds.height, bounds.width, dragging, onPositionChange]);

  function handleDragStart(event: ReactPointerEvent<HTMLDivElement>) {
    if (!(event.target instanceof HTMLElement)) return;
    if (event.target.closest("button")) return;
    const rect = toolbarRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragOffsetRef.current = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
    setDragging(true);
  }

  return (
    <div
      ref={toolbarRef}
      className={`drawing-toolbar ${collapsed ? "collapsed" : ""} ${dragging ? "dragging" : ""}`}
      style={{ left: `${position.x}px`, top: `${position.y}px` }}
    >
      <div className="drawing-toolbar-header" onPointerDown={handleDragStart}>
        <div className="drawing-toolbar-title">
          <span className="drawing-toolbar-grip" aria-hidden="true">::</span>
          <span>Tools</span>
        </div>
        <button
          type="button"
          className="drawing-toolbar-toggle"
          onClick={() => onCollapsedChange(!collapsed)}
          aria-expanded={!collapsed}
          aria-controls="drawing-toolbar-body"
          title={collapsed ? "Expand toolbar" : "Collapse toolbar"}
        >
          {collapsed ? "Open" : "Hide"}
        </button>
      </div>
      {!collapsed && (
        <div id="drawing-toolbar-body" role="toolbar" aria-label="Drawing tools">
          {TOOLS.map((item) => (
            <button
              key={item.tool}
              type="button"
              className={`drawing-tool-btn ${activeTool === item.tool ? "active" : ""}`}
              onClick={() => {
                onToolChange(item.tool);
              }}
              title={`${item.label} (${item.shortcut})`}
            >
              <span className="drawing-tool-icon" aria-hidden="true">{item.icon}</span>
              <span className="drawing-tool-label">{item.label}</span>
              <span className="drawing-tool-shortcut">{item.shortcut}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
