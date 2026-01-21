#!/bin/bash

echo "测试 Claude Messages API"
echo "========================"
echo ""

# 测试非流式请求
echo "1. 测试非流式请求..."
curl -X POST http://localhost:7860/v1/messages \
  -H "x-api-key: test-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello, Claude!"}
    ],
    "stream": false
  }'

echo ""
echo ""

# 测试流式请求
echo "2. 测试流式请求..."
curl -X POST http://localhost:7860/v1/messages \
  -H "x-api-key: test-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Count to 5"}
    ],
    "stream": true
  }'

echo ""
echo ""
echo "测试完成！"
