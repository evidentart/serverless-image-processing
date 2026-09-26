data "archive_file" "processor" {
  type        = "zip"
  source_dir  = "${path.module}/../.phase4-build/processor-package"
  output_path = "${path.module}/.terraform/processor.zip"

  excludes = [
    "**/__pycache__/**",
    "**/*.pyc",
  ]
}

resource "aws_sqs_queue" "processing_dlq" {
  name                      = "${var.project_name}-${var.environment}-processing-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "processing" {
  name                       = "${var.project_name}-${var.environment}-processing"
  visibility_timeout_seconds = 360
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = 3
  })
}

data "aws_iam_policy_document" "processing_queue" {
  statement {
    sid    = "AllowS3IncomingNotifications"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.processing.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.images.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "processing" {
  queue_url = aws_sqs_queue.processing.id
  policy    = data.aws_iam_policy_document.processing_queue.json
}

resource "aws_s3_bucket_notification" "images_processing" {
  bucket = aws_s3_bucket.images.id

  queue {
    queue_arn     = aws_sqs_queue.processing.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "incoming/"
  }

  depends_on = [aws_sqs_queue_policy.processing]
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-processor"
  retention_in_days = 14
}

resource "aws_lambda_function" "processor" {
  function_name = "${var.project_name}-${var.environment}-processor"
  description   = "Validates and transforms images from the S3 incoming quarantine prefix."
  role          = aws_iam_role.processor.arn
  runtime       = "python3.12"
  handler       = "processor_handler.lambda_handler"

  architectures = ["x86_64"]

  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256

  memory_size = 1024
  timeout     = 60

  environment {
    variables = {
      IMAGE_BUCKET = aws_s3_bucket.images.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.processor]
}

resource "aws_lambda_event_source_mapping" "processor" {
  event_source_arn                   = aws_sqs_queue.processing.arn
  function_name                      = aws_lambda_function.processor.arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = 0

  scaling_config {
    maximum_concurrency = 2
  }

  depends_on = [aws_iam_role_policy.processor]
}
