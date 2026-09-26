resource "aws_apigatewayv2_api" "upload" {
  name          = "${var.project_name}-${var.environment}-upload-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = false
    allow_headers     = ["content-type"]
    allow_methods     = ["GET", "POST", "OPTIONS"]
    allow_origins     = var.frontend_allowed_origins
    max_age           = 300
  }
}

resource "aws_apigatewayv2_integration" "presign_upload" {
  api_id                 = aws_apigatewayv2_api.upload.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.presign_upload.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "presign_upload" {
  api_id    = aws_apigatewayv2_api.upload.id
  route_key = "POST /uploads/presign"
  target    = "integrations/${aws_apigatewayv2_integration.presign_upload.id}"
}

resource "aws_apigatewayv2_integration" "status_upload" {
  api_id                 = aws_apigatewayv2_api.upload.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.status_upload.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "status_upload" {
  api_id    = aws_apigatewayv2_api.upload.id
  route_key = "GET /uploads/{upload_id}/status"
  target    = "integrations/${aws_apigatewayv2_integration.status_upload.id}"
}

resource "aws_apigatewayv2_stage" "upload" {
  api_id      = aws_apigatewayv2_api.upload.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 2
    throttling_rate_limit  = 0.2
  }
}

resource "aws_lambda_permission" "presign_upload_from_api" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.presign_upload.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.upload.execution_arn}/$default/POST/uploads/presign"
}

resource "aws_lambda_permission" "status_upload_from_api" {
  statement_id  = "AllowApiGatewayInvokeStatus"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.status_upload.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.upload.execution_arn}/$default/GET/uploads/*/status"
}

resource "aws_s3_bucket_cors_configuration" "images" {
  bucket = aws_s3_bucket.images.id

  cors_rule {
    allowed_headers = ["content-type"]
    allowed_methods = ["POST"]
    allowed_origins = var.frontend_allowed_origins
    expose_headers  = []
    max_age_seconds = 300
  }
}
