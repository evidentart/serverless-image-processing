data "aws_iam_policy_document" "presign_upload_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "presign_upload" {
  name                 = "${var.project_name}-${var.environment}-presign-upload"
  assume_role_policy   = data.aws_iam_policy_document.presign_upload_assume_role.json
  permissions_boundary = local.lambda_runtime_boundary_arn
}

data "aws_iam_policy_document" "presign_upload" {
  statement {
    sid    = "AllowPresignedImageUploads"
    effect = "Allow"

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.images.arn}/incoming/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["AES256"]
    }
  }

  statement {
    sid    = "WriteFunctionLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.presign_upload.arn}:*"]
  }
}

resource "aws_iam_role_policy" "presign_upload" {
  name   = "${var.project_name}-${var.environment}-presign-upload"
  role   = aws_iam_role.presign_upload.id
  policy = data.aws_iam_policy_document.presign_upload.json
}

data "aws_iam_policy_document" "status_upload_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "status_upload" {
  name                 = "${var.project_name}-${var.environment}-status-upload"
  assume_role_policy   = data.aws_iam_policy_document.status_upload_assume_role.json
  permissions_boundary = local.lambda_runtime_boundary_arn
}

data "aws_iam_policy_document" "status_upload" {
  statement {
    sid    = "ReadProcessedObjects"
    effect = "Allow"

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.images.arn}/processed/*"]
  }

  statement {
    sid    = "WriteFunctionLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.status_upload.arn}:*"]
  }
}

resource "aws_iam_role_policy" "status_upload" {
  name   = "${var.project_name}-${var.environment}-status-upload"
  role   = aws_iam_role.status_upload.id
  policy = data.aws_iam_policy_document.status_upload.json
}
