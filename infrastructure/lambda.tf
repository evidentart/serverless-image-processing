data "archive_file" "presign_upload" {
  type        = "zip"
  source_file = "${path.module}/../lambda/presign_upload.py"
  output_path = "${path.module}/.terraform/presign_upload.zip"
}

resource "aws_cloudwatch_log_group" "presign_upload" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-presign-upload"
  retention_in_days = 14
}

resource "aws_lambda_function" "presign_upload" {
  function_name = "${var.project_name}-${var.environment}-presign-upload"
  description   = "Creates short-lived S3 presigned POST upload policies."
  role          = aws_iam_role.presign_upload.arn
  runtime       = "python3.12"
  handler       = "presign_upload.lambda_handler"

  filename         = data.archive_file.presign_upload.output_path
  source_code_hash = data.archive_file.presign_upload.output_base64sha256

  memory_size = 128
  timeout     = 10
  environment {
    variables = {
      IMAGE_BUCKET = aws_s3_bucket.images.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.presign_upload]
}
