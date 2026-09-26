data "aws_iam_policy_document" "processor_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "processor" {
  name               = "${var.project_name}-${var.environment}-processor"
  assume_role_policy = data.aws_iam_policy_document.processor_assume_role.json
}

data "aws_iam_policy_document" "processor" {
  statement {
    sid    = "ReadIncomingObjects"
    effect = "Allow"

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.images.arn}/incoming/*"]
  }

  statement {
    sid    = "WriteProcessedObjects"
    effect = "Allow"

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.images.arn}/processed/*"]
  }

  statement {
    sid    = "ConsumeProcessingQueue"
    effect = "Allow"

    actions = [
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [aws_sqs_queue.processing.arn]
  }

  statement {
    sid    = "WriteFunctionLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.processor.arn}:*"]
  }
}

resource "aws_iam_role_policy" "processor" {
  name   = "${var.project_name}-${var.environment}-processor"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor.json
}
