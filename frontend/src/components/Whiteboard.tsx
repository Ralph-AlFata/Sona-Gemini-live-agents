import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Rect, Text } from "react-konva";
import type Konva from "konva";
import type { DSLMessageRaw } from "../services/drawingSocket";

interface TextItem {
  id: string;
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
}

interface WhiteboardProps {
  messages: DSLMessageRaw[];
}

const HANDWRITING_FONT = '"Patrick Hand", "Comic Sans MS", cursive';

export function Whiteboard({ messages }: WhiteboardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const stageRef = useRef<Konva.Stage>(null);

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

  const textItems: TextItem[] = messages
    .filter((msg) => msg.type === "text")
    .map((msg) => {
      const p = msg.payload;
      return {
        id: msg.id,
        text: String(p["text"] ?? ""),
        x: Number(p["x"] ?? 0) * dimensions.width,
        y: Number(p["y"] ?? 0) * dimensions.height,
        fontSize: Number(p["font_size"] ?? 18),
        color: String(p["color"] ?? "#000"),
      };
    });

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", background: "#f5f5f5" }}
    >
      {dimensions.width > 0 && dimensions.height > 0 && (
        <Stage
          ref={stageRef}
          width={dimensions.width}
          height={dimensions.height}
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
            {textItems.map((item) => (
              <Text
                key={item.id}
                x={item.x}
                y={item.y}
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
