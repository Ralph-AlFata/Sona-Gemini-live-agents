# Testing Commands
# 1. Title
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t1",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"Lesson 1","x":0.35,"y":0.05,"font_size":36,"style":{"stroke_color":"#111111"}}
  }'

# 2. Subtitle
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t2",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"Pythagorean Theorem","x":0.25,"y":0.14,"font_size":24,"style":{"stroke_color":"#4b5563"}}
  }'

# 3. Right triangle (right angle at bottom-left)
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t3",
    "session_id": "dev-session",
    "operation": "draw_shape",
    "payload": {
      "shape": "right_triangle",
      "points": [
        {"x": 0.28, "y": 0.68},
        {"x": 0.72, "y": 0.68},
        {"x": 0.28, "y": 0.25},
        {"x": 0.28, "y": 0.68}
      ],
      "style": {"stroke_color":"#111111","stroke_width":3}
    }
  }'

# 4. Vertex A — bottom-left (right angle)
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t4",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"A","x":0.21,"y":0.70,"font_size":20,"style":{"stroke_color":"#1d4ed8"}}
  }'

# 5. Vertex B — bottom-right
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t5",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"B","x":0.74,"y":0.70,"font_size":20,"style":{"stroke_color":"#1d4ed8"}}
  }'

# 6. Vertex C — top-left
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t6",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"C","x":0.21,"y":0.22,"font_size":20,"style":{"stroke_color":"#1d4ed8"}}
  }'



# 7. Formula
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t10",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"a² + b² = c²","x":0.32,"y":0.80,"font_size":28,"style":{"stroke_color":"#111111"}}
  }'

# 8. Explanation line 1
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t11",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"The square of the hypotenuse (c) equals","x":0.12,"y":0.88,"font_size":16,"style":{"stroke_color":"#4b5563"}}
  }'

# 9. Explanation line 2
curl -s -X POST http://localhost:8002/draw \
  -H "Content-Type: application/json" \
  -d '{
    "command_id": "t12",
    "session_id": "dev-session",
    "operation": "draw_text",
    "payload": {"text":"the sum of the squares of legs a and b.","x":0.12,"y":0.94,"font_size":16,"style":{"stroke_color":"#4b5563"}}
  }'
