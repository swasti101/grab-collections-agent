import boto3
import json

# Create Bedrock Runtime client
bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name="us-west-2",
    aws_access_key_id="ASIAUTRCN2YMHAZPIONR",
    aws_secret_access_key="ytHMuMzwd2V73IXEtWGNxKC9mIOTPIuN7PtkXXRJ",
    aws_session_token="IQoJb3JpZ2luX2VjEMT//////////wEaCXVzLWVhc3QtMSJHMEUCICG2TjHre5uMCX02lluoyshLcv9dRRj30OO42pziI2y1AiEA+MOKDh13lIJuK1s2H2xpaQQZdui2N7MIhWczHA4PiSkqogIIjf//////////ARAAGgwzMTY4MjYwNDgwMjQiDEY9irAfa4p/eLOXZyr2ASP/YW914QA7HbiddO3DXosXTDiKZR4FrLXa8c9Y0r6NDUa9jhEcxoXTHten5Dm2KonzJhiOaqQZNGRt8w+FHm0u8hIV9GgHynPBUQE1nb+BrdAPoYDiq9263QsaW63RAgSWsrKNi65dXIOwn4vl943RhpJaoWWGS/NC6vsDbnTZx3XQh4e6Thlk5iNZS2H1xnqV1L3d53ak7R13UjuEwUTnXQWmbbxVaB3pVVu34UB8pFwh7czcXruPB/6v+5c+CyyK+ab/uiaVdTjGQ5SHLQFHjWjfQn1EgOq6zDJRjs/loCcriDxdL5fodbnNSeANeieFZBBdSzCZr6HQBjqdAaQ4uCK21bno3wOmFUI9gXS3IxxQrzVzjHPMlVg8KopROfob7zV9twoSOPw8EiXFYR2TgwTxk4Sa7TsakyUM3EjSUh/cRgfhi8NxDci8O6wvIDuyceciJlxL0UynovIaZBUFfVQ4LZdl9NuOv86/Crx0OUtxs0WT/WWbfx6qvwCeYzY+5tCdNPaSDtlDUfIVzHzq/GcDe7QR/2E9adY="
)

# DeepSeek model ID
model_id = "deepseek.v3.2"

# Request payload
payload = {
    "messages": [
        {
            "role": "user",
            "content": "Hello, who are you?"
        }
    ],
    "max_tokens": 512,
    "temperature": 0.7
}

# Invoke model
response = bedrock.invoke_model(
    modelId=model_id,
    body=json.dumps(payload),
    contentType="application/json",
    accept="application/json"
)

# Read response
response_body = json.loads(response["body"].read())

print(response_body)